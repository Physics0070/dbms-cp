"""DuckDB adapter.

Implements :class:`DatabaseAdapter` for a DuckDB database file. Introspection uses DuckDB's own
catalog functions (`duckdb_tables()`, `duckdb_columns()`, `duckdb_constraints()`,
`duckdb_indexes()`); plans come from `EXPLAIN (FORMAT JSON)` (the planner's ESTIMATES; the query
is not run) and `EXPLAIN ANALYZE` (which does run it, for actual cardinalities/timings).

Safety, in layers:
1. the file is opened ``read_only=True``;
2. ``enable_external_access=false`` + ``lock_configuration=true``: queries cannot read or write
   files (``read_csv``, ``'file.csv'`` in FROM, COPY, ATTACH, INSTALL/LOAD all fail inside the
   engine) and cannot switch that off again;
3. every statement passes :func:`check_sql` first: one statement, SELECT-shaped, no file/extension
   functions;
4. a watchdog interrupts statements longer than the timeout.

Only the ``main`` schema is introspected.
"""
from __future__ import annotations

import json
import os
import re
import statistics as _stats
import threading
import time
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import duckdb

from ..config import get_settings
from ..optimizer.safety import UnsafeQueryError
from .adapter import (
    Column,
    ColumnStatistics,
    DatabaseAdapter,
    ForeignKey,
    Index,
    TableSchema,
    TableStatistics,
)
from .sqlite_adapter import _SQLITE_MAGIC, DatabaseUnavailable, _quote_ident, set_adapter

_DUCKDB_MAGIC = b"DUCK"  # bytes 8..12 of every DuckDB database file
STATEMENT_TIMEOUT_S = int(os.environ.get("DUCKDB_STATEMENT_TIMEOUT_MS", "30000")) / 1000.0
_EXACT_DISTINCT_ROW_LIMIT = 1_000_000  # above this, distinct counts use approx_count_distinct

_ALLOWED_FIRST_WORDS = {"SELECT", "WITH", "FROM", "VALUES", "TABLE"}
# Table/scalar functions that touch files, run nested SQL, or expose secrets.
_FORBIDDEN_FUNCTIONS = (
    "READ_CSV", "READ_CSV_AUTO", "READ_JSON", "READ_JSON_AUTO", "READ_NDJSON", "READ_NDJSON_AUTO",
    "READ_PARQUET", "PARQUET_SCAN", "PARQUET_METADATA", "PARQUET_SCHEMA", "READ_TEXT", "READ_BLOB",
    "GLOB", "SNIFF_CSV", "ICEBERG_SCAN", "DELTA_SCAN", "QUERY", "QUERY_TABLE", "DUCKDB_SECRETS",
    "WRITE_FILE", "SQLITE_SCAN", "POSTGRES_SCAN", "MYSQL_SCAN", "READ_XLSX",
)
# Statement-leading words (COPY, ATTACH, SET, ...) are already rejected by the first-word check; these
# are the write verbs that could hide inside a WITH. (DuckDB's read-only open refuses them anyway.)
_FORBIDDEN_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE")


def sniff_format(path: str) -> Optional[str]:
    """'sqlite', 'duckdb', or None (missing/unreadable/unknown) from the file's magic bytes."""
    try:
        with open(Path(path).expanduser(), "rb") as fh:
            header = fh.read(16)
    except OSError:
        return None
    if header == _SQLITE_MAGIC:
        return "sqlite"
    if header[8:12] == _DUCKDB_MAGIC:
        return "duckdb"
    return None


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", " ", sql)


