"""Cardinality estimation over the relational algebra tree.

Combines table statistics with the selectivity engine to estimate how many rows
each operator produces. Join cardinality uses the classic System-R formula:

    |A ⋈ B on a=b| = |A| * |B| / max(distinct(a), distinct(b))

All inputs come from statistics computed from the live database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings, get_settings
from .relational_algebra import (
    Aggregate,
    Comparison,
    Join,
    Projection,
    RANode,
    Scan,
    Selection,
    Sort,
)
from .selectivity import SelectivityEstimator
from .statistics import StatisticsProvider


@dataclass
class CardinalityEstimate:
    node_id: str
    op: str
    input_rows: int
    output_rows: int
    method: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "op": self.op,
            "input_rows": self.input_rows,
            "output_rows": self.output_rows,
            "method": self.method,
            "detail": self.detail,
        }


class CardinalityEstimator:
    def __init__(
        self,
        stats: StatisticsProvider,
        alias_to_table: dict[str, str],
        settings: Optional[Settings] = None,
    ):
        self.stats = stats
        self.alias_to_table = alias_to_table
        self.cfg = settings or get_settings()
        self.selectivity = SelectivityEstimator(stats, alias_to_table, self.cfg)
        self.estimates: dict[str, CardinalityEstimate] = {}

    def estimate(self, node: RANode) -> int:
        rows = self._estimate(node)
        return rows

    def _record(self, node: RANode, input_rows: int, output_rows: int, method: str, detail=None) -> int:
        out = max(0, int(round(output_rows)))
        self.estimates[node.id] = CardinalityEstimate(
            node.id, node.op, int(input_rows), out, method, detail or {}
        )
        return out

    def _estimate(self, node: RANode) -> int:
        if isinstance(node, Scan):
            real = self.alias_to_table.get(node.alias, node.table)
            rc = self.stats.row_count(real)
            return self._record(node, rc, rc, "base table row count", {"table": real})

        if isinstance(node, Selection):
            child_rows = self._estimate(node.child)
            est = self.selectivity.estimate(node.predicate)
            out = child_rows * est.selectivity
            return self._record(
                node, child_rows, out, f"selection ({est.method})",
                {"selectivity": round(est.selectivity, 6), "assumptions": est.assumptions},
            )

        if isinstance(node, Join):
            left_rows = self._estimate(node.left)
            right_rows = self._estimate(node.right)
            sel, method, detail = self._join_selectivity(node)
            out = left_rows * right_rows * sel
            if node.join_type in ("LEFT", "FULL"):
                out = max(out, left_rows)  # preserved rows on the outer side
            detail.update({"left_rows": left_rows, "right_rows": right_rows, "join_selectivity": round(sel, 8)})
            return self._record(node, left_rows * right_rows, out, method, detail)

        if isinstance(node, Aggregate):
            child_rows = self._estimate(node.child)
            groups = self._group_count(node, child_rows)
            return self._record(
                node, child_rows, groups, "distinct group estimate",
                {"group_by": node.group_by},
            )

        if isinstance(node, (Projection, Sort)):
            child_rows = self._estimate(node.children[0])
            return self._record(node, child_rows, child_rows, "pass-through")

        # generic
        child_rows = self._estimate(node.children[0]) if node.children else 0
        return self._record(node, child_rows, child_rows, "pass-through")

    def _join_selectivity(self, node: Join) -> tuple[float, str, dict]:
        cond = node.condition
        if node.join_type == "CROSS" or cond is None:
            return 1.0, "cross product", {}
        if isinstance(cond, Comparison) and cond.is_join_predicate and cond.op == "=":
            left = cond.left
            right = cond.right  # ColumnRef
            d_left = self._distinct(left.table, left.column)
            d_right = self._distinct(getattr(right, "table", None), getattr(right, "column", ""))
            denom = max(d_left, d_right, 1)
            return (
                1.0 / denom,
                "System-R equi-join (1/max(distinct))",
                {"distinct_left": d_left, "distinct_right": d_right},
            )
        # non-equi join
        return (
            self.cfg.default_join_selectivity,
            "default join selectivity (non-equi)",
            {},
        )

    def _distinct(self, alias: Optional[str], column: str) -> int:
        cs = self.stats.resolve(alias, column, self.alias_to_table)
        return cs.distinct_count if cs else 1

    def _group_count(self, node: Aggregate, child_rows: int) -> int:
        if not node.group_by:
            return 1  # scalar aggregate
        product = 1
        for g in node.group_by:
            alias, _, col = g.partition(".")
            if not col:
                alias, col = None, alias
            d = self._distinct(alias, col)
            product *= max(1, d)
        return min(product, child_rows) if child_rows else product

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self.estimates.values()]
