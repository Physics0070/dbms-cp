"""MySQL through the HTTP API: connect-remote, schema, examples, optimize, index advisor, lab.

All tests here need a REAL MySQL server (set MYSQL_TEST_HOST, see test_mysql_adapter.py) and are
skipped otherwise. Registry / request-validation tests that need no server: test_mysql_registry.py.
Verified on MySQL 8.0.46. MariaDB is NOT verified.
"""
import logging
import os

import pytest
from fastapi.testclient import TestClient

from app import history_store
from app.config import get_settings
from app.database.sqlite_adapter import get_adapter, set_adapter

pytestmark = [
    pytest.mark.mysql,
    pytest.mark.skipif(not os.environ.get("MYSQL_TEST_HOST"), reason="needs a real MySQL server (set MYSQL_TEST_HOST)"),
]
DB = "qp_pipeline_test"
SECRET = "s3cret-pw-do-not-leak"


def _args():
    return dict(host=os.environ.get("MYSQL_TEST_HOST", "127.0.0.1"), port=int(os.environ.get("MYSQL_TEST_PORT", "3306")),
                user=os.environ.get("MYSQL_TEST_USER", "root"), password=os.environ.get("MYSQL_TEST_PASSWORD", ""))


@pytest.fixture(scope="module")
def server_db():
    import pymysql

    admin = pymysql.connect(**_args(), autocommit=True)
    c = admin.cursor()
    c.execute(f"DROP DATABASE IF EXISTS {DB}")
    c.execute(f"CREATE DATABASE {DB}")
    c.execute(f"USE {DB}")
    c.execute("CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(40), city VARCHAR(20), KEY idx_city (city))")
    c.execute("CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT NOT NULL, status VARCHAR(12), total DECIMAL(10,2), "
              "CONSTRAINT fk_c FOREIGN KEY (customer_id) REFERENCES customers(id))")
    c.execute("CREATE TABLE order_items (id INT PRIMARY KEY, order_id INT NOT NULL, qty INT, "
              "CONSTRAINT fk_o FOREIGN KEY (order_id) REFERENCES orders(id))")
    c.executemany("INSERT INTO customers VALUES (%s,%s,%s)", [(i, f"c{i}", ["Pune", "Delhi", "Goa", "Agra"][i % 4]) for i in range(1, 501)])
    c.executemany("INSERT INTO orders VALUES (%s,%s,%s,%s)", [(i, (i % 500) + 1, ["shipped", "new", "paid"][i % 3], i * 1.25) for i in range(1, 3001)])
    c.executemany("INSERT INTO order_items VALUES (%s,%s,%s)", [(i, (i % 3000) + 1, i % 7 + 1) for i in range(1, 9001)])
    c.execute("ANALYZE TABLE customers, orders, order_items")
    c.fetchall()
    yield DB
    c.execute(f"DROP DATABASE IF EXISTS {DB}")
    admin.close()


def _body(**over):
    a = _args()
    return {"engine": "mysql", "host": a["host"], "port": a["port"], "database": DB, "user": a["user"],
            "password": a["password"], **over}


