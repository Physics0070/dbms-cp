"""Index advisor + explicit (opt-in) index creation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...database.turso_adapter import TursoAdapter
from ...optimizer.index_advisor import IndexAdvisor
from ...optimizer.parser import parse_query
from ...optimizer.safety import UnsafeQueryError
from ...optimizer.statistics import StatisticsProvider
from ..deps import adapter_dep

router = APIRouter(tags=["index-advisor"])


class SqlRequest(BaseModel):
    sql: str


class CreateIndexRequest(BaseModel):
    table: str
    columns: list[str]
    unique: bool = False
    confirm: bool = False  # must be explicitly true to actually create


@router.post("/api/index-advisor")
def advise(req: SqlRequest, adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    try:
        schema = adapter.get_schema()
        parsed = parse_query(req.sql, schema)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse failed: {e}")
    stats = StatisticsProvider(adapter)
    return IndexAdvisor(parsed, stats, schema).recommend()


@router.post("/api/index/create")
def create_index(req: CreateIndexRequest, adapter: TursoAdapter = Depends(adapter_dep)) -> dict:
    # This is the ONLY write path exposed, and only when the user explicitly confirms.
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="Index creation requires explicit confirmation (set confirm=true).",
        )
    try:
        ddl = adapter.create_index(req.table, req.columns, req.unique)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Index creation failed: {e}")
    return {"created": True, "ddl": ddl}
