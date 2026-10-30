"""Capability flags: fixed keys, truthful SQLite values, exposed by /api/database."""
from fastapi.testclient import TestClient

from app.database.adapter import DatabaseAdapter
from app.database.sqlite_adapter import set_adapter


def test_sqlite_capabilities_are_truthful(ecommerce_adapter):
    caps = ecommerce_adapter.capabilities
    assert set(caps) == set(DatabaseAdapter.CAPABILITY_KEYS)
    assert caps["native_explain"] and caps["benchmarking"] and caps["result_equivalence"]
    # SQLite has neither per-operator actuals nor native hypothetical indexes
    assert not caps["actual_plan_analysis"] and not caps["hypothetical_index"]


def test_capabilities_exposed_by_api(ecommerce_adapter):
    from app.main import app

    set_adapter(ecommerce_adapter)
    try:
        info = TestClient(app).get("/api/database").json()
    finally:
        set_adapter(None)
    assert info["capabilities"] == ecommerce_adapter.capabilities
