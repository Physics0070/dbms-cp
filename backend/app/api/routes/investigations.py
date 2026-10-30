"""Benchmark lab comparison and saved investigations."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ... import benchmark_lab, investigations
from ...database.sqlite_adapter import DatabaseUnavailable, SqliteAdapter, get_adapter
from ...optimizer.safety import UnsafeQueryError
from ..deps import adapter_dep

router = APIRouter(tags=["lab"])


class CompareRequest(BaseModel):
    baseline_sql: str
    candidate_sql: str
    warmup: int | None = None
    runs: int | None = None


class SaveRequest(BaseModel):
    title: str = ""
    rationale: str = ""
    comparison: dict


@router.post("/api/lab/compare")
def lab_compare(req: CompareRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    try:
        return benchmark_lab.compare(adapter, req.baseline_sql, req.candidate_sql, req.warmup, req.runs)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Comparison failed: {e}")


@router.post("/api/investigations")
def save_investigation(req: SaveRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    c = req.comparison
    try:  # a saved record must be a real lab result, not arbitrary client JSON
        c["measured"]["verdict"], c["measured"]["baseline"]["median_ms"], c["measured"]["candidate"]["median_ms"]
        c["estimated"]["baseline"], c["equivalence"], c["baseline_sql"], c["candidate_sql"], c["caveats"], c["config"]
    except (KeyError, TypeError):
        raise HTTPException(status_code=400, detail="comparison must be the result of /api/lab/compare.")
    return investigations.create(adapter, req.title, req.rationale, c)


@router.get("/api/investigations")
def list_investigations() -> dict:
    return {"items": investigations.list_summaries()}


@router.get("/api/investigations/{inv_id}")
def get_investigation(inv_id: str) -> dict:
    try:
        adapter = get_adapter()
    except DatabaseUnavailable:
        adapter = None
    rec = investigations.get(inv_id, adapter)
    if rec is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return rec


@router.delete("/api/investigations/{inv_id}")
def delete_investigation(inv_id: str) -> dict:
    if not investigations.delete(inv_id):
        raise HTTPException(status_code=404, detail="Investigation not found")
    return {"deleted": inv_id}


@router.get("/api/investigations/{inv_id}/export", response_model=None)
def export_investigation(inv_id: str, format: Literal["json", "md"] = "md"):
    rec = investigations.get(inv_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if format == "json":
        return rec
    return PlainTextResponse(investigations.to_markdown(rec), media_type="text/markdown")
