"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .api.routes import database, history, index_advisor, optimize, schema

settings = get_settings()

app = FastAPI(
    title="AI-Powered Cost-Based SQL Query Optimizer",
    description="A schema-agnostic, cost-based SQL optimizer & performance analyzer over any SQLite database.",
    version=settings.optimizer_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(database.router)
app.include_router(schema.router)
app.include_router(optimize.router)
app.include_router(index_advisor.router)
app.include_router(history.router)


@app.get("/api/health")
def health() -> dict:
    from .database.sqlite_adapter import DatabaseUnavailable, get_adapter

    try:
        adapter = get_adapter()
    except DatabaseUnavailable as e:
        return {"status": "no_database", "reason": str(e), "database_backend": None,
                "tables": [], "openai_configured": bool(settings.openai_api_key)}
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
        "optimizer_version": settings.optimizer_version,
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
        "index_creation_enabled": settings.allow_index_creation,
    }
