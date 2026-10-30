"""Saved investigations: persistence, no row data, staleness detection, export."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import investigations
from app.database.sqlite_adapter import SqliteAdapter, set_adapter

BASE = "SELECT * FROM customers WHERE customer_id < 50"
SAME = BASE + " ORDER BY customer_id"


@pytest.fixture
def client(ecommerce_adapter, tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setattr(investigations, "_PATH", tmp_path / "inv.json")
    set_adapter(ecommerce_adapter)
    yield TestClient(app)
    set_adapter(None)


def _save(client, **kw):
    cmp = client.post("/api/lab/compare", json={"baseline_sql": BASE, "candidate_sql": SAME, "runs": 3, "warmup": 0}).json()
    r = client.post("/api/investigations", json={"title": "Add ORDER BY", "rationale": "Stable order", "comparison": cmp, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_save_list_get_delete(client):
    rec = _save(client)
    assert client.get("/api/investigations").json()["items"][0]["id"] == rec["id"]
    got = client.get(f"/api/investigations/{rec['id']}").json()
    assert got["schema_changed"] is False and got["staleness_note"] is None
    assert client.delete(f"/api/investigations/{rec['id']}").status_code == 200
    assert client.get(f"/api/investigations/{rec['id']}").status_code == 404
    assert client.delete(f"/api/investigations/{rec['id']}").status_code == 404


def test_record_holds_no_result_rows_or_secrets(client, tmp_path):
    _save(client)
    text = (tmp_path / "inv.json").read_text()
    for forbidden in ('"rows"', "password", "api_key", "OPENAI"):
        assert forbidden not in text


def test_schema_change_flagged_on_reopen(client, tmp_path):
    rec = _save(client)
    other = tmp_path / "other.db"
    c = sqlite3.connect(other); c.execute("create table zzz(a int)"); c.commit(); c.close()
    set_adapter(SqliteAdapter(str(other)))
    got = client.get(f"/api/investigations/{rec['id']}").json()
    assert got["schema_changed"] is True and "differs" in got["staleness_note"]


def test_rejects_arbitrary_comparison_json(client):
    r = client.post("/api/investigations", json={"title": "x", "comparison": {"hello": 1}})
    assert r.status_code == 400


def test_markdown_export_answers_the_six_questions(client):
    rec = _save(client)
    md = client.get(f"/api/investigations/{rec['id']}/export?format=md").text
    for heading in ("What changed", "Why", "predicted", "measured", "equivalent", "Uncertainty"):
        assert heading in md
    assert client.get(f"/api/investigations/{rec['id']}/export?format=json").json()["id"] == rec["id"]