def check_sql(sql: str) -> None:
    """Raise UnsafeQueryError unless `sql` is one SELECT-shaped statement with no file access."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")
    bare = _strip_literals(re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)).strip().lstrip("( ").upper()
    flat = " ".join(bare.split())
    # DuckDB's own splitter, so ';' inside literals or comments is handled correctly.
    try:
        n = len(duckdb.extract_statements(sql))
    except duckdb.Error as e:
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e
    if n != 1:
        raise UnsafeQueryError("Multiple statements are not allowed." if n > 1 else "No statement found.")
    first = flat.split(" ", 1)[0] if flat else ""
    if first not in _ALLOWED_FIRST_WORDS:
        raise UnsafeQueryError(f"Only read-only SELECT queries are allowed (got {first or 'nothing'}).")
    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(r"(?<![A-Z0-9_])" + kw + r"(?![A-Z0-9_])", flat):
            raise UnsafeQueryError(f"Forbidden keyword detected: {kw}")
    for fn in _FORBIDDEN_FUNCTIONS:
        if re.search("(?<![A-Z0-9_])" + fn + r"[ ]*[(]", flat):
            raise UnsafeQueryError(f"Function {fn.lower()}() is not permitted.")


def _norm(v: Any) -> Any:
    """JSON-safe value."""
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date, dtime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    return str(v)


def _open(path: Path):
    return duckdb.connect(
        str(path), read_only=True,
        config={"enable_external_access": False, "lock_configuration": True,
                "autoinstall_known_extensions": False, "autoload_known_extensions": False},
    )


def validate_duckdb_file(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise DatabaseUnavailable(f"Database file not found: {path}")
    if sniff_format(str(p)) != "duckdb":
        raise DatabaseUnavailable(f"Not a DuckDB database file: {path}")
    return p.resolve()


class DuckdbAdapter(DatabaseAdapter):
    dialect = "duckdb"
    engine = "DuckDB"

    def __init__(self, path: str) -> None:
        self._settings = get_settings()
        self.path = validate_duckdb_file(path)
        self._lock = threading.RLock()  # a DuckDB connection is not safe for concurrent use
        try:
            self._conn = _open(self.path)
            self._conn.execute("SELECT count(*) FROM duckdb_tables()").fetchone()
        except duckdb.Error as e:
            raise DatabaseUnavailable(f"Could not open database: {e}") from e
        self.server_version = duckdb.__version__
        self._stats_cache: dict[str, tuple[float, TableStatistics]] = {}

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except duckdb.Error:
                pass

    @property
    def backend_name(self) -> str:
        return f"DuckDB {self.server_version} · {self.path.name} (read-only)"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def capabilities(self) -> dict[str, bool]:
        caps = {k: False for k in self.CAPABILITY_KEYS}
        caps.update(
            schema_introspection=True, index_discovery=True, statistics=True, native_explain=True,
            # EXPLAIN ANALYZE gives real per-operator rows/timings (it executes the query).
            actual_plan_analysis=True, benchmarking=True,
            # False: the rewriter/equivalence pipeline emits and checks SQLite-dialect SQL and has not
            # been run against DuckDB; DuckDB has no hypothetical indexes.
            hypothetical_index=False, sql_rewrite=False, result_equivalence=False,
        )
        return caps

    # -- low level ------------------------------------------------------------
    def _rows(self, sql: str, params: Optional[list] = None, *, guard: bool = False) -> tuple[list[str], list[tuple]]:
        """Run on the shared connection. `guard=True` for any SQL that came from a user."""
        if guard:
            check_sql(sql)
        with self._lock:
            timer = threading.Timer(STATEMENT_TIMEOUT_S, self._conn.interrupt)
            timer.start()
            try:
                cur = self._conn.execute(sql, params or [])
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
            except duckdb.InterruptException as e:
                raise TimeoutError(f"Statement exceeded the {STATEMENT_TIMEOUT_S:g}s timeout and was cancelled.") from e
            finally:
                timer.cancel()
        return cols, [tuple(_norm(v) for v in r) for r in rows]

    # -- schema discovery -------------------------------------------------------
    def get_tables(self) -> list[str]:
        _, rows = self._rows(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main' AND NOT internal ORDER BY table_name")
        return [r[0] for r in rows]

    def _constraints(self, table: str) -> list[tuple]:
        _, rows = self._rows(
            "SELECT constraint_type, constraint_column_names, referenced_table, referenced_column_names "
            "FROM duckdb_constraints() WHERE schema_name = 'main' AND table_name = ? ORDER BY constraint_index",
            [table])
        return rows

    def get_columns(self, table: str) -> list[Column]:
        pk: set[str] = set()
        for ctype, cols, _, _ in self._constraints(table):
            if ctype == "PRIMARY KEY":
                pk.update(cols)
        _, rows = self._rows(
            "SELECT column_name, data_type, is_nullable, column_default FROM duckdb_columns() "
            "WHERE schema_name = 'main' AND table_name = ? ORDER BY column_index", [table])
        return [Column(name=r[0], data_type=(r[1] or "").upper() or "UNKNOWN", nullable=bool(r[2]),
                       primary_key=r[0] in pk, default=r[3]) for r in rows]

    def get_indexes(self, table: str) -> list[Index]:
        out: list[Index] = []
        for ctype, cols, _, _ in self._constraints(table):
            if ctype == "PRIMARY KEY":
                out.append(Index(name=f"pk_{table}", columns=list(cols), unique=True, origin="pk"))
            elif ctype == "UNIQUE":
                out.append(Index(name=f"uq_{table}_{'_'.join(cols)}", columns=list(cols), unique=True, origin="u"))
        _, rows = self._rows(
            "SELECT index_name, is_unique, expressions FROM duckdb_indexes() "
            "WHERE schema_name = 'main' AND table_name = ? ORDER BY index_name", [table])
        for name, unique, expr in rows:
            cols = [c.strip().strip('"') for c in (expr or "").strip("[]").split(",") if c.strip()]
            out.append(Index(name=name, columns=cols, unique=bool(unique), origin="c"))
        return out

    def get_foreign_keys(self, table: str) -> list[ForeignKey]:
        return [ForeignKey(columns=list(cols), ref_table=ref, ref_columns=list(rcols),
                           on_update="NO ACTION", on_delete="NO ACTION")  # DuckDB has no referential actions
                for ctype, cols, ref, rcols in self._constraints(table) if ctype == "FOREIGN KEY"]

    def get_table_schema(self, table: str) -> TableSchema:
        return TableSchema(name=table, columns=self.get_columns(table), indexes=self.get_indexes(table),
                           foreign_keys=self.get_foreign_keys(table))

    def get_schema(self) -> dict[str, TableSchema]:
        return {t: self.get_table_schema(t) for t in self.get_tables()}

    # -- statistics ---------------------------------------------------------------
    def get_statistics(self, table: str, use_cache: bool = True) -> TableStatistics:
        now = time.time()
        if use_cache and table in self._stats_cache and now - self._stats_cache[table][0] < self._settings.stats_cache_ttl:
            return self._stats_cache[table][1]
        computed = self._compute_statistics(table)
        self._stats_cache[table] = (now, computed)
        return computed

    def _compute_statistics(self, table: str) -> TableStatistics:
        if table not in set(self.get_tables()):
            raise ValueError(f"Unknown table: {table!r}")
        schema, qt = self.get_table_schema(table), _quote_ident(table)
        row_count = int(self._rows(f"SELECT COUNT(*) FROM {qt}")[1][0][0])  # exact; cheap in DuckDB
        approx = row_count > _EXACT_DISTINCT_ROW_LIMIT
        cfg, col_stats = self._settings, {}
        for col in schema.columns:
            qc = _quote_ident(col.name)
            d = f"approx_count_distinct({qc})" if approx else f"COUNT(DISTINCT {qc})"
            _, agg = self._rows(f"SELECT {d}, COUNT(*) - COUNT({qc}), MIN({qc}), MAX({qc}) FROM {qt}")
            distinct, nulls, mn, mx = agg[0]
            distinct, nulls = int(distinct or 0), int(nulls or 0)
            mcv: list[tuple[Any, int]] = []
            cap = max(cfg.mcv_min_distinct_cap, int(row_count * cfg.mcv_distinct_ratio) + 1)
            if 0 < distinct <= cap:
                _, mc = self._rows(f"SELECT {qc}, COUNT(*) c FROM {qt} WHERE {qc} IS NOT NULL "
                                   f"GROUP BY {qc} ORDER BY c DESC LIMIT {int(cfg.mcv_limit)}")
                mcv = [(m[0], int(m[1])) for m in mc]
            col_stats[col.name] = ColumnStatistics(
                column=col.name, data_type=col.data_type, distinct_count=distinct, null_count=nulls,
                null_fraction=(nulls / row_count) if row_count else 0.0, min_value=mn, max_value=mx, most_common=mcv)
        src = ("Computed from the connected database (row/null counts exact; distinct counts approximate: "
               "approx_count_distinct)") if approx else "Computed from the connected database (exact)"
        return TableStatistics(table=table, row_count=row_count, columns=col_stats,
                               collected_at=datetime.now(timezone.utc).isoformat(), source=src)

    def invalidate_stats(self, table: Optional[str] = None) -> None:
        self._stats_cache.clear() if table is None else self._stats_cache.pop(table, None)

    # -- execution ------------------------------------------------------------------
    def execute_readonly(self, sql: str, params: Optional[list] = None, limit: Optional[int] = None):
        cols, rows = self._rows(sql, params, guard=True)
        return cols, (rows[:limit] if limit is not None else rows)

    def explain_query(self, sql: str) -> list[dict]:
        """EXPLAIN (FORMAT JSON) flattened into id/parent/detail rows. Planner ESTIMATES only."""
        check_sql(sql)
        _, rows = self._rows(f"EXPLAIN (FORMAT JSON) {sql}")
        out: list[dict] = []

        def walk(node: dict, parent: int) -> None:
            nid = len(out) + 1
            info = node.get("extra_info") or {}
            card = str(info.get("Estimated Cardinality", "")).lstrip("~")
            out.append({"id": nid, "parent": parent, "detail": _detail(node), "node_type": node.get("name"),
                        "estimated_rows": int(card) if card.isdigit() else None})
            for ch in node.get("children", []):
                walk(ch, nid)

        for r in rows:
            if r[0] == "physical_plan":
                for root in json.loads(r[1]):
                    walk(root, 0)
        return out

    def explain_bytecode(self, sql: str) -> list[dict]:
        """DuckDB has no bytecode listing; return the text plan instead."""
        check_sql(sql)
        _, rows = self._rows(f"EXPLAIN {sql}")
        return [{"explain_key": r[0], "plan": r[1]} for r in rows]

    def explain_analyze(self, sql: str) -> list[dict]:
        """EXPLAIN ANALYZE: EXECUTES the (read-only) query and reports actual rows and timings."""
        check_sql(sql)
        _, rows = self._rows(f"EXPLAIN ANALYZE {sql}")
        return [{"explain_key": r[0], "plan": r[1]} for r in rows]

    def benchmark_query(self, sql: str, warmup: Optional[int] = None, runs: Optional[int] = None) -> dict:
        warmup = self._settings.benchmark_warmup if warmup is None else warmup
        runs = self._settings.benchmark_runs if runs is None else runs
        for _ in range(max(0, warmup)):
            self.execute_readonly(sql)
        durations, row_count = [], 0
        for _ in range(max(1, runs)):
            start = time.perf_counter()
            _, rows = self.execute_readonly(sql)
            durations.append((time.perf_counter() - start) * 1000.0)
            row_count = len(rows)
        durations.sort()
        return {
            "label": "Application Benchmark",
            "note": "Wall-clock execution time - NOT an optimizer cost value.",
            "warmup_runs": warmup, "measured_runs": runs, "rows_returned": row_count,
            "min_ms": round(min(durations), 4), "max_ms": round(max(durations), 4),
            "avg_ms": round(sum(durations) / len(durations), 4), "median_ms": round(_stats.median(durations), 4),
            "samples_ms": [round(d, 4) for d in durations],
        }


def _detail(node: dict) -> str:
    """One SQLite-EQP-style line per plan node so the shared explain parser understands it."""
    name, info = node.get("name", ""), node.get("extra_info") or {}
    if name in ("SEQ_SCAN", "TABLE_SCAN", "INDEX_SCAN") or "Table" in info:
        table = str(info.get("Table", "")).split(".")[-1]
        flt = f" WHERE {info['Filters']}" if info.get("Filters") else ""
        if "index" in str(info.get("Type", name)).lower():
            return f"SEARCH {table} (Index Scan){flt}"
        return f"SCAN {table} (Seq Scan){flt}"
    extra = " ".join(f"{k}: {info[k]}" for k in ("Join Type", "Conditions", "Groups", "Aggregates", "Order By")
                     if k in info and not isinstance(info[k], list))
    return f"{name} {extra}".strip()


def connect_duckdb(path: str) -> DuckdbAdapter:
    """Open a DuckDB file read-only and make it the current database; the old one stays on failure."""
    adapter = DuckdbAdapter(path)
    set_adapter(adapter)
    return adapter
