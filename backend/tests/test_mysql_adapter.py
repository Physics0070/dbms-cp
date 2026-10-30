"""MySQL adapter tests - they need a REAL MySQL/MariaDB server and are skipped otherwise.

Point them at a server you do not mind creating a scratch database on:

    MYSQL_TEST_HOST=127.0.0.1 MYSQL_TEST_PORT=3306 MYSQL_TEST_USER=root MYSQL_TEST_PASSWORD=... pytest -m mysql

Without MYSQL_TEST_HOST every test here is skipped, so the MySQL adapter is only as verified
as the last run that had a server. The fixture creates and drops `qp_adapter_test`.
"""
import os

import pytest

pymysql = pytest.importorskip("pymysql")

from app.database.mysql_adapter import MysqlAdapter, connect_mysql  # noqa: E402
from app.database.sqlite_adapter import DatabaseUnavailable  # noqa: E402

pytestmark = [
    pytest.mark.mysql,
    pytest.mark.skipif(not os.environ.get("MYSQL_TEST_HOST"), reason="needs a real MySQL server (set MYSQL_TEST_HOST)"),
]

DB = "qp_adapter_test"


def _conn_args():
    return dict(host=os.environ["MYSQL_TEST_HOST"], port=int(os.environ.get("MYSQL_TEST_PORT", "3306")),
                user=os.environ.get("MYSQL_TEST_USER", "root"), password=os.environ.get("MYSQL_TEST_PASSWORD", ""))


@pytest.fixture(scope="module")
def adapter():
    admin = pymysql.connect(**_conn_args(), autocommit=True)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    cur.execute(f"CREATE DATABASE {DB}")
    cur.execute(f"USE {DB}")
    cur.execute("CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR(40) NOT NULL, city VARCHAR(20) NULL)")
    cur.execute("CREATE TABLE `Order Items` (id INT PRIMARY KEY, customer_id INT NOT NULL, total DECIMAL(10,2), "
                "KEY idx_cust (customer_id), CONSTRAINT fk_cust FOREIGN KEY (customer_id) REFERENCES customers(id) "
                "ON DELETE CASCADE)")
    cur.executemany("INSERT INTO customers VALUES (%s,%s,%s)",
                    [(i, f"c{i}", None if i % 5 == 0 else ("Pune" if i % 2 else "Delhi")) for i in range(1, 201)])
    cur.executemany("INSERT INTO `Order Items` VALUES (%s,%s,%s)", [(i, (i % 200) + 1, i * 1.5) for i in range(1, 1001)])
    cur.execute("ANALYZE TABLE customers, `Order Items`")
    cur.fetchall()
    ad = connect_mysql(database=DB, **_conn_args())
    yield ad
    ad.close()
    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    admin.close()


def _order_items(ad):
    return next(x for x in ad.get_tables() if x.lower() == "order items")


def test_schema_discovery(adapter):
    # lower_case_table_names=1 (Windows default) folds names, so compare case-insensitively
    assert sorted(x.lower() for x in adapter.get_tables()) == ["customers", "order items"]
    cols = {c.name: c for c in adapter.get_columns("customers")}
    assert cols["id"].primary_key and not cols["name"].nullable and cols["city"].nullable
    idx = {i.name: i for i in adapter.get_indexes(_order_items(adapter))}
    assert idx["PRIMARY"].origin == "pk" and idx["idx_cust"].columns == ["customer_id"] and not idx["idx_cust"].unique
    fk = adapter.get_foreign_keys(_order_items(adapter))[0]
    assert (fk.columns, fk.ref_table, fk.ref_columns, fk.on_delete) == (["customer_id"], "customers", ["id"], "CASCADE")


def test_statistics_exact_for_small_tables(adapter):
    st = adapter.get_statistics("customers", use_cache=False)
    assert st.row_count == 200
    city = st.columns["city"]
    assert city.null_count == 40 and abs(city.null_fraction - 0.2) < 1e-9 and city.distinct_count == 2
    assert {v for v, _ in city.most_common} == {"Pune", "Delhi"}
    assert "exactly" in st.source


def test_execute_readonly_and_limit(adapter):
    cols, rows = adapter.execute_readonly("SELECT id, name FROM customers ORDER BY id", limit=3)
    assert cols == ["id", "name"] and len(rows) == 3 and rows[0] == (1, "c1")
    _, rows = adapter.execute_readonly("SELECT total FROM `Order Items` WHERE id = %s", [2])
    assert rows == [(3.0,)]  # DECIMAL converted to JSON-friendly float


@pytest.mark.parametrize("sql", [
    "INSERT INTO customers VALUES (999,'x','y')", "DELETE FROM customers", "DROP TABLE customers",
    "CREATE TABLE zzz (a INT)",
])
def test_writes_rejected_by_the_server_itself(adapter, sql):
    with pytest.raises(pymysql.MySQLError):
        adapter.execute_readonly(sql)
    assert adapter.execute_readonly("SELECT COUNT(*) FROM customers")[1] == [(200,)]


def test_multi_statement_rejected(adapter):
    with pytest.raises(pymysql.MySQLError):
        adapter.execute_readonly("SELECT 1; DROP TABLE customers")
    assert "customers" in adapter.get_tables()


def test_explain_json_flattened_and_parseable(adapter):
    from app.optimizer.explain_parser import parse_explain_query_plan
    rows = adapter.explain_query("SELECT * FROM `Order Items` o JOIN customers c ON c.id = o.customer_id WHERE o.customer_id = 5")
    assert {r["node"]["table_name"] for r in rows if "table_name" in r["node"]} == {"o", "c"}
    parsed = parse_explain_query_plan(rows)
    assert any(s.get("index") for s in parsed["steps"]) or any(s["access"] == "full-scan" for s in parsed["steps"])
    assert all("detail" in r and "parent" in r for r in rows)


def test_explain_tree_and_analyze(adapter):
    assert adapter.explain_bytecode("SELECT * FROM customers")
    text = adapter.explain_analyze("SELECT * FROM customers WHERE id < 10")
    assert "actual time" in text and "rows=" in text


def test_benchmark_shape(adapter):
    b = adapter.benchmark_query("SELECT * FROM customers", warmup=1, runs=3)
    assert b["measured_runs"] == 3 and len(b["samples_ms"]) == 3 and b["rows_returned"] == 200


def test_capabilities_are_honest(adapter):
    c = adapter.capabilities
    assert c["native_explain"] and c["statistics"] and not c["hypothetical_index"]
    assert not c["sql_rewrite"] and c["result_equivalence"]  # no join-order rewrite on MySQL; equivalence verified in test_mysql_pipeline


def test_bad_credentials_error_hides_password():
    args = {**_conn_args(), "user": "no_such_user_zz", "password": "s3cr3t-pass"}
    with pytest.raises(DatabaseUnavailable) as e:
        MysqlAdapter(database=DB, **args)
    assert "s3cr3t-pass" not in str(e.value)


def test_unreachable_host_is_a_clean_error():
    with pytest.raises(DatabaseUnavailable):
        MysqlAdapter("127.0.0.1", 1, "u", "p", "d")
