from app.optimizer.explain_parser import compare, parse_explain_query_plan


def test_explain_query_plan_parses(ecommerce_adapter):
    rows = ecommerce_adapter.explain_query("SELECT * FROM orders WHERE customer_id = 5")
    parsed = parse_explain_query_plan(rows)
    assert parsed["steps"]
    assert "orders" in parsed["tables"]


def test_explain_detects_index_search(ecommerce_adapter):
    # products.category_id is indexed -> EXPLAIN should SEARCH using the index
    rows = ecommerce_adapter.explain_query("SELECT * FROM products WHERE category_id = 1")
    parsed = parse_explain_query_plan(rows)
    assert parsed["indexes_used"] or any(
        s["access"] in ("index-search", "rowid-lookup") for s in parsed["steps"]
    )


def test_compare_structure(ecommerce_adapter):
    from app.optimizer.join_optimizer import JoinOptimizer
    from app.optimizer.parser import parse_query
    from app.optimizer.physical_plans import PhysicalPlanner
    from app.optimizer.statistics import StatisticsProvider

    schema = ecommerce_adapter.get_schema()
    stats = StatisticsProvider(ecommerce_adapter)
    sql = "SELECT * FROM orders o WHERE o.status='completed'"
    pq = parse_query(sql, schema)
    res = JoinOptimizer(PhysicalPlanner(pq, stats, schema)).optimize()
    parsed = parse_explain_query_plan(ecommerce_adapter.explain_query(sql))
    cmp = compare(res.selected.plan.to_dict(), parsed, pq.alias_to_table)
    assert "custom" in cmp and "turso" in cmp and "differences" in cmp


def test_benchmark_reports_stats(ecommerce_adapter):
    b = ecommerce_adapter.benchmark_query("SELECT * FROM orders WHERE status='completed'")
    for k in ("min_ms", "max_ms", "avg_ms", "median_ms", "rows_returned"):
        assert k in b
    assert b["min_ms"] <= b["avg_ms"] <= b["max_ms"] + 1e-6
    assert b["label"] == "Application Benchmark"
