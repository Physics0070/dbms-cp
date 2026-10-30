"""PostgreSQL connector, tested against a REAL PostgreSQL server.

Needs `pip install pgserver` (an embedded PostgreSQL). If it cannot start, every test here is
skipped, not faked: run with `pytest -m postgres -rs` to see why. Not covered: TLS modes,
password authentication (the embedded server uses trust auth), other PostgreSQL versions.
"""
import logging
from urllib.parse import urlparse

import pytest

psycopg = pytest.importorskip("psycopg")
pgserver = pytest.importorskip("pgserver")

from fastapi.testclient import TestClient  # noqa: E402

from app import history_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database.postgres_adapter import PostgresAdapter  # noqa: E402
from app.database.sqlite_adapter import DatabaseUnavailable, get_adapter, set_adapter  # noqa: E402
from app.optimizer.explain_parser import parse_explain_query_plan  # noqa: E402
from app.optimizer.orchestrator import optimize_query  # noqa: E402

pytestmark = pytest.mark.postgres

DDL = """
CREATE TABLE customers (id serial PRIMARY KEY, name text NOT NULL, country text, joined date, balance numeric(10,2));
CREATE TABLE orders (id serial PRIMARY KEY, customer_id int NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                     status text, total numeric(10,2), placed timestamp);
CREATE INDEX idx_orders_customer ON orders(customer_id);
INSERT INTO customers(name, country, joined, balance)
  SELECT 'c' || g, (ARRAY['IN','US','DE','FR'])[1 + g % 4], date '2020-01-01' + g, g * 1.5 FROM generate_series(1, 400) g;
INSERT INTO orders(customer_id, status, total, placed)
  SELECT 1 + g % 400, (ARRAY['new','shipped','paid'])[1 + g % 3], g * 0.5, timestamp '2024-01-01' + g * interval '1 hour'
  FROM generate_series(1, 2000) g;
ANALYZE;
"""
JOIN_SQL = ("SELECT c.name, SUM(o.total) AS spent FROM customers c JOIN orders o ON o.customer_id = c.id "
            "WHERE o.status = 'shipped' GROUP BY c.name")


@pytest.fixture(scope="session")
def pg(tmp_path_factory):
    try:
        server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    except Exception as e:  # no embedded server available on this machine
        pytest.skip(f"embedded PostgreSQL could not start: {e}")
    u = urlparse(server.get_uri())
    with psycopg.connect(server.get_uri(), autocommit=True) as c:
        c.execute(DDL)
    yield dict(host=u.hostname, port=u.port, database=u.path.lstrip("/"), user=u.username)
    server.cleanup()


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK", "true")  # the test server is on loopback
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def adapter(pg, settings):
    a = PostgresAdapter(password="", sslmode="prefer", **pg)
    yield a
    a.close()


def test_schema_discovery(adapter):
    assert adapter.get_tables() == ["customers", "orders"]
    cols = {c.name: c for c in adapter.get_columns("orders")}
    assert cols["id"].primary_key and not cols["customer_id"].nullable and cols["status"].nullable
    idx = {i.name: i for i in adapter.get_indexes("orders")}
    assert idx["idx_orders_customer"].columns == ["customer_id"] and not idx["idx_orders_customer"].unique
    assert idx["orders_pkey"].origin == "pk"
    (fk,) = adapter.get_foreign_keys("orders")
    assert (fk.columns, fk.ref_table, fk.ref_columns, fk.on_delete) == (["customer_id"], "customers", ["id"], "CASCADE")


def test_exact_statistics_are_json_and_optimizer_friendly(adapter):
    st = adapter.get_statistics("customers")
    assert st.row_count == 400
    c = st.columns
    assert c["country"].distinct_count == 4 and len(c["country"].most_common) == 4
    assert isinstance(c["balance"].max_value, float) and c["balance"].max_value == 600.0   # Decimal -> float
    assert c["joined"].min_value == "2020-01-02"                                            # date -> ISO string
    assert c["name"].null_count == 0 and c["country"].null_fraction == 0.0


def test_large_table_statistics_use_pg_stats(adapter):
    adapter.EXACT_STATS_MAX_ROWS = 0
    st = adapter.get_statistics("orders", use_cache=False)
    assert "pg_stats" in st.source and st.row_count == 2000
    assert st.columns["status"].distinct_count == 3 and st.columns["status"].min_value is None


def test_connection_is_read_only(adapter):
    for sql in ("DELETE FROM orders", "INSERT INTO customers(name) VALUES ('x')", "CREATE TABLE t(a int)"):
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            adapter.execute_readonly(sql)
    assert adapter.execute_readonly("SELECT COUNT(*) FROM orders")[1] == [(2000,)]  # nothing changed, still usable


def test_statement_timeout(pg, settings, monkeypatch):
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "200")
    get_settings.cache_clear()
    a = PostgresAdapter(password="", **pg)
    with pytest.raises(psycopg.errors.QueryCanceled):
        a.execute_readonly("SELECT pg_sleep(3)")
    a.close()


def test_execute_limit_and_percent_in_sql(adapter):
    _, rows = adapter.execute_readonly("SELECT name FROM customers WHERE name LIKE 'c1%' ORDER BY id", limit=3)
    assert [r[0] for r in rows] == ["c1", "c10", "c11"]


