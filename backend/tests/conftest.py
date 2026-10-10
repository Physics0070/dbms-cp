"""Test fixtures.

Builds TWO independent databases — the e-commerce demo schema and a completely
unrelated 'library' schema — so the whole suite can prove the optimizer is
schema-agnostic.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database.turso_adapter import TursoAdapter  # noqa: E402
from seed.generate import seed_ecommerce, seed_library  # noqa: E402


def _make_adapter(db_path: Path) -> TursoAdapter:
    os.environ["TURSO_DATABASE_URL"] = ""
    os.environ["LOCAL_DB_PATH"] = str(db_path)
    get_settings.cache_clear()
    return TursoAdapter()


@pytest.fixture(scope="session")
def ecommerce_adapter(tmp_path_factory) -> TursoAdapter:
    db = tmp_path_factory.mktemp("ec") / "ecommerce.db"
    conn = sqlite3.connect(db)
    seed_ecommerce(conn, seed=7, customer_count=300, order_count=1200, product_count=150)
    conn.close()
    return _make_adapter(db)


@pytest.fixture(scope="session")
def library_adapter(tmp_path_factory) -> TursoAdapter:
    db = tmp_path_factory.mktemp("lib") / "library.db"
    conn = sqlite3.connect(db)
    seed_library(conn, seed=7, scale=1)
    conn.close()
    return _make_adapter(db)
