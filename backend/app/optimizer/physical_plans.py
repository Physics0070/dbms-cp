"""Physical plan generation.

For each relation we consider Sequential Scan and Index Scan access paths, and
for each join we consider Nested-Loop, Index-Nested-Loop, Hash and Merge joins.
Costs come from the :class:`CostModel`; cardinalities from statistics. Nothing
is specific to any schema — index availability and join keys are discovered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings, get_settings
from ..database.adapter import Index, TableSchema
from .cost_model import CostBreakdown, CostModel
from .parser import ParsedQuery
from .relational_algebra import (
    Between,
    ColumnRef,
    Comparison,
    InList,
    Predicate,
)
from .selectivity import SelectivityEstimator
from .statistics import StatisticsProvider

_PLAN_COUNTER = {"n": 0}


def _pid() -> str:
    _PLAN_COUNTER["n"] += 1
    return f"pp{_PLAN_COUNTER['n']}"


class PhysicalPlan:
    def __init__(
        self,
        operator: str,
        children: list["PhysicalPlan"],
        rows: float,
        self_cost: CostBreakdown,
        cumulative_cost: float,
        reasoning: str,
        meta: Optional[dict] = None,
    ):
        self.id = _pid()
        self.operator = operator
        self.children = children
        self.rows = int(round(rows))
        self.self_cost = self_cost
        self.cumulative_cost = cumulative_cost
        self.reasoning = reasoning
        self.meta = meta or {}

    def relations(self) -> set[str]:
        if "alias" in self.meta:
            return {self.meta["alias"]}
        rels: set[str] = set()
        for c in self.children:
            rels |= c.relations()
        return rels

    def operators(self) -> list[str]:
        out = [self.operator]
        for c in self.children:
            out.extend(c.operators())
        return out

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "operator": self.operator,
            "estimated_rows": self.rows,
            "cpu_cost": round(self.self_cost.cpu, 4),
            "io_cost": round(self.self_cost.io, 4),
            "memory_cost": round(self.self_cost.memory, 4),
            "self_total_cost": round(self.self_cost.total, 4),
            "total_cost": round(self.cumulative_cost, 4),
            "reasoning": self.reasoning,
            "meta": self.meta,
            "children": [c.to_dict() for c in self.children],
        }


# ---------------------------------------------------------------------------
def _pred_column(p: Predicate) -> Optional[ColumnRef]:
    if isinstance(p, Comparison) and not p.is_join_predicate:
        return p.left
    if isinstance(p, (Between, InList)):
        return p.col
    return None


def _sargable(p: Predicate) -> bool:
    if isinstance(p, Comparison):
        return not p.is_join_predicate and p.op in ("=", ">", ">=", "<", "<=")
    return isinstance(p, (Between, InList))


@dataclass
class RelationInfo:
    alias: str
    real: str
    schema: TableSchema
    row_count: int
    local_preds: list[Predicate] = field(default_factory=list)
    local_selectivity: float = 1.0


class PhysicalPlanner:
    def __init__(
        self,
        parsed: ParsedQuery,
        stats: StatisticsProvider,
        schema: dict[str, TableSchema],
        settings: Optional[Settings] = None,
        pushdown: bool = True,
    ):
        self.parsed = parsed
        self.stats = stats
        self.schema = schema
        self.cfg = settings or get_settings()
        self.cost = CostModel(self.cfg)
        self.sel = SelectivityEstimator(stats, parsed.alias_to_table, self.cfg)
        self.pushdown = pushdown
        self.relations: dict[str, RelationInfo] = {}
        self.global_preds: list[Predicate] = []
        self._prepare()

    def _prepare(self) -> None:
        per_alias: dict[str, list[Predicate]] = {a: [] for a in self.parsed.alias_to_table}
        for p in self.parsed.base_predicates():
            if not self.pushdown:
                # No predicate pushdown: every filter is applied above the joins.
                self.global_preds.append(p)
                continue
            tset = p.tables()
            if len(tset) == 1 and next(iter(tset)) in per_alias:
                per_alias[next(iter(tset))].append(p)
            else:
                self.global_preds.append(p)

        for alias, real in self.parsed.alias_to_table.items():
            ts = self.schema[real]
            rc = self.stats.row_count(real)
            preds = per_alias.get(alias, [])
            local_sel = 1.0
            for p in preds:
                local_sel *= self.sel.estimate(p).selectivity
            self.relations[alias] = RelationInfo(
                alias=alias, real=real, schema=ts, row_count=rc,
                local_preds=preds, local_selectivity=local_sel,
            )

    # -- access paths --------------------------------------------------------
    def access_paths(self, alias: str) -> list[PhysicalPlan]:
        info = self.relations[alias]
        out: list[PhysicalPlan] = []
        final_rows = info.row_count * info.local_selectivity

        # Sequential scan (+ filter for local predicates)
        scan_cost = self.cost.seq_scan(info.row_count)
        scan = PhysicalPlan(
            "SeqScan", [], info.row_count, scan_cost, scan_cost.total,
            f"Full scan of {info.real} ({info.row_count} rows); no index required.",
            {"alias": alias, "table": info.real, "access": "sequential"},
        )
        seq_path = scan
        if info.local_preds:
            fcost = self.cost.filter(info.row_count)
            seq_path = PhysicalPlan(
                "Filter", [scan], final_rows, fcost, scan.cumulative_cost + fcost.total,
                f"Apply {len(info.local_preds)} pushed-down predicate(s) to scanned rows.",
                {"predicates": [str(p) for p in info.local_preds]},
            )
        out.append(seq_path)

        # Index scans (one per usable index)
        for idx in info.schema.indexes:
            path = self._index_access_path(info, idx, final_rows)
            if path is not None:
                out.append(path)

        out.sort(key=lambda p: p.cumulative_cost)
        return out

    def _index_access_path(self, info: RelationInfo, idx: Index, final_rows: float) -> Optional[PhysicalPlan]:
        if not idx.columns:
            return None
        lead = idx.columns[0]
        chosen: Optional[Predicate] = None
        for p in info.local_preds:
            col = _pred_column(p)
            if col is not None and col.column.lower() == lead.lower() and _sargable(p):
                chosen = p
                break
        if chosen is None:
            return None
        idx_sel = self.sel.estimate(chosen).selectivity
        matched = info.row_count * idx_sel
        icost = self.cost.index_scan(info.row_count, matched)
        iscan = PhysicalPlan(
            "IndexScan", [], matched, icost, icost.total,
            f"Use index {idx.name} on {info.real}({lead}) for predicate '{chosen}'.",
            {"alias": info.alias, "table": info.real, "index": idx.name,
             "index_columns": idx.columns, "access": "index"},
        )
        residual = [p for p in info.local_preds if p is not chosen]
        if not residual:
            return iscan
        fcost = self.cost.filter(matched)
        return PhysicalPlan(
            "Filter", [iscan], final_rows, fcost, iscan.cumulative_cost + fcost.total,
            f"Apply {len(residual)} residual predicate(s) after index lookup.",
            {"predicates": [str(p) for p in residual]},
        )

    def best_access_path(self, alias: str) -> PhysicalPlan:
        return self.access_paths(alias)[0]

    # -- joins ---------------------------------------------------------------
    def _join_predicate(self, left_rels: set[str], right_alias: str) -> Optional[Comparison]:
        for jc in self.parsed.join_conditions:
            lt = jc.left.table
            rt = jc.right.table if isinstance(jc.right, ColumnRef) else None
            if lt in left_rels and rt == right_alias:
                return jc
            if rt in left_rels and lt == right_alias:
                # normalise so `.left` is on the existing (outer) side
                return Comparison(jc.right, jc.op, jc.left)  # type: ignore[arg-type]
        return None

    def _distinct(self, col: ColumnRef) -> int:
        cs = self.stats.resolve(col.table, col.column, self.parsed.alias_to_table)
        return cs.distinct_count if cs else 1

    def _index_on(self, alias: str, column: str) -> Optional[Index]:
        info = self.relations[alias]
        for idx in info.schema.indexes:
            if idx.columns and idx.columns[0].lower() == column.lower():
                return idx
        return None

    def join(self, left: PhysicalPlan, right_alias: str) -> PhysicalPlan:
        left_rels = left.relations()
        right = self.best_access_path(right_alias)
        jc = self._join_predicate(left_rels, right_alias)

        # output cardinality (System-R for equi-joins)
        if jc is not None and jc.op == "=" and isinstance(jc.right, ColumnRef):
            d = max(self._distinct(jc.left), self._distinct(jc.right), 1)
            out_rows = left.rows * right.rows / d
            join_sel_note = f"1/max(distinct)=1/{d}"
        else:
            out_rows = left.rows * right.rows * (1.0 if jc is None else self.cfg.default_join_selectivity)
            join_sel_note = "cross product" if jc is None else "non-equi default"

        candidates: list[PhysicalPlan] = []
        cond_text = str(jc) if jc else "cross join"

        # --- Nested-Loop Join ---
        nlj_self = self.cost.nested_loop_compare(left.rows, right.rows)
        nlj_cum = left.cumulative_cost + left.rows * right.cumulative_cost + nlj_self.total
        candidates.append(PhysicalPlan(
            "NestedLoopJoin", [left, right], out_rows, nlj_self, nlj_cum,
            f"For each of {left.rows} outer rows, scan inner ({right.rows} rows). Cheap only for tiny inputs.",
            {"condition": cond_text, "join_selectivity": join_sel_note},
        ))

        # --- Index-Nested-Loop Join (only if inner join key is indexed) ---
        if jc is not None and jc.op == "=" and isinstance(jc.right, ColumnRef):
            inner_col = jc.right if jc.right.table == right_alias else jc.left
            idx = self._index_on(right_alias, inner_col.column) if inner_col.table == right_alias else None
            if idx is not None:
                info = self.relations[right_alias]
                per_probe = self.cost.index_probe(info.row_count, max(1.0, info.row_count / max(1, self._distinct(inner_col))))
                inl_cum = left.cumulative_cost + left.rows * per_probe.total
                candidates.append(PhysicalPlan(
                    "IndexNestedLoopJoin", [left, right], out_rows,
                    self.cost.output(out_rows), inl_cum,
                    f"Probe index {idx.name} on inner join key once per outer row ({left.rows} probes).",
                    {"condition": cond_text, "index": idx.name, "join_selectivity": join_sel_note},
                ))

        # --- Hash Join (equi only) ---
        if jc is not None and jc.op == "=":
            build_rows, probe_rows = sorted([left.rows, right.rows])
            hj_self = self.cost.hash_join_self(build_rows, probe_rows)
            hj_cum = left.cumulative_cost + right.cumulative_cost + hj_self.total
            candidates.append(PhysicalPlan(
                "HashJoin", [left, right], out_rows, hj_self, hj_cum,
                f"Build hash table on the smaller input ({build_rows} rows), probe with {probe_rows}. Great for large equi-joins.",
                {"condition": cond_text, "build_rows": build_rows, "join_selectivity": join_sel_note},
            ))

            # --- Merge Join (equi only; requires both sides sorted) ---
            sort_l = self.cost.sort(left.rows)
            sort_r = self.cost.sort(right.rows)
            mj_self = self.cost.merge_join_self(left.rows, right.rows)
            mj_cum = left.cumulative_cost + right.cumulative_cost + sort_l.total + sort_r.total + mj_self.total
            candidates.append(PhysicalPlan(
                "MergeJoin", [left, right], out_rows, mj_self + sort_l + sort_r, mj_cum,
                "Sort both inputs on the join key, then merge. Wins when inputs are already ordered.",
                {"condition": cond_text, "join_selectivity": join_sel_note,
                 "includes_sort": True},
            ))

        candidates.sort(key=lambda p: p.cumulative_cost)
        return candidates[0]

    def build_left_deep(self, order: list[str]) -> PhysicalPlan:
        current = self.best_access_path(order[0])
        for alias in order[1:]:
            current = self.join(current, alias)
        return current

    # -- finalize with common top operators ----------------------------------
    def finalize(self, join_plan: PhysicalPlan) -> PhysicalPlan:
        plan = join_plan
        # residual multi-table predicates -> Filter
        if self.global_preds:
            sel = 1.0
            for p in self.global_preds:
                sel *= self.sel.estimate(p).selectivity
            fcost = self.cost.filter(plan.rows)
            plan = PhysicalPlan(
                "Filter", [plan], plan.rows * sel, fcost, plan.cumulative_cost + fcost.total,
                "Apply predicate(s) spanning multiple relations after the join.",
                {"predicates": [str(p) for p in self.global_preds]},
            )
        # aggregate
        if self.parsed.group_by or self.parsed.aggregates:
            groups = self._group_count(plan.rows)
            acost = self.cost.aggregate(plan.rows, groups)
            plan = PhysicalPlan(
                "Aggregate", [plan], groups, acost, plan.cumulative_cost + acost.total,
                f"Group {plan.rows} rows into ~{groups} group(s).",
                {"group_by": self.parsed.group_by, "aggregates": self.parsed.aggregates},
            )
        # projection
        pcost = self.cost.projection(plan.rows)
        plan = PhysicalPlan(
            "Projection", [plan], plan.rows, pcost, plan.cumulative_cost + pcost.total,
            "Project the requested output columns.",
            {"columns": self.parsed.projections, "is_star": self.parsed.is_star},
        )
        # sort
        if self.parsed.order_by:
            scost = self.cost.sort(plan.rows)
            plan = PhysicalPlan(
                "Sort", [plan], plan.rows, scost, plan.cumulative_cost + scost.total,
                f"Sort output on {self.parsed.order_by}.",
                {"keys": self.parsed.order_by},
            )
        return plan

    def _group_count(self, input_rows: int) -> int:
        if not self.parsed.group_by:
            return 1
        product = 1
        for g in self.parsed.group_by:
            alias, _, col = g.partition(".")
            if not col:
                alias, col = None, alias
            cs = self.stats.resolve(alias, col, self.parsed.alias_to_table)
            product *= max(1, cs.distinct_count if cs else 1)
        return min(product, input_rows) if input_rows else product
