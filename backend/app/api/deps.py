"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import HTTPException

from ..database.sqlite_adapter import DatabaseUnavailable, SqliteAdapter, get_adapter


def adapter_dep() -> SqliteAdapter:
    try:
        return get_adapter()
    except DatabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
