from app.optimizer.index_advisor import IndexAdvisor
from app.optimizer.parser import parse_query
from app.optimizer.statistics import StatisticsProvider
from app.optimizer.transformations import (
    LogicalOptimizer,
    predicate_pushdown,
    projection_pushdown,
)
from app.optimizer.relational_algebra import Scan, Selection


def _ctx(adapter):
    return adapter.get_schema(), StatisticsProvider(adapter)


def test_predicate_pushdown_moves_selection_to_scan(ecommerce_adapter):
    schema, stats = _ctx(ecommerce_adapter)
    pq = parse_query(
        "SELECT c.name FROM customers c JOIN orders o ON o.customer_id=c.customer_id "
        "WHERE o.status='completed'",
        schema,
    )
    pushed = predicate_pushdown(pq.ra_tree, pq)

    # find the Scan for 'o' and assert a Selection now sits directly above it
    found = {"ok": False}

    def walk(node, parent):
        if isinstance(node, Scan) and node.alias == "o":
            found["ok"] = isinstance(parent, Selection)
        for c in node.children:
            walk(c, node)

    walk(pushed, None)
    assert found["ok"]


def test_projection_pushdown_narrows_columns(ecommerce_adapter):
    schema, stats = _ctx(ecommerce_adapter)
    pq = parse_query("SELECT c.name FROM customers c WHERE c.country='India'", schema)
    pushed = projection_pushdown(pq.ra_tree, pq, schema)
    # a Projection with a bounded column list should wrap the scan
    from app.optimizer.relational_algebra import Projection
    projs = []

    def walk(n):
        if isinstance(n, Projection):
            projs.append(n)
        for c in n.children:
            walk(c)

    walk(pushed)
    # innermost projection keeps only needed cols (name, country) not all 6
    leaf_proj = [p for p in projs if any(isinstance(c, Scan) for c in p.children)]
    assert leaf_proj
    assert len(leaf_proj[0].columns) <= 3


def test_logical_optimizer_quantifies_improvement(ecommerce_adapter):
    schema, stats = _ctx(ecommerce_adapter)
    pq = parse_query(
        "SELECT c.name, o.total FROM customers c JOIN orders o ON o.customer_id=c.customer_id "
        "WHERE o.status='refunded'",
        schema,
    )
    out = LogicalOptimizer(pq, stats, schema).run()
    names = {t["name"] for t in out["transformations"]}
    assert {"Predicate Pushdown", "Join Reordering", "Projection Pushdown"} <= names
    assert "original_tree" in out and "optimized_tree" in out
    # pushing a selective predicate down should not increase cost
    pp = next(t for t in out["transformations"] if t["name"] == "Predicate Pushdown")
    assert pp["after_cost"] <= pp["before_cost"] + 1e-6


def test_index_advisor_recommends_for_selective_where(ecommerce_adapter):
    schema, stats = _ctx(ecommerce_adapter)
    pq = parse_query("SELECT * FROM orders o WHERE o.status='refunded'", schema)
    rec = IndexAdvisor(pq, stats, schema).recommend()
    assert rec["recommendations"]
    top = rec["recommendations"][0]
    assert top["hypothetical_cost"] <= top["current_cost"] + 1e-6
    assert top["table"] == "orders" and top["columns"] == ["status"]