def test_explain_matches_shared_parser(adapter):
    rows = adapter.explain_query("SELECT * FROM customers WHERE country = 'IN'")
    assert rows[0]["detail"].startswith("SCAN customers") and rows[0]["estimated_rows"] > 0
    parsed = parse_explain_query_plan(adapter.explain_query("SELECT * FROM orders WHERE customer_id = 5"))
    assert parsed["indexes_used"] == ["idx_orders_customer"] and "orders" in parsed["tables"]
    assert any("QUERY PLAN" in r for r in adapter.explain_bytecode("SELECT 1"))


def test_explain_never_executes_the_query(adapter):
    adapter.explain_query("SELECT pg_sleep(5)")  # would hit the timeout if it ran


def test_benchmark_shape(adapter):
    b = adapter.benchmark_query(JOIN_SQL, warmup=1, runs=3)
    assert b["measured_runs"] == 3 and b["rows_returned"] == 400 and len(b["samples_ms"]) == 3
    assert b["min_ms"] <= b["median_ms"] <= b["max_ms"] and "NOT an optimizer cost" in b["note"]


def test_capabilities_are_truthful(adapter):
    caps = adapter.capabilities
    assert caps["native_explain"] and caps["benchmarking"] and caps["statistics"]
    assert not caps["actual_plan_analysis"]   # plain EXPLAIN only
    assert not caps["hypothetical_index"]     # hypopg not installed on the test server


def test_full_optimizer_pipeline_on_postgres(adapter):
    r = optimize_query(adapter, JOIN_SQL, run_benchmark=True, run_index_advisor=True)
    assert r["optimization"]["relations"] and r["optimization"]["selected_total_cost"] > 0
    assert r["benchmark"] is not None
    assert "error" not in r["explain"] and r["explain"]["engine"]["tables"] == ["customers", "orders"]
    assert r["explain"]["engine"]["steps"][0]["detail"].startswith("Aggregate")  # real PostgreSQL plan, not SQLite's


def test_bad_credentials_and_unreachable_host_do_not_leak(pg, settings):
    with pytest.raises(DatabaseUnavailable) as e:
        PostgresAdapter(password="hunter2-secret", **{**pg, "database": "nope"})
    assert "hunter2-secret" not in str(e.value) and "nope" in str(e.value)
    with pytest.raises(DatabaseUnavailable):
        PostgresAdapter(password="x", **{**pg, "port": 1})


# -- HTTP API -----------------------------------------------------------------------------------
@pytest.fixture
def client(pg, settings, ecommerce_adapter, tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setattr(history_store, "_HISTORY_PATH", tmp_path / "history.json")
    set_adapter(ecommerce_adapter)
    yield TestClient(app)
    cur = get_adapter()
    if isinstance(cur, PostgresAdapter):
        cur.close()
    set_adapter(None)


def _body(pg, **kw):
    return {"engine": "postgresql", "host": pg["host"], "port": pg["port"], "database": pg["database"],
            "user": pg["user"], "password": "s3cret-pw-123", "sslmode": "prefer", **kw}


def test_connect_remote_switches_database_and_never_echoes_password(client, pg, caplog):
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/database/connect-remote", json=_body(pg))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "PostgreSQL" and body["table_names"] == ["customers", "orders"] and body["read_only"]
    assert body["path"] is None and body["host"] == pg["host"] and not body["capabilities"]["actual_plan_analysis"]
    assert "s3cret-pw-123" not in r.text and "s3cret-pw-123" not in caplog.text
    assert client.get("/api/health").json()["tables"] == ["customers", "orders"]
    assert client.get("/api/schema").status_code == 200
    opt = client.post("/api/optimize", json={"sql": JOIN_SQL, "benchmark": False, "save_history": False})
    assert opt.status_code == 200, opt.text


def test_failed_connect_keeps_previous_connection(client, pg, ecommerce_adapter):
    r = client.post("/api/database/connect-remote", json=_body(pg, database="does_not_exist"))
    assert r.status_code == 400 and "s3cret-pw-123" not in r.text
    assert get_adapter() is ecommerce_adapter


def test_test_remote_does_not_switch(client, pg, ecommerce_adapter):
    r = client.post("/api/database/test-remote", json=_body(pg))
    assert r.status_code == 200 and r.json()["ok"] and r.json()["tables"] == 2
    assert get_adapter() is ecommerce_adapter


def test_private_host_blocked_over_http_by_default(client, pg, monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_NETWORK")
    get_settings.cache_clear()
    for host in ("127.0.0.1", "169.254.169.254"):
        r = client.post("/api/database/connect-remote", json=_body(pg, host=host))
        assert r.status_code == 400 and "blocked" in r.json()["detail"]


def test_request_validation(client, pg):
    assert client.post("/api/database/connect-remote", json=_body(pg, engine="oracle")).status_code == 422
    assert client.post("/api/database/connect-remote", json=_body(pg, port=0)).status_code == 422
    assert client.post("/api/database/connect-remote", json=_body(pg, sslmode="bogus")).status_code == 422
