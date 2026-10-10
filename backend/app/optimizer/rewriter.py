"""Reconstruct an optimized SQL statement from the optimizer's decisions.

Given the parsed query and the cost-based join order, this module re-emits SQL that
  * joins relations in the chosen order,
  * pushes single-relation predicates down into the relation they filter, and
  * narrows each relation to the columns the rest of the query actually uses.

Everything is derived from the sqlglot AST and the discovered schema — no table or
column name is known in advance.

Safety first: a rewrite is only produced when it is *provably* shape-preserving
(inner joins only, no subqueries / set operations / LIMIT, resolvable columns). Even
then the caller is expected to verify equal results against the database before
presenting it as an optimized query (see `verify_equivalent`).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from ..database.adapter import DatabaseAdapter, TableSchema
from .parser import ParsedQuery


@dataclass
class RewriteOutcome:
    status: str                          # "rewritten" | "no_change" | "unsupported"
    sql: Optional[str] = None
    changes: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    join_order: list[str] = field(default_factory=list)
    original_order: list[str] = field(default_factory=list)


def _split_conjuncts(e: Optional[exp.Expression]) -> list[exp.Expression]:
    if e is None:
        return []
    if isinstance(e, exp.Paren):
        return _split_conjuncts(e.this)
    if isinstance(e, exp.And):
        return _split_conjuncts(e.this) + _split_conjuncts(e.expression)
    return [e]


def _and(parts: list[exp.Expression]) -> Optional[exp.Expression]:
    parts = [p.copy() for p in parts]
    if not parts:
        return None
    out = parts[0]
    for p in parts[1:]:
        out = exp.And(this=out, expression=p)
    return out


def _select_has_star(select: exp.Select) -> tuple[bool, set[str]]:
    """(bare `*` present, set of qualifiers used in `t.*`) — top-level select list only."""
    bare, qualified = False, set()
    for e in select.expressions:
        if isinstance(e, exp.Star):
            bare = True
        elif isinstance(e, exp.Column) and isinstance(e.this, exp.Star):
            if e.table:
                qualified.add(e.table)
            else:
                bare = True
    return bare, qualified


class _Resolver:
    def __init__(self, parsed: ParsedQuery, schema: dict[str, TableSchema]):
        self.alias_to_table = parsed.alias_to_table
        self.schema = schema

    def alias_of(self, col: exp.Column) -> Optional[str]:
        if isinstance(col.this, exp.Star):
            return col.table or None
        name = col.name
        q = col.table
        if q:
            if q in self.alias_to_table:
                return q
            for alias, real in self.alias_to_table.items():
                if real.lower() == q.lower():
                    return alias
            return None
        owners = [
            a for a, real in self.alias_to_table.items()
            if (ts := self.schema.get(real)) and ts.column(name) is not None
        ]
        return owners[0] if len(owners) == 1 else None


def rewrite_query(
    parsed: ParsedQuery, best_order: list[str], schema: dict[str, TableSchema]
) -> RewriteOutcome:
    original_order = list(parsed.alias_to_table.keys())
    out = RewriteOutcome("unsupported", original_order=original_order, join_order=list(best_order))

    select = parsed.ast
    if not isinstance(select, exp.Select):
        out.reasons.append("Only plain SELECT statements can be rewritten (no CTE / set operations).")
        return out
    if len(list(select.find_all(exp.Select))) > 1 or select.find(exp.Subquery):
        out.reasons.append("Subqueries are not rewritten — moving predicates across them is not provably safe.")
        return out
    if select.args.get("limit") or select.args.get("offset"):
        out.reasons.append("LIMIT/OFFSET present — reordering could change which rows are returned.")
        return out

    from_key = "from_" if "from_" in select.args else "from"
    joins = select.args.get("joins") or []
    for j in joins:
        side = (j.args.get("side") or "").upper()
        kind = (j.args.get("kind") or "").upper()
        if side in ("LEFT", "RIGHT", "FULL") or kind in ("LEFT", "RIGHT", "FULL", "OUTER"):
            out.reasons.append(
                "Outer join present — reordering or pushing predicates would change which rows survive."
            )
            return out
        if not isinstance(j.this, exp.Table):
            out.reasons.append("A join target is not a plain table.")
            return out

    if len(original_order) < 2:
        # With a single relation there is nothing to reorder and the WHERE already
        # filters at the scan; wrapping it in a subquery would be a cosmetic no-op.
        out.status = "no_change"
        out.reasons.append(
            "Single-table query: there are no joins to reorder and the filter is already applied "
            "at the scan. The remaining lever is an index — see the Index advisor."
        )
        return out

    res = _Resolver(parsed, schema)

    # -- gather every conjunct from ON clauses and WHERE (all joins are inner) --
    conjuncts: list[exp.Expression] = []
    for j in joins:
        conjuncts += _split_conjuncts(j.args.get("on"))
    where = select.args.get("where")
    conjuncts += _split_conjuncts(where.this if where is not None else None)

    conj_aliases: list[set[str]] = []
    for c in conjuncts:
        aliases: set[str] = set()
        for col in c.find_all(exp.Column):
            a = res.alias_of(col)
            if a is None:
                out.reasons.append(f"Could not resolve column '{col.sql()}' to a single table.")
                return out
            aliases.add(a)
        conj_aliases.append(aliases)

    bare_star, star_aliases = _select_has_star(select)
    order = list(best_order)
    if bare_star and order != original_order:
        order = original_order
        out.reasons.append("SELECT * fixes output column order to the FROM order, so the join order was kept.")

    # -- which conjuncts move into a relation, which attach to a join -----------
    pushed: dict[str, list[exp.Expression]] = {a: [] for a in original_order}
    pushed_ids: set[int] = set()
    for c, al in zip(conjuncts, conj_aliases):
        if len(al) == 1:
            pushed[next(iter(al))].append(c)
            pushed_ids.update(id(col) for col in c.find_all(exp.Column))

    # -- columns still needed outside the pushed predicates ---------------------
    needed: dict[str, set[str]] = {a: set() for a in original_order}
    for col in select.find_all(exp.Column):
        if id(col) in pushed_ids or isinstance(col.this, exp.Star):
            continue
        a = res.alias_of(col)
        if a:
            needed[a].add(col.name.lower())

    def leaf(alias: str) -> tuple[exp.Expression, Optional[dict]]:
        real = parsed.alias_to_table[alias]
        ts = schema[real]
        all_cols = [c.name for c in ts.columns]
        narrow = not bare_star and alias not in star_aliases
        keep = [c for c in all_cols if c.lower() in needed[alias]] if narrow else all_cols
        if narrow and not keep and all_cols:
            keep = [ts.primary_key[0] if ts.primary_key else all_cols[0]]
        narrowed = narrow and len(keep) < len(all_cols)
        preds = pushed.get(alias, [])

        table_alias = exp.TableAlias(this=exp.to_identifier(alias)) if alias != real else None
        if not preds and not narrowed:
            t = exp.Table(this=exp.to_identifier(real))
            if table_alias is not None:
                t.set("alias", table_alias)
            return t, None

        proj = [exp.column(c) for c in keep] if narrowed else [exp.Star()]
        inner = exp.select(*proj).from_(exp.Table(this=exp.to_identifier(real)))
        stripped = []
        for p in preds:
            pc = p.copy()
            for col in pc.find_all(exp.Column):
                col.set("table", None)
            stripped.append(pc)
        cond = _and(stripped)
        if cond is not None:
            inner = inner.where(cond)
        sub = exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias)))
        info = {
            "alias": alias, "table": real,
            "pushed_predicates": [p.sql(dialect="sqlite") for p in preds],
            "columns_kept": keep if narrowed else None,
            "columns_total": len(all_cols),
        }
        return sub, info

    leaves: dict[str, exp.Expression] = {}
    leaf_info: list[dict] = []
    for a in original_order:
        node, info = leaf(a)
        leaves[a] = node
        if info:
            leaf_info.append(info)

    # -- assemble FROM / JOINs in the chosen order -------------------------------
    attached = [False] * len(conjuncts)
    built = {order[0]}
    new_joins: list[exp.Join] = []
    for alias in order[1:]:
        conds = []
        for i, (c, al) in enumerate(zip(conjuncts, conj_aliases)):
            if attached[i] or len(al) < 2:
                continue
            if alias in al and al <= built | {alias}:
                conds.append(c)
                attached[i] = True
        built.add(alias)
        on = _and(conds)
        j = exp.Join(this=leaves[alias].copy(), on=on) if on is not None else exp.Join(
            this=leaves[alias].copy(), kind="CROSS")
        new_joins.append(j)

    leftover = [c for i, (c, al) in enumerate(zip(conjuncts, conj_aliases))
                if len(al) == 0 or (len(al) >= 2 and not attached[i])]

    new = select.copy()
    new.set(from_key, exp.From(this=leaves[order[0]].copy()))
    new.set("joins", new_joins or None)
    lw = _and(leftover)
    new.set("where", exp.Where(this=lw) if lw is not None else None)
    new_sql = new.sql(dialect="sqlite", pretty=True)

    # -- describe what changed ---------------------------------------------------
    changes: list[dict] = []
    if order != original_order and len(order) > 1:
        changes.append({
            "name": "Join Reordering",
            "what": f"Joins reordered from {' ⋈ '.join(original_order)} to {' ⋈ '.join(order)}.",
            "why": "The cost model estimates this order produces smaller intermediate results.",
            "tradeoff": "SQLite's own planner may still choose a different physical order.",
        })
    pushed_info = [i for i in leaf_info if i["pushed_predicates"]]
    if pushed_info:
        listing = "; ".join(f"{i['alias']}: {', '.join(i['pushed_predicates'])}" for i in pushed_info)
        changes.append({
            "name": "Predicate Pushdown",
            "what": f"Filters moved into the relation they apply to — {listing}.",
            "why": "Rows are discarded before joining, so joins process fewer rows.",
            "tradeoff": "SQLite usually flattens simple subqueries, so the runtime gain can be small.",
        })
    narrowed_info = [i for i in leaf_info if i["columns_kept"] is not None]
    if narrowed_info:
        listing = "; ".join(f"{i['alias']}: {len(i['columns_kept'])}/{i['columns_total']} columns" for i in narrowed_info)
        changes.append({
            "name": "Projection Pushdown",
            "what": f"Each relation reads only the columns the query uses — {listing}.",
            "why": "Narrower intermediate rows reduce the data carried through joins.",
            "tradeoff": "Gains are most visible for wide tables; narrow tables benefit little.",
        })

    out.changes = changes
    out.sql = new_sql
    out.join_order = order

    # Column narrowing alone has no effect in the cost model and SQLite flattens the
    # subqueries, so a projection-only rewrite is not a real optimization. Only report a
    # rewrite when join order or predicate placement actually changed.
    meaningful = [c for c in changes if c["name"] in ("Join Reordering", "Predicate Pushdown")]
    if changes and not meaningful:
        out.status = "no_change"
        out.sql = None
        out.changes = []
        out.reasons.append(
            "Join order is already the cost-based choice and there are no predicates to push down. "
            "The only possible rewrite is column narrowing, which has no estimated benefit here "
            "(SQLite flattens the subqueries), so the query is left as written."
        )
        return out

    if not changes or _normalize(parsed.sql) == _normalize(new_sql):
        out.status = "no_change"
        out.sql = None
        out.changes = []
        out.reasons.append(
            "The query is already in its best form: the written join order matches the "
            "cost-based choice and there are no predicates or columns left to push down."
        )
        return out

    out.status = "rewritten"
    return out


def _normalize(sql: str) -> str:
    try:
        return sqlglot.parse_one(sql, read="sqlite").sql(dialect="sqlite")
    except Exception:
        return re.sub(r"\s+", " ", sql).strip().lower()


# ---------------------------------------------------------------------------
# Verification — never present a rewrite as equivalent without checking.
# ---------------------------------------------------------------------------
def _canon(rows: list[tuple]) -> Counter:
    def norm(v):
        return round(v, 9) if isinstance(v, float) else v
    return Counter(tuple(norm(v) for v in r) for r in rows)


def verify_equivalent(adapter: DatabaseAdapter, original_sql: str, optimized_sql: str, row_cap: int) -> dict:
    try:
        cols_a, rows_a = adapter.execute_readonly(original_sql)
        cols_b, rows_b = adapter.execute_readonly(optimized_sql)
    except Exception as e:
        return {"checked": False, "equal": False, "note": f"Could not execute both queries: {e}"}

    if len(rows_a) > row_cap or len(rows_b) > row_cap:
        return {
            "checked": False, "equal": False,
            "original_rows": len(rows_a), "optimized_rows": len(rows_b),
            "note": f"Result sets exceed the {row_cap}-row verification cap; equivalence not verified.",
        }
    same_cols = [c.lower() for c in cols_a] == [c.lower() for c in cols_b]
    equal = same_cols and _canon(rows_a) == _canon(rows_b)
    return {
        "checked": True,
        "equal": equal,
        "original_rows": len(rows_a),
        "optimized_rows": len(rows_b),
        "columns_match": same_cols,
        "note": (
            "Both queries returned the same columns and the same multiset of rows "
            "(row order is not compared)." if equal
            else "Results differ — the rewrite was rejected."
        ),
    }


def compare_benchmarks(original: dict, optimized: dict) -> dict:
    """Honest timing comparison: only call it faster when the ranges do not overlap."""
    o_med, n_med = original["median_ms"], optimized["median_ms"]
    separated_faster = optimized["max_ms"] < original["min_ms"]
    separated_slower = original["max_ms"] < optimized["min_ms"]
    if separated_faster:
        verdict = "faster"
    elif separated_slower:
        verdict = "slower"
    else:
        verdict = "indistinguishable"
    change_pct = round(100.0 * (o_med - n_med) / o_med, 2) if o_med > 0 else 0.0
    return {
        "original": original,
        "optimized": optimized,
        "median_change_pct": change_pct,
        "verdict": verdict,
        "note": (
            "Wall-clock medians over a small number of runs on a shared machine. "
            + ("The measured ranges do not overlap, so the difference is likely real."
               if verdict != "indistinguishable"
               else "The measured ranges overlap, so this difference is within noise and should not be read as a speedup.")
        ),
    }
