import pytest

from app.optimizer.safety import UnsafeQueryError, validate_readonly


@pytest.mark.parametrize("sql", [
    "SELECT * FROM orders",
    "SELECT a.x FROM t a JOIN u b ON a.id=b.id WHERE a.x > 1",
    "WITH q AS (SELECT 1 AS n) SELECT n FROM q",
])
def test_allows_select(sql):
    validate_readonly(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO orders VALUES (1)",
    "UPDATE orders SET total = 0",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE t (id INT)",
    "TRUNCATE TABLE orders",
    "PRAGMA table_info(orders)",
    "ATTACH DATABASE 'x' AS y",
    "SELECT 1; DELETE FROM orders",
    "REPLACE INTO orders VALUES (1)",
])
def test_rejects_writes(sql):
    with pytest.raises(UnsafeQueryError):
        validate_readonly(sql)


def test_keyword_inside_string_is_allowed():
    # 'DELETE' appears only inside a string literal, not as a statement.
    validate_readonly("SELECT * FROM orders WHERE status = 'DELETE_ME'")
