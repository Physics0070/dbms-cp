"""Example-query generator driven entirely by the discovered schema + statistics.

Nothing here knows any table or column name: joins come from foreign keys, filters
from the most-common-values histograms, aggregates from low-cardinality columns.
Swap the database and the suggestions change with it.
"""
from __future__ import annotations

from typing import Optional

from ..database.adapter import DatabaseAdapter, TableSchema


def _q(name: str) -> str:
    return f'"{name}"' if not name.replace("_", "").isalnum() else name


def _literal(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _alias_for(name: str, used: set[str]) -> str:
    parts = [p for p in name.split("_") if p]
    base = ("".join(p[0] for p in parts) if len(parts) > 1 else name[:1] or "t").lower()
    alias, n = base, 1
    while alias in used:
        n += 1
        alias = f"{base}{n}"
    used.add(alias)
    return alias


def _display_col(ts: TableSchema, exclude: set[str]) -> Optional[str]:
    """Pick a non-key column to display: prefer text, then anything not a key."""
    keys = set(ts.primary_key) | exclude
    cands = [c for c in ts.columns if c.name not in keys]
    for c in cands:
        if "CHAR" in c.data_type or "TEXT" in c.data_type:
            return c.name
    return cands[0].name if cands else None


def _fk_edges(schema: dict[str, TableSchema]) -> list[tuple[str, list[str], str, list[str]]]:
    edges = []
    for t, ts in schema.items():
        for fk in ts.foreign_keys:
            if fk.ref_table in schema and fk.ref_table != t:
                edges.append((t, fk.columns, fk.ref_table, fk.ref_columns))
    return edges


def generate_examples(adapter: DatabaseAdapter, limit: int = 6) -> list[dict]:
    schema = adapter.get_schema()
    edges = _fk_edges(schema)
    out: list[dict] = []

    def add(label: str, sql: str, kind: str):
        out.append({"label": label, "kind": kind, "sql": sql})

    # --- 2-table join with a selective filter -------------------------------
    best_join = None
    best_rows = -1
    for (child, ccols, parent, pcols) in edges:
        rows = adapter.get_statistics(child).row_count
        if rows > best_rows:
            best_rows, best_join = rows, (child, ccols, parent, pcols)

    if best_join:
        child, ccols, parent, pcols = best_join
        used: set[str] = set()
        a, b = _alias_for(child, used), _alias_for(parent, used)
        cond = " AND ".join(f"{a}.{_q(x)} = {b}.{_q(y)}" for x, y in zip(ccols, pcols))
        show_p = _display_col(schema[parent], set(pcols))
        show_c = _display_col(schema[child], set(ccols))
        cols = ", ".join(
            x for x in (f"{b}.{_q(show_p)}" if show_p else None, f"{a}.{_q(show_c)}" if show_c else None) if x
        ) or f"{a}.*"

        # filter on the child's most selective *common-value* column
        cst = adapter.get_statistics(child)
        pick = None
        for col, cs in cst.columns.items():
            if col in ccols or col in schema[child].primary_key or not cs.most_common:
                continue
            if cs.distinct_count >= 2:
                pick = (col, cs)
                break
        where = ""
        if pick:
            col, cs = pick
            where = f"\nWHERE {a}.{_q(col)} = {_literal(cs.most_common[0][0])}"
        add(
            f"Join: {child} → {parent}" + (" + filter" if where else ""),
            f"SELECT {cols}\nFROM {_q(child)} {a}\nJOIN {_q(parent)} {b} ON {cond}{where}",
            "join",
        )

    # --- 3-way join (join-order search): two FK edges sharing exactly one table ---
    path = None
    for i, e1 in enumerate(edges):
        for e2 in edges[i + 1:]:
            s1, s2 = {e1[0], e1[2]}, {e2[0], e2[2]}
            shared = s1 & s2
            if len(shared) == 1 and len(s1 | s2) == 3:
                path = (e1, e2, next(iter(shared)))
                break
        if path:
            break
    if path:
        e1, e2, mid = path
        first = e1[2] if e1[0] == mid else e1[0]
        last = e2[2] if e2[0] == mid else e2[0]
        tables = [first, mid, last]
        used: set[str] = set()
        al = {t: _alias_for(t, used) for t in tables}

        def on(e):
            t, cc, r, rc = e
            return " AND ".join(f"{al[t]}.{_q(x)} = {al[r]}.{_q(y)}" for x, y in zip(cc, rc))

        shows = {t: _display_col(schema[t], set()) for t in tables}
        sel = ", ".join(f"{al[t]}.{_q(shows[t])}" for t in tables if shows[t]) or f"{al[first]}.*"
        add(
            f"3-way join: {' → '.join(tables)}",
            f"SELECT {sel}\n"
            f"FROM {_q(first)} {al[first]}\n"
            f"JOIN {_q(mid)} {al[mid]} ON {on(e1)}\n"
            f"JOIN {_q(last)} {al[last]} ON {on(e2)}",
            "multi-join",
        )

    # --- selective vs. common filter on the same column ----------------------
    biggest = max(schema, key=lambda t: adapter.get_statistics(t).row_count, default=None)
    if biggest:
        st = adapter.get_statistics(biggest)
        for col, cs in st.columns.items():
            if len(cs.most_common) >= 2 and cs.most_common[0][1] != cs.most_common[-1][1]:
                common, rare = cs.most_common[0][0], cs.most_common[-1][0]
                add(f"Rare value: {biggest}.{col}",
                    f"SELECT * FROM {_q(biggest)} WHERE {_q(col)} = {_literal(rare)}", "selective")
                add(f"Common value: {biggest}.{col}",
                    f"SELECT * FROM {_q(biggest)} WHERE {_q(col)} = {_literal(common)}", "common")
                # aggregation on that same low-cardinality column
                add(f"Aggregate: {biggest} by {col}",
                    f"SELECT {_q(col)}, COUNT(*) AS n\nFROM {_q(biggest)}\nGROUP BY {_q(col)}\nORDER BY n DESC",
                    "aggregate")
                break

    # de-dup, keep the order, cap
    seen, uniq = set(), []
    for ex in out:
        if ex["sql"] not in seen:
            seen.add(ex["sql"])
            uniq.append(ex)
    # put the richest query first so it becomes the default
    rank = {"multi-join": 0, "join": 1, "selective": 2, "common": 3, "aggregate": 4}
    uniq.sort(key=lambda e: rank.get(e["kind"], 9))
    if not uniq and schema:
        t = next(iter(schema))
        uniq.append({"label": f"Scan {t}", "kind": "scan", "sql": f"SELECT * FROM {_q(t)}"})
    return uniq[:limit]
