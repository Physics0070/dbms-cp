"""AI Copilot.

Two paths, both grounded in the structured optimizer output and nothing else:

* **offline (default)** - a deterministic explanation. Every sentence is derived from a field
  of the payload; no number is computed that is not in the input (only rounded for display).
* **external LLM (optional, needs OPENAI_API_KEY)** - receives a minimised context: SQL with
  literals removed, plan shape and costs, index advice, benchmark summary numbers. Never
  credentials, never result rows. With COPILOT_SEND_SCHEMA=false every table, alias and
  column name is replaced by a placeholder before sending and restored in the reply.

The response always says whether an external model was used. LLM text is labelled as
hypotheses: it is not a measurement and the optimizer does not depend on it.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx
import sqlglot
from sqlglot import exp

from ..config import get_settings
from ..logging_setup import redact

SYSTEM_PROMPT = (
    "You are a database query-optimization assistant embedded in a performance tool. "
    "You are given ONLY structured output produced by a cost-based SQL optimizer. "
    "Rules:\n"
    "- Use ONLY the supplied data. Never invent numbers, tables, indexes, statistics or costs.\n"
    "- If something is not in the data, say it is unavailable.\n"
    "- Estimated COST (abstract units) and measured BENCHMARK time (ms) are different things; never equate them.\n"
    "- Present your reasoning as hypotheses to test, not as established facts.\n"
    "- Be concise and reference the actual operators, join order, costs and row counts."
)

HYPOTHESIS_NOTICE = ("> **AI-generated hypotheses.** These are explanations to test, not measurements. "
                     "Verify with the benchmark before acting on them.")


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def build_context(payload: dict) -> dict:
    """Trim the full optimizer payload down to what the copilot needs (no data rows, no secrets)."""
    opt = payload.get("optimization", {})
    selected = opt.get("selected", {})
    oq = payload.get("optimized_query") or {}
    bench = payload.get("benchmark")
    return {
        "sql": payload.get("sql"),
        "database_backend": payload.get("database_backend"),
        "selected_plan": _compact_plan(selected.get("plan", {})),
        "join_order": selected.get("join_order"),
        "selected_total_cost": opt.get("selected_total_cost"),
        "candidates": [
            {"join_order": c.get("join_order"), "total_cost": c.get("total_cost"),
             "join_operators": c.get("join_operators")}
            for c in opt.get("candidates", [])[:6]
        ],
        "candidate_count": len(opt.get("candidates", [])),
        "join_orders_considered": opt.get("join_orders_considered"),
        "selection_reason": opt.get("reason"),
        "estimated_final_rows": selected.get("estimated_rows"),
        "statistics_source": payload.get("statistics_source"),
        "base_table_rows": [
            {"table": (o.get("detail") or {}).get("table"), "rows": o.get("output_rows"), "method": o.get("method")}
            for o in payload.get("cardinality", {}).get("per_operator", []) if o.get("op") == "Scan"
        ],
        "transformations": [
            {k: t.get(k) for k in ("name", "improvement_pct", "before_cost", "after_cost")}
            for t in payload.get("logical_optimization", {}).get("transformations", [])
        ],
        "engine_explain": payload.get("explain", {}).get("engine"),
        "explain_differences": payload.get("explain", {}).get("differences"),
        "benchmark": ({k: bench.get(k) for k in ("median_ms", "measured_runs", "rows_returned")}
                      if isinstance(bench, dict) and "error" not in bench else None),
        "rewrite_status": oq.get("status"),
        "index_recommendations": [
            {k: r.get(k) for k in ("table", "columns", "index_ddl", "source", "current_cost",
                                   "hypothetical_cost", "improvement_pct", "affected_operator", "reason")}
            for r in payload.get("index_advisor", {}).get("recommendations", [])
        ],
    }


def _compact_plan(plan: dict) -> dict:
    if not plan:
        return {}
    meta = plan.get("meta") or {}
    return {
        "operator": plan.get("operator"),
        "estimated_rows": plan.get("estimated_rows"),
        "self_total_cost": plan.get("self_total_cost"),
        "total_cost": plan.get("total_cost"),
        "detail": {k: meta[k] for k in ("table", "index", "condition", "build_rows") if k in meta},
        "children": [_compact_plan(c) for c in plan.get("children", [])],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def explain(payload: dict, question: Optional[str] = None) -> dict:
    cfg = get_settings()
    context = build_context(payload)
    offline = _offline_explanation(context, question)
    base = {"external_ai_used": False, "model": None, "source": "offline", "explanation": offline,
            "disclosure": "Computed locally from the optimizer output. Nothing was sent to an external service."}
    if not cfg.openai_api_key:
        return base
    outbound, mapping = _prepare_outbound(context, cfg.copilot_send_schema)
    try:
        text = _call_openai(cfg.openai_api_key, cfg.openai_model, outbound, question)
    except Exception as e:  # pragma: no cover - network dependent
        return {**base, "warning": f"External AI call failed ({redact(str(e))}); showing the local explanation."}
    text = _restore(text, mapping)
    return {
        "external_ai_used": True, "model": cfg.openai_model, "source": "openai",
        "explanation": f"{HYPOTHESIS_NOTICE}\n\n{text}",
        "local_explanation": offline,
        "disclosure": ("Sent to the configured AI provider: query shape (literals removed), plan operators and "
                       "estimated costs, index advice, benchmark summary numbers. "
                       + ("Table and column names were included."
                          if cfg.copilot_send_schema else "Table and column names were replaced by placeholders.")
                       + " No credentials or result rows are ever sent."),
    }


def _call_openai(api_key: str, model: str, context: dict, question: Optional[str]) -> str:  # pragma: no cover
    user = "Here is the optimizer output:\n" + json.dumps(context, indent=2, default=str)
    if question:
        user += f"\n\nUser question: {question}\nAnswer using only the data above."
    else:
        user += ("\n\nExplain why the plan may be expensive, which operators dominate, whether join order or "
                 "access paths are worth investigating, why any index is recommended, what limits confidence, "
                 "and the single most useful experiment.")
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


# ---------------------------------------------------------------------------
# Minimising what leaves the machine
# ---------------------------------------------------------------------------
def _strip_literals(sql: str) -> str:
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
        return tree.transform(lambda n: exp.Placeholder() if isinstance(n, exp.Literal) else n).sql(dialect="sqlite")
    except Exception:
        return re.sub(r"'[^']*'|\b\d+(?:\.\d+)?\b", "?", sql)


def _identifiers(sql: str) -> list[str]:
    names: set[str] = set()
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
        for t in tree.find_all(exp.Table):
            names.add(t.name)
            if t.alias:
                names.add(t.alias)
        for c in tree.find_all(exp.Column):
            names.add(c.name)
        for a in tree.find_all(exp.Alias):
            names.add(a.alias)
    except Exception:
        pass
    return sorted((n for n in names if n), key=len, reverse=True)


def _prepare_outbound(context: dict, send_schema: bool) -> tuple[dict, dict[str, str]]:
    ctx = dict(context)
    sql = context.get("sql") or ""
    ctx["sql"] = _strip_literals(sql)
    ctx["database_backend"] = None  # may contain a file name
    names = list(_identifiers(sql))
    for r in context.get("index_recommendations") or []:  # advisor may name columns absent from the SQL text
        names += [r.get("table")] + list(r.get("columns") or [])
    names = sorted({n for n in names if n}, key=len, reverse=True)
    mapping: dict[str, str] = {}
    if not send_schema:
        mapping = {f"ident_{i}": n for i, n in enumerate(names)}
    # "_" counts as a separator so names embedded in e.g. idx_orders_order_id are replaced too
    pats = [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", re.I), ph)
            for ph, n in mapping.items()]

    def scrub(v):  # values only: JSON keys must stay intact
        if isinstance(v, str):
            for pat, ph in pats:
                v = pat.sub(ph, v)
            return redact(v)
        if isinstance(v, list):
            return [scrub(x) for x in v]
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items()}
        return v

    return scrub(ctx), mapping


def _restore(text: str, mapping: dict[str, str]) -> str:
    for ph, n in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(ph, n)
    return text


# ---------------------------------------------------------------------------
# Deterministic, grounded offline explanation
# ---------------------------------------------------------------------------
def _n(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _flat(plan: dict) -> list[dict]:
    out = [plan] if plan else []
    for c in plan.get("children", []) if plan else []:
        out.extend(_flat(c))
    return out


def _label(n: dict) -> str:
    d = n.get("detail") or {}
    return n["operator"] + (f" on {d['table']}" if d.get("table") else "")


def _offline_explanation(context: dict, question: Optional[str]) -> str:
    plan = context.get("selected_plan") or {}
    nodes = _flat(plan)
    L: list[str] = []
    L.append("> Deterministic analysis computed locally from the optimizer output. No external AI was used. "
             "Costs are abstract estimator units, not milliseconds.")

    L.append("### Selected plan")
    L.append(f"The cost model's preferred plan has estimated total cost **{_n(context.get('selected_total_cost'))}** "
             f"and returns about **{_n(context.get('estimated_final_rows'))}** rows. This is a prediction, "
             "not a measurement.")
    order = context.get("join_order") or []
    if len(order) > 1:
        L.append(f"Join order: **{' ⋈ '.join(order)}**, chosen from {_n(context.get('join_orders_considered'))} enumerated order(s).")
    joins = list(dict.fromkeys(n["operator"] for n in nodes if "Join" in n["operator"]))
    if joins:
        L.append(f"Join method(s): **{', '.join(joins)}**.")

    L.append("\n### Why it may be expensive")
    ranked = sorted((n for n in nodes if n.get("self_total_cost") is not None),
                    key=lambda n: n["self_total_cost"], reverse=True)[:3]
    if ranked:
        for n in ranked:
            L.append(f"- **{_label(n)}**: own cost {_n(n['self_total_cost'])} over {_n(n.get('estimated_rows'))} "
                     f"estimated rows (cumulative {_n(n.get('total_cost'))}).")
    else:
        L.append("- Per-operator costs are unavailable.")

    L.append("\n### Join order and access paths worth investigating")
    cands = context.get("candidates") or []
    sel_cost = context.get("selected_total_cost")
    others = [c for c in cands if c.get("join_order") != order]
    if others:
        best = min(others, key=lambda c: c.get("total_cost") or float("inf"))
        L.append(f"- Next-cheapest enumerated order: **{' ⋈ '.join(best['join_order'])}** at estimated cost "
                 f"{_n(best['total_cost'])} versus {_n(sel_cost)} for the selected plan. If the two estimates are "
                 "close, the choice depends on statistics that may be imprecise; measure both.")
    elif len(order) > 1:
        L.append("- Only one join order was enumerated.")
    else:
        L.append("- The query has no join to reorder.")
    scans = [n for n in nodes if "Scan" in n["operator"]]
    for s in scans:
        d = s.get("detail") or {}
        L.append(f"- {s['operator']} on **{d.get('table', '?')}**"
                 + (f" using index **{d['index']}**" if d.get("index") else "")
                 + f", about {_n(s.get('estimated_rows'))} rows estimated.")

    L.append("\n### Statistics behind the estimates")
    base = [b for b in context.get("base_table_rows") or [] if b.get("table")]
    for b in base:
        L.append(f"- {b['table']}: {_n(b['rows'])} rows ({b.get('method')}).")
    L.append(f"- Statistics source: {context.get('statistics_source')}.")

    L.append("\n### Logical optimizations")
    tr = context.get("transformations") or []
    if tr:
        for t in tr:
            L.append(f"- **{t['name']}**: cost {_n(t['before_cost'])} → {_n(t['after_cost'])} "
                     f"({_n(t['improvement_pct'])}% change).")
    else:
        L.append("- No logical transformation data available.")

    L.append("\n### Comparison with the database's own plan")
    diffs = context.get("explain_differences")
    if diffs:
        L.extend(f"- {d}" for d in diffs)
    elif context.get("engine_explain"):
        L.append("- The platform's plan and the database's plan agree on tables, index usage and sorting.")
    else:
        L.append("- The database's EXPLAIN data is unavailable.")

    L.append("\n### Measured benchmark")
    bench = context.get("benchmark")
    if bench:
        L.append(f"- Wall-clock median **{_n(bench.get('median_ms'))} ms** over {_n(bench.get('measured_runs'))} runs, "
                 f"{_n(bench.get('rows_returned'))} rows returned. This is a measurement, separate from the cost estimate.")
    else:
        L.append("- No benchmark was run, so nothing here is measured yet.")

    L.append("\n### Index advice")
    recs = context.get("index_recommendations") or []
    helpful = [r for r in recs if (r.get("improvement_pct") or 0) > 0]
    if helpful:
        for r in helpful:
            L.append(f"- **{r['table']}({', '.join(r['columns'])})** on a {r.get('source')} column: simulated cost "
                     f"{_n(r['current_cost'])} → {_n(r['hypothetical_cost'])} ({_n(r['improvement_pct'])}% lower), "
                     f"affecting {r.get('affected_operator')}. This is an analytical simulation, not a native "
                     f"hypothetical index. Proposed DDL (not executed): `{r.get('index_ddl')}`")
    for r in [r for r in recs if r not in helpful][:3]:
        L.append(f"- {r['table']}({', '.join(r['columns'])}): {r.get('reason')}")
    if not recs:
        L.append("- No candidate index was generated for this query.")

    L.append("\n### What limits confidence")
    L.append("- Cardinality and cost come from the statistics above and the documented cost model, not from the database's planner.")
    L.append("- No per-operator actual rows or timings are available, so estimation errors cannot be located.")
    if not bench:
        L.append("- Nothing has been measured for this query.")

    L.append("\n### Most useful next experiment")
    L.append("- " + _next_experiment(context, helpful, bool(bench)))

    if question:
        L.append("\n### Note")
        L.append("Free-form questions need an AI provider; this local answer is limited to the structured data above.")
    return "\n".join(L)


def _next_experiment(context: dict, helpful: list, benchmarked: bool) -> str:
    if not benchmarked:
        return "Run the benchmark on the query as written to get a measured baseline before changing anything."
    if context.get("rewrite_status") == "rewritten":
        return "Compare the proposed rewrite with the original in the benchmark; adopt it only if the measured ranges do not overlap."
    if helpful:
        r = helpful[0]
        return (f"On a copy of the database, create the index on {r['table']}({', '.join(r['columns'])}) and "
                "benchmark this query before and after.")
    return "Re-run the benchmark after a statistics or schema change to see whether the plan or timing moves."
