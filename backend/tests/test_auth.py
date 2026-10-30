"""Optional shared-token auth and SPA serving."""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture
def client(monkeypatch):
    from app.main import app

    monkeypatch.setenv("API_TOKEN", "s3cret-token")
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def test_no_token_configured_leaves_api_open(monkeypatch):
    from app.main import app

    monkeypatch.delenv("API_TOKEN", raising=False)
    get_settings.cache_clear()
    assert TestClient(app).get("/api/config").status_code == 200


def test_missing_or_wrong_token_is_401(client):
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/config", headers={"Authorization": "Basic s3cret-token"}).status_code == 401
    assert client.post("/api/database/upload", content=b"x").status_code == 401


def test_correct_token_and_open_health(client):
    assert client.get("/api/config", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/health").status_code == 200


def test_token_not_logged(client, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        client.get("/api/config", headers={"Authorization": "Bearer s3cret-token"})
    assert "s3cret-token" not in caplog.text


def test_spa_fallback_without_shadowing_api(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA</html>")
    (tmp_path / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    get_settings.cache_clear()
    import importlib

    import app.main as m

    m = importlib.reload(m)
    c = TestClient(m.app)
    assert "SPA" in c.get("/app/schema").text and "SPA" in c.get("/").text
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/api/health").json()["status"] in ("ok", "no_database")
    assert c.get("/api/nope").status_code == 404
    assert "nope" not in c.get("/..%2fsecret.txt").text and "nope" not in c.get("/%2e%2e/secret.txt").text
    monkeypatch.delenv("FRONTEND_DIST")
    get_settings.cache_clear()
    importlib.reload(m)
