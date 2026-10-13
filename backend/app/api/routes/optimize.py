"""Optimize / validate / explain / benchmark / copilot endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...database.sqlite_adapter import SqliteAdapter
from ...optimizer import copilot
from ...optimizer.explain_parser import parse_explain_query_plan
from ...optimizer.orchestrator import optimize_query
from ...optimizer.safety import UnsafeQueryError, validate_readonly
from ... import history_store
from ..deps import adapter_dep

router = APIRouter(tags=["optimize"])


class OptimizeRequest(BaseModel):
    sql: str
    benchmark: bool = False
    index_advisor: bool = True
    save_history: bool = True


class SqlRequest(BaseModel):
    sql: str


class BenchmarkRequest(BaseModel):
    sql: str
    warmup: int | None = None   # None -> configured default (BENCHMARK_WARMUP)
    runs: int | None = None     # None -> configured default (BENCHMARK_RUNS)


class CopilotRequest(BaseModel):
    sql: str
    question: str | None = None


@router.post("/api/validate")
def validate(req: SqlRequest) -> dict:
    try:
        validate_readonly(req.sql)
        return {"valid": True, "message": "Query is a valid read-only SELECT."}
    except UnsafeQueryError as e:
        return {"valid": False, "message": str(e)}


@router.post("/api/optimize")
def optimize(req: OptimizeRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    try:
        result = optimize_query(
            adapter, req.sql, run_benchmark=req.benchmark, run_index_advisor=req.index_advisor
        )
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Optimization failed: {e}")
    if req.save_history:
        record = history_store.add(result)
        result["history_id"] = record["id"]
    return result


@router.post("/api/explain")
def explain(req: SqlRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    try:
        validate_readonly(req.sql)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        eqp_rows = adapter.explain_query(req.sql)
        parsed = parse_explain_query_plan(eqp_rows)
        try:
            bytecode = adapter.explain_bytecode(req.sql)
        except Exception:
            bytecode = []
        return {"query_plan": parsed, "bytecode": bytecode}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"EXPLAIN failed: {e}")


@router.post("/api/benchmark")
def benchmark(req: BenchmarkRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    try:
        validate_readonly(req.sql)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return adapter.benchmark_query(req.sql, warmup=req.warmup, runs=req.runs)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Benchmark failed: {e}")


@router.post("/api/copilot")
def ai_copilot(req: CopilotRequest, adapter: SqliteAdapter = Depends(adapter_dep)) -> dict:
    try:
        result = optimize_query(adapter, req.sql, run_benchmark=False, run_index_advisor=True)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Copilot preparation failed: {e}")
    return copilot.explain(result, req.question)
