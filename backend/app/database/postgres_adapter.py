"""PostgreSQL adapter.

Implements :class:`DatabaseAdapter` with ``information_schema`` / ``pg_catalog`` introspection,
``pg_stats`` / exact-count statistics and ``EXPLAIN (FORMAT JSON)`` (plain EXPLAIN, never
ANALYZE, so a query is never executed just to be planned).

Safety: every transaction on the connection is READ ONLY (``conn.read_only`` plus
``default_transaction_read_only=on`` at session level), each statement is capped by
``statement_timeout``, and the password is passed to libpq once and never kept on this object.
Prefer a role that only has SELECT; the read-only transaction is defence in depth, not a
substitute for least-privilege credentials.

Values are normalised to what the SQLite adapter yields (Decimal -> float, dates -> ISO
strings) because the optimizer's selectivity code interpolates min/max values.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import statistics as _stats
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg

from ..config import get_settings
from .adapter import (
    Column,
    ColumnStatistics,
    DatabaseAdapter,
    ForeignKey,
    Index,
    TableSchema,
    TableStatistics,
)
from .sqlite_adapter import DatabaseUnavailable, _quote_ident

_FK_ACTIONS = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


def _norm(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _clean_error(e: Exception, secret: str = "") -> str:
    msg = (str(e).strip().splitlines() or ["connection failed"])[0]
    return msg.replace(secret, "***") if secret else msg


class PostgresAdapter(DatabaseAdapter):
    dialect = "postgres"
    engine = "PostgreSQL"
    dialect = "postgres"
    read_only = True
    # Tables larger than this use pg_stats instead of full-table aggregate scans.
    EXACT_STATS_MAX_ROWS = 200_000

    def __init__(self, host: str, port: int, database: str, user: str, password: str,
                 sslmode: str = "prefer", hostaddr: Optional[str] = None, schema: str = "public") -> None:
        self._settings = get_settings()
        self.host, self.port, self.database, self.schema = host, port, database, schema
        self._lock = threading.RLock()
        self._stats_cache: dict[str, tuple[float, TableStatistics]] = {}
        s = self._settings
        try:
            self._conn = psycopg.connect(
                host=host, hostaddr=hostaddr, port=port, dbname=database, user=user, password=password,
                sslmode=sslmode, connect_timeout=s.pg_connect_timeout_s, application_name="querypilot",
                options=f"-c statement_timeout={int(s.pg_statement_timeout_ms)} "
                        f"-c default_transaction_read_only=on -c idle_in_transaction_session_timeout=60000",
            )
            self._conn.read_only = True
            self._has_hypopg = bool(self._rows("SELECT 1 FROM pg_extension WHERE extname = 'hypopg'")[1])
            self.server_version = self._rows("SHOW server_version")[1][0][0]
        except psycopg.Error as e:
            raise DatabaseUnavailable(f"Could not connect to PostgreSQL: {_clean_error(e, password)}") from None

    # -- connection ----------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def backend_name(self) -> str:
        return f"PostgreSQL {self.server_version} · {self.database}@{self.host} (read-only)"

    @property
    def capabilities(self) -> dict[str, bool]:
        return {
            "schema_introspection": True, "index_discovery": True, "statistics": True,
            "native_explain": True,
            "actual_plan_analysis": False,   # plain EXPLAIN only: estimates, no per-operator actuals
            "benchmarking": True,
            "hypothetical_index": self._has_hypopg,  # only when the hypopg extension is installed
            "sql_rewrite": False,  # join pinning (CROSS JOIN ... ON) is SQLite-only; see rewriter.py
            "result_equivalence": True,  # verified by tests/test_dialects.py against real PostgreSQL
        }

    def _rows(self, sql: str, params: Optional[list] = None, limit: Optional[int] = None):
        """Run one statement in its own READ ONLY transaction; always roll back."""
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(sql, params) if params else cur.execute(sql)
                    cols = [d.name for d in cur.description] if cur.description else []
                    raw = (cur.fetchmany(limit) if limit is not None else cur.fetchall()) if cols else []
                return cols, [tuple(_norm(v) for v in r) for r in raw]
            finally:
                self._conn.rollback()

    # -- schema discovery ----------------------------------------------------
    def get_tables(self) -> list[str]:
        _, rows = self._rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name", [self.schema])
        return [r[0] for r in rows]

    def get_columns(self, table: str) -> list[Column]:
        _, pk = self._rows(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name "
            "AND kcu.constraint_schema = tc.constraint_schema AND kcu.table_name = tc.table_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s AND tc.table_name = %s",
            [self.schema, table])
        pks = {r[0] for r in pk}
        _, rows = self._rows(
            "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", [self.schema, table])
        return [Column(r[0], (r[1] or "").upper() or "UNKNOWN", r[2] == "YES", r[0] in pks, r[3]) for r in rows]

    def get_indexes(self, table: str) -> list[Index]:
        _, rows = self._rows(
            "SELECT ic.relname, i.indisunique, i.indisprimary, array_agg(a.attname ORDER BY k.ord) "
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord) "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum "  # attnum 0 = expression column, skipped
            "WHERE n.nspname = %s AND c.relname = %s "
            "GROUP BY ic.relname, i.indisunique, i.indisprimary ORDER BY ic.relname", [self.schema, table])
        return [Index(r[0], list(r[3]), bool(r[1]), "pk" if r[2] else "u" if r[1] else "c") for r in rows]

    def get_foreign_keys(self, table: str) -> list[ForeignKey]:
        cols = ("(SELECT array_agg(a.attname ORDER BY u.ord) FROM unnest(con.{k}) WITH ORDINALITY u(attnum, ord) "
                "JOIN pg_attribute a ON a.attrelid = con.{r} AND a.attnum = u.attnum)")
        _, rows = self._rows(
            f"SELECT {cols.format(k='conkey', r='conrelid')}, rc.relname, {cols.format(k='confkey', r='confrelid')}, "
            "con.confupdtype, con.confdeltype FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_class rc ON rc.oid = con.confrelid "
            "WHERE con.contype = 'f' AND n.nspname = %s AND c.relname = %s ORDER BY con.conname",
            [self.schema, table])
        return [ForeignKey(list(r[0]), r[1], list(r[2]), _FK_ACTIONS.get(r[3], ""), _FK_ACTIONS.get(r[4], ""))
                for r in rows]

    def get_table_schema(self, table: str) -> TableSchema:
        return TableSchema(table, self.get_columns(table), self.get_indexes(table), self.get_foreign_keys(table))

    def get_schema(self) -> dict[str, TableSchema]:
        return {t: self.get_table_schema(t) for t in self.get_tables()}

    # -- statistics ----------------------------------------------------------
    def get_statistics(self, table: str, use_cache: bool = True) -> TableStatistics:
        now = time.time()
        if use_cache and table in self._stats_cache:
            ts, cached = self._stats_cache[table]
            if now - ts < self._settings.stats_cache_ttl:
                return cached
        computed = self._compute_statistics(table)
        self._stats_cache[table] = (now, computed)
        return computed

    def invalidate_stats(self, table: Optional[str] = None) -> None:
        self._stats_cache.clear() if table is None else self._stats_cache.pop(table, None)

    def _compute_statistics(self, table: str) -> TableStatistics:
        schema = self.get_table_schema(table)
        _, rt = self._rows(
            "SELECT c.reltuples::float8 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s", [self.schema, table])
        reltuples = rt[0][0] if rt else -1.0
        if 0 <= reltuples and reltuples > self.EXACT_STATS_MAX_ROWS:
            return self._planner_statistics(table, schema, reltuples)
        return self._exact_statistics(table, schema)

    def _exact_statistics(self, table: str, schema: TableSchema) -> TableStatistics:
        qt = f"{_quote_ident(self.schema)}.{_quote_ident(table)}"
        row_count = int(self._rows(f"SELECT COUNT(*) FROM {qt}")[1][0][0])
        cfg = self._settings
        cap = max(cfg.mcv_min_distinct_cap, int(row_count * cfg.mcv_distinct_ratio) + 1)
        out: dict[str, ColumnStatistics] = {}
        for col in schema.columns:
            qc = _quote_ident(col.name)
            try:
                distinct, nulls, mn, mx = self._rows(
                    f"SELECT COUNT(DISTINCT {qc}), COUNT(*) - COUNT({qc}), MIN({qc}), MAX({qc}) FROM {qt}")[1][0]
            except psycopg.Error:
                # Types without equality/ordering (json, point, ...): report only what can be counted.
                distinct, mn, mx = 0, None, None
                nulls = self._rows(f"SELECT COUNT(*) - COUNT({qc}) FROM {qt}")[1][0][0]
            distinct, nulls = int(distinct or 0), int(nulls or 0)
            mcv: list[tuple[Any, int]] = []
            if 0 < distinct <= cap:
                _, mc = self._rows(
                    f"SELECT {qc}, COUNT(*) AS c FROM {qt} WHERE {qc} IS NOT NULL GROUP BY {qc} "
                    f"ORDER BY c DESC LIMIT {int(cfg.mcv_limit)}")
                mcv = [(m[0], int(m[1])) for m in mc]
            out[col.name] = ColumnStatistics(col.name, col.data_type, distinct, nulls,
                                             (nulls / row_count) if row_count else 0.0, mn, mx, mcv)
        return TableStatistics(table, row_count, out, datetime.now(timezone.utc).isoformat())

    def _planner_statistics(self, table: str, schema: TableSchema, reltuples: float) -> TableStatistics:
        """Large tables: read pg_stats instead of scanning. Estimated as of the last ANALYZE."""
        _, rows = self._rows(
            "SELECT attname, null_frac, n_distinct FROM pg_stats WHERE schemaname = %s AND tablename = %s",
            [self.schema, table])
        by_col = {r[0]: r for r in rows}
        n = int(reltuples)
        out: dict[str, ColumnStatistics] = {}
        for col in schema.columns:
            _, nf, nd = by_col.get(col.name, (col.name, 0.0, 0.0))
            distinct = int(nd) if nd > 0 else int(-nd * n)  # negative n_distinct is a fraction of rows
            out[col.name] = ColumnStatistics(col.name, col.data_type, distinct, int(nf * n), float(nf))
        return TableStatistics(table, n, out, datetime.now(timezone.utc).isoformat(),
                               source="PostgreSQL planner statistics (pg_stats), estimated as of the last ANALYZE; "
                                      "min/max and most-common values are not collected for large tables")

    # -- execution -----------------------------------------------------------
    def execute_readonly(self, sql: str, params: Optional[list] = None, limit: Optional[int] = None):
        return self._rows(sql, params, limit)

    def explain_query(self, sql: str) -> list[dict]:
        """EXPLAIN (FORMAT JSON), flattened into the id/parent/detail rows the SQLite path uses.

        These are planner ESTIMATES (plain EXPLAIN never runs the query)."""
        _, rows = self._rows(f"EXPLAIN (FORMAT JSON) {sql}")
        out: list[dict] = []

        def walk(node: dict, parent: int) -> None:
            nid = len(out) + 1
            out.append({"id": nid, "parent": parent, "detail": _detail(node), "node_type": node["Node Type"],
                        "estimated_rows": node.get("Plan Rows"), "estimated_total_cost": node.get("Total Cost")})
            for ch in node.get("Plans", []):
                walk(ch, nid)

        plan = rows[0][0]
        walk((plan[0] if isinstance(plan, list) else plan)["Plan"], 0)
        return out

    def explain_bytecode(self, sql: str) -> list[dict]:
        """PostgreSQL has no bytecode listing; return the text plan instead."""
        _, rows = self._rows(f"EXPLAIN {sql}")
        return [{"QUERY PLAN": r[0]} for r in rows]

    def benchmark_query(self, sql: str, warmup: Optional[int] = None, runs: Optional[int] = None) -> dict:
        warmup = self._settings.benchmark_warmup if warmup is None else warmup
        runs = self._settings.benchmark_runs if runs is None else runs
        for _ in range(max(0, warmup)):
            self.execute_readonly(sql)
        durations: list[float] = []
        row_count = 0
        for _ in range(max(1, runs)):
            start = time.perf_counter()
            _, rows = self.execute_readonly(sql)
            durations.append((time.perf_counter() - start) * 1000.0)
            row_count = len(rows)
        durations.sort()
        return {
            "label": "Application Benchmark",
            "note": "Wall-clock time including network transfer and server cache effects - NOT an optimizer cost value.",
            "warmup_runs": warmup, "measured_runs": runs, "rows_returned": row_count,
            "min_ms": round(min(durations), 4), "max_ms": round(max(durations), 4),
            "avg_ms": round(sum(durations) / len(durations), 4),
            "median_ms": round(_stats.median(durations), 4),
            "samples_ms": [round(d, 4) for d in durations],
        }

    def create_index(self, table: str, columns: list[str], unique: bool = False) -> str:
        raise PermissionError("Index creation is not supported on PostgreSQL connections: they are read-only. "
                              "Run the suggested DDL yourself with a privileged role.")


def _detail(node: dict) -> str:
    """One SQLite-EQP-style line per plan node, so the shared explain parser understands it."""
    t, rel = node["Node Type"], node.get("Relation Name")
    alias = f" AS {node['Alias']}" if node.get("Alias") and node["Alias"] != rel else ""
    if t == "Seq Scan":
        return f"SCAN {rel}{alias} (Seq Scan)"
    if t in ("Index Scan", "Index Only Scan"):
        cover = "COVERING " if t == "Index Only Scan" else ""
        return f"SEARCH {rel}{alias} USING {cover}INDEX {node['Index Name']} ({t})"
    if t == "Bitmap Heap Scan":
        return f"SEARCH {rel}{alias} (Bitmap Heap Scan)"
    if t == "Bitmap Index Scan":
        return f"Bitmap Index Scan USING INDEX {node['Index Name']}"
    extra = " ".join(f"{k}: {node[k]}" for k in ("Join Type", "Hash Cond", "Merge Cond", "Sort Key", "Group Key") if k in node)
    return f"{t} {extra}".strip()
