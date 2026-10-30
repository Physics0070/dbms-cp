"""Log redaction, body cap, timeout and rate limiting."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.sqlite_adapter import set_adapter
from app.logging_setup import JsonFormatter, redact


@pytest.mark.parametrize("raw,secret", [
    ("connect postgresql://admin:hunter2@db.internal:5432/app", "hunter2"),
    ("password=hunter2 host=x", "hunter2"),
    ('{"password": "hunter2"}', "hunter2"),
    ("Authorization: Bearer abcdef123456", "abcdef123456"),
    ("key is sk-abcdefghijkl1234", "abcdefghijkl1234"),
    ("api_key=ABCD1234efgh", "ABCD1234efgh"),
    ("mysql://root:pw@localhost/db?token=zzz999", "zzz999"),
])
def test_redact_removes_secrets(raw, secret):
    out = redact(raw)
    assert secret not in out and "***" in out


def test_json_formatter_redacts_message_and_fields():
    rec = logging.LogRecord("querypilot.t", logging.INFO, __file__, 1, "dsn %s", ("postgres://u:p4ss@h/db",), None)
    rec.fields = {"query": "password=p4ss", "ms": 3}
    doc = json.loads(JsonFormatter().format(rec))
    assert "p4ss" not in json.dumps(doc) and doc["ms"] == 3 and doc["level"] == "INFO"


def test_redact_leaves_ordinary_text_alone():
    assert redact("SELECT name FROM customers WHERE id = 5") == "SELECT name FROM customers WHERE id = 5"


@pytest.fixture
def client(ecommerce_adapter, monkeypatch):
    from app.main import app

    set_adapter(ecommerce_adapter)
    get_settings.cache_clear()
    yield TestClient(app)
    set_adapter(None)
    get_settings.cache_clear()


def test_oversized_body_rejected(client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_MB", "1")
    get_settings.cache_clear()
    r = client.post("/api/validate", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_rate_limit_applies_to_heavy_endpoints_only(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    get_settings.cache_clear()
    from app.middleware import HardeningMiddleware

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    c = TestClient(HardeningMiddleware(ok))
    codes = [c.post("/api/optimize", json={}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert c.post("/api/optimize", json={}).headers["retry-after"].isdigit()
    assert all(c.get("/api/health").status_code == 200 for _ in range(10))  # not a heavy path


def test_timeout_returns_504(monkeypatch):
    import asyncio

    from app.middleware import HardeningMiddleware

    monkeypatch.setenv("REQUEST_TIMEOUT_S", "0.2")
    get_settings.cache_clear()

    async def slow(scope, receive, send):
        await asyncio.sleep(2)

    r = TestClient(HardeningMiddleware(slow)).get("/api/anything")
    get_settings.cache_clear()
    assert r.status_code == 504
