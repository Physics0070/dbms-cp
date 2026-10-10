"""Query history endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ... import history_store

router = APIRouter(tags=["history"])


@router.get("/api/history")
def list_history() -> dict:
    return {"items": history_store.list_summaries()}


@router.get("/api/history/{history_id}")
def get_history(history_id: str) -> dict:
    rec = history_store.get(history_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="History record not found")
    return rec
