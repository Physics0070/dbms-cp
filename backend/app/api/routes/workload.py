"""Workload CSV preview and analysis. The CSV is the raw request body; mapping is in the query string."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ... import workload as wl

router = APIRouter(tags=["workload"])


async def _body(request: Request) -> bytes:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > wl.MAX_BYTES:
            raise HTTPException(status_code=413, detail="CSV is larger than the 5 MB limit.")
    return bytes(buf)


@router.post("/api/workload/preview")
async def preview(request: Request) -> dict:
    try:
        headers, rows = wl.read_csv(await _body(request))
    except wl.WorkloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"headers": headers, "row_count": len(rows), "preview": rows[:10], "suggested_mapping": wl.suggest_mapping(headers)}


@router.post("/api/workload/analyze")
async def analyze(request: Request) -> dict:
    mapping = {f: request.query_params.get(f) for f in wl.FIELDS}
    try:
        headers, rows = wl.read_csv(await _body(request))
        return wl.analyze(headers, rows, mapping)
    except wl.WorkloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
