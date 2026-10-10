"""Selectivity estimation engine.

Every estimate reports the *method* used and the *assumptions* made, and is
derived from statistics computed from the live database. Default fallbacks (used
only when statistics are unavailable) come from configuration, never from magic
numbers scattered through the code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings, get_settings
from .relational_algebra import (
    And,
    Between,
    Comparison,
    ColumnRef,
    InList,
    Like,
    Literal,
    NullCheck,
    Or,
    Predicate,
    TruePredicate,
    UnknownPredicate,
)
from .statistics import StatisticsProvider


@dataclass
class SelectivityEstimate:
    selectivity: float
    method: str
    assumptions: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def clamp(self) -> "SelectivityEstimate":
        self.selectivity = max(0.0, min(1.0, self.selectivity))
        return self

    def to_dict(self) -> dict:
        return {
            "selectivity": round(self.selectivity, 6),
            "method": self.method,
            "assumptions": self.assumptions,
            "detail": self.detail,
        }


def _as_number(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class SelectivityEstimator:
    def __init__(
        self,
        stats: StatisticsProvider,
        alias_to_table: dict[str, str],
        settings: Optional[Settings] = None,
    ):
        self.stats = stats
        self.alias_to_table = alias_to_table
        self.cfg = settings or get_settings()

    # -- public --------------------------------------------------------------
    def estimate(self, pred: Predicate) -> SelectivityEstimate:
        if pred is None or isinstance(pred, TruePredicate):
            return SelectivityEstimate(1.0, "no-op", ["no predicate"])
        if isinstance(pred, And):
            return self._estimate_and(pred)
        if isinstance(pred, Or):
            return self._estimate_or(pred)
        if isinstance(pred, Comparison):
            return self._estimate_comparison(pred)
        if isinstance(pred, Between):
            return self._estimate_between(pred)
        if isinstance(pred, NullCheck):
            return self._estimate_null(pred)
        if isinstance(pred, InList):
            return self._estimate_in(pred)
        if isinstance(pred, Like):
            return SelectivityEstimate(
                self.cfg.default_range_selectivity,
                "default-like",
                ["LIKE pattern selectivity is not modelled; using configured default"],
            )
        if isinstance(pred, UnknownPredicate):
            return SelectivityEstimate(
                self.cfg.default_range_selectivity,
                "default-unknown",
                [f"unmodelled predicate: {pred.text}"],
            )
        return SelectivityEstimate(self.cfg.default_range_selectivity, "default", ["unhandled predicate"])

    # -- helpers -------------------------------------------------------------
    def _col_stats(self, col: ColumnRef):
        return self.stats.resolve(col.table, col.column, self.alias_to_table)

    def _row_count_for(self, col: ColumnRef) -> int:
        if col.table is None:
            return 0
        real = self.alias_to_table.get(col.table, col.table)
        return self.stats.table_stats(real).row_count

    def _estimate_and(self, pred: And) -> SelectivityEstimate:
        sel = 1.0
        methods = []
        assumptions = ["independence assumption between AND terms"]
        for p in pred.parts:
            e = self.estimate(p)
            sel *= e.selectivity
            methods.append(e.method)
        return SelectivityEstimate(sel, f"and({', '.join(methods)})", assumptions).clamp()

    def _estimate_or(self, pred: Or) -> SelectivityEstimate:
        # P(A or B) = P(A) + P(B) - P(A)P(B), generalised
        sel = 0.0
        methods = []
        for p in pred.parts:
            e = self.estimate(p)
            sel = sel + e.selectivity - sel * e.selectivity
            methods.append(e.method)
        return SelectivityEstimate(
            sel, f"or({', '.join(methods)})", ["independence assumption between OR terms"]
        ).clamp()

    def _estimate_comparison(self, pred: Comparison) -> SelectivityEstimate:
        # Join predicates are handled by the cardinality/join model, not here.
        if pred.is_join_predicate:
            return SelectivityEstimate(
                self.cfg.default_join_selectivity,
                "join-predicate",
                ["column=column comparison handled by join cardinality model"],
            )
        cs = self._col_stats(pred.left)
        op = pred.op
        if not isinstance(pred.right, Literal):
            return SelectivityEstimate(self.cfg.default_eq_selectivity, "default", ["non-literal RHS"])
        value = pred.right.value

        if cs is None:
            base = self.cfg.default_eq_selectivity if op in ("=", "!=") else self.cfg.default_range_selectivity
            return SelectivityEstimate(base, "default-no-stats", ["no column statistics available"])

        if op in ("=", "!="):
            eq = self._equality_selectivity(cs, value, self._row_count_for(pred.left))
            if op == "=":
                return eq
            inv = SelectivityEstimate(
                max(0.0, (1.0 - cs.null_fraction) - eq.selectivity),
                "inequality (1 - eq, excluding NULLs)",
                eq.assumptions + ["NULLs never satisfy '!='"],
                eq.detail,
            )
            return inv.clamp()

        # range operators
        return self._range_selectivity(cs, op, value)

    def _equality_selectivity(self, cs, value, total: int) -> SelectivityEstimate:
        # 1) exact hit in the most-common-values histogram
        for v, cnt in cs.most_common:
            if _values_equal(v, value):
                sel = (cnt / total) if total else 0.0
                return SelectivityEstimate(
                    sel,
                    "MCV histogram (exact frequency)",
                    ["value found in most-common-values list"],
                    {"value_count": cnt, "row_count": total},
                ).clamp()
        # 2) uniform distribution over non-null distinct values
        if cs.distinct_count > 0:
            sel = (1.0 - cs.null_fraction) / cs.distinct_count
            return SelectivityEstimate(
                sel,
                "uniform (1/distinct, excluding NULLs)",
                ["uniform distribution over distinct values"],
                {"distinct_count": cs.distinct_count, "null_fraction": round(cs.null_fraction, 4)},
            ).clamp()
        return SelectivityEstimate(self.cfg.default_eq_selectivity, "default-no-distinct", ["no distinct count"])

    def _range_selectivity(self, cs, op: str, value) -> SelectivityEstimate:
        lo = _as_number(cs.min_value)
        hi = _as_number(cs.max_value)
        v = _as_number(value)
        if lo is None or hi is None or v is None or hi <= lo:
            return SelectivityEstimate(
                self.cfg.default_range_selectivity,
                "default-range",
                ["min/max not numeric or degenerate range; using configured default"],
            )
        span = hi - lo
        if op in (">", ">="):
            frac = (hi - v) / span
        else:  # < or <=
            frac = (v - lo) / span
        return SelectivityEstimate(
            frac,
            "linear interpolation over [min,max]",
            ["values assumed uniformly distributed between min and max"],
            {"min": lo, "max": hi, "value": v},
        ).clamp()

    def _estimate_between(self, pred: Between) -> SelectivityEstimate:
        cs = self._col_stats(pred.col)
        if cs is None:
            return SelectivityEstimate(self.cfg.default_range_selectivity, "default-no-stats", ["no stats"])
        lo = _as_number(cs.min_value)
        hi = _as_number(cs.max_value)
        a = _as_number(pred.low.value)
        b = _as_number(pred.high.value)
        if None in (lo, hi, a, b) or hi <= lo:
            return SelectivityEstimate(self.cfg.default_range_selectivity, "default-range", ["non-numeric range"])
        frac = (min(b, hi) - max(a, lo)) / (hi - lo)
        return SelectivityEstimate(
            frac, "range fraction over [min,max]", ["uniform distribution assumption"],
            {"min": lo, "max": hi, "low": a, "high": b},
        ).clamp()

    def _estimate_null(self, pred: NullCheck) -> SelectivityEstimate:
        cs = self._col_stats(pred.col)
        if cs is None:
            return SelectivityEstimate(0.0 if not pred.negated else 1.0, "default-no-stats", ["no stats"])
        nf = cs.null_fraction
        sel = (1.0 - nf) if pred.negated else nf
        return SelectivityEstimate(
            sel,
            "null fraction from statistics",
            [],
            {"null_fraction": round(nf, 6)},
        ).clamp()

    def _estimate_in(self, pred: InList) -> SelectivityEstimate:
        cs = self._col_stats(pred.col)
        if cs is None:
            sel = min(1.0, len(pred.values) * self.cfg.default_eq_selectivity)
            return SelectivityEstimate(sel, "default-no-stats", ["no stats; N * default eq selectivity"])
        row_count = self._row_count_for(pred.col)
        total = 0.0
        for v in pred.values:
            total += self._equality_selectivity(cs, v.value, row_count).selectivity
        return SelectivityEstimate(
            total, "sum of per-value equality selectivities", ["values assumed mutually exclusive"]
        ).clamp()


def _values_equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return str(a) == str(b)
