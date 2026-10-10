"""Join-order optimization.

Relations and their connecting predicates are discovered from the parsed query;
no join order is ever hardcoded. Small queries use exhaustive enumeration of
connected left-deep orders; larger queries use a System-R style dynamic-programming
search over relation subsets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterator, Optional

from .physical_plans import PhysicalPlan, PhysicalPlanner


@dataclass
class CandidatePlan:
    plan: PhysicalPlan
    join_order: list[str]

    def to_dict(self) -> dict:
        ops = self.plan.operators()
        join_ops = [o for o in ops if "Join" in o]
        return {
            "id": self.plan.id,
            "join_order": self.join_order,
            "operators": ops,
            "join_operators": join_ops,
            "estimated_rows": self.plan.rows,
            "total_cost": round(self.plan.cumulative_cost, 4),
            "plan": self.plan.to_dict(),
        }


@dataclass
class OptimizationResult:
    selected: CandidatePlan
    candidates: list[CandidatePlan]
    method: str
    join_orders_considered: int
    reason: str
    relations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "join_orders_considered": self.join_orders_considered,
            "relations": self.relations,
            "selected_plan_id": self.selected.plan.id,
            "selected_total_cost": round(self.selected.plan.cumulative_cost, 4),
            "reason": self.reason,
            "selected": self.selected.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
        }


class JoinOptimizer:
    def __init__(self, planner: PhysicalPlanner):
        self.planner = planner
        self.aliases = list(planner.relations.keys())
        self.adj = self._build_graph()

    def _build_graph(self) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = {a: set() for a in self.aliases}
        for jc in self.planner.parsed.join_conditions:
            lt = jc.left.table
            rt = getattr(jc.right, "table", None)
            if lt in adj and rt in adj:
                adj[lt].add(rt)
                adj[rt].add(lt)
        return adj

    def _adjacent(self, alias: str, subset: set[str]) -> bool:
        return bool(self.adj.get(alias, set()) & subset)

    # -- optimize ------------------------------------------------------------
    def optimize(self, max_candidates: Optional[int] = None) -> OptimizationResult:
        cfg = self.planner.cfg
        max_candidates = cfg.max_candidates if max_candidates is None else max_candidates
        n = len(self.aliases)
        if n <= 1:
            return self._single_relation_result()
        if n <= cfg.exhaustive_join_threshold:
            return self._exhaustive(max_candidates)
        return self._dynamic_programming()

    def _single_relation_result(self) -> OptimizationResult:
        alias = self.aliases[0]
        paths = self.planner.access_paths(alias)
        candidates = []
        for p in paths:
            final = self.planner.finalize(p)
            candidates.append(CandidatePlan(final, [alias]))
        candidates.sort(key=lambda c: c.plan.cumulative_cost)
        selected = candidates[0]
        reason = self._reason(selected, candidates)
        return OptimizationResult(
            selected, candidates, "single-relation access-path selection",
            len(candidates), reason, self.aliases,
        )

    def _iter_connected_orders(self) -> Iterator[list[str]]:
        # Ordered lists (never sets): enumeration must be deterministic so that cost ties
        # resolve to the written order instead of depending on Python's per-process hash
        # seed. The sort in `_exhaustive` is stable, so the first-enumerated order wins ties.
        has_edges = any(self.adj[a] for a in self.aliases)

        def extend(prefix: list[str], remaining: list[str]):
            if not remaining:
                yield list(prefix)
                return
            pset = set(prefix)
            # prefer relations connected to the current prefix
            connected = [r for r in remaining if not prefix or not has_edges or self._adjacent(r, pset)]
            candidates = connected if connected else list(remaining)
            for r in candidates:
                prefix.append(r)
                yield from extend(prefix, [x for x in remaining if x != r])
                prefix.pop()

        yield from extend([], list(self.aliases))

    def _exhaustive(self, max_candidates: int) -> OptimizationResult:
        candidates: list[CandidatePlan] = []
        considered = 0
        for order in self._iter_connected_orders():
            considered += 1
            join_plan = self.planner.build_left_deep(order)
            final = self.planner.finalize(join_plan)
            candidates.append(CandidatePlan(final, order))

        candidates.sort(key=lambda c: c.plan.cumulative_cost)
        trimmed = candidates[:max_candidates]
        selected = candidates[0]
        reason = self._reason(selected, candidates)
        return OptimizationResult(
            selected, trimmed, "exhaustive left-deep enumeration",
            considered, reason, self.aliases,
        )

    def _dynamic_programming(self) -> OptimizationResult:
        # best[frozenset(subset)] = (cost, plan, order)
        best: dict[frozenset, tuple[float, PhysicalPlan, list[str]]] = {}
        for a in self.aliases:
            p = self.planner.best_access_path(a)
            best[frozenset([a])] = (p.cumulative_cost, p, [a])

        states = 0
        n = len(self.aliases)
        for size in range(2, n + 1):
            for subset in combinations(self.aliases, size):
                sset = frozenset(subset)
                best_here: Optional[tuple[float, PhysicalPlan, list[str]]] = None
                for r in subset:
                    rest = sset - {r}
                    if rest not in best:
                        continue
                    if self.adj[r] and not (self.adj[r] & set(rest)):
                        continue  # keep it connected when possible
                    states += 1
                    _, left_plan, left_order = best[rest]
                    joined = self.planner.join(left_plan, r)
                    if best_here is None or joined.cumulative_cost < best_here[0]:
                        best_here = (joined.cumulative_cost, joined, left_order + [r])
                if best_here is None:
                    # disconnected — fall back to any split
                    for r in subset:
                        rest = sset - {r}
                        if rest in best:
                            _, left_plan, left_order = best[rest]
                            joined = self.planner.join(left_plan, r)
                            if best_here is None or joined.cumulative_cost < best_here[0]:
                                best_here = (joined.cumulative_cost, joined, left_order + [r])
                if best_here is not None:
                    best[sset] = best_here

        full = frozenset(self.aliases)
        _, plan, order = best[full]
        final = self.planner.finalize(plan)
        selected = CandidatePlan(final, order)
        reason = self._reason(selected, [selected])
        return OptimizationResult(
            selected, [selected], "System-R dynamic programming (left-deep)",
            states, reason, self.aliases,
        )

    def _reason(self, selected: CandidatePlan, candidates: list[CandidatePlan]) -> str:
        ops = selected.plan.operators()
        join_ops = [o for o in ops if "Join" in o]
        parts = [
            f"Selected plan has the lowest total cost ({round(selected.plan.cumulative_cost, 2)})",
            f"among {len(candidates)} candidate(s).",
        ]
        if selected.join_order and len(selected.join_order) > 1:
            parts.append(f"Join order: {' ⋈ '.join(selected.join_order)}.")
        if join_ops:
            parts.append(f"Join method(s): {', '.join(dict.fromkeys(join_ops))}.")
        sel_cost = selected.plan.cumulative_cost
        runner_up = next(
            (c for c in candidates if c.plan.cumulative_cost > sel_cost + 1e-9), None
        )
        if runner_up is not None:
            delta = runner_up.plan.cumulative_cost - sel_cost
            parts.append(
                f"It beats the next distinct candidate by {round(delta, 2)} cost units "
                f"(~{_pct(delta, runner_up.plan.cumulative_cost)}% cheaper)."
            )
        elif len(candidates) > 1:
            parts.append("Multiple candidates tie at this cost (symmetric join order).")
        return " ".join(parts)


def _pct(delta: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return round(100.0 * delta / base, 1)
