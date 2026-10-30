"""Inspect and switch the connected database."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ... import uploads
from ...database.duckdb_adapter import connect_duckdb, sniff_format
from ...config import get_settings
from ...database.sqlite_adapter import (
    DatabaseUnavailable,
    SqliteAdapter,
    connect_database,
    get_adapter,
)

router = APIRouter(tags=["database"])


class ConnectRequest(BaseModel):
    path: str


def _describe(adapter) -> dict:
    tables = adapter.get_tables()
    path = getattr(adapter, "path", None)  # remote engines have no file path
    return {
        "connected": True,
        "engine": getattr(adapter, "engine", "SQLite"),
        "name": path.name if path else adapter.database,
        "path": str(path) if path else None,
        "read_only": adapter.read_only,
        "tables": len(tables),
        "table_names": tables,
        "label": adapter.backend_name,
        "capabilities": adapter.capabilities,
    }


@router.get("/api/database")
def current_database() -> dict:
    try:
        return _describe(get_adapter())
    except DatabaseUnavailable as e:
        return {"connected": False, "reason": str(e)}


@router.post("/api/database/connect")
def connect(req: ConnectRequest) -> dict:
    """Switch to another SQLite or DuckDB database file. The previous connection is kept on failure."""
    if not get_settings().allow_path_connect:
        raise HTTPException(status_code=403, detail="Connecting by file path is disabled on this server. Upload a database instead.")
    path = req.path.strip().strip('"')
    if not path:
        raise HTTPException(status_code=400, detail="Enter the path to a SQLite database file.")
    try:
        adapter = connect_duckdb(path) if sniff_format(path) == "duckdb" else connect_database(path)
    except DatabaseUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e))
    info = _describe(adapter)
    if info["tables"] == 0:
        info["warning"] = "The database has no tables, so there is nothing to optimize against."
    return info


@router.post("/api/database/upload")
async def upload(request: Request) -> dict:
    """Upload a SQLite or DuckDB file as the raw request body. The previous connection is kept on failure."""
    try:
        adapter = await uploads.save_and_connect(request.stream())
    except uploads.UploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    info = _describe(adapter)
    info["uploaded"] = True
    info["path"] = None  # server filesystem layout is not exposed for uploads
    info["name"] = request.headers.get("x-filename", "uploaded.db")[:100]
    return info
