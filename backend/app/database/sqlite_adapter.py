"""SQLite adapter.

Implements :class:`DatabaseAdapter` for any SQLite database file using SQLite's own
metadata mechanisms (`sqlite_master`, `PRAGMA table_info`, `PRAGMA index_list`,
`PRAGMA index_info`, `PRAGMA foreign_key_list`) and `EXPLAIN QUERY PLAN` / `EXPLAIN`.

The optimizer talks to the :class:`DatabaseAdapter` interface only, so supporting another
engine means writing another adapter. This one is deliberately file-agnostic: nothing here
knows a table or column name, and the connected file can be switched at runtime.

Safety: files are opened **read-only** unless `ALLOW_INDEX_CREATION=true`, so an analysis
session cannot modify the database it inspects.
"""
from __future__ import annotations

import sqlite3
import statistics as _stats
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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

_SQLITE_MAGIC = b"SQLite format 3\x00"


class DatabaseUnavailable(RuntimeError):
    """The configured/requested database cannot be opened."""


def _quote_ident(name: str) -> str:
    """Quote an identifier discovered from the schema (escapes embedded quotes)."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def validate_sqlite_file(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise DatabaseUnavailable(f"Database file not found: {path}")
    try:
        with open(p, "rb") as fh:
            header = fh.read(16)
    except OSError as e:
        raise DatabaseUnavailable(f"Cannot read database file: {e}") from e
    if header != _SQLITE_MAGIC:
        raise DatabaseUnavailable(f"Not a SQLite database file: {path}")
    return p.resolve()


class SqliteAdapter(DatabaseAdapter):
    def __init__(self, path: str) -> None:
        self._settings = get_settings()
        self.path = validate_sqlite_file(path)
        # FastAPI runs sync endpoints in a thread pool, and statements here toggle
        # connection-level PRAGMAs, so every use of the shared connection is serialized.
        self._lock = threading.RLock()
        self._conn = self._connect()
        self._stats_cache: dict[str, tuple[float, TableStatistics]] = {}

    # -- connection ----------------------------------------------------------
    def _connect(self):
        try:
            if self._settings.allow_index_creation:
                conn = sqlite3.connect(str(self.path), check_same_thread=False)
            else:
                conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")  # fails fast on a corrupt file
            return conn
        except sqlite3.Error as e:
            raise DatabaseUnavailable(f"Could not open database: {e}") from e

    @property
    def backend_name(self) -> str:
        mode = "read-write" if self._settings.allow_index_creation else "read-only"
        return f"SQLite · {self.path.name} ({mode})"

    @property
    def read_only(self) -> bool:
        return not self._settings.allow_index_creation

    def _rows(self, sql: str, params: Optional[list] = None) -> tuple[list[str], list[tuple]]:
        with self._lock:
            cur = self._conn.execute(sql, params or [])
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, [tuple(r) for r in rows]

    # -- schema discovery ----------------------------------------------------
    def get_tables(self) -> list[str]:
        _, rows = self._rows(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r[0] for r in rows]

    def get_columns(self, table: str) -> list[Column]:
        _, rows = self._rows(f"PRAGMA table_info({_quote_ident(table)})")
        # cid, name, type, notnull, dflt_value, pk
        return [
            Column(
                name=r[1],
                data_type=(r[2] or "").upper() or "UNKNOWN",
                nullable=not bool(r[3]),
                primary_key=bool(r[5]),
                default=r[4],
            )
            for r in rows
        ]

    def get_indexes(self, table: str) -> list[Index]:
        _, idx_rows = self._rows(f"PRAGMA index_list({_quote_ident(table)})")
        indexes: list[Index] = []
        for row in idx_rows:
            # seq, name, unique, origin, partial
            idx_name = row[1]
            _, info = self._rows(f"PRAGMA index_info({_quote_ident(idx_name)})")
            cols = [i[2] for i in info]
            indexes.append(
                Index(
                    name=idx_name,
                    columns=cols,
                    unique=bool(row[2]),
                    origin=row[3] if len(row) > 3 else "",
                )
            )
        return indexes

    def get_foreign_keys(self, table: str) -> list[ForeignKey]:
        _, rows = self._rows(f"PRAGMA foreign_key_list({_quote_ident(table)})")
        # id, seq, table, from, to, on_update, on_delete, match
        grouped: dict[int, dict[str, Any]] = {}
        for r in rows:
            fk_id = r[0]
            g = grouped.setdefault(
                fk_id,
                {
                    "ref_table": r[2],
                    "columns": [],
                    "ref_columns": [],
                    "on_update": r[5],
                    "on_delete": r[6],
                },
            )
            g["columns"].append(r[3])
            g["ref_columns"].append(r[4])
        return [
            ForeignKey(
                columns=g["columns"],
                ref_table=g["ref_table"],
                ref_columns=g["ref_columns"],
                on_update=g["on_update"],
                on_delete=g["on_delete"],
            )
            for g in grouped.values()
        ]

    def get_table_schema(self, table: str) -> TableSchema:
        return TableSchema(
            name=table,
            columns=self.get_columns(table),
            indexes=self.get_indexes(table),
            foreign_keys=self.get_foreign_keys(table),
        )

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

    def _compute_statistics(self, table: str) -> TableStatistics:
        schema = self.get_table_schema(table)
        qt = _quote_ident(table)
        _, rc = self._rows(f"SELECT COUNT(*) FROM {qt}")
        row_count = int(rc[0][0]) if rc else 0

        col_stats: dict[str, ColumnStatistics] = {}
        for col in schema.columns:
            qc = _quote_ident(col.name)
            # One pass for distinct / null / min / max.
            _, agg = self._rows(
                f"SELECT COUNT(DISTINCT {qc}), "
                f"SUM(CASE WHEN {qc} IS NULL THEN 1 ELSE 0 END), "
                f"MIN({qc}), MAX({qc}) FROM {qt}"
            )
            distinct_count, null_count, min_v, max_v = agg[0]
            distinct_count = int(distinct_count or 0)
            null_count = int(null_count or 0)
            null_fraction = (null_count / row_count) if row_count else 0.0

            most_common: list[tuple[Any, int]] = []
            # Only build a histogram of common values for low-cardinality columns
            # (avoids scanning huge distinct sets). Threshold is data-driven.
            cfg = self._settings
            cap = max(cfg.mcv_min_distinct_cap, int(row_count * cfg.mcv_distinct_ratio) + 1)
            if 0 < distinct_count <= cap:
                _, mc = self._rows(
                    f"SELECT {qc}, COUNT(*) AS c FROM {qt} "
                    f"WHERE {qc} IS NOT NULL GROUP BY {qc} "
                    f"ORDER BY c DESC LIMIT {int(cfg.mcv_limit)}"
                )
                most_common = [(m[0], int(m[1])) for m in mc]

            col_stats[col.name] = ColumnStatistics(
                column=col.name,
                data_type=col.data_type,
                distinct_count=distinct_count,
                null_count=null_count,
                null_fraction=null_fraction,
                min_value=min_v,
                max_value=max_v,
                most_common=most_common,
            )

        return TableStatistics(
            table=table,
            row_count=row_count,
            columns=col_stats,
            collected_at=datetime.now(timezone.utc).isoformat(),
        )

    def invalidate_stats(self, table: Optional[str] = None) -> None:
        if table is None:
            self._stats_cache.clear()
        else:
            self._stats_cache.pop(table, None)

    # -- execution -----------------------------------------------------------
    def execute_readonly(
        self, sql: str, params: Optional[list] = None, limit: Optional[int] = None
    ) -> tuple[list[str], list[tuple]]:
        # Defence in depth: the safety validator gates callers, but we also set
        # query_only so the engine itself refuses writes. The lock keeps the PRAGMA
        # toggle from interleaving with other requests on the shared connection.
        with self._lock:
            try:
                self._conn.execute("PRAGMA query_only = ON")
            except sqlite3.Error:
                pass
            try:
                cols, rows = self._rows(sql, params)
            finally:
                try:
                    self._conn.execute("PRAGMA query_only = OFF")
                except sqlite3.Error:
                    pass
        if limit is not None:
            rows = rows[:limit]
        return cols, rows

    def explain_query(self, sql: str) -> list[dict]:
        _, rows = self._rows(f"EXPLAIN QUERY PLAN {sql}")
        # id, parent, notused, detail
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "parent": r[1],
                    "detail": r[3] if len(r) > 3 else str(r[-1]),
                }
            )
        return out

    def explain_bytecode(self, sql: str) -> list[dict]:
        cols, rows = self._rows(f"EXPLAIN {sql}")
        return [dict(zip(cols, r)) for r in rows]

    def benchmark_query(
        self, sql: str, warmup: Optional[int] = None, runs: Optional[int] = None
    ) -> dict:
        warmup = self._settings.benchmark_warmup if warmup is None else warmup
        runs = self._settings.benchmark_runs if runs is None else runs
        # Warm-up runs are executed and discarded.
        for _ in range(max(0, warmup)):
            self.execute_readonly(sql)

        durations_ms: list[float] = []
        row_count = 0
        for _ in range(max(1, runs)):
            start = time.perf_counter()
            _, rows = self.execute_readonly(sql)
            elapsed = (time.perf_counter() - start) * 1000.0
            durations_ms.append(elapsed)
            row_count = len(rows)

        durations_ms.sort()
        return {
            "label": "Application Benchmark",
            "note": "Wall-clock execution time - NOT an optimizer cost value.",
            "warmup_runs": warmup,
            "measured_runs": runs,
            "rows_returned": row_count,
            "min_ms": round(min(durations_ms), 4),
            "max_ms": round(max(durations_ms), 4),
            "avg_ms": round(sum(durations_ms) / len(durations_ms), 4),
            "median_ms": round(_stats.median(durations_ms), 4),
            "samples_ms": [round(d, 4) for d in durations_ms],
        }

    # -- explicit index creation (opt-in; validated identifiers only) ---------
    def create_index(self, table: str, columns: list[str], unique: bool = False) -> str:
        """Create a real index — only when ALLOW_INDEX_CREATION is enabled.

        The database is otherwise opened read-only. Identifiers are escaped, and the
        table/columns must exist in the discovered schema.
        """
        if self.read_only:
            raise PermissionError(
                "Index creation is disabled: the database is opened read-only. "
                "Set ALLOW_INDEX_CREATION=true and restart to enable it."
            )
        if table not in set(self.get_tables()):
            raise ValueError(f"Unknown table: {table!r}")
        table_cols = {c.name for c in self.get_columns(table)}
        for col in columns:
            if col not in table_cols:
                raise ValueError(f"Unknown column {col!r} on table {table!r}")
        qcols = ", ".join(_quote_ident(c) for c in columns)
        idx_name = f"idx_{table}_{'_'.join(columns)}"
        uniq = "UNIQUE " if unique else ""
        ddl = (
            f"CREATE {uniq}INDEX IF NOT EXISTS {_quote_ident(idx_name)} "
            f"ON {_quote_ident(table)} ({qcols})"
        )
        with self._lock:
            self._conn.execute(ddl)
            self._conn.commit()
        self.invalidate_stats(table)
        return ddl


# ---------------------------------------------------------------------------
# The currently connected database (switchable at runtime).
# ---------------------------------------------------------------------------
_CURRENT: Optional[SqliteAdapter] = None
_CURRENT_LOCK = threading.Lock()


def get_adapter() -> SqliteAdapter:
    """Return the connected adapter, opening the configured default on first use."""
    global _CURRENT
    with _CURRENT_LOCK:
        if _CURRENT is None:
            _CURRENT = SqliteAdapter(get_settings().database_path)
        return _CURRENT


def connect_database(path: str) -> SqliteAdapter:
    """Validate and switch to another SQLite file; the previous one stays if this fails.

    The old adapter is not closed explicitly: requests already running on it must be able
    to finish. Its connection is released once nothing references it any more.
    """
    global _CURRENT
    new = SqliteAdapter(path)
    with _CURRENT_LOCK:
        _CURRENT = new
    return new


def set_adapter(adapter: Optional[SqliteAdapter]) -> None:
    """Install an adapter directly (used by tests)."""
    global _CURRENT
    with _CURRENT_LOCK:
        _CURRENT = adapter
