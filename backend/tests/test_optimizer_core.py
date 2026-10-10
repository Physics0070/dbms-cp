"""Parser, selectivity, cardinality, cost, plans, join order — on the e-commerce DB."""
import pytest

from app.optimizer.cardinality import CardinalityEstimator
from app.optimizer.cost_model import CostModel
from app.optimizer.join_optimizer import JoinOptimizer
from app.optimizer.parser import parse_query
from app.optimizer.physical_plans import PhysicalPlanner
from app.optimizer.relational_algebra import Join, Projection, Scan, Selection, Sort
from app.optimizer.selectivity import SelectivityEstimator
from app.optimizer.statistics import StatisticsProvider


@pytest.fixture
def ctx(ecommerce_adapter):
    schema = ecommerce_adapter.get_schema()
    stats = StatisticsProvider(ecommerce_adapter)
    return ecommerce_adapter, schema, stats


# -- parser ------------------------------------------------------------------
def test_parse_join_and_where(ctx):
    _, schema, _ = ctx
    pq = parse_query(
        "SELECT c.name, o.total FROM customers c "
        "JOIN orders o ON o.customer_id = c.customer_id "
        "WHERE o.status = 'completed' ORDER BY o.total DESC",
        schema,
    )
    assert pq.alias_to_table == {"c": "customers", "o": "orders"}
    assert len(pq.join_conditions) == 1
    assert pq.order_by and "DESC" in pq.order_by[0]
    assert isinstance(pq.ra_tree, Sort)
    assert isinstance(pq.ra_tree.children[0], Projection)


def test_parse_aggregate(ctx):
    _, schema, _ = ctx
    pq = parse_query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status", schema)
    # the parser resolves the unqualified column to its owning table
    assert pq.group_by == ["orders.status"]
    assert any("COUNT" in a.upper() for a in pq.aggregates)


# -- selectivity -------------------------------------------------------------
def test_equality_selectivity_uses_mcv(ctx):
    _, schema, stats = ctx
    pq = parse_query("SELECT * FROM orders o WHERE o.status = 'completed'", schema)
    est = SelectivityEstimator(stats, pq.alias_to_table)
    e = est.estimate(pq.base_predicates()[0])
    assert 0 < e.selectivity < 1
    assert "MCV" in e.method or "uniform" in e.method


def test_rare_value_is_more_selective(ctx):
    _, schema, stats = ctx
    def sel(v):
        pq = parse_query(f"SELECT * FROM orders o WHERE o.status = '{v}'", schema)
        return SelectivityEstimator(stats, pq.alias_to_table).estimate(pq.base_predicates()[0]).selectivity
    assert sel("refunded") < sel("completed")


def test_and_is_conjunctive(ctx):
    _, schema, stats = ctx
    pq = parse_query("SELECT * FROM orders o WHERE o.status='completed' AND o.total > 50", schema)
    est = SelectivityEstimator(stats, pq.alias_to_table)
    from app.optimizer.relational_algebra import And
    combined = And(pq.base_predicates())
    s_and = est.estimate(combined).selectivity
    s0 = est.estimate(pq.base_predicates()[0]).selectivity
    assert s_and <= s0 + 1e-9  # conjunction never increases selectivity


# -- cardinality -------------------------------------------------------------
def test_scan_cardinality_is_rowcount(ctx):
    _, schema, stats = ctx
    pq = parse_query("SELECT * FROM orders", schema)
    ce = CardinalityEstimator(stats, pq.alias_to_table)
    rows = ce.estimate(pq.ra_tree)
    assert rows == stats.row_count("orders")


def test_join_cardinality_system_r(ctx):
    _, schema, stats = ctx
    pq = parse_query(
        "SELECT * FROM customers c JOIN orders o ON o.customer_id = c.customer_id", schema
    )
    ce = CardinalityEstimator(stats, pq.alias_to_table)
    rows = ce.estimate(pq.ra_tree)
    # |c|*|o| / max(distinct) — bounded by product, positive
    assert 0 < rows <= stats.row_count("customers") * stats.row_count("orders")


# -- cost model --------------------------------------------------------------
def test_cost_monotonic_in_rows():
    cm = CostModel()
    assert cm.seq_scan(1000).total > cm.seq_scan(100).total


def test_index_scan_cheaper_when_selective():
    cm = CostModel()
    # scanning 1% of a big table via index beats a full sequential scan
    assert cm.index_scan(100000, 1000).total < cm.seq_scan(100000).total


# -- physical plans ----------------------------------------------------------
def test_access_paths_include_seqscan(ctx):
    adapter, schema, stats = ctx
    pq = parse_query("SELECT * FROM orders o WHERE o.status='completed'", schema)
    planner = PhysicalPlanner(pq, stats, schema)
    paths = planner.access_paths("o")
    assert any(p.operators()[-1] == "SeqScan" or "SeqScan" in p.operators() for p in paths)


def test_index_access_path_when_index_exists(ctx):
    adapter, schema, stats = ctx
    # products has an index on category_id
    pq = parse_query("SELECT * FROM products p WHERE p.category_id = 1", schema)
    planner = PhysicalPlanner(pq, stats, schema)
    ops = set()
    for p in planner.access_paths("p"):
        ops |= set(p.operators())
    assert "IndexScan" in ops


# -- join order --------------------------------------------------------------
def test_multiple_candidates_and_min_selected(ctx):
    adapter, schema, stats = ctx
    pq = parse_query(
        "SELECT c.name, o.total, oi.quantity FROM customers c "
        "JOIN orders o ON o.customer_id = c.customer_id "
        "JOIN order_items oi ON oi.order_id = o.order_id "
        "WHERE o.status='completed'",
        schema,
    )
    planner = PhysicalPlanner(pq, stats, schema)
    res = JoinOptimizer(planner).optimize()
    assert res.join_orders_considered >= 2
    assert len(res.candidates) >= 1
    costs = [c.plan.cumulative_cost for c in res.candidates]
    assert res.selected.plan.cumulative_cost == min(costs)
