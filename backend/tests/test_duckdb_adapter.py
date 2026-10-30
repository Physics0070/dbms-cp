"""DuckDB adapter, tested against a real DuckDB file: introspection, statistics, plans,
read-only/lockdown guarantees, timeout, and detection on /connect and /upload."""
import threading
import time

import duckdb
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import duckdb_adapter
from app.database.duckdb_adapter import DuckdbAdapter, check_sql, sniff_format
from app.database.sqlite_adapter import DatabaseUnavailable, get_adapter, set_adapter
from app.optimizer.safety import UnsafeQueryError


def _make_db(path):
    c = duckdb.connect(str(path))
    c.execute("CREATE TABLE customers(id INTEGER PRIMARY KEY, email VARCHAR UNIQUE, region VARCHAR, balance DECIMAL(10,2))")
    c.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, total DOUBLE, placed DATE,"
              " FOREIGN KEY (customer_id) REFERENCES customers(id))")
    c.execute("CREATE INDEX idx_orders_customer ON orders(customer_id)")
    c.execute("INSERT INTO customers SELECT i, 'u'||i||'@x.io', CASE WHEN i%4=0 THEN NULL ELSE 'r'||(i%3) END, i*1.25 FROM range(1,201) t(i)")
    c.execute("INSERT INTO orders SELECT i, (i%200)+1, i*0.5, DATE '2024-01-01' + CAST(i%300 AS INTEGER) FROM range(1,1001) t(i)")
    c.close()
    return path


@pytest.fixture(scope="module")
def adapter(tmp_path_factory):
    a = DuckdbAdapter(str(_make_db(tmp_path_factory.mktemp("dd") / "shop.duckdb")))
    yield a
    a.close()


# -- format detection ---------------------------------------------------------
def test_sniff_format(tmp_path, adapter, ecommerce_adapter):
    assert sniff_format(str(adapter.path)) == "duckdb"
    assert sniff_format(str(ecommerce_adapter.path)) == "sqlite"
    junk = tmp_path / "j.bin"; junk.write_bytes(b"x" * 64)
    assert sniff_format(str(junk)) is None and sniff_format(str(tmp_path / "missing")) is None


def test_rejects_non_duckdb_file(ecommerce_adapter):
    with pytest.raises(DatabaseUnavailable):
        DuckdbAdapter(str(ecommerce_adapter.path))


# -- introspection ------------------------------------------------------------------
def test_schema_discovery(adapter):
    assert adapter.get_tables() == ["customers", "orders"]
    cols = {c.name: c for c in adapter.get_columns("customers")}
    assert cols["id"].primary_key and not cols["id"].nullable
    assert cols["region"].nullable and cols["balance"].data_type.startswith("DECIMAL")
    idx = {i.name: i for i in adapter.get_indexes("orders")}
    assert idx["idx_orders_customer"].columns == ["customer_id"] and idx["idx_orders_customer"].origin == "c"
    assert idx["pk_orders"].unique and idx["pk_orders"].origin == "pk"
    assert any(i.unique and i.columns == ["email"] for i in adapter.get_indexes("customers"))
    fk = adapter.get_foreign_keys("orders")
    assert [(f.columns, f.ref_table, f.ref_columns) for f in fk] == [(["customer_id"], "customers", ["id"])]
    assert set(adapter.get_schema()) == {"customers", "orders"}


def test_statistics_are_exact_for_small_tables(adapter):
    st = adapter.get_statistics("customers", use_cache=False)
    assert st.row_count == 200 and "exact" in st.source
    region = st.columns["region"]
    assert region.null_count == 50 and region.distinct_count == 3 and abs(region.null_fraction - 0.25) < 1e-9
    assert sum(c for _, c in region.most_common) == 150
    assert st.columns["id"].min_value == 1 and st.columns["id"].max_value == 200
    with pytest.raises(ValueError):
        adapter.get_statistics("nope", use_cache=False)


