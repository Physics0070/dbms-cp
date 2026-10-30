"""Upload security: size cap, format validation, safe naming, previous connection preserved."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.sqlite_adapter import get_adapter, set_adapter


@pytest.fixture
def client(ecommerce_adapter, tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    get_settings.cache_clear()
    set_adapter(ecommerce_adapter)
    yield TestClient(app)
    set_adapter(None)
    get_settings.cache_clear()


def _db_bytes(tmp_path, rows=2):
    p = tmp_path / "x.db"
    c = sqlite3.connect(p)
    c.execute("create table t(id integer primary key, v text)")
    c.executemany("insert into t(v) values (?)", [("a" * 200,)] * rows)
    c.commit(); c.close()
    return p.read_bytes()


def test_valid_upload_switches_database_with_safe_name(client, tmp_path):
    r = client.post("/api/database/upload", content=_db_bytes(tmp_path), headers={"x-filename": "../../evil.db"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["table_names"] == ["t"] and body["read_only"] and body["path"] is None
    stored = get_adapter().path
    assert stored.parent == (tmp_path / "up").resolve() and len(stored.stem) == 32  # server-generated name
    assert client.get("/api/health").json()["tables"] == ["t"]


@pytest.mark.parametrize("payload,msg", [(b"", "empty"), (b"not a database" * 50, "not a SQLite")])
def test_invalid_upload_rejected_and_previous_connection_kept(client, ecommerce_adapter, payload, msg):
    r = client.post("/api/database/upload", content=payload)
    assert r.status_code == 400 and msg in r.json()["detail"]
    assert get_adapter() is ecommerce_adapter


def test_corrupt_database_rejected(client, ecommerce_adapter, tmp_path):
    data = _db_bytes(tmp_path, rows=200)  # several pages
    corrupt = data[:4096] + b"\xff" * (len(data) - 4096)  # keep header + page 1, trash the rest
    r = client.post("/api/database/upload", content=corrupt)
    assert r.status_code == 400
    assert get_adapter() is ecommerce_adapter
    assert list((tmp_path / "up").glob("*")) == []  # temp file cleaned up


def test_size_limit_enforced_and_temp_file_removed(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    r = client.post("/api/database/upload", content=b"SQLite format 3\x00" + b"0" * (1024 * 1024 + 10))
    assert r.status_code == 400 and "limit" in r.json()["detail"]
    assert list((tmp_path / "up").glob("*")) == []


def test_path_connect_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("ALLOW_PATH_CONNECT", "false")
    get_settings.cache_clear()
    assert client.post("/api/database/connect", json={"path": "x.db"}).status_code == 403
