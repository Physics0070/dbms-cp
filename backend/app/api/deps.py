"""Shared FastAPI dependencies."""
from __future__ import annotations

from ..database.turso_adapter import TursoAdapter, get_adapter


def adapter_dep() -> TursoAdapter:
    return get_adapter()
