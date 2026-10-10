"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .api.routes import history, index_advisor, optimize, schema

settings = get_settings()

app = FastAPI(
    title="AI-Powered Cost-Based SQL Query Optimizer",
    description="A schema-agnostic, cost-based SQL optimizer & performance analyzer over Turso/libSQL.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(schema.router)
app.include_router(optimize.router)
app.include_router(index_advisor.router)
app.include_router(history.router)


@app.get("/api/health")
def health() -> dict:
    from .database.turso_adapter import get_adapter

    adapter = get_adapter()
    return {
        "status": "ok",
        "database_backend": adapter.backend_name,
        "tables": adapter.get_tables(),
        "openai_configured": bool(settings.openai_api_key),
    }


@app.get("/api/config")
def config() -> dict:
    """Non-secret configuration surfaced to the dashboard (never exposes secrets)."""
    return {
        "optimizer_version": "1.0.0",
        "cost_model": {
            "cost_io_per_page": settings.cost_io_per_page,
            "cost_cpu_per_row": settings.cost_cpu_per_row,
            "cost_cpu_per_operator": settings.cost_cpu_per_operator,
            "rows_per_page": settings.rows_per_page,
        },
        "selectivity_defaults": {
            "equality": settings.default_eq_selectivity,
            "range": settings.default_range_selectivity,
            "join": settings.default_join_selectivity,
        },
        "openai_configured": bool(settings.openai_api_key),
    }
