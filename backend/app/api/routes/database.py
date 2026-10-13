"""Inspect and switch the connected database."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...database.sqlite_adapter import (
    DatabaseUnavailable,
    SqliteAdapter,
    connect_database,
    get_adapter,
)

router = APIRouter(tags=["database"])


class ConnectRequest(BaseModel):
    path: str


def _describe(adapter: SqliteAdapter) -> dict:
    tables = adapter.get_tables()
    return {
        "connected": True,
        "engine": "SQLite",
        "name": adapter.path.name,
        "path": str(adapter.path),
        "read_only": adapter.read_only,
        "tables": len(tables),
        "table_names": tables,
        "label": adapter.backend_name,
    }


@router.get("/api/database")
def current_database() -> dict:
    try:
        return _describe(get_adapter())
    except DatabaseUnavailable as e:
        return {"connected": False, "reason": str(e)}


@router.post("/api/database/connect")
def connect(req: ConnectRequest) -> dict:
    """Switch to another SQLite database file. The previous connection is kept on failure."""
    path = req.path.strip().strip('"')
    if not path:
        raise HTTPException(status_code=400, detail="Enter the path to a SQLite database file.")
    try:
        adapter = connect_database(path)
    except DatabaseUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e))
    info = _describe(adapter)
    if info["tables"] == 0:
        info["warning"] = "The database has no tables, so there is nothing to optimize against."
    return info
