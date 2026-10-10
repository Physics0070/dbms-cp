"""Proof that the optimizer is NOT hardcoded to the e-commerce schema.

1. Run the *entire* optimization pipeline against an unrelated 'library' schema.
2. Statically audit the optimizer/database source for any e-commerce table names.
"""
import re
from pathlib import Path

import pytest

from app.optimizer.orchestrator import optimize_query


def test_full_pipeline_on_library_schema(library_adapter):
    sql = (
        "SELECT a.name, b.title FROM authors a "
        "JOIN books b ON b.author_id = a.author_id "
        "WHERE b.genre = 'Fiction' ORDER BY b.title"
    )
    result = optimize_query(library_adapter, sql, run_benchmark=True, run_index_advisor=True)

    # relational algebra + plans generated dynamically for a schema it never saw before
    assert result["relational_algebra"]["op"] in ("Sort", "Projection")
    assert result["summary"]["candidate_count"] >= 1
    assert result["summary"]["selected_total_cost"] > 0
    assert result["summary"]["estimated_cardinality"] >= 0

    # statistics came from the live library DB
    assert result["statistics_source"] == "Computed from Turso database"

    # logical optimizations ran
    names = {t["name"] for t in result["logical_optimization"]["transformations"]}
    assert "Predicate Pushdown" in names

    # Turso EXPLAIN comparison worked
    assert "differences" in result["explain"]

    # benchmark produced real timings
    assert result["benchmark"]["median_ms"] >= 0

    # the selected plan references ONLY library tables
    plan_text = str(result["optimization"]["selected"])
    for ecommerce_table in ("customers", "orders", "order_items", "products", "categories"):
        assert ecommerce_table not in plan_text


def test_library_aggregate_query(library_adapter):
    sql = "SELECT genre, COUNT(*) AS n FROM books GROUP BY genre ORDER BY n DESC"
    result = optimize_query(library_adapter, sql)
    assert result["summary"]["selected_total_cost"] > 0


ECOMMERCE_NAMES = {"customers", "orders", "order_items", "products", "categories"}


def test_optimizer_source_has_no_hardcoded_table_names():
    """No optimizer/database module may branch on a demo table name.

    We use AST inspection so that the English word 'orders' appearing in a comment
    or docstring (e.g. "enumerate join orders") is NOT flagged — only exact string
    literals and identifiers that equal a demo table name count as hardcoding.
    """
    import ast

    base = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for pyfile in list((base / "optimizer").glob("*.py")) + list((base / "database").glob("*.py")):
        tree = ast.parse(pyfile.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            val = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.strip().lower()
            elif isinstance(node, ast.Name):
                val = node.id.lower()
            elif isinstance(node, ast.Attribute):
                val = node.attr.lower()
            if val in ECOMMERCE_NAMES:
                offenders.append(f"{pyfile.name}: '{val}'")
    assert not offenders, (
        "Found hardcoded demo table names in optimizer/database code: " + ", ".join(offenders)
    )
