"""Logical optimizations on the relational algebra tree.

Implements Predicate Pushdown, Projection Pushdown and Join Reordering. Each
transformation reports the before/after trees and quantifies the change using the
same cost model and statistics that drive physical planning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..config import get_settings
from ..database.adapter import TableSchema
from .parser import ParsedQuery
from .physical_plans import PhysicalPlanner
from .join_optimizer import JoinOptimizer
from .relational_algebra import (
    Aggregate,
    ColumnRef,
    Comparison,
    Join,
    Predicate,
    Projection,
    RANode,
    Scan,
    Selection,
    Sort,
    combine_conjuncts,
    flatten_conjuncts,
)
from .statistics import StatisticsProvider


# ---------------------------------------------------------------------------
# RA rewrites (pure tree -> tree)
# ---------------------------------------------------------------------------
def predicate_pushdown(tree: RANode, parsed: ParsedQuery) -> RANode:
    """Push each single-table WHERE conjunct down to just above its Scan."""
    t = tree.copy()

    def rewrite(node: RANode) -> RANode:
        node.children = [rewrite(c) for c in node.children]
        if isinstance(node, Selection):
            conjuncts = flatten_conjuncts(node.predicate)
            pushable, residual = [], []
            for p in conjuncts:
                tset = p.tables()
                if len(tset) == 1:
                    pushable.append((next(iter(tset)), p))
                else:
                    residual.append(p)
            child = node.child
            for alias, pred in pushable:
                child = _insert_selection_above_scan(child, alias, pred)
            combined = combine_conjuncts(residual)
            return Selection(combined, child) if combined is not None else child
        return node

    return rewrite(t)


def _insert_selection_above_scan(node: RANode, alias: str, pred: Predicate) -> RANode:
    if isinstance(node, Scan):
        if node.alias == alias:
            return Selection(pred, node)
        return node
    node.children = [_insert_selection_above_scan(c, alias, pred) for c in node.children]
    return node


def projection_pushdown(tree: RANode, parsed: ParsedQuery, schema: dict[str, TableSchema]) -> RANode:
    """Insert a narrow Projection above each Scan, keeping only needed columns."""
    t = tree.copy()
    needed = _needed_columns(parsed, schema)

    def rewrite(node: RANode) -> RANode:
        if isinstance(node, Scan):
            cols = sorted(needed.get(node.alias, set()))
            if not cols:
                return node
            return Projection([f"{node.alias}.{c}" for c in cols], node)
        node.children = [rewrite(c) for c in node.children]
        return node

    return rewrite(t)


def _needed_columns(parsed: ParsedQuery, schema: dict[str, TableSchema]) -> dict[str, set[str]]:
    needed: dict[str, set[str]] = {a: set() for a in parsed.alias_to_table}

    def add(ref: ColumnRef):
        if ref.table in needed:
            needed[ref.table].add(ref.column)

    # WHERE + join predicates
    for p in flatten_conjuncts(parsed.where):
        for c in p.columns():
            add(c)
    for jc in parsed.join_conditions:
        for c in jc.columns():
            add(c)

    # projections / group by / order by (qualified refs like "alias.col")
    text_cols = list(parsed.projections) + list(parsed.group_by) + list(parsed.order_by)
    for token in text_cols:
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", token)
        if m and m.group(1) in needed:
            needed[m.group(1)].add(m.group(2))

    # If a table's columns can't be determined (e.g. SELECT *), keep all of them.
    if parsed.is_star:
        for alias, real in parsed.alias_to_table.items():
            ts = schema.get(real)
            if ts:
                needed[alias] |= {c.name for c in ts.columns}
    return needed


def build_optimized_logical(parsed: ParsedQuery, order: list[str], schema: dict[str, TableSchema]) -> RANode:
    """Rebuild the logical tree in the chosen join order with pushdowns applied."""
    # local predicates by alias
    per_alias: dict[str, list[Predicate]] = {a: [] for a in parsed.alias_to_table}
    global_preds: list[Predicate] = []
    for p in parsed.base_predicates():
        tset = p.tables()
        if len(tset) == 1 and next(iter(tset)) in per_alias:
            per_alias[next(iter(tset))].append(p)
        else:
            global_preds.append(p)

    needed = _needed_columns(parsed, schema)

    def leaf(alias: str) -> RANode:
        node: RANode = Scan(parsed.alias_to_table[alias], alias)
        cols = sorted(needed.get(alias, set()))
        if cols and not parsed.is_star:
            node = Projection([f"{alias}.{c}" for c in cols], node)
        local = per_alias.get(alias, [])
        combined = combine_conjuncts(local)
        if combined is not None:
            node = Selection(combined, node)
        return node

    current = leaf(order[0])
    built = {order[0]}
    for alias in order[1:]:
        cond = _find_join_cond(parsed, built, alias)
        current = Join(current, leaf(alias), cond, "INNER")
        built.add(alias)

    combined_global = combine_conjuncts(global_preds)
    if combined_global is not None:
        current = Selection(combined_global, current)
    if parsed.group_by or parsed.aggregates:
        current = Aggregate(parsed.group_by, parsed.aggregates, current)
    current = Projection(parsed.projections, current, is_star=parsed.is_star)
    if parsed.order_by:
        current = Sort(parsed.order_by, current)
    return current


def _find_join_cond(parsed: ParsedQuery, built: set[str], alias: str) -> Optional[Comparison]:
    for jc in parsed.join_conditions:
        lt = jc.left.table
        rt = getattr(jc.right, "table", None)
        if lt in built and rt == alias:
            return jc
        if rt in built and lt == alias:
            return Comparison(jc.right, jc.op, jc.left)  # type: ignore[arg-type]
    return None


# ---------------------------------------------------------------------------
# Orchestrated logical optimization with quantified improvements
# ---------------------------------------------------------------------------
@dataclass
class TransformationResult:
    name: str
    description: str
    before_cost: float
    after_cost: float
    before_rows: int
    after_rows: int
    details: dict

    @property
    def improvement_pct(self) -> float:
        if self.before_cost <= 0:
            return 0.0
        return round(100.0 * (self.before_cost - self.after_cost) / self.before_cost, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "before_cost": round(self.before_cost, 4),
            "after_cost": round(self.after_cost, 4),
            "before_rows": self.before_rows,
            "after_rows": self.after_rows,
            "improvement_pct": self.improvement_pct,
            "details": self.details,
        }


class LogicalOptimizer:
    def __init__(self, parsed: ParsedQuery, stats: StatisticsProvider, schema: dict[str, TableSchema]):
        self.parsed = parsed
        self.stats = stats
        self.schema = schema
        self.cfg = get_settings()

    def run(self) -> dict:
        parsed, stats, schema = self.parsed, self.stats, self.schema
        written_order = list(parsed.alias_to_table.keys())

        # Physical plans for isolating each transformation's effect.
        naive = PhysicalPlanner(parsed, stats, schema, self.cfg, pushdown=False)
        naive_plan = naive.finalize(naive.build_left_deep(written_order))

        pushed = PhysicalPlanner(parsed, stats, schema, self.cfg, pushdown=True)
        pushed_written = pushed.finalize(pushed.build_left_deep(written_order))

        jo = JoinOptimizer(pushed)
        opt = jo.optimize()
        best_plan = opt.selected.plan
        best_order = opt.selected.join_order

        transformations: list[TransformationResult] = []

        # 1) Predicate pushdown: naive (filter on top) vs pushed (filter at scans)
        transformations.append(TransformationResult(
            "Predicate Pushdown",
            "Move single-table WHERE predicates down to their base tables so joins "
            "process fewer rows.",
            naive_plan.cumulative_cost, pushed_written.cumulative_cost,
            naive_plan.rows, pushed_written.rows,
            {"pushed_predicates": [
                str(p) for p in parsed.base_predicates() if len(p.tables()) == 1
            ]},
        ))

        # 2) Join reordering: written order vs cost-based best order
        transformations.append(TransformationResult(
            "Join Reordering",
            "Reorder joins so smaller intermediate results are produced first.",
            pushed_written.cumulative_cost, best_plan.cumulative_cost,
            pushed_written.rows, best_plan.rows,
            {"written_order": written_order, "chosen_order": best_order,
             "orders_considered": opt.join_orders_considered},
        ))

        # 3) Projection pushdown: column-narrowing (structural)
        needed = _needed_columns(parsed, schema)
        total_cols = 0
        kept_cols = 0
        for alias, real in parsed.alias_to_table.items():
            ts = schema.get(real)
            if ts:
                total_cols += len(ts.columns)
                kept_cols += len(needed.get(alias, set())) if not parsed.is_star else len(ts.columns)
        transformations.append(TransformationResult(
            "Projection Pushdown",
            "Read only the columns each downstream operator needs, narrowing rows early.",
            float(total_cols), float(kept_cols), pushed_written.rows, pushed_written.rows,
            {"columns_available": total_cols, "columns_kept": kept_cols,
             "needed_by_table": {a: sorted(c) for a, c in needed.items()}},
        ))

        original_tree = parsed.ra_tree.to_dict()
        optimized_tree = build_optimized_logical(parsed, best_order, schema).to_dict()

        overall_before = naive_plan.cumulative_cost
        overall_after = best_plan.cumulative_cost
        overall_pct = (
            round(100.0 * (overall_before - overall_after) / overall_before, 2)
            if overall_before > 0 else 0.0
        )

        return {
            "original_tree": original_tree,
            "optimized_tree": optimized_tree,
            "transformations": [t.to_dict() for t in transformations],
            "overall": {
                "before_cost": round(overall_before, 4),
                "after_cost": round(overall_after, 4),
                "improvement_pct": overall_pct,
            },
        }
