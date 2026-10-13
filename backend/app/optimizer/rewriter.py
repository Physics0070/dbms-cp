"""Reconstruct an optimized SQL statement from the optimizer's decisions.

The one thing a rewrite can genuinely control is **join order**. Filters and column lists
need no rewriting: SQLite already applies single-table predicates at the scan, so wrapping
them in subqueries changes the SQL text without changing the plan (and measured slower in
testing). Pushdown and projection are therefore reported in the analysis tabs, not emitted.

Given the parsed query and the cost-based join order, this module re-emits the statement
with the tables joined in that order. SQLite's planner normally picks its own join order and
ignores the written one, so the chosen order is pinned with ``CROSS JOIN ... ON``, which
SQLite treats as a fixed outer/inner order. Join conditions are re-attached to the earliest
join where all of their tables are present; every other predicate stays in WHERE untouched.

Safety first: a rewrite is only produced when it is shape-preserving (inner joins only, no
subqueries / set operations / LIMIT, resolvable columns, `SELECT *` column order unchanged).
Even then the caller must verify equal results against the database before presenting it as
an optimized query (see :func:`verify_equivalent`).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from ..database.adapter import DatabaseAdapter, TableSchema
from .parser import ParsedQuery


@dataclass
class RewriteOutcome:
    status: str                          # "rewritten" | "no_change" | "unsupported"
    sql: Optional[str] = None
    changes: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    join_order: list[str] = field(default_factory=list)
    original_order: list[str] = field(default_factory=list)


def _split_conjuncts(e: Optional[exp.Expression]) -> list[exp.Expression]:
    if e is None:
        return []
    if isinstance(e, exp.Paren):
        return _split_conjuncts(e.this)
    if isinstance(e, exp.And):
        return _split_conjuncts(e.this) + _split_conjuncts(e.expression)
    return [e]


def _and(parts: list[exp.Expression]) -> Optional[exp.Expression]:
    parts = [p.copy() for p in parts]
    if not parts:
        return None
    out = parts[0]
    for p in parts[1:]:
        out = exp.And(this=out, expression=p)
    return out


def _has_bare_star(select: exp.Select) -> bool:
    """True when the select list contains `*` or `t.*` (output column order then matters)."""
    for e in select.expressions:
        if isinstance(e, exp.Star):
            return True
        if isinstance(e, exp.Column) and isinstance(e.this, exp.Star):
            return True
    return False


class _Resolver:
    def __init__(self, parsed: ParsedQuery, schema: dict[str, TableSchema]):
        self.alias_to_table = parsed.alias_to_table
        self.schema = schema

    def alias_of(self, col: exp.Column) -> Optional[str]:
        name, q = col.name, col.table
        if q:
            if q in self.alias_to_table:
                return q
            for alias, real in self.alias_to_table.items():
                if real.lower() == q.lower():
                    return alias
            return None
        owners = [
            a for a, real in self.alias_to_table.items()
            if (ts := self.schema.get(real)) and ts.column(name) is not None
        ]
        return owners[0] if len(owners) == 1 else None


def rewrite_query(
    parsed: ParsedQuery, best_order: list[str], schema: dict[str, TableSchema]
) -> RewriteOutcome:
    original_order = list(parsed.alias_to_table.keys())
    out = RewriteOutcome("unsupported", original_order=original_order, join_order=list(best_order))

    select = parsed.ast
    if not isinstance(select, exp.Select):
        out.reasons.append("Only plain SELECT statements can be rewritten (no CTE / set operations).")
        return out
    if len(list(select.find_all(exp.Select))) > 1 or select.find(exp.Subquery):
        out.reasons.append("Subqueries are not rewritten — moving predicates across them is not provably safe.")
        return out
    if select.args.get("limit") or select.args.get("offset"):
        out.reasons.append("LIMIT/OFFSET present — reordering could change which rows are returned.")
        return out

    from_key = "from_" if "from_" in select.args else "from"
    from_exp = select.args.get(from_key)
    joins = select.args.get("joins") or []
    for j in joins:
        side = (j.args.get("side") or "").upper()
        kind = (j.args.get("kind") or "").upper()
        if side in ("LEFT", "RIGHT", "FULL") or kind in ("LEFT", "RIGHT", "FULL", "OUTER"):
            out.reasons.append(
                "Outer join present — reordering would change which rows survive."
            )
            return out
        if not isinstance(j.this, exp.Table):
            out.reasons.append("A join target is not a plain table.")
            return out

    if len(original_order) < 2:
        out.status = "no_change"
        out.reasons.append(
            "Single-table query: there are no joins to reorder and the filter is already applied "
            "at the scan. The remaining lever is an index — see the Index advisor."
        )
        return out

    # Table nodes by alias, exactly as the user wrote them.
    table_nodes: dict[str, exp.Table] = {}
    for t in ([from_exp.this] if from_exp is not None else []) + [j.this for j in joins]:
        if isinstance(t, exp.Table):
            table_nodes[t.alias_or_name] = t
    if set(table_nodes) != set(original_order):
        out.reasons.append("Could not map every table in the query to its alias.")
        return out

    res = _Resolver(parsed, schema)

    # -- gather every conjunct from ON clauses and WHERE (all joins are inner) --
    conjuncts: list[exp.Expression] = []
    for j in joins:
        conjuncts += _split_conjuncts(j.args.get("on"))
    where = select.args.get("where")
    where_conjuncts = _split_conjuncts(where.this if where is not None else None)
    conjuncts += where_conjuncts

    conj_aliases: list[set[str]] = []
    for c in conjuncts:
        aliases: set[str] = set()
        for col in c.find_all(exp.Column):
            a = res.alias_of(col)
            if a is None:
                out.reasons.append(f"Could not resolve column '{col.sql()}' to a single table.")
                return out
            aliases.add(a)
        conj_aliases.append(aliases)

    order = list(best_order)
    if _has_bare_star(select) and order != original_order:
        order = original_order
        out.reasons.append("SELECT * fixes output column order to the FROM order, so the join order was kept.")
    out.join_order = order

    if order == original_order:
        out.status = "no_change"
        out.reasons.append(
            "The written join order is already the cost-based choice, so there is nothing to reorder."
        )
        return out

    # -- assemble FROM / JOINs in the chosen order -------------------------------
    # Multi-table predicates become ON conditions at the earliest join that has all their
    # tables. Single-table (and constant) predicates stay in WHERE exactly as written.
    attached = [False] * len(conjuncts)
    built = {order[0]}
    new_joins: list[exp.Join] = []
    for alias in order[1:]:
        conds = []
        for i, (c, al) in enumerate(zip(conjuncts, conj_aliases)):
            if attached[i] or len(al) < 2:
                continue
            if alias in al and al <= built | {alias}:
                conds.append(c)
                attached[i] = True
        built.add(alias)
        on = _and(conds)
        # CROSS JOIN pins SQLite's join order; ON keeps the condition with its join.
        new_joins.append(exp.Join(this=table_nodes[alias].copy(), kind="CROSS", on=on))

    leftover = [c for i, (c, al) in enumerate(zip(conjuncts, conj_aliases)) if not attached[i]]

    new = select.copy()
    new.set(from_key, exp.From(this=table_nodes[order[0]].copy()))
    new.set("joins", new_joins)
    lw = _and(leftover)
    new.set("where", exp.Where(this=lw) if lw is not None else None)
    new_sql = new.sql(dialect="sqlite", pretty=True)

    if _normalize(parsed.sql) == _normalize(new_sql):
        out.status = "no_change"
        out.reasons.append("The rewritten query is identical to the one you wrote.")
        return out

    out.changes = [{
        "name": "Join Reordering",
        "what": f"Joins reordered from {' ⋈ '.join(original_order)} to {' ⋈ '.join(order)}, "
                "and written as CROSS JOIN … ON so SQLite keeps that order.",
        "why": "The cost model estimates this order produces smaller intermediate results. "
               "Filters and columns are left exactly as written: SQLite already applies them at the scan.",
        "tradeoff": "SQLite normally chooses its own join order; pinning ours overrides that. "
                    "The measured comparison shows whether it actually helps. "
                    "CROSS JOIN … ON is SQLite-specific syntax.",
    }]
    out.sql = new_sql
    out.status = "rewritten"
    return out


def _normalize(sql: str) -> str:
    try:
        return sqlglot.parse_one(sql, read="sqlite").sql(dialect="sqlite")
    except Exception:
        return re.sub(r"\s+", " ", sql).strip().lower()


# ---------------------------------------------------------------------------
# Verification — never present a rewrite as equivalent without checking.
# ---------------------------------------------------------------------------
def _canon(rows: list[tuple]) -> Counter:
    def norm(v):
        return round(v, 9) if isinstance(v, float) else v
    return Counter(tuple(norm(v) for v in r) for r in rows)


def verify_equivalent(adapter: DatabaseAdapter, original_sql: str, optimized_sql: str, row_cap: int) -> dict:
    try:
        cols_a, rows_a = adapter.execute_readonly(original_sql)
        cols_b, rows_b = adapter.execute_readonly(optimized_sql)
    except Exception as e:
        return {"checked": False, "equal": False, "note": f"Could not execute both queries: {e}"}

    if len(rows_a) > row_cap or len(rows_b) > row_cap:
        return {
            "checked": False, "equal": False,
            "original_rows": len(rows_a), "optimized_rows": len(rows_b),
            "note": f"Result sets exceed the {row_cap}-row verification cap; equivalence not verified.",
        }
    same_cols = [c.lower() for c in cols_a] == [c.lower() for c in cols_b]
    equal = same_cols and _canon(rows_a) == _canon(rows_b)
    return {
        "checked": True,
        "equal": equal,
        "original_rows": len(rows_a),
        "optimized_rows": len(rows_b),
        "columns_match": same_cols,
        "note": (
            "Both queries returned the same columns and the same multiset of rows on this "
            "database (row order is not compared). This is evidence for this data, not a proof "
            "of equivalence on every possible database." if equal
            else "Results differ — the rewrite was rejected."
        ),
    }


def compare_benchmarks(original: dict, optimized: dict) -> dict:
    """Honest timing comparison: only call it faster when the ranges do not overlap."""
    o_med, n_med = original["median_ms"], optimized["median_ms"]
    separated_faster = optimized["max_ms"] < original["min_ms"]
    separated_slower = original["max_ms"] < optimized["min_ms"]
    if separated_faster:
        verdict = "faster"
    elif separated_slower:
        verdict = "slower"
    else:
        verdict = "indistinguishable"
    change_pct = round(100.0 * (o_med - n_med) / o_med, 2) if o_med > 0 else 0.0
    return {
        "original": original,
        "optimized": optimized,
        "median_change_pct": change_pct,
        "verdict": verdict,
        "note": (
            "Wall-clock medians over a small number of runs on a shared machine. "
            + ("The measured ranges do not overlap, so the difference is likely real."
               if verdict != "indistinguishable"
               else "The measured ranges overlap, so this difference is within noise and should not be read as a speedup.")
        ),
    }
