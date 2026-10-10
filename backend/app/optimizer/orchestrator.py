"""Optimizer orchestrator — implements the full data flow end to end.

Turso -> schema discovery -> statistics -> parse -> relational algebra ->
selectivity -> cardinality -> candidate physical plans -> cost model -> best plan
-> logical optimizations -> Turso EXPLAIN QUERY PLAN -> (optional) benchmark ->
index advisor -> (structured payload for the AI copilot).
"""
from __future__ import annotations

import time
from typing import Optional

from ..config import get_settings
from ..database.adapter import DatabaseAdapter
from .cardinality import CardinalityEstimator
from .explain_parser import compare, parse_explain_query_plan
from .index_advisor import IndexAdvisor
from .join_optimizer import JoinOptimizer
from .parser import parse_query
from .physical_plans import PhysicalPlanner
from .rewriter import compare_benchmarks, rewrite_query, verify_equivalent
from .statistics import StatisticsProvider
from .transformations import LogicalOptimizer


def build_optimized_query(
    adapter: DatabaseAdapter, parsed, order, schema, logical: dict,
    original_benchmark: Optional[dict], run_benchmark: bool,
) -> dict:
    """Reconstruct, verify and (optionally) measure an optimized version of the query."""
    cfg = get_settings()
    overall = logical["overall"]
    estimated = {
        "before_cost": overall["before_cost"],
        "after_cost": overall["after_cost"],
        "improvement_pct": overall["improvement_pct"],
        "note": "Estimated by the cost model — not a measured speedup.",
    }
    rw = rewrite_query(parsed, order, schema)
    report: dict = {
        "status": rw.status,
        "original_sql": parsed.sql.strip(),
        "sql": None,
        "changes": rw.changes,
        "reasons": rw.reasons,
        "original_order": rw.original_order,
        "join_order": rw.join_order,
        "estimated": estimated,
        "equivalence": None,
        "benchmark": None,
        "turso_plan": None,
    }
    if rw.status != "rewritten":
        return report

    eq = verify_equivalent(adapter, parsed.sql, rw.sql, cfg.equivalence_row_cap)
    report["equivalence"] = eq
    if not (eq["checked"] and eq["equal"]):
        # Never present an unverified rewrite as an optimization.
        report["status"] = "rejected" if eq["checked"] else "unverified"
        report["rejected_sql"] = rw.sql
        report["changes"] = []
        report["reasons"] = [eq["note"]]
        return report

    report["sql"] = rw.sql
    try:
        report["turso_plan"] = [s["detail"] for s in parse_explain_query_plan(adapter.explain_query(rw.sql))["steps"]]
    except Exception:  # pragma: no cover
        pass
    if run_benchmark and original_benchmark and not original_benchmark.get("error"):
        try:
            report["benchmark"] = compare_benchmarks(original_benchmark, adapter.benchmark_query(rw.sql))
        except Exception as e:  # pragma: no cover
            report["benchmark"] = {"error": str(e)}
    return report


def optimize_query(
    adapter: DatabaseAdapter,
    sql: str,
    run_benchmark: bool = False,
    run_index_advisor: bool = True,
) -> dict:
    t0 = time.perf_counter()
    stats = StatisticsProvider(adapter)
    schema = adapter.get_schema()

    parsed = parse_query(sql, schema)

    # cardinality annotation over the logical tree
    card = CardinalityEstimator(stats, parsed.alias_to_table)
    final_rows = card.estimate(parsed.ra_tree)

    # physical planning + cost-based selection
    planner = PhysicalPlanner(parsed, stats, schema)
    optimization = JoinOptimizer(planner).optimize()

    # logical optimizations (before/after trees + quantified improvements)
    logical = LogicalOptimizer(parsed, stats, schema).run()

    # Turso / SQLite EXPLAIN QUERY PLAN comparison
    try:
        eqp = parse_explain_query_plan(adapter.explain_query(sql))
        explain_cmp = compare(optimization.selected.plan.to_dict(), eqp, parsed.alias_to_table)
    except Exception as e:  # pragma: no cover
        explain_cmp = {"error": str(e), "differences": [], "turso": None}

    # optional application benchmark
    benchmark = None
    if run_benchmark:
        try:
            benchmark = adapter.benchmark_query(sql)
        except Exception as e:  # pragma: no cover
            benchmark = {"error": str(e)}

    # reconstructed, verified optimized query
    try:
        optimized_query = build_optimized_query(
            adapter, parsed, optimization.selected.join_order, schema, logical,
            benchmark, run_benchmark,
        )
    except Exception as e:  # pragma: no cover
        optimized_query = {"status": "error", "reasons": [str(e)], "sql": None, "changes": []}

    # what-if index advisor
    index_advisor = None
    if run_index_advisor:
        try:
            index_advisor = IndexAdvisor(parsed, stats, schema).recommend()
        except Exception as e:  # pragma: no cover
            index_advisor = {"error": str(e), "recommendations": []}

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return {
        "sql": sql,
        "optimizer_version": get_settings().optimizer_version,
        "database_backend": getattr(adapter, "backend_name", "libSQL"),
        "statistics_source": "Computed from Turso database",
        "optimization_time_ms": elapsed_ms,
        "relational_algebra": parsed.ra_tree.to_dict(),
        "cardinality": {
            "estimated_final_rows": final_rows,
            "per_operator": card.to_list(),
        },
        "optimization": optimization.to_dict(),
        "logical_optimization": logical,
        "explain": explain_cmp,
        "optimized_query": optimized_query,
        "benchmark": benchmark,
        "index_advisor": index_advisor,
        "summary": {
            "selected_total_cost": optimization.selected.plan.cumulative_cost,
            "candidate_count": len(optimization.candidates),
            "estimated_cardinality": final_rows,
            "join_orders_considered": optimization.join_orders_considered,
            "relations": optimization.relations,
        },
    }
