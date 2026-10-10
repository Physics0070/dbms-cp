"""Optimizer orchestrator — implements the full data flow end to end.

Turso -> schema discovery -> statistics -> parse -> relational algebra ->
selectivity -> cardinality -> candidate physical plans -> cost model -> best plan
-> logical optimizations -> Turso EXPLAIN QUERY PLAN -> (optional) benchmark ->
index advisor -> (structured payload for the AI copilot).
"""
from __future__ import annotations

import time
from typing import Optional

from ..database.adapter import DatabaseAdapter
from .cardinality import CardinalityEstimator
from .explain_parser import compare, parse_explain_query_plan
from .index_advisor import IndexAdvisor
from .join_optimizer import JoinOptimizer
from .parser import parse_query
from .physical_plans import PhysicalPlanner
from .statistics import StatisticsProvider
from .transformations import LogicalOptimizer

OPTIMIZER_VERSION = "1.0.0"


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
        "optimizer_version": OPTIMIZER_VERSION,
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
