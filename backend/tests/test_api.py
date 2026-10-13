"""HTTP API behaviour, database switching, read-only guarantees and concurrency."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import history_store
from app.config import get_settings
from app.database.sqlite_adapter import SqliteAdapter, set_adapter
from app.optimizer.examples import generate_examples
from app.optimizer.explain_parser import compare, parse_explain_query_plan
from seed.generate import seed_ecommerce


@pytest.fixture
def client(ecommerce_adapter, tmp_path, monkeypatch):
    from app.main import app

    set_adapter(ecommerce_adapter)
    monkeypatch.setattr(history_store, "_HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    yield TestClient(app)
    set_adapter(None)
    get_settings.cache_clear()


def _join_sql(adapter):
    return next(e["sql"] for e in generate_examples(adapter) if e["kind"] in ("join", "multi-join"))


# -- health / schema / examples ----------------------------------------------------
def test_health_reports_connected_database(client, ecommerce_adapter):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and set(r["tables"]) == set(ecommerce_adapter.get_tables())
    assert "read-only" in r["database_backend"]


def test_schema_and_examples(client):
    assert client.get("/api/schema").json()["tables"]
    assert client.get("/api/examples").json()["examples"]
    assert client.get("/api/schema/not_a_table").status_code == 404
    assert client.get("/api/statistics/not_a_table").status_code == 404


def test_no_database_degrades_gracefully(client, tmp_path, monkeypatch):
    set_adapter(None)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    get_settings.cache_clear()
    h = client.get("/api/health").json()
    assert h["status"] == "no_database" and "not found" in h["reason"].lower()
    assert client.get("/api/schema").status_code == 503
    assert client.get("/api/database").json()["connected"] is False


# -- switching databases ------------------------------------------------------------
def test_connect_to_another_database(client, library_adapter):
    r = client.post("/api/database/connect", json={"path": str(library_adapter.path)})
    assert r.status_code == 200 and r.json()["tables"] == 4
    names = {t["name"] for t in client.get("/api/schema").json()["tables"]}
    assert names == {"authors", "books", "members", "loans"}


def test_failed_connect_keeps_previous_database(client, ecommerce_adapter, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not a database")
    for path in (str(bad), str(tmp_path / "nope.db"), "   "):
        assert client.post("/api/database/connect", json={"path": path}).status_code == 400
    assert client.get("/api/database").json()["name"] == ecommerce_adapter.path.name


# -- optimize / validate / explain / benchmark --------------------------------------
def test_optimize_returns_full_result_and_history(client, ecommerce_adapter):
    sql = _join_sql(ecommerce_adapter)
    r = client.post("/api/optimize", json={"sql": sql, "benchmark": True})
    assert r.status_code == 200
    body = r.json()
    for key in ("optimization", "logical_optimization", "explain", "optimized_query", "benchmark", "index_advisor"):
        assert key in body
    est = body["optimized_query"]["estimated"]
    assert "baseline" in est and "naive_baseline" in est and est["note"].startswith("Estimated")
    assert body["optimized_query"]["original_pretty"]

    items = client.get("/api/history").json()["items"]
    assert any(i["id"] == body["history_id"] for i in items)
    assert client.get(f"/api/history/{body['history_id']}").status_code == 200
    assert client.get("/api/history/does-not-exist").status_code == 404


@pytest.mark.parametrize("sql,status", [
    ("DROP TABLE orders", 400),
    ("UPDATE orders SET total = 0", 400),
    ("   ", 400),
    ("SELECT * FROM table_that_does_not_exist", 422),
    ("SELECT 1 UNION SELECT 2", 422),
])
def test_bad_queries_get_clear_errors(client, sql, status):
    r = client.post("/api/optimize", json={"sql": sql})
    assert r.status_code == status and r.json()["detail"]


def test_validate_endpoint(client):
    assert client.post("/api/validate", json={"sql": "SELECT 1"}).json()["valid"] is True
    assert client.post("/api/validate", json={"sql": "DELETE FROM orders"}).json()["valid"] is False


def test_explain_and_benchmark_endpoints(client, ecommerce_adapter):
    sql = _join_sql(ecommerce_adapter)
    assert client.post("/api/explain", json={"sql": sql}).json()["query_plan"]["steps"]
    b = client.post("/api/benchmark", json={"sql": sql, "runs": 3, "warmup": 1}).json()
    assert b["measured_runs"] == 3 and b["warmup_runs"] == 1
    assert client.post("/api/benchmark", json={"sql": "DROP TABLE x"}).status_code == 400


def test_copilot_offline_is_grounded(client, ecommerce_adapter):
    r = client.post("/api/copilot", json={"sql": _join_sql(ecommerce_adapter)}).json()
    assert r["source"] == "offline" and "Selected plan" in r["explanation"]


# -- the database is read-only unless explicitly enabled ----------------------------
def test_database_is_read_only_by_default(ecommerce_adapter):
    with pytest.raises(sqlite3.OperationalError):
        ecommerce_adapter._conn.execute("CREATE TABLE should_not_exist (a INTEGER)")


def test_index_creation_is_gated(client):
    body = {"table": "orders", "columns": ["status"], "confirm": True}
    assert client.post("/api/index/create", json=body).status_code == 403
    assert client.post("/api/index/create", json={**body, "confirm": False}).status_code == 400
    assert client.get("/api/config").json()["index_creation_enabled"] is False


def test_index_creation_when_enabled(tmp_path, monkeypatch):
    from app.main import app

    db = tmp_path / "rw.db"
    conn = sqlite3.connect(db)
    seed_ecommerce(conn, seed=3, customer_count=50, order_count=120, product_count=30)
    conn.close()
    monkeypatch.setenv("ALLOW_INDEX_CREATION", "true")
    get_settings.cache_clear()
    try:
        adapter = SqliteAdapter(str(db))
        set_adapter(adapter)
        c = TestClient(app)
        ok = c.post("/api/index/create", json={"table": "orders", "columns": ["status"], "confirm": True})
        assert ok.status_code == 200 and "CREATE INDEX" in ok.json()["ddl"]
        assert any(i.columns == ["status"] for i in adapter.get_indexes("orders"))
        assert c.post("/api/index/create", json={"table": "nope", "columns": ["x"], "confirm": True}).status_code == 400
        assert c.post("/api/index/create", json={"table": "orders", "columns": ["nope"], "confirm": True}).status_code == 400
    finally:
        set_adapter(None)
        get_settings.cache_clear()


# -- previously untested branch (crashed on a stale variable name) -----------------
def test_plan_comparison_reports_differences(ecommerce_adapter):
    custom = {"operator": "SeqScan", "meta": {"table": "orders"}, "children": []}
    engine = parse_explain_query_plan([
        {"id": 1, "parent": 0, "detail": "SEARCH customers USING INDEX idx (c=?)"},
        {"id": 2, "parent": 0, "detail": "USE TEMP B-TREE FOR ORDER BY"},
    ])
    out = compare(custom, engine)
    assert len(out["differences"]) == 3 and "engine" in out
    assert not out["agreement"]["same_tables"]


# -- concurrency: shared connection must be safe under the server's thread pool ----
def test_concurrent_requests_are_safe(ecommerce_adapter):
    def work(i):
        _, rows = ecommerce_adapter.execute_readonly("SELECT COUNT(*) FROM orders")
        st = ecommerce_adapter.get_statistics("orders", use_cache=False)
        return rows[0][0], st.row_count

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, range(40)))
    assert set(results) == {(1200, 1200)}


# -- "any database": awkward identifiers must work, not just tidy snake_case -------
def test_works_with_awkward_identifiers(tmp_path):
    db = tmp_path / "odd.db"
    c = sqlite3.connect(db)
    c.executescript('''
        CREATE TABLE "Order Details" ("Order-ID" INTEGER PRIMARY KEY, "Unit Price" REAL, "Sku" TEXT);
        CREATE TABLE "Line Items" ("Item ID" INTEGER PRIMARY KEY, "Order-ID" INTEGER REFERENCES "Order Details"("Order-ID"), qty INTEGER);
    ''')
    c.executemany('INSERT INTO "Order Details" VALUES (?,?,?)', [(i, i * 1.5, "A" if i % 3 else "B") for i in range(1, 101)])
    c.executemany('INSERT INTO "Line Items" VALUES (?,?,?)', [(i, (i % 100) + 1, i % 5) for i in range(1, 301)])
    c.commit(); c.close()

    a = SqliteAdapter(str(db))
    assert set(a.get_tables()) == {"Order Details", "Line Items"}
    assert a.get_statistics("Order Details").row_count == 100

    from app.optimizer.orchestrator import optimize_query
    sql = ('SELECT d."Sku", l.qty FROM "Line Items" l JOIN "Order Details" d '
           'ON l."Order-ID" = d."Order-ID" WHERE d."Sku" = \'B\'')
    r = optimize_query(a, sql, run_index_advisor=False)
    assert r["summary"]["selected_total_cost"] > 0
    oq = r["optimized_query"]
    assert oq["status"] in ("rewritten", "no_change")
    if oq["status"] == "rewritten":
        assert oq["equivalence"]["equal"] is True