# -- execution and plans ----------------------------------------------------------------
def test_execute_returns_json_safe_values(adapter):
    cols, rows = adapter.execute_readonly("SELECT balance, placed FROM customers, orders WHERE customers.id=1 AND orders.id=1")
    assert cols == ["balance", "placed"] and rows == [(1.25, "2024-01-02")]
    assert len(adapter.execute_readonly("SELECT * FROM orders", limit=7)[1]) == 7
    assert adapter.execute_readonly("SELECT ? + 1", [41])[1] == [(42,)]


def test_explain_query_structure(adapter):
    plan = adapter.explain_query("SELECT c.region, SUM(o.total) FROM orders o JOIN customers c ON c.id=o.customer_id "
                                 "WHERE o.total > 10 GROUP BY c.region")
    assert plan[0]["parent"] == 0 and all(p["parent"] < p["id"] for p in plan)
    scans = [p["detail"] for p in plan if p["detail"].startswith(("SCAN", "SEARCH"))]
    assert {s.split()[1] for s in scans} == {"orders", "customers"}
    assert any("JOIN" in (p["node_type"] or "") for p in plan)
    assert any(isinstance(p["estimated_rows"], int) for p in plan)
    from app.optimizer.explain_parser import parse_explain_query_plan
    assert parse_explain_query_plan(plan)["tables"] == ["customers", "orders"]


def test_explain_analyze_reports_actuals(adapter):
    text = "\n".join(r["plan"] for r in adapter.explain_analyze("SELECT count(*) FROM orders WHERE total > 100"))
    assert "Total Time" in text or "Rows" in text or "rows" in text.lower()


def test_benchmark(adapter):
    b = adapter.benchmark_query("SELECT * FROM orders WHERE customer_id = 5", warmup=1, runs=3)
    assert b["measured_runs"] == 3 and b["rows_returned"] == 5 and len(b["samples_ms"]) == 3


def test_capabilities_are_honest(adapter):
    caps = adapter.capabilities
    assert set(caps) == set(adapter.CAPABILITY_KEYS)
    assert caps["actual_plan_analysis"] and caps["native_explain"] and caps["benchmarking"]
    assert not caps["hypothetical_index"] and not caps["sql_rewrite"] and not caps["result_equivalence"]
    assert adapter.read_only and adapter.dialect == "duckdb"


# -- read-only and file-access lockdown -------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('x.csv')", "select * from READ_PARQUET('x.parquet')", "SELECT * FROM glob('*')",
    "SELECT * FROM read_text('C:/Windows/win.ini')", "SELECT * FROM query('SELECT 1')",
    "COPY orders TO 'out.csv'", "ATTACH 'other.db' AS o", "INSTALL httpfs", "LOAD httpfs", "PRAGMA database_list",
    "SET enable_external_access=true", "CALL pragma_version()", "EXPORT DATABASE 'd'",
    "DELETE FROM orders", "INSERT INTO orders VALUES (1,1,1,NULL)", "DROP TABLE orders", "CREATE TABLE z(i INT)",
    "UPDATE orders SET total=0", "WITH x AS (SELECT 1) DELETE FROM orders",
    "SELECT 1; SELECT 2", "SELECT 1; DROP TABLE orders", "", "   ",
])
def test_unsafe_sql_rejected_by_guard(adapter, sql):
    with pytest.raises(UnsafeQueryError):
        check_sql(sql)
    with pytest.raises(UnsafeQueryError):
        adapter.execute_readonly(sql)
    n = adapter.execute_readonly("SELECT count(*) FROM orders")[1][0][0]
    assert n == 1000


def test_guard_allows_normal_reads_and_literals(adapter):
    for sql in ("SELECT 'delete; drop' AS s", "WITH t AS (SELECT 1 a) SELECT * FROM t", "FROM orders LIMIT 1",
                "SELECT /* set; copy */ 1", 'SELECT "load" FROM (SELECT 1 AS "load")', "VALUES (1),(2)"):
        check_sql(sql)
    assert adapter.execute_readonly("SELECT 'a;b'")[1] == [("a;b",)]


