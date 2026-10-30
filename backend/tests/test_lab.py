"""Benchmark lab: bounded runs, separate estimated/measured, honest verdicts, safety."""
import pytest
from fastapi.testclient import TestClient

from app import benchmark_lab
from app.database.sqlite_adapter import set_adapter
from app.optimizer.safety import UnsafeQueryError

BASE = "SELECT * FROM customers WHERE customer_id < 50"
SAME = "SELECT * FROM customers WHERE customer_id < 50 ORDER BY customer_id"
OTHER = "SELECT * FROM customers WHERE customer_id < 10"


def test_compare_shape_and_separate_labels(ecommerce_adapter):
    r = benchmark_lab.compare(ecommerce_adapter, BASE, SAME, warmup=1, runs=4)
    assert r["config"] == {"warmup_runs": 1, "measured_runs": 4, "equivalence_row_cap": r["config"]["equivalence_row_cap"]}
    for side in ("baseline", "candidate"):
        m = r["measured"][side]
        assert len(m["samples_ms"]) == 4 and m["min_ms"] <= m["median_ms"] <= m["max_ms"] and m["iqr_ms"] >= 0
    assert "Estimated" in r["estimated"]["label"] and "Measured" in r["measured"]["label"]
    assert r["equivalence"]["equal"] is True and r["caveats"]


def test_runs_are_clamped(ecommerce_adapter):
    r = benchmark_lab.compare(ecommerce_adapter, BASE, BASE, warmup=999, runs=999)
    assert r["config"]["warmup_runs"] == benchmark_lab.MAX_WARMUP and r["config"]["measured_runs"] == benchmark_lab.MAX_RUNS
    r = benchmark_lab.compare(ecommerce_adapter, BASE, BASE, warmup=0, runs=0)
    assert r["config"]["measured_runs"] == benchmark_lab.MIN_RUNS


def test_different_results_give_no_verdict_or_percentage(ecommerce_adapter):
    r = benchmark_lab.compare(ecommerce_adapter, BASE, OTHER, warmup=0, runs=3)
    assert r["equivalence"]["equal"] is False
    assert r["measured"]["verdict"] == "not_comparable" and r["measured"]["median_change_pct"] is None


def test_no_percentage_when_indistinguishable(ecommerce_adapter, monkeypatch):
    def fake(self, sql, warmup=None, runs=None):  # identical overlapping timings
        return {"samples_ms": [1.0, 1.1, 1.2], "min_ms": 1.0, "max_ms": 1.2, "median_ms": 1.1, "avg_ms": 1.1, "rows_returned": 1}
    monkeypatch.setattr(type(ecommerce_adapter), "benchmark_query", fake)
    r = benchmark_lab.compare(ecommerce_adapter, BASE, SAME, runs=3)
    assert r["measured"]["verdict"] == "indistinguishable" and r["measured"]["median_change_pct"] is None


def test_faster_only_when_ranges_separate(ecommerce_adapter, monkeypatch):
    calls = iter([
        {"samples_ms": [10.0, 11.0, 12.0], "min_ms": 10.0, "max_ms": 12.0, "median_ms": 11.0, "avg_ms": 11.0, "rows_returned": 1},
        {"samples_ms": [2.0, 3.0, 4.0], "min_ms": 2.0, "max_ms": 4.0, "median_ms": 3.0, "avg_ms": 3.0, "rows_returned": 1},
    ])
    monkeypatch.setattr(type(ecommerce_adapter), "benchmark_query", lambda self, sql, warmup=None, runs=None: next(calls))
    r = benchmark_lab.compare(ecommerce_adapter, BASE, SAME, runs=3)
    assert r["measured"]["verdict"] == "faster" and r["measured"]["median_change_pct"] > 0


def test_write_statements_rejected(ecommerce_adapter):
    with pytest.raises(UnsafeQueryError):
        benchmark_lab.compare(ecommerce_adapter, BASE, "DELETE FROM customers")


def test_api_endpoint(ecommerce_adapter):
    from app.main import app

    set_adapter(ecommerce_adapter)
    try:
        c = TestClient(app)
        ok = c.post("/api/lab/compare", json={"baseline_sql": BASE, "candidate_sql": SAME, "runs": 3, "warmup": 0})
        assert ok.status_code == 200 and ok.json()["measured"]["verdict"] in ("faster", "slower", "indistinguishable")
        bad = c.post("/api/lab/compare", json={"baseline_sql": BASE, "candidate_sql": "DROP TABLE customers"})
        assert bad.status_code == 400
    finally:
        set_adapter(None)
