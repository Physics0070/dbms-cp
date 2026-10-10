"""What-if index advisor.

Candidate columns are discovered from the query's WHERE / JOIN / ORDER BY / GROUP
BY clauses. For each candidate we simulate a hypothetical index by re-running the
cost-based optimizer with that index added to a *copy* of the schema — no index is
ever created. Improvement is the drop in the selected plan's total cost.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from ..database.adapter import Index, TableSchema
from ..config import get_settings
from .join_optimizer import JoinOptimizer
from .parser import ParsedQuery
from .physical_plans import PhysicalPlanner, _pred_column, _sargable
from .relational_algebra import ColumnRef
from .statistics import StatisticsProvider


@dataclass
class IndexRecommendation:
    table: str
    columns: list[str]
    source: str
    current_cost: float
    hypothetical_cost: float
    affected_operator: str
    reason: str
    estimated_overhead: dict

    @property
    def improvement_pct(self) -> float:
        if self.current_cost <= 0:
            return 0.0
        return round(100.0 * (self.current_cost - self.hypothetical_cost) / self.current_cost, 2)

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "columns": self.columns,
            "index_ddl": f"CREATE INDEX idx_{self.table}_{'_'.join(self.columns)} "
                         f"ON {self.table}({', '.join(self.columns)})",
            "source": self.source,
            "current_cost": round(self.current_cost, 4),
            "hypothetical_cost": round(self.hypothetical_cost, 4),
            "improvement_pct": self.improvement_pct,
            "affected_operator": self.affected_operator,
            "reason": self.reason,
            "estimated_overhead": self.estimated_overhead,
        }


class IndexAdvisor:
    def __init__(self, parsed: ParsedQuery, stats: StatisticsProvider, schema: dict[str, TableSchema]):
        self.parsed = parsed
        self.stats = stats
        self.schema = schema
        self.cfg = get_settings()

    def _baseline_cost(self) -> float:
        planner = PhysicalPlanner(self.parsed, self.stats, self.schema, self.cfg)
        return JoinOptimizer(planner).optimize().selected.plan.cumulative_cost

    def _cost_with_index(self, real_table: str, columns: list[str]) -> tuple[float, str]:
        schema_copy = {k: copy.deepcopy(v) for k, v in self.schema.items()}
        ts = schema_copy[real_table]
        # skip if an equivalent leading-column index already exists
        for idx in ts.indexes:
            if idx.columns and idx.columns[0].lower() == columns[0].lower():
                return self._baseline_cost(), "already-indexed"
        ts.indexes.append(Index(name=f"hypo_{real_table}_{'_'.join(columns)}", columns=columns, unique=False))
        planner = PhysicalPlanner(self.parsed, self.stats, schema_copy, self.cfg)
        result = JoinOptimizer(planner).optimize()
        # figure out which operator now uses the hypothetical index
        used = _find_index_use(result.selected.plan.to_dict(), columns[0])
        return result.selected.plan.cumulative_cost, used

    def _candidates(self) -> list[tuple[str, str, str]]:
        """Return (alias, column, source) candidates, discovered from the query."""
        found: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(alias: Optional[str], column: str, source: str):
            if alias is None:
                return
            key = (alias, column)
            if key in seen:
                return
            seen.add(key)
            found.append((alias, column, source))

        for p in self.parsed.base_predicates():
            if _sargable(p):
                col = _pred_column(p)
                if col is not None:
                    add(col.table, col.column, "WHERE")
        for jc in self.parsed.join_conditions:
            add(jc.left.table, jc.left.column, "JOIN")
            if isinstance(jc.right, ColumnRef):
                add(jc.right.table, jc.right.column, "JOIN")
        for token in self.parsed.order_by:
            alias, _, rest = token.partition(".")
            col = rest.split()[0] if rest else alias
            if "." in token:
                add(alias, col, "ORDER BY")
        for token in self.parsed.group_by:
            if "." in token:
                alias, _, col = token.partition(".")
                add(alias, col, "GROUP BY")
        return found

    def recommend(self) -> dict:
        baseline = self._baseline_cost()
        recs: list[IndexRecommendation] = []
        for alias, column, source in self._candidates():
            real = self.parsed.alias_to_table.get(alias, alias)
            ts = self.schema.get(real)
            if ts is None or ts.column(column) is None:
                continue
            hypo_cost, affected = self._cost_with_index(real, [column])
            if affected == "already-indexed":
                continue
            row_count = self.stats.row_count(real)
            overhead = {
                "index_entries": row_count,
                "note": "Adds storage proportional to row count and slows INSERT/UPDATE "
                        "on this table; created only if you choose to.",
            }
            reason = _reason(source, affected, baseline, hypo_cost)
            recs.append(IndexRecommendation(
                real, [column], source, baseline, hypo_cost, affected, reason, overhead,
            ))
        recs.sort(key=lambda r: r.hypothetical_cost)
        return {
            "baseline_cost": round(baseline, 4),
            "recommendations": [r.to_dict() for r in recs],
            "note": "Hypothetical analysis only — no index is created unless explicitly requested.",
        }


def _find_index_use(plan: dict, column: str) -> str:
    op = plan.get("operator", "")
    meta = plan.get("meta", {})
    idx = meta.get("index", "")
    if idx and idx.startswith("hypo_"):
        return op
    for ch in plan.get("children", []):
        r = _find_index_use(ch, column)
        if r not in ("", "none"):
            return r
    return "none"


def _reason(source: str, affected: str, baseline: float, hypo: float) -> str:
    if hypo >= baseline - 1e-9:
        return (f"An index on this {source} column does not lower the plan cost for this "
                f"query (the optimizer still prefers a scan).")
    if affected == "IndexNestedLoopJoin":
        return (f"Enables an index-nested-loop join on the {source} key, replacing a "
                f"hash/scan join and cutting cost from {round(baseline,1)} to {round(hypo,1)}.")
    if affected == "IndexScan":
        return (f"Enables an index range/equality scan for the {source} predicate, "
                f"avoiding a full table scan (cost {round(baseline,1)} -> {round(hypo,1)}).")
    return (f"Lowers estimated plan cost from {round(baseline,1)} to {round(hypo,1)} "
            f"by improving access on the {source} column.")