def test_engine_itself_blocks_files_and_writes_even_if_guard_is_bypassed(adapter):
    """Defence in depth: go straight to the connection, skipping check_sql."""
    for sql in ("SELECT * FROM read_csv('x.csv')", "SELECT * FROM 'x.csv'", "COPY orders TO 'o.csv'",
                "ATTACH 'o.db'", "DELETE FROM orders", "CREATE TABLE z(i INT)", "SET enable_external_access=true",
                "INSTALL httpfs"):
        with pytest.raises(duckdb.Error):
            adapter._rows(sql)
    assert adapter.get_tables() == ["customers", "orders"]


def test_statement_timeout_interrupts_long_query(adapter, monkeypatch):
    monkeypatch.setattr(duckdb_adapter, "STATEMENT_TIMEOUT_S", 0.5)
    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        adapter.execute_readonly("SELECT count(*) FROM range(100000000000) a, range(1000000) b")
    assert time.perf_counter() - t0 < 10
    assert adapter.execute_readonly("SELECT 1")[1] == [(1,)]  # connection still usable


def test_concurrent_requests_are_serialised(adapter):
    errors = []

    def work():
        try:
            for _ in range(15):
                assert adapter.execute_readonly("SELECT count(*) FROM orders")[1] == [(1000,)]
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert errors == []


# -- HTTP: /connect and /upload ------------------------------------------------------------
@pytest.fixture
def client(ecommerce_adapter, tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    get_settings.cache_clear()
    set_adapter(ecommerce_adapter)
    yield TestClient(app)
    cur = get_adapter()
    if isinstance(cur, DuckdbAdapter):
        cur.close()
    set_adapter(None)
    get_settings.cache_clear()


def test_connect_by_path_detects_duckdb(client, tmp_path):
    db = _make_db(tmp_path / "p.duckdb")
    r = client.post("/api/database/connect", json={"path": str(db)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "DuckDB" and body["read_only"] and body["table_names"] == ["customers", "orders"]
    assert body["capabilities"]["actual_plan_analysis"] is True
    assert client.get("/api/health").json()["tables"] == ["customers", "orders"]
    r = client.post("/api/optimize", json={"sql": "SELECT c.region, SUM(o.total) FROM orders o JOIN customers c "
                                                  "ON c.id = o.customer_id GROUP BY c.region",
                                           "benchmark": True, "index_advisor": False})
    assert r.status_code == 200, r.text  # the existing pipeline runs end to end on DuckDB
    assert r.json()["database_backend"].startswith("DuckDB")


def test_upload_duckdb_safe_name_and_readonly(client, tmp_path):
    data = _make_db(tmp_path / "u.duckdb").read_bytes()
    r = client.post("/api/database/upload", content=data, headers={"x-filename": "../../evil.duckdb"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "DuckDB" and body["path"] is None and body["read_only"]
    stored = get_adapter().path
    assert stored.parent == (tmp_path / "up").resolve() and stored.suffix == ".duckdb" and len(stored.stem) == 32
    assert client.post("/api/database/upload", content=b"x" * 40).status_code == 400  # not a database


def test_corrupt_duckdb_upload_rejected_and_previous_kept(client, ecommerce_adapter, tmp_path):
    data = _make_db(tmp_path / "c.duckdb").read_bytes()
    corrupt = data[:16] + b"\xff" * (len(data) - 16)  # valid magic, destroyed contents
    r = client.post("/api/database/upload", content=corrupt)
    assert r.status_code == 400
    assert get_adapter() is ecommerce_adapter
    assert list((tmp_path / "up").glob("*")) == []  # nothing left behind


def test_duckdb_upload_size_limit(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    r = client.post("/api/database/upload", content=b"\x00" * 8 + b"DUCK" + b"0" * (1024 * 1024 + 10))
    assert r.status_code == 400 and "limit" in r.json()["detail"]
    assert list((tmp_path / "up").glob("*")) == []
