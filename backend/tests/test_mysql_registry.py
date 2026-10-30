"""MySQL registry and request validation. No server needed."""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

SECRET = "s3cret-pw-do-not-leak"


def test_mysql_registered_and_params_mapped_without_hostaddr_or_sslmode(monkeypatch):
    from app.database import registry

    seen = {}
    monkeypatch.setitem(registry.ENGINES, "mysql", lambda **kw: seen.update(kw) or object())
    registry.build_adapter("mysql", host="db.example.com", hostaddr="93.184.216.34", port=3306, database="d", user="u",
                           password="p", sslmode="prefer", schema="public")
    assert seen == dict(host="93.184.216.34", port=3306, user="u", password="p", database="d")  # pinned to the checked IP


def test_remote_route_blocks_private_mysql_host_by_default(monkeypatch):
    from app.main import app

    monkeypatch.delenv("ALLOW_PRIVATE_NETWORK", raising=False)
    get_settings.cache_clear()
    r = TestClient(app).post("/api/database/connect-remote", json={
        "engine": "mysql", "host": "127.0.0.1", "port": 3306, "database": "d", "user": "u", "password": SECRET})
    assert r.status_code == 400 and SECRET not in r.text
    get_settings.cache_clear()


def test_unknown_engine_rejected():
    from app.main import app

    r = TestClient(app).post("/api/database/connect-remote", json={
        "engine": "oracle", "host": "h", "port": 1, "database": "d", "user": "u"})
    assert r.status_code == 422
