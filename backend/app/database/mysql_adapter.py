"""MySQL / MariaDB adapter (PyMySQL).

Schema, index and foreign-key discovery come from `information_schema`; statistics are
computed from the live tables (exact when the table is small, `information_schema`
estimates when it is large); plans come from `EXPLAIN FORMAT=JSON` and, where the server
supports it, `EXPLAIN ANALYZE`.

Safety: the session is put in `READ ONLY` transaction mode (the server then rejects writes
with error 1792), multi-statement queries are not enabled, and `max_execution_time` bounds
SELECT runtime. Prefer a read-only MySQL account as well - session flags are defence in depth.

Credentials are never stored on the adapter beyond the open connection and never appear in
error messages raised from here.
"""
from __future__ import annotations

import json
import statistics as _stats
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import pymysql
import pymysql.cursors

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
from .sqlite_adapter import DatabaseUnavailable

# Above this many rows, per-column statistics come from information_schema instead of full scans.
EXACT_STATS_ROW_LIMIT = 200_000
CONNECT_TIMEOUT_S = 8
READ_TIMEOUT_S = 60
MAX_EXECUTION_MS = 30_000


def _q(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return "`" + name.replace("`", "``") + "`"


def _py(v: Any) -> Any:
    """JSON-friendly scalar."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


class MysqlAdapter(DatabaseAdapter):
    engine = "MySQL"
    dialect = "mysql"   # sqlglot dialect: backtick quoting, MySQL-style SQL emitted by the rewriter

    def __init__(self, host: str, port: int, user: str, password: str, database: str) -> None:
        self._settings = get_settings()
        self.host, self.port, self.user, self.database = host, int(port), user, database
        self._lock = threading.RLock()
        self._stats_cache: dict[str, tuple[float, TableStatistics]] = {}
        try:
            self._conn = pymysql.connect(
                host=host, port=self.port, user=user, password=password, database=database,
                connect_timeout=CONNECT_TIMEOUT_S, read_timeout=READ_TIMEOUT_S,
                autocommit=True, charset="utf8mb4",
            )
            self._harden()
        except pymysql.MySQLError as e:
            # Only the server's message is surfaced - it never contains the password.
            raise DatabaseUnavailable(f"Could not connect to MySQL at {host}:{self.port}: {_msg(e)}") from None
        except OSError as e:
            raise DatabaseUnavailable(f"Could not reach MySQL at {host}:{self.port}: {e.strerror or e}") from None
        self._is_mariadb = "mariadb" in self._conn.get_server_info().lower()

    def _harden(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            for stmt in (  # MySQL: ms, MariaDB: seconds - whichever the server knows
                f"SET SESSION max_execution_time = {MAX_EXECUTION_MS}",
                f"SET SESSION max_statement_time = {MAX_EXECUTION_MS // 1000}",
            ):
                try:
                    cur.execute(stmt)
                except pymysql.MySQLError:
                    pass

    # -- identity ------------------------------------------------------------
    @property
    def backend_name(self) -> str:
        flavour = "MariaDB" if self._is_mariadb else "MySQL"
        return f"{flavour} · {self.database}@{self.host}:{self.port} (read-only session)"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def server_version(self) -> str:
        return self._conn.get_server_info()

    @property
    def capabilities(self) -> dict[str, bool]:
        # Only what is implemented AND exercised against a real server here. The rewriter and
        # join-order rewrite is not offered (MySQL ignores the CROSS JOIN hint); result equivalence
        # is exercised by the lab compare tests against MySQL 8.0.
        return {
            **super().capabilities,
            "schema_introspection": True, "index_discovery": True, "statistics": True,
            "native_explain": True, "actual_plan_analysis": not self._is_mariadb,
            "benchmarking": True, "hypothetical_index": False,
            "sql_rewrite": False, "result_equivalence": True,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except pymysql.MySQLError:
                pass

    # -- plumbing ------------------------------------------------------------
    def _rows(self, sql: str, params: Optional[list] = None, limit: Optional[int] = None):
        with self._lock:
            self._conn.ping(reconnect=False)
            with self._conn.cursor(pymysql.cursors.SSCursor) as cur:  # streaming: LIMIT cannot buffer a huge result
                cur.execute(sql, params)
                rows = cur.fetchmany(limit) if limit is not None else cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
                return cols, [tuple(r) for r in rows]

    # -- schema discovery ----------------------------------------------------
    def get_tables(self) -> list[str]:
        _, rows = self._rows(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME", [self.database])
        return [r[0] for r in rows]

    def get_columns(self, table: str) -> list[Column]:
        _, rows = self._rows(
            "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION", [self.database, table])
        return [Column(r[0], _s(r[1]), r[2] == "YES", r[3] == "PRI", None if r[4] is None else _s(r[4])) for r in rows]

    def get_indexes(self, table: str) -> list[Index]:
        _, rows = self._rows(
            "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME IS NOT NULL "
            "ORDER BY INDEX_NAME, SEQ_IN_INDEX", [self.database, table])
        out: dict[str, Index] = {}
        for name, col, non_unique in rows:
            name = _s(name)
            if name not in out:
                out[name] = Index(name, [], int(non_unique) == 0, "pk" if name == "PRIMARY" else ("u" if int(non_unique) == 0 else "c"))
            out[name].columns.append(_s(col))
        return list(out.values())

    def get_foreign_keys(self, table: str) -> list[ForeignKey]:
        _, rows = self._rows(
            "SELECT k.CONSTRAINT_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME, "
            "r.UPDATE_RULE, r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
            "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME AND r.TABLE_NAME = k.TABLE_NAME "
            "WHERE k.TABLE_SCHEMA = %s AND k.TABLE_NAME = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION", [self.database, table])
        out: dict[str, ForeignKey] = {}
        for cname, col, rtab, rcol, upd, dele in rows:
            fk = out.setdefault(_s(cname), ForeignKey([], _s(rtab), [], _s(upd), _s(dele)))
            fk.columns.append(_s(col))
            fk.ref_columns.append(_s(rcol))
        return list(out.values())

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
        if table is None:
            self._stats_cache.clear()
        else:
            self._stats_cache.pop(table, None)

    def _compute_statistics(self, table: str) -> TableStatistics:
        schema = self.get_table_schema(table)
        qt = _q(table)
        _, est = self._rows("SELECT TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                            [self.database, table])
        estimated_rows = int(est[0][0] or 0) if est else 0
        exact = estimated_rows <= EXACT_STATS_ROW_LIMIT   # TABLE_ROWS is itself approximate for InnoDB
        if exact:
            _, rc = self._rows(f"SELECT COUNT(*) FROM {qt}")
            row_count = int(rc[0][0])
        else:
            row_count = estimated_rows

        col_stats: dict[str, ColumnStatistics] = {}
        cfg = self._settings
        if exact:
            for col in schema.columns:
                qc = _q(col.name)
                _, agg = self._rows(
                    f"SELECT COUNT(DISTINCT {qc}), SUM({qc} IS NULL), MIN({qc}), MAX({qc}) FROM {qt}")
                distinct, nulls, mn, mx = agg[0]
                distinct, nulls = int(distinct or 0), int(nulls or 0)
                mcv: list[tuple[Any, int]] = []
                cap = max(cfg.mcv_min_distinct_cap, int(row_count * cfg.mcv_distinct_ratio) + 1)
                if 0 < distinct <= cap:
                    _, mc = self._rows(
                        f"SELECT {qc}, COUNT(*) AS c FROM {qt} WHERE {qc} IS NOT NULL GROUP BY {qc} "
                        f"ORDER BY c DESC LIMIT {int(cfg.mcv_limit)}")
                    mcv = [(_py(m[0]), int(m[1])) for m in mc]
                col_stats[col.name] = ColumnStatistics(
                    col.name, col.data_type, distinct, nulls, (nulls / row_count) if row_count else 0.0,
                    _py(mn), _py(mx), mcv)
            source = "Computed exactly from the connected database"
        else:
            # Large table: only columns that lead an index have a cardinality estimate. Null counts,
            # min/max and common values were NOT measured, so those columns are left out of nothing -
            # they are reported with distinct_count only and zero nulls (documented in `source`).
            _, card = self._rows(
                "SELECT COLUMN_NAME, MAX(CARDINALITY) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND SEQ_IN_INDEX=1 GROUP BY COLUMN_NAME",
                [self.database, table])
            by_col = {_s(c): int(v or 0) for c, v in card}
            for col in schema.columns:
                if col.name in by_col:
                    col_stats[col.name] = ColumnStatistics(col.name, col.data_type, by_col[col.name], 0, 0.0)
            source = (f"Estimated from information_schema (table has ~{estimated_rows:,} rows, over the "
                      f"{EXACT_STATS_ROW_LIMIT:,}-row exact limit): row count and index cardinalities only; "
                      "null fractions, min/max and common values were not measured")
        return TableStatistics(table, row_count, col_stats, datetime.now(timezone.utc).isoformat(), source)

    # -- execution -----------------------------------------------------------
    def execute_readonly(
        self, sql: str, params: Optional[list] = None, limit: Optional[int] = None
    ) -> tuple[list[str], list[tuple]]:
        with self._lock:
            self._conn.ping(reconnect=False)
            with self._conn.cursor() as cur:   # re-asserted on every call
                cur.execute("SET SESSION TRANSACTION READ ONLY")
            cols, rows = self._rows(sql, params, limit)
        return cols, [tuple(_py(v) for v in r) for r in rows]

    def explain_query(self, sql: str) -> list[dict]:
        """`EXPLAIN FORMAT=JSON`, flattened to rows of {id, parent, detail, node}.

        `detail` uses the SCAN/SEARCH ... USING INDEX wording the shared explain parser reads;
        `node` carries the engine's own fields (rows examined, cost info, attached conditions).
        """
        _, rows = self._rows(f"EXPLAIN FORMAT=JSON {sql}")
        doc = json.loads(rows[0][0])
        out: list[dict] = []
        _flatten(doc.get("query_block", doc), None, out)
        return out

    def explain_bytecode(self, sql: str) -> list[dict]:
        """MySQL has no bytecode form; the closest low-level view is the iterator tree."""
        cols, rows = self._rows(f"EXPLAIN FORMAT=TREE {sql}")
        return [dict(zip(cols, r)) for r in rows]

    def explain_analyze(self, sql: str) -> str:
        """`EXPLAIN ANALYZE`: EXECUTES the query and returns actual rows/timings per iterator (MySQL >= 8.0.18)."""
        if self._is_mariadb:
            raise DatabaseUnavailable("EXPLAIN ANALYZE is not supported on MariaDB through this adapter.")
        _, rows = self._rows(f"EXPLAIN ANALYZE {sql}")
        return "\n".join(str(r[0]) for r in rows)

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
            "note": "Wall-clock execution time including network round-trips - NOT an optimizer cost value.",
            "warmup_runs": warmup, "measured_runs": runs, "rows_returned": row_count,
            "min_ms": round(min(durations), 4), "max_ms": round(max(durations), 4),
            "avg_ms": round(sum(durations) / len(durations), 4),
            "median_ms": round(_stats.median(durations), 4),
            "samples_ms": [round(d, 4) for d in durations],
        }


def connect_mysql(host: str, port: int, user: str, password: str, database: str) -> MysqlAdapter:
    """Factory used by the connection registry."""
    return MysqlAdapter(host, port, user, password, database)


# -- helpers -------------------------------------------------------------------
def _s(v: Any) -> str:
    return v.decode() if isinstance(v, (bytes, bytearray)) else str(v)


def _msg(e: pymysql.MySQLError) -> str:
    return str(e.args[1]) if len(e.args) > 1 else str(e)


def _flatten(node: Any, parent: Optional[int], out: list[dict]) -> None:
    """Walk EXPLAIN FORMAT=JSON; every `table` object becomes one step, wrappers become structure steps."""
    if isinstance(node, list):
        for n in node:
            _flatten(n, parent, out)
        return
    if not isinstance(node, dict):
        return
    cur = parent
    if "table_name" in node:
        out.append({"id": len(out), "parent": parent, "detail": _table_detail(node), "node": node})
        cur = len(out) - 1
    else:
        for key in ("ordering_operation", "grouping_operation", "duplicates_removal", "buffer_result"):
            if key in node:
                using_temp = node[key].get("using_temporary_table")
                filesort = node[key].get("using_filesort")
                label = {"ordering_operation": "ORDER BY", "grouping_operation": "GROUP BY"}.get(key, key.upper())
                extra = " USE TEMP B-TREE" if (using_temp or filesort) else ""
                out.append({"id": len(out), "parent": parent, "detail": f"{label}{extra}", "node": {"operation": key, **{k: v for k, v in node[key].items() if not isinstance(v, (dict, list))}}})
                cur = len(out) - 1
                break
    for k, v in node.items():
        if isinstance(v, (dict, list)) and k not in _SKIP_KEYS:
            _flatten(v, cur, out)


_SKIP_KEYS = ("used_columns", "key_length", "ref", "possible_keys", "used_key_parts", "cost_info")


def _table_detail(t: dict) -> str:
    name, access, key = t["table_name"], t.get("access_type", "ALL"), t.get("key")
    if access == "ALL":
        return f"SCAN {name}"
    if key:
        covering = " COVERING" if t.get("using_index") else ""
        return f"SEARCH {name} USING{covering} INDEX {key} ({access})"
    return f"SEARCH {name} ({access})"
