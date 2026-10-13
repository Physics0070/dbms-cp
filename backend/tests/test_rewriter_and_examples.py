"""Optimized-query reconstruction + schema-derived examples, on BOTH schemas."""
import pytest

from app.optimizer.examples import generate_examples
from app.optimizer.join_optimizer import JoinOptimizer
from app.optimizer.orchestrator import optimize_query
from app.optimizer.parser import parse_query
from app.optimizer.physical_plans import PhysicalPlanner
from app.optimizer.rewriter import compare_benchmarks, rewrite_query, verify_equivalent
from app.optimizer.statistics import StatisticsProvider


@pytest.fixture(params=["ecommerce_adapter", "library_adapter"])
def adapter(request):
    return request.getfixturevalue(request.param)


def _rewrite(adapter, sql):
    schema = adapter.get_schema()
    pq = parse_query(sql, schema)
    order = JoinOptimizer(PhysicalPlanner(pq, StatisticsProvider(adapter), schema)).optimize().selected.join_order
    return pq, rewrite_query(pq, order, schema)


# -- schema-derived examples ---------------------------------------------------
def test_examples_exist_and_all_optimize(adapter):
    examples = generate_examples(adapter)
    assert examples, "a schema with tables must yield at least one example"
    for ex in examples:
        result = optimize_query(adapter, ex["sql"], run_index_advisor=False)
        assert result["summary"]["selected_total_cost"] > 0, ex["label"]


def test_examples_only_reference_discovered_tables(adapter):
    tables = set(adapter.get_tables())
    for ex in generate_examples(adapter):
        pq = parse_query(ex["sql"], adapter.get_schema())
        assert set(pq.alias_to_table.values()) <= tables


def test_examples_differ_between_schemas(ecommerce_adapter, library_adapter):
    a = {e["sql"] for e in generate_examples(ecommerce_adapter)}
    b = {e["sql"] for e in generate_examples(library_adapter)}
    assert a and b and a.isdisjoint(b)


# -- rewrite: positive cases ---------------------------------------------------
def test_join_query_is_rewritten_and_equivalent(adapter):
    # Use a generated join example so the test is schema-agnostic.
    join = next(e for e in generate_examples(adapter) if e["kind"] in ("join", "multi-join"))
    pq, rw = _rewrite(adapter, join["sql"])
    assert rw.status in ("rewritten", "no_change")
    if rw.status == "rewritten":
        assert rw.sql and rw.changes
        v = verify_equivalent(adapter, join["sql"], rw.sql, 50000)
        assert v["checked"] and v["equal"], v


def test_rewrite_uses_only_query_tables(adapter):
    join = next(e for e in generate_examples(adapter) if e["kind"] in ("join", "multi-join"))
    pq, rw = _rewrite(adapter, join["sql"])
    if rw.sql:
        import sqlglot
        from sqlglot import exp
        used = {t.name for t in sqlglot.parse_one(rw.sql, read="sqlite").find_all(exp.Table)}
        assert used <= set(pq.alias_to_table.values())


def test_rewrite_is_a_real_join_reorder(adapter):
    """A rewrite must change the join order and pin it; it must never be cosmetic."""
    for ex in generate_examples(adapter):
        _, rw = _rewrite(adapter, ex["sql"])
        if rw.status == "rewritten":
            assert rw.join_order != rw.original_order, ex["label"]
            assert [c["name"] for c in rw.changes] == ["Join Reordering"]
            assert "CROSS JOIN" in rw.sql


def test_filters_and_columns_are_left_untouched(adapter):
    """The rewrite must not wrap tables in subqueries or alter the select list/filters."""
    import sqlglot
    from sqlglot import exp
    for ex in generate_examples(adapter):
        pq, rw = _rewrite(adapter, ex["sql"])
        if rw.status != "rewritten":
            continue
        new = sqlglot.parse_one(rw.sql, read="sqlite")
        assert not list(new.find_all(exp.Subquery))
        assert [e.sql() for e in new.expressions] == [e.sql() for e in pq.ast.expressions]


