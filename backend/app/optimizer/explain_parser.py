"""Parse SQLite `EXPLAIN QUERY PLAN` output and compare it to our plan.

We only rely on SQLite-supported mechanisms (EXPLAIN QUERY PLAN, and optionally
EXPLAIN bytecode). We never assume PostgreSQL EXPLAIN ANALYZE semantics.
"""
from __future__ import annotations

import re


def parse_explain_query_plan(rows: list[dict]) -> dict:
    steps = []
    indexes_used: list[str] = []
    tables: list[str] = []
    uses_temp_btree = False

    for r in rows:
        detail = r.get("detail", "")
        step = _parse_detail(detail)
        step["id"] = r.get("id")
        step["parent"] = r.get("parent")
        steps.append(step)
        if step.get("table"):
            tables.append(step["table"])
        if step.get("index"):
            indexes_used.append(step["index"])
        if step.get("temp_btree"):
            uses_temp_btree = True

    return {
        "raw": rows,
        "steps": steps,
        "tables": sorted(set(tables)),
        "indexes_used": sorted(set(indexes_used)),
        "uses_temp_btree": uses_temp_btree,
    }


def _parse_detail(detail: str) -> dict:
    step: dict = {"detail": detail, "access": None, "table": None, "index": None, "temp_btree": False}
    if not detail:
        return step

    # SCAN <table> | SEARCH <table>
    m = re.match(r"(SCAN|SEARCH)\s+(?:TABLE\s+)?([A-Za-z_][A-Za-z0-9_]*)", detail)
    if m:
        step["access"] = "index-search" if m.group(1) == "SEARCH" else "full-scan"
        step["table"] = m.group(2)

    idx = re.search(r"USING\s+(?:COVERING\s+)?INDEX\s+([A-Za-z_][A-Za-z0-9_]*)", detail)
    if idx:
        step["index"] = idx.group(1)
        step["access"] = "index-search"
    if "USING INTEGER PRIMARY KEY" in detail:
        step["access"] = "rowid-lookup"
    if "USE TEMP B-TREE" in detail or "TEMP B-TREE" in detail:
        step["temp_btree"] = True
    if "COVERING INDEX" in detail:
        step["covering"] = True
    return step


def summarize_custom_plan(plan: dict) -> dict:
    """Flatten our selected physical plan into a comparable summary."""
    tables: list[str] = []
    indexes: list[str] = []
    scan_methods: list[str] = []
    join_methods: list[str] = []
    has_sort = False

    def walk(node: dict):
        nonlocal has_sort
        op = node.get("operator", "")
        meta = node.get("meta", {})
        if op in ("SeqScan", "IndexScan"):
            scan_methods.append(op)
            if meta.get("table"):
                tables.append(meta["table"])
            if meta.get("index"):
                indexes.append(meta["index"])
        if "Join" in op:
            join_methods.append(op)
        if op == "Sort":
            has_sort = True
        for ch in node.get("children", []):
            walk(ch)

    walk(plan)
    return {
        "tables": sorted(set(tables)),
        "indexes_used": sorted(set(i for i in indexes if not i.startswith("hypo_"))),
        "scan_methods": scan_methods,
        "join_methods": join_methods,
        "has_sort": has_sort,
    }


def compare(custom_plan: dict, explain_parsed: dict, alias_map: dict[str, str] | None = None) -> dict:
    custom = summarize_custom_plan(custom_plan)
    engine = explain_parsed
    alias_map = alias_map or {}

    def to_real(name: str) -> str:
        return alias_map.get(name, name)

    custom_tables = {to_real(t) for t in custom["tables"]}
    engine_tables = {to_real(t) for t in engine["tables"]}

    differences = []
    if custom_tables != engine_tables:
        differences.append(
            f"Tables referenced differ: custom={sorted(custom_tables)} vs engine={sorted(engine_tables)}."
        )
    custom_uses_index = bool(custom["indexes_used"]) or "IndexScan" in custom["scan_methods"]
    engine_uses_index = bool(engine["indexes_used"]) or any(
        s.get("access") in ("index-search", "rowid-lookup") for s in engine["steps"]
    )
    if custom_uses_index != engine_uses_index:
        differences.append(
            f"Index usage differs: custom {'uses' if custom_uses_index else 'does not use'} an index; "
            f"SQLite {'uses' if engine_uses_index else 'does not use'} one."
        )
    if custom["has_sort"] != engine["uses_temp_btree"]:
        differences.append(
            f"Sorting differs: custom plan {'sorts' if custom['has_sort'] else 'does not sort'}; "
            f"SQLite {'uses a temp B-tree' if engine['uses_temp_btree'] else 'does not use a temp B-tree'}."
        )

    return {
        "custom": custom,
        "engine": {
            "tables": sorted(engine_tables),
            "tables_raw": engine["tables"],
            "indexes_used": engine["indexes_used"],
            "uses_temp_btree": engine["uses_temp_btree"],
            "steps": engine["steps"],
        },
        "differences": differences,
        "agreement": {
            "same_tables": custom_tables == engine_tables,
            "same_index_usage": custom_uses_index == engine_uses_index,
        },
        "note": "Our cost model is an independent educational estimator; SQLite "
                "uses its own planner. Differences are expected and informative.",
    }
