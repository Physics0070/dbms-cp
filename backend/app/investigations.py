"""Saved investigations: reproducible evidence records (never secrets, never result rows)."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings
from .database.adapter import DatabaseAdapter

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parent.parent / "data" / "investigations.json"
_LIMIT = 500


def schema_fingerprint(adapter: DatabaseAdapter) -> str:
    """Hash of table/column/index names and types: changes when the schema changes, not the data."""
    parts = []
    for name, t in sorted(adapter.get_schema().items()):
        cols = ",".join(f"{c.name}:{c.data_type}" for c in t.columns)
        idx = ",".join(sorted(f"{i.name}({'|'.join(i.columns)})" for i in t.indexes))
        parts.append(f"{name}[{cols}]{{{idx}}}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def _load() -> list[dict]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def create(adapter: DatabaseAdapter, title: str, rationale: str, comparison: dict) -> dict:
    s = get_settings()
    record = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title.strip()[:200] or "Untitled investigation",
        "rationale": rationale.strip()[:4000],
        "engine": "SQLite",
        "database": getattr(getattr(adapter, "path", None), "name", "unknown"),
        "schema_fingerprint": schema_fingerprint(adapter),
        "optimizer_version": s.optimizer_version,
        "optimizer_config": {
            "cost_io_per_page": s.cost_io_per_page, "cost_cpu_per_row": s.cost_cpu_per_row,
            "cost_cpu_per_operator": s.cost_cpu_per_operator, "rows_per_page": s.rows_per_page,
        },
        "comparison": comparison,  # SQL, plan summaries, timings, equivalence: no result rows
    }
    with _LOCK:
        items = [record] + _load()
        _save(items[:_LIMIT])
    return record


def list_summaries() -> list[dict]:
    with _LOCK:
        items = _load()
    out = []
    for it in items:
        m = it["comparison"]["measured"]
        out.append({
            "id": it["id"], "created_at": it["created_at"], "title": it["title"], "database": it["database"],
            "verdict": m["verdict"], "median_change_pct": m["median_change_pct"],
            "baseline_median_ms": m["baseline"]["median_ms"], "candidate_median_ms": m["candidate"]["median_ms"],
        })
    return out


def get(inv_id: str, adapter: DatabaseAdapter | None = None) -> dict | None:
    with _LOCK:
        rec = next((i for i in _load() if i["id"] == inv_id), None)
    if rec is None:
        return None
    rec = dict(rec)
    rec["schema_changed"] = None  # unknown without a connected database
    rec["staleness_note"] = None
    if adapter is not None:
        rec["schema_changed"] = schema_fingerprint(adapter) != rec["schema_fingerprint"]
    if rec["schema_changed"] is True:
        rec["staleness_note"] = "The connected database schema differs from when this was recorded. Re-run before relying on it."
    elif rec["schema_changed"] is None:
        rec["staleness_note"] = "No database is connected, so the schema could not be compared."
    return rec


def delete(inv_id: str) -> bool:
    with _LOCK:
        items = _load()
        kept = [i for i in items if i["id"] != inv_id]
        if len(kept) == len(items):
            return False
        _save(kept)
    return True


def to_markdown(rec: dict) -> str:
    c = rec["comparison"]
    e, m, eq = c["estimated"], c["measured"], c["equivalence"]
    b, k = m["baseline"], m["candidate"]

    def est(x):
        return f"{x['cost']:.2f}" if x.get("available") and x.get("cost") is not None else "unavailable"

    verdict = {"faster": "Candidate measured faster (ranges do not overlap).",
               "slower": "Candidate measured slower (ranges do not overlap).",
               "indistinguishable": "No measurable difference (ranges overlap).",
               "not_comparable": "No verdict: results were not verified equal."}[m["verdict"]]
    pct = f" Median change: {m['median_change_pct']}% (positive = faster)." if m["median_change_pct"] is not None else ""
    lines = [
        f"# {rec['title']}", "",
        f"Recorded {rec['created_at']} on {rec['engine']} database `{rec['database']}` "
        f"(schema fingerprint `{rec['schema_fingerprint']}`, optimizer {rec['optimizer_version']}).", "",
        "## What changed", "", "Baseline:", "```sql", c["baseline_sql"], "```", "Candidate:", "```sql", c["candidate_sql"], "```", "",
        "## Why", "", rec["rationale"] or "_No rationale recorded._", "",
        "## What the optimizer predicted (estimated, unitless)", "",
        f"- Baseline cost: {est(e['baseline'])}", f"- Candidate cost: {est(e['candidate'])}", "",
        "## What the benchmark measured (wall-clock ms)", "",
        f"- Runs: {c['config']['warmup_runs']} warm-up + {c['config']['measured_runs']} measured each",
        f"- Baseline: median {b['median_ms']} ms, range {b['min_ms']}-{b['max_ms']}, IQR {b['iqr_ms']}",
        f"- Candidate: median {k['median_ms']} ms, range {k['min_ms']}-{k['max_ms']}, IQR {k['iqr_ms']}",
        f"- {verdict}{pct}", "",
        "## Were the results equivalent?", "",
        f"{'Yes' if eq.get('equal') else 'No / not verified'}: {eq.get('note', '')}", "",
        "## Uncertainty and limitations", "",
        *[f"- {x}" for x in c["caveats"]],
        "- This is historical evidence for the data and schema at the recorded time, not a guarantee of present performance.",
        "",
    ]
    return "\n".join(lines)
