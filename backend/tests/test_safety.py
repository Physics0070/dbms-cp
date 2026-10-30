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


@pytest.mark.parametrize("sql", [
    "SELECT load_extension('evil.dll')",
    "SELECT readfile('/etc/passwd')",
    "SELECT writefile('x', 'y')",
    "SELECT fts3_tokenizer('simple')",
    "SELECT 1; PRAGMA writable_schema = 1",
    "EXPLAIN DELETE FROM orders",
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "VACUUM INTO 'copy.db'",
    "DETACH DATABASE x",
    "BEGIN; SELECT 1",
])
def test_rejects_escapes_and_side_effects(sql):
    with pytest.raises(UnsafeQueryError):
        validate_readonly(sql)


def test_function_names_inside_literals_or_columns_are_allowed():
    validate_readonly("SELECT * FROM t WHERE note = 'call load_extension(x)'")
    validate_readonly("SELECT readfile_count FROM t")


def test_function_check_survives_whitespace_tricks():
    with pytest.raises(UnsafeQueryError):
        validate_readonly("SELECT load_extension\n\t('x')")
