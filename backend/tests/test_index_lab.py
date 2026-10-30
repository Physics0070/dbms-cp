"""Index Lab: enriched recommendations are labelled as simulation and never create indexes."""
from app.optimizer.index_advisor import IndexAdvisor
from app.optimizer.parser import parse_query
from app.optimizer.statistics import StatisticsProvider


def _rec(adapter, sql):
    schema = adapter.get_schema()
    return IndexAdvisor(parse_query(sql, schema), StatisticsProvider(adapter), schema).recommend()


def test_recommendation_is_explained_and_labelled(ecommerce_adapter):
    out = _rec(ecommerce_adapter, "SELECT * FROM orders o WHERE o.status='refunded'")
    assert out["native_hypothetical_indexes"] is False
    r = out["recommendations"][0]
    assert r["benefit_basis"] == "analytical simulation"
    assert r["patterns"] == ["WHERE on o.status"] and r["filter_columns"] == ["status"]
    assert r["ddl"].startswith('CREATE INDEX IF NOT EXISTS "idx_orders_status" ON "orders" ("status")')
    assert r["assumptions"] and r["tradeoffs"] and r["expected_plan_change"]
    est = r["estimated_overhead"]
    assert "bytes_estimate" in est and est["basis"]  # estimate or explicit 'unavailable'


def test_advising_never_modifies_database(ecommerce_adapter):
    before = {i.name for t in ecommerce_adapter.get_tables() for i in ecommerce_adapter.get_indexes(t)}
    _rec(ecommerce_adapter, "SELECT * FROM orders o WHERE o.status='refunded'")
    after = {i.name for t in ecommerce_adapter.get_tables() for i in ecommerce_adapter.get_indexes(t)}
    assert before == after


def test_fixed_width_storage_estimate_and_text_unavailable(ecommerce_adapter):
    from app.optimizer.index_advisor import _storage_estimate
    ts = ecommerce_adapter.get_table_schema("orders")
    num = next(c.name for c in ts.columns if c.data_type.upper().startswith("INT"))
    txt = next(c.name for c in ts.columns if c.data_type.upper().startswith("TEXT"))
    assert _storage_estimate(ts, [num], 100)["bytes_estimate"] == 1600
    assert _storage_estimate(ts, [txt], 100)["bytes_estimate"] is None
