"""Baseline-vs-candidate comparison: estimated cost and measured runtime, kept separate.

Reuses the optimizer (estimated cost), `verify_equivalent` (result check) and the adapter's
`benchmark_query` (timing). Nothing here invents a number: a speedup percentage is only
reported when the measured ranges do not overlap and the results were verified equal.
"""
from __future__ import annotations

import statistics

from .config import get_settings
from .database.adapter import DatabaseAdapter
from .optimizer.orchestrator import optimize_query
from .optimizer.rewriter import compare_benchmarks, verify_equivalent
from .optimizer.safety import validate_readonly

MAX_WARMUP = 10
MAX_RUNS = 30
MIN_RUNS = 3


def _clamp(v: int | None, default: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, default if v is None else v))


def _iqr(samples: list[float]) -> float:
    if len(samples) < 4:
        return round(max(samples) - min(samples), 4)
    q = statistics.quantiles(samples, n=4, method="inclusive")
    return round(q[2] - q[0], 4)


def _estimated_cost(adapter: DatabaseAdapter, sql: str) -> dict:
    try:
        r = optimize_query(adapter, sql, run_benchmark=False, run_index_advisor=False)
        return {"available": True, "cost": r["summary"]["selected_total_cost"],
                "join_order": r["optimization"]["selected"]["join_order"]}
    except Exception as e:  # unsupported shape for the cost model; timing can still run
        return {"available": False, "cost": None, "reason": str(e)}


def _timing(bench: dict) -> dict:
    s = bench["samples_ms"]
    return {**bench, "iqr_ms": _iqr(s)}


def compare(adapter: DatabaseAdapter, baseline_sql: str, candidate_sql: str,
            warmup: int | None = None, runs: int | None = None) -> dict:
    """Raises UnsafeQueryError for non read-only SQL; other failures propagate."""
    validate_readonly(baseline_sql)
    validate_readonly(candidate_sql)
    s = get_settings()
    warmup = _clamp(warmup, s.benchmark_warmup, 0, MAX_WARMUP)
    runs = _clamp(runs, s.benchmark_runs, MIN_RUNS, MAX_RUNS)

    equivalence = verify_equivalent(adapter, baseline_sql, candidate_sql, s.equivalence_row_cap)
    est_base, est_cand = _estimated_cost(adapter, baseline_sql), _estimated_cost(adapter, candidate_sql)
    base = _timing(adapter.benchmark_query(baseline_sql, warmup=warmup, runs=runs))
    cand = _timing(adapter.benchmark_query(candidate_sql, warmup=warmup, runs=runs))

    cmp = compare_benchmarks(base, cand)
    comparable = bool(equivalence.get("checked") and equivalence.get("equal"))
    verdict = cmp["verdict"] if comparable else "not_comparable"
    change = cmp["median_change_pct"] if verdict in ("faster", "slower") else None  # negative = slower

    caveats = [
        "Wall-clock times on one machine, sequential runs: the baseline runs before the candidate, so OS and file caches favour neither fully.",
        f"{warmup} warm-up and {runs} measured runs per query. This is a small sample; the ranges, not a single number, are the evidence.",
        "Estimated cost comes from this tool's cost model and is not a time. It can disagree with the measurement.",
    ]
    if not comparable:
        caveats.append("Results were not verified equal, so no performance verdict is given. " + equivalence.get("note", ""))
    elif verdict == "indistinguishable":
        caveats.append("The measured ranges overlap: the difference is within noise.")
    if not (est_base["available"] and est_cand["available"]):
        caveats.append("Estimated cost is unavailable for at least one query (unsupported by the cost model).")

    return {
        "baseline_sql": baseline_sql, "candidate_sql": candidate_sql,
        "config": {"warmup_runs": warmup, "measured_runs": runs, "equivalence_row_cap": s.equivalence_row_cap},
        "estimated": {"label": "Estimated (cost model, unitless)", "baseline": est_base, "candidate": est_cand},
        "measured": {"label": "Measured (wall-clock ms)", "baseline": base, "candidate": cand,
                     "verdict": verdict, "median_change_pct": change},
        "equivalence": equivalence,
        "caveats": caveats,
    }
