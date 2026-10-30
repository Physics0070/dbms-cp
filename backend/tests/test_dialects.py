"""Dialect handling: parsing, rewriting and index advice follow the connected adapter.

The pure-sqlglot tests need no server. The `postgres`-marked tests run against a REAL embedded
PostgreSQL (see test_postgres.py) and skip if one cannot start.
"""
import pytest

from app.database.sqlite_adapter import set_adapter
from app.optimizer import index_advisor
from app.optimizer.parser import parse_query
from app.optimizer.rewriter import rewrite_query
from app.optimizer.safety import UnsafeQueryError, default_dialect, validate_readonly


# -- no server needed ------------------------------------------------------------------
def test_postgres_and_mysql_syntax_parses_only_in_its_dialect():
    validate_readonly("SELECT a::int FROM t WHERE b ILIKE 'x%'", "postgres")
    validate_readonly("SELECT `a` FROM `t` LIMIT 5, 10", "mysql")
    with pytest.raises(UnsafeQueryError):
        validate_readonly("SELECT `a` FROM `t` LIMIT 5, 10", "postgres")


def test_default_dialect_follows_connected_adapter(ecommerce_adapter):
    set_adapter(ecommerce_adapter)
    try:
        assert default_dialect() == "sqlite"
        ecommerce_adapter.dialect = "postgres"  # instance override, removed below
        validate_readonly("SELECT 1::int")      # only valid when parsed as postgres
    finally:
        del ecommerce_adapter.dialect
        set_adapter(None)
    assert default_dialect() == "sqlite"  # nothing connected


def test_writes_still_rejected_in_every_dialect():
    for d in ("sqlite", "postgres", "mysql"):
        for bad in ("DELETE FROM t", "UPDATE t SET a = 1", "SELECT 1; DROP TABLE t"):
            with pytest.raises(UnsafeQueryError):
                validate_readonly(bad, d)


def test_rewrite_refused_outside_sqlite_with_reason(ecommerce_adapter):
    from app.optimizer.examples import generate_examples

    sql = next(e["sql"] for e in generate_examples(ecommerce_adapter) if e["kind"] in ("join", "multi-join"))
    schema = ecommerce_adapter.get_schema()
    parsed = parse_query(sql, schema, "sqlite")
    order = list(reversed(list(parsed.alias_to_table)))
    out = rewrite_query(parsed, order, schema, "postgres")
    assert out.status == "unsupported" and "postgres" in out.reasons[0] and out.sql is None


def test_ddl_quoting_per_engine():
    assert index_advisor._quoted_ddl("o", ["a b"], "sqlite") == 'CREATE INDEX IF NOT EXISTS "idx_o_a b" ON "o" ("a b");'
    assert index_advisor._quoted_ddl("o", ["a"], "postgres").startswith('CREATE INDEX IF NOT EXISTS "idx_o_a" ON "o"')
    my = index_advisor._quoted_ddl("o", ["a"], "mysql")
    assert my == "CREATE INDEX `idx_o_a` ON `o` (`a`);"  # MySQL has no IF NOT EXISTS


def test_sqlite_advisor_text_still_names_sqlite(ecommerce_adapter):
    from app.optimizer.orchestrator import optimize_query
    from app.optimizer.examples import generate_examples

    sql = next(e["sql"] for e in generate_examples(ecommerce_adapter) if e["kind"] in ("filter", "join", "multi-join"))
    adv = optimize_query(ecommerce_adapter, sql, run_benchmark=False)["index_advisor"]
    assert "SQLite" in adv["note"]
    for r in adv["recommendations"]:
        assert any("SQLite" in a for a in r["assumptions"])


# -- real PostgreSQL ---------------------------------------------------------------------
try:
    from test_postgres import JOIN_SQL, adapter, pg, settings  # noqa: F401  (fixtures)
except Exception:  # pragma: no cover - psycopg/pgserver missing
    JOIN_SQL = ""

pgm = pytest.mark.postgres

PG_SQL = ("SELECT c.name, c.balance::int AS b FROM customers c JOIN orders o ON o.customer_id = c.id "
          "WHERE c.name ILIKE 'C1%' AND o.total::numeric > 5")


@pgm
def test_postgres_adapter_reports_dialect_and_honest_capabilities(adapter):
    assert adapter.dialect == "postgres"
    assert adapter.capabilities["sql_rewrite"] is False
    assert adapter.capabilities["result_equivalence"] is True


@pgm
def test_postgres_cast_and_ilike_run_the_whole_pipeline(adapter):
    from app.optimizer.orchestrator import optimize_query

    set_adapter(adapter)
    try:
        res = optimize_query(adapter, PG_SQL, run_benchmark=False)
    finally:
        set_adapter(None)
    assert res["optimization"]["selected"]["plan"]
    oq = res["optimized_query"]
    assert oq["status"] == "unsupported" and "postgres" in " ".join(oq["reasons"])
    assert "::" in oq["original_pretty"] or "CAST" in oq["original_pretty"].upper()


@pgm
def test_postgres_index_advice_is_engine_specific(adapter):
    from app.optimizer.orchestrator import optimize_query

    res = optimize_query(adapter, JOIN_SQL, run_benchmark=False)
    adv = res["index_advisor"]
    assert "PostgreSQL" in adv["note"] and "SQLite" not in adv["note"]
    for r in adv["recommendations"]:
        assert r["ddl"].startswith('CREATE INDEX IF NOT EXISTS "idx_')
        assert not any("SQLite" in a for a in r["assumptions"])


@pgm
def test_postgres_result_equivalence_is_real(adapter):
    from app.optimizer.rewriter import verify_equivalent

    same = ("SELECT c.name, SUM(o.total) AS spent FROM orders o JOIN customers c ON o.customer_id = c.id "
            "WHERE o.status = 'shipped' GROUP BY c.name")
    assert verify_equivalent(adapter, JOIN_SQL, same, 10000)["equal"] is True
    different = same.replace("'shipped'", "'paid'")
    assert verify_equivalent(adapter, JOIN_SQL, different, 10000)["equal"] is False
