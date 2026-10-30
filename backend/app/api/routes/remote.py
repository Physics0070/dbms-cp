"""Connect to a remote database server (PostgreSQL, MySQL).

The password arrives in the request body, goes straight to the driver, and is never stored,
logged or echoed back. Hosts are resolved and checked by :mod:`app.netguard` first.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr

from ...database.registry import build_adapter, connect_remote
from ...database.sqlite_adapter import DatabaseUnavailable
from ...netguard import HostRejected, resolve_host
from .database import _describe

router = APIRouter(tags=["database"])
log = logging.getLogger("querypilot.remote")


class RemoteRequest(BaseModel):
    engine: Literal["postgresql", "mysql"] = "postgresql"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password: SecretStr = SecretStr("")
    sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    schema_name: str = Field(default="public", max_length=63)


def _params(req: RemoteRequest) -> dict:
    try:
        ip = resolve_host(req.host)
    except HostRejected as e:
        log.warning("remote connect rejected engine=%s host=%s", req.engine, req.host)
        raise HTTPException(status_code=400, detail=str(e))
    return dict(host=req.host.strip(), hostaddr=ip, port=req.port, database=req.database, user=req.user,
                password=req.password.get_secret_value(), sslmode=req.sslmode, schema=req.schema_name)


def _public(info: dict, req: RemoteRequest) -> dict:
    # No credentials: host/database are shown, the user name and password are not.
    return {**info, "host": req.host.strip(), "database": req.database}


@router.post("/api/database/test-remote")
def test_remote(req: RemoteRequest) -> dict:
    """Open and close a connection without switching the active database."""
    params = _params(req)
    try:
        adapter = build_adapter(req.engine, **params)
    except DatabaseUnavailable as e:
        log.info("remote test failed engine=%s host=%s", req.engine, req.host)
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return {"ok": True, "server_version": adapter.server_version, "tables": len(adapter.get_tables()),
                "capabilities": adapter.capabilities}
    finally:
        adapter.close()


@router.post("/api/database/connect-remote")
def connect_remote_db(req: RemoteRequest) -> dict:
    """Switch to a remote database. The previous connection is kept if this fails."""
    params = _params(req)
    try:
        adapter = connect_remote(req.engine, **params)
    except DatabaseUnavailable as e:
        log.info("remote connect failed engine=%s host=%s", req.engine, req.host)
        raise HTTPException(status_code=400, detail=str(e))
    log.info("remote connected engine=%s host=%s db=%s", req.engine, req.host, req.database)
    info = _public(_describe(adapter), req)
    if info["tables"] == 0:
        info["warning"] = f"Schema {req.schema_name!r} has no tables, so there is nothing to optimize against."
    return info
