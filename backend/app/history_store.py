"""Simple JSON-backed query-history store (app metadata; never touches the DB under test)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_LOCK = threading.Lock()
_HISTORY_PATH = Path(__file__).resolve().parent.parent / "query_history.json"


def _load() -> list[dict]:
    if _HISTORY_PATH.exists():
        try:
            return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(items: list[dict]) -> None:
    _HISTORY_PATH.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def add(result: dict) -> dict:
    with _LOCK:
        items = _load()
        opt = result.get("optimization", {})
        selected = opt.get("selected", {})
        record = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sql": result.get("sql"),
            "optimizer_version": result.get("optimizer_version"),
            "estimated_cost": opt.get("selected_total_cost"),
            "estimated_rows": selected.get("estimated_rows"),
            "candidate_count": len(opt.get("candidates", [])),
            "join_order": selected.get("join_order"),
            "benchmark": result.get("benchmark"),
            "index_recommendations": (result.get("index_advisor") or {}).get("recommendations", []),
            "result": result,  # full snapshot so it can be reopened
        }
        items.insert(0, record)
        items = items[: get_settings().history_limit]  # keep it bounded
        _save(items)
        return record


def list_summaries() -> list[dict]:
    with _LOCK:
        items = _load()
    return [{k: v for k, v in it.items() if k != "result"} for it in items]


def get(history_id: str) -> dict | None:
    with _LOCK:
        for it in _load():
            if it["id"] == history_id:
                return it
    return None