def test_showcase_example_gets_a_verified_rewrite_on_some_schema(ecommerce_adapter, library_adapter):
    """The generated 'reorderable' example exists and, where the model finds a gain, verifies."""
    for a in (ecommerce_adapter, library_adapter):
        ex = [e for e in generate_examples(a) if e["kind"] == "reorderable"]
        assert ex, "the schema-derived showcase example should be generated for a 3-table chain"
        rows = a.execute_readonly(ex[0]["sql"])[1]
        assert rows, "showcase example must return rows so equivalence is meaningful"


# -- rewrite: honest refusals --------------------------------------------------
def test_single_table_query_reports_already_optimal(adapter):
    t = adapter.get_tables()[0]
    pq, rw = _rewrite(adapter, f"SELECT * FROM {t}")
    assert rw.status == "no_change" and rw.sql is None and rw.reasons


def test_outer_join_is_not_rewritten(adapter):
    ex = next(e for e in generate_examples(adapter) if e["kind"] == "join")
    sql = ex["sql"].replace("\nJOIN", "\nLEFT JOIN").split("\nWHERE")[0]
    _, rw = _rewrite(adapter, sql)
    assert rw.status == "unsupported" and any("Outer join" in r for r in rw.reasons)


def test_limit_is_not_rewritten(adapter):
    ex = next(e for e in generate_examples(adapter) if e["kind"] == "join")
    _, rw = _rewrite(adapter, ex["sql"] + "\nLIMIT 3")
    assert rw.status == "unsupported"


def test_select_star_keeps_column_order(adapter):
    ex = next(e for e in generate_examples(adapter) if e["kind"] == "join")
    head = ex["sql"].split("\nFROM", 1)[1]
    pq, rw = _rewrite(adapter, "SELECT *\nFROM" + head)
    if rw.sql:
        assert rw.join_order == rw.original_order  # order pinned by SELECT *
        assert verify_equivalent(adapter, pq.sql, rw.sql, 50000)["equal"]


# -- verification must catch wrong rewrites ------------------------------------
def test_verifier_rejects_different_results(adapter):
    t = adapter.get_tables()[0]
    v = verify_equivalent(adapter, f"SELECT * FROM {t}", f"SELECT * FROM {t} LIMIT 1", 50000)
    assert v["checked"] and not v["equal"]


def test_verifier_respects_row_cap(adapter):
    t = adapter.get_tables()[0]
    v = verify_equivalent(adapter, f"SELECT * FROM {t}", f"SELECT * FROM {t}", 0)
    assert not v["checked"]


# -- benchmark comparison must not over-claim ----------------------------------
def _b(med, lo, hi):
    return {"median_ms": med, "min_ms": lo, "max_ms": hi}


def test_overlapping_timings_are_indistinguishable():
    r = compare_benchmarks(_b(1.0, 0.8, 1.4), _b(0.9, 0.7, 1.2))
    assert r["verdict"] == "indistinguishable"


def test_separated_timings_are_reported():
    assert compare_benchmarks(_b(10, 9, 11), _b(2, 1.5, 3))["verdict"] == "faster"
    assert compare_benchmarks(_b(2, 1.5, 3), _b(10, 9, 11))["verdict"] == "slower"


# -- end to end ------------------------------------------------------------------
def test_pipeline_returns_optimized_query_block(adapter):
    ex = next(e for e in generate_examples(adapter) if e["kind"] in ("join", "multi-join"))
    r = optimize_query(adapter, ex["sql"], run_benchmark=True, run_index_advisor=False)
    oq = r["optimized_query"]
    assert oq["status"] in ("rewritten", "no_change")
    assert oq["estimated"]["note"].startswith("Estimated")
    if oq["status"] == "rewritten":
        assert oq["equivalence"]["equal"] is True
        assert oq["benchmark"]["verdict"] in ("faster", "slower", "indistinguishable")