@pytest.fixture
def client(server_db, tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK", "true")  # the test server is on loopback
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    monkeypatch.setattr(history_store, "_HISTORY_PATH", tmp_path / "history.json")
    get_settings.cache_clear()
    set_adapter(None)
    cl = TestClient(app)
    r = cl.post("/api/database/connect-remote", json=_body())
    assert r.status_code == 200, r.text
    yield cl
    ad = get_adapter()
    set_adapter(None)
    ad.close()
    get_settings.cache_clear()


JOIN = ("SELECT oi.order_id, o.customer_id, c.name FROM order_items oi "
        "JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id")


def test_connect_reports_mysql_without_credentials(client):
    info = client.get("/api/database").json()
    assert info["engine"] == "MySQL" and info["read_only"] and info["path"] is None
    assert set(info["table_names"]) == {"customers", "orders", "order_items"}
    assert info["capabilities"]["native_explain"] and not info["capabilities"]["hypothetical_index"]
    assert "user" not in info and "password" not in str(info)


def test_schema_examples_statistics(client):
    schema = client.get("/api/schema").json()
    orders = next(t for t in schema["tables"] if t["name"] == "orders")
    assert orders["primary_key"] == ["id"] and orders["foreign_keys"][0]["ref_table"] == "customers"
    ex = client.get("/api/examples").json()["examples"]
    assert ex and all(any(t in e["sql"] for t in ("customers", "orders", "order_items")) for e in ex)  # from the live schema
    st = client.get("/api/statistics/orders").json()
    assert st["row_count"] == 3000 and "status" in st["columns"]


def test_validate_and_write_rejection(client):
    assert client.post("/api/validate", json={"sql": JOIN}).json()["valid"]
    assert client.post("/api/optimize", json={"sql": "DELETE FROM orders"}).status_code == 400
    assert client.post("/api/optimize", json={"sql": "SELECT 1 FROM orders; DROP TABLE orders"}).status_code == 400
    assert client.get("/api/statistics/orders").json()["row_count"] == 3000  # nothing changed


def test_optimize_returns_native_plan_and_honest_rewrite_status(client):
    r = client.post("/api/optimize", json={"sql": JOIN, "benchmark": True, "index_advisor": True})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "MySQL" in j["database_backend"] and j["summary"]["join_orders_considered"] >= 1
    assert j["optimization"]["selected"]["total_cost"] > 0
    assert j["benchmark"] and j["benchmark"]["measured_runs"] >= 1 and j["benchmark"]["median_ms"] > 0
    # MySQL does not honour the join-order pin, so no rewrite is offered (never a fake speedup).
    oq = j["optimized_query"]
    assert oq["status"] == "unsupported" and oq["sql"] is None and "mysql" in " ".join(oq["reasons"]).lower()
    plan = client.post("/api/explain", json={"sql": JOIN}).json()
    assert plan["query_plan"]["raw"] and plan["query_plan"]["raw"][0]["node"]["table_name"]


def test_backtick_quoted_query_works(client):
    r = client.post("/api/optimize", json={"sql": "SELECT `name` FROM `customers` WHERE city = 'Pune'", "benchmark": False})
    assert r.status_code == 200, r.text


def test_index_advisor_emits_mysql_ddl_and_never_creates(client):
    before = {i.name for i in get_adapter().get_indexes("orders")}
    r = client.post("/api/optimize", json={"sql": "SELECT o.id FROM orders o WHERE o.status = 'shipped'", "benchmark": False, "index_advisor": True})
    recs = r.json()["index_advisor"]["recommendations"]
    assert recs and all("IF NOT EXISTS" not in x["ddl"] for x in recs)  # MySQL has no CREATE INDEX IF NOT EXISTS
    assert {i.name for i in get_adapter().get_indexes("orders")} == before


def test_lab_compare_runs_with_equivalence(client):
    r = client.post("/api/lab/compare", json={"baseline_sql": JOIN, "candidate_sql": JOIN + " ORDER BY oi.order_id",
                                              "warmup": 1, "runs": 3})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["equivalence"]["checked"] and j["equivalence"]["equal"] and j["equivalence"]["original_rows"] == 9000
    assert j["measured"]["verdict"] in ("faster", "slower", "indistinguishable", "not_comparable")


def test_failed_remote_connect_keeps_previous_and_never_echoes_password(client, caplog):
    before = get_adapter()
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/database/connect-remote", json=_body(password=SECRET, user="nobody_" + "x"))
    assert r.status_code == 400 and SECRET not in r.text and SECRET not in caplog.text
    assert get_adapter() is before
    assert client.get("/api/health").json()["status"] == "ok"


def test_test_remote_does_not_switch_database(client):
    before = get_adapter()
    r = client.post("/api/database/test-remote", json=_body())
    assert r.status_code == 200 and r.json()["ok"] and r.json()["server_version"].startswith("8.")
    assert get_adapter() is before
