"""AI Copilot.

The copilot receives ONLY structured optimizer output and must not invent metrics.
If the OpenAI API key is absent or the call fails, a deterministic, fully offline
explanation is produced from the same structured data — the optimizer never depends
on the network.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from ..config import get_settings

SYSTEM_PROMPT = (
    "You are a database query-optimization assistant embedded in a teaching tool. "
    "You are given ONLY structured output produced by a cost-based SQL optimizer running "
    "on a SQLite database. Explain the results clearly for a student. "
    "Rules:\n"
    "- Use ONLY the supplied optimizer data. Never invent numbers, tables, indexes, or costs.\n"
    "- If a piece of information is not present in the data, say it is unavailable.\n"
    "- Keep estimated COST (abstract units) and application BENCHMARK time (milliseconds) "
    "as separate concepts; never equate them.\n"
    "- Be concise and specific: reference the actual operators, join order, costs and "
    "cardinalities from the data."
)


def build_context(payload: dict) -> dict:
    """Trim the full optimizer payload down to what the copilot needs."""
    opt = payload.get("optimization", {})
    selected = opt.get("selected", {})
    return {
        "sql": payload.get("sql"),
        "database_backend": payload.get("database_backend"),
        "selected_plan": _compact_plan(selected.get("plan", {})),
        "join_order": selected.get("join_order"),
        "selected_total_cost": opt.get("selected_total_cost"),
        "candidate_count": len(opt.get("candidates", [])),
        "join_orders_considered": opt.get("join_orders_considered"),
        "selection_reason": opt.get("reason"),
        "estimated_final_rows": selected.get("estimated_rows"),
        "statistics_source": payload.get("statistics_source"),
        "transformations": [
            {k: t.get(k) for k in ("name", "improvement_pct", "before_cost", "after_cost")}
            for t in payload.get("logical_optimization", {}).get("transformations", [])
        ],
        "engine_explain": payload.get("explain", {}).get("engine"),
        "explain_differences": payload.get("explain", {}).get("differences"),
        "benchmark": payload.get("benchmark"),
        "index_recommendations": [
            {k: r.get(k) for k in ("table", "columns", "improvement_pct", "affected_operator")}
            for r in payload.get("index_advisor", {}).get("recommendations", [])
        ],
    }


def _compact_plan(plan: dict, depth: int = 0) -> dict:
    if not plan:
        return {}
    return {
        "operator": plan.get("operator"),
        "estimated_rows": plan.get("estimated_rows"),
        "total_cost": plan.get("total_cost"),
        "children": [_compact_plan(c, depth + 1) for c in plan.get("children", [])],
    }


def explain(payload: dict, question: Optional[str] = None) -> dict:
    cfg = get_settings()
    context = build_context(payload)
    if cfg.openai_api_key:
        try:
            text = _call_openai(cfg.openai_api_key, cfg.openai_model, context, question)
            return {"source": "openai", "model": cfg.openai_model, "explanation": text}
        except Exception as e:  # pragma: no cover - network dependent
            return {
                "source": "offline",
                "model": None,
                "explanation": _offline_explanation(context, question),
                "warning": f"OpenAI call failed ({e}); used offline explanation.",
            }
    return {
        "source": "offline",
        "model": None,
        "explanation": _offline_explanation(context, question),
    }


def _call_openai(api_key: str, model: str, context: dict, question: Optional[str]) -> str:  # pragma: no cover
    user = "Here is the optimizer output:\n" + json.dumps(context, indent=2, default=str)
    if question:
        user += f"\n\nUser question: {question}\nAnswer using only the data above."
    else:
        user += "\n\nExplain the selected plan, its cost drivers, the join order, the logical " \
                "optimizations applied, how it compares to SQLite's own query plan, and any index advice."
    cfg = get_settings()
    resp = httpx.post(
        cfg.openai_api_url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": cfg.openai_temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        },
        timeout=cfg.openai_timeout_s,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _offline_explanation(context: dict, question: Optional[str]) -> str:
    plan = context.get("selected_plan", {})
    lines: list[str] = []
    lines.append("### Selected plan")
    lines.append(
        f"The optimizer chose a plan with estimated total cost "
        f"**{context.get('selected_total_cost')}** (abstract units) producing about "
        f"**{context.get('estimated_final_rows')}** rows."
    )
    order = context.get("join_order") or []
    if len(order) > 1:
        lines.append(f"Join order: **{' ⋈ '.join(order)}**, chosen from "
                     f"{context.get('join_orders_considered')} enumerated order(s).")

    ops = _operator_list(plan)
    join_ops = [o for o in ops if "Join" in o]
    if join_ops:
        lines.append(f"Join method(s) used: **{', '.join(dict.fromkeys(join_ops))}**.")

    # cost driver = most expensive subtree step
    driver = _max_cost_operator(plan)
    if driver:
        lines.append(f"The dominant cost driver is the **{driver['operator']}** step "
                     f"(cumulative cost {driver['total_cost']}).")

    lines.append("\n### Logical optimizations")
    tr = context.get("transformations") or []
    if tr:
        for t in tr:
            lines.append(f"- **{t['name']}**: cost {t['before_cost']} -> {t['after_cost']} "
                         f"({t['improvement_pct']}% change).")
    else:
        lines.append("- No logical transformation data available.")

    lines.append("\n### SQLite EXPLAIN QUERY PLAN comparison")
    diffs = context.get("explain_differences")
    if diffs:
        for d in diffs:
            lines.append(f"- {d}")
    elif context.get("engine_explain"):
        lines.append("- The custom plan and SQLite's plan agree on tables, index usage and sorting.")
    else:
        lines.append("- SQLite EXPLAIN data is unavailable.")

    lines.append("\n### Application benchmark")
    bench = context.get("benchmark")
    if bench:
        lines.append(
            f"- Measured wall-clock time (NOT the cost estimate): median "
            f"**{bench.get('median_ms')} ms** over {bench.get('measured_runs')} runs, "
            f"returning {bench.get('rows_returned')} rows."
        )
    else:
        lines.append("- No benchmark was run for this query.")

    lines.append("\n### Index advice")
    recs = context.get("index_recommendations") or []
    if recs:
        for r in recs:
            lines.append(f"- Index on **{r['table']}({', '.join(r['columns'])})** could change "
                         f"cost by {r['improvement_pct']}% (affects {r['affected_operator']}).")
    else:
        lines.append("- No beneficial hypothetical index was found for this query.")

    if question:
        lines.append("\n### Note")
        lines.append("This offline explanation is limited to the structured optimizer data above; "
                     "targeted Q&A requires the OpenAI API key to be configured.")
    lines.append("\n_Statistics source: " + str(context.get("statistics_source")) + "._")
    return "\n".join(lines)


def _operator_list(plan: dict) -> list[str]:
    out = [plan.get("operator", "")] if plan else []
    for c in plan.get("children", []) if plan else []:
        out.extend(_operator_list(c))
    return [o for o in out if o]


def _max_cost_operator(plan: dict) -> Optional[dict]:
    best = None

    def walk(n: dict):
        nonlocal best
        if not n:
            return
        if best is None or (n.get("total_cost", 0) or 0) > (best.get("total_cost", 0) or 0):
            best = n
        for c in n.get("children", []):
            walk(c)

    walk(plan)
    return best
