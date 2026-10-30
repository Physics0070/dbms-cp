"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .logging_setup import configure_logging
from .middleware import HardeningMiddleware
from .api.routes import database, history, index_advisor, investigations, optimize, remote, schema, workload

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="AI-Powered Cost-Based SQL Query Optimizer",
    description="A schema-agnostic, cost-based SQL optimizer & performance analyzer over any SQLite database.",
    version=settings.optimizer_version,
)

# Added first so CORS wraps it (429/413/504 responses still carry CORS headers).
app.add_middleware(HardeningMiddleware)
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
app.include_router(investigations.router)
app.include_router(workload.router)
app.include_router(remote.router)


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


def _mount_frontend() -> None:
    """Serve the built SPA. /api/* is never shadowed; unknown paths fall back to index.html."""
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    dist = Path(settings.frontend_dist) if settings.frontend_dist else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    index = dist / "index.html"
    if not settings.serve_frontend or not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not found")
        target = (root / full_path).resolve()
        if full_path and target.is_file() and root in target.parents:  # no path traversal
            return FileResponse(target)
        return FileResponse(index)


_mount_frontend()
