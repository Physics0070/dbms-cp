"""Workload analysis from an uploaded CSV of recorded queries.

Only fields present in the file are used. Nothing is invented: no CPU, cache-hit or live
metrics. Queries are grouped by fingerprint (SQL with literals replaced by `?`).

Ranking score (transparent): the group's total recorded execution time in ms
(`sum(total_ms)`; if a row has no total but has avg_ms and count, total = avg_ms * count and
the group is flagged `derived_total`). If the file has no timing columns at all, groups are
ranked by execution count and `score_basis` says so.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

import sqlglot
from sqlglot import exp

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 100_000
FIELDS = ("sql", "count", "total_ms", "avg_ms", "errors", "rows")
_HINTS = {
    "sql": ("query", "sql", "statement", "query_text", "text"),
    "count": ("calls", "count", "executions", "exec_count", "frequency"),
    "total_ms": ("total_time", "total_ms", "total_exec_time", "total_time_ms"),
    "avg_ms": ("mean_time", "avg_ms", "mean_exec_time", "avg_time", "average_ms"),
    "errors": ("errors", "error_count", "failures"),
    "rows": ("rows", "rows_returned", "rows_examined", "rows_sent"),
}


class WorkloadError(ValueError):
    """Bad upload or mapping; message is safe to show."""


def read_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not data.strip():
        raise WorkloadError("The CSV file is empty.")
    if len(data) > MAX_BYTES:
        raise WorkloadError(f"CSV is larger than the {MAX_BYTES // (1024 * 1024)} MB limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise WorkloadError("The file is not valid UTF-8 text.")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    if not headers:
        raise WorkloadError("No header row found; the first line must name the columns.")
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "") for k, v in r.items() if k})
        if len(rows) > MAX_ROWS:
            raise WorkloadError(f"More than {MAX_ROWS} rows; split the file.")
    if not rows:
        raise WorkloadError("The CSV has a header but no data rows.")
    return headers, rows


def suggest_mapping(headers: list[str]) -> dict[str, Optional[str]]:
    low = {h.lower(): h for h in headers}
    return {f: next((low[a] for a in _HINTS[f] if a in low), None) for f in FIELDS}


def fingerprint(sql: str) -> str:
    """Normalize literals to `?` and whitespace/case so repeated patterns group together."""
    try:
        tree = sqlglot.parse_one(sql)
        tree = tree.transform(lambda n: exp.Placeholder() if isinstance(n, exp.Literal) else n)
        return tree.sql()
    except Exception:
        s = re.sub(r"'(?:[^']|'')*'", "?", sql)
        s = re.sub(r"\b\d+(?:\.\d+)?\b", "?", s)
        return re.sub(r"\s+", " ", s).strip()


def _num(v: str) -> Optional[float]:
    v = (v or "").strip().replace(",", "")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def analyze(headers: list[str], rows: list[dict[str, str]], mapping: dict[str, Optional[str]]) -> dict:
    mapping = {f: (mapping.get(f) or None) for f in FIELDS}
    if not mapping["sql"]:
        raise WorkloadError("Map the SQL column: it is required.")
    for f, col in mapping.items():
        if col and col not in headers:
            raise WorkloadError(f"Mapped column '{col}' (for {f}) is not in the file. Columns: {', '.join(headers)}")

    groups: dict[str, dict] = {}
    skipped: list[dict] = []
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        sql = r.get(mapping["sql"], "").strip().rstrip(";")
        if not sql:
            skipped.append({"line": i, "reason": "empty SQL"}); continue
        vals = {f: (_num(r.get(mapping[f], "")) if mapping[f] else None) for f in FIELDS if f != "sql"}
        for f, col in mapping.items():
            if f != "sql" and col and r.get(col, "").strip() and vals[f] is None:
                skipped.append({"line": i, "reason": f"'{col}' is not a number: {r[col][:30]!r}"}); vals = None; break
        if vals is None:
            continue
        cnt = vals["count"] if vals["count"] is not None else 1.0
        total, derived = vals["total_ms"], False
        if total is None and vals["avg_ms"] is not None:
            total, derived = vals["avg_ms"] * cnt, True
        g = groups.setdefault(fingerprint(sql), {
            "fingerprint": fingerprint(sql), "example_sql": sql, "executions": 0.0, "total_ms": None,
            "errors": None, "rows": None, "derived_total": False, "source_lines": [],
        })
        g["executions"] += cnt
        for key, v in (("total_ms", total), ("errors", vals["errors"]), ("rows", vals["rows"])):
            if v is not None:
                g[key] = (g[key] or 0.0) + v
        g["derived_total"] |= derived
        g["source_lines"].append(i)

    if not groups:
        raise WorkloadError("No usable rows. " + (f"First problem: line {skipped[0]['line']}: {skipped[0]['reason']}." if skipped else ""))
    timed = any(g["total_ms"] is not None for g in groups.values())
    for g in groups.values():
        g["avg_ms"] = g["total_ms"] / g["executions"] if g["total_ms"] is not None and g["executions"] else None
        g["score"] = (g["total_ms"] or 0.0) if timed else g["executions"]
        g["source_lines"] = g["source_lines"][:20]
    ranked = sorted(groups.values(), key=lambda g: g["score"], reverse=True)
    grand = sum(g["score"] for g in ranked) or 1.0
    for rank, g in enumerate(ranked, 1):
        g["rank"], g["share_pct"] = rank, round(100 * g["score"] / grand, 2)
    return {
        "score_basis": "total recorded execution time (ms)" if timed else "execution count (file has no timing column)",
        "groups": ranked, "input_rows": len(rows), "skipped": skipped[:50], "skipped_count": len(skipped),
        "mapping": mapping,
    }
