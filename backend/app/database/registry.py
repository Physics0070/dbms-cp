"""Engine factory for remote databases.

The current-adapter holder (``get_adapter`` / ``set_adapter``) lives in ``sqlite_adapter`` and
accepts any :class:`DatabaseAdapter`, so a remote connection is installed through the same
call. The adapter is fully built (connection opened and verified) BEFORE it replaces the
current one, so a failed attempt leaves the previous connection untouched.
"""
from __future__ import annotations

from typing import Any

from .adapter import DatabaseAdapter
from .mysql_adapter import MysqlAdapter
from .postgres_adapter import PostgresAdapter
from .sqlite_adapter import DatabaseUnavailable, set_adapter

ENGINES: dict[str, type[DatabaseAdapter]] = {"postgresql": PostgresAdapter, "mysql": MysqlAdapter}


def _mysql_params(p: dict[str, Any]) -> dict[str, Any]:
    # MySQL has no hostaddr/sslmode/schema: connect to the SSRF-checked IP directly (pinned).
    return dict(host=p.get("hostaddr") or p["host"], port=p["port"], user=p["user"],
                password=p["password"], database=p["database"])


_PARAM_MAPPERS = {"mysql": _mysql_params}


def build_adapter(engine: str, **params: Any) -> DatabaseAdapter:
    cls = ENGINES.get(engine)
    if cls is None:
        raise DatabaseUnavailable(f"Unsupported engine {engine!r}. Supported remote engines: {', '.join(ENGINES)}.")
    return cls(**_PARAM_MAPPERS.get(engine, lambda p: p)(params))


def connect_remote(engine: str, **params: Any) -> DatabaseAdapter:
    adapter = build_adapter(engine, **params)
    set_adapter(adapter)
    return adapter
