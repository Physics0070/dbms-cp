"""SQL -> relational algebra, driven entirely by sqlglot + the discovered schema.

Nothing here knows any table or column name in advance; column resolution uses
whatever schema the :class:`DatabaseAdapter` reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp

from ..database.adapter import TableSchema
from .relational_algebra import (
    Aggregate,
    And,
    Between,
    ColumnRef,
    Comparison,
    InList,
    Join,
    Like,
    Literal,
    NullCheck,
    Operand,
    Or,
    Predicate,
    Projection,
    RANode,
    Scan,
    Selection,
    Sort,
    TruePredicate,
    UnknownPredicate,
    combine_conjuncts,
    flatten_conjuncts,
)
from .safety import validate_readonly

_OP_MAP = {
    exp.EQ: "=",
    exp.NEQ: "!=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
}
_AGG_FUNCS = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)


@dataclass
class ParsedQuery:
    sql: str
    ast: exp.Expression
    ra_tree: RANode
    alias_to_table: dict[str, str]  # query alias -> real base table
    where: Optional[Predicate]
    join_conditions: list[Comparison]
    projections: list[str]
    is_star: bool
    group_by: list[str]
    aggregates: list[str]
    order_by: list[str]

    def base_predicates(self) -> list[Predicate]:
        """Single-table WHERE conjuncts (i.e. not join predicates)."""
        out = []
        for p in flatten_conjuncts(self.where):
            if isinstance(p, Comparison) and p.is_join_predicate:
                continue
            out.append(p)
        return out


class QueryContext:
    def __init__(self, schema: dict[str, TableSchema]):
        self.schema = schema
        self.alias_to_table: dict[str, str] = {}

    def register(self, real_table: str, alias: Optional[str]) -> str:
        alias = alias or real_table
        self.alias_to_table[alias] = real_table
        return alias

    def resolve_column(self, name: str, qualifier: Optional[str]) -> ColumnRef:
        if qualifier:
            # qualifier may be an alias or a real table name
            if qualifier in self.alias_to_table:
                return ColumnRef(table=qualifier, column=name)
            # match a real table name to its alias
            for alias, real in self.alias_to_table.items():
                if real.lower() == qualifier.lower():
                    return ColumnRef(table=alias, column=name)
            return ColumnRef(table=qualifier, column=name)
        # unqualified — find which registered table owns this column
        for alias, real in self.alias_to_table.items():
            ts = self.schema.get(real)
            if ts and ts.column(name) is not None:
                return ColumnRef(table=alias, column=name)
        return ColumnRef(table=None, column=name)

    def real_table(self, alias: str) -> Optional[str]:
        return self.alias_to_table.get(alias)


def parse_query(sql: str, schema: dict[str, TableSchema]) -> ParsedQuery:
    root = validate_readonly(sql)
    select = root.this if isinstance(root, exp.With) else root
    if not isinstance(select, exp.Select):
        raise ValueError("Only SELECT statements are supported for optimization.")

    ctx = QueryContext(schema)

    # ---- FROM + JOIN tables -------------------------------------------------
    from_tables: list[tuple[str, str]] = []  # (real_table, alias)
    # sqlglot key differs across versions ("from" vs "from_"); find() is robust.
    from_exp = select.args.get("from") or select.args.get("from_") or select.find(exp.From)
    if from_exp is None:
        raise ValueError("Query has no FROM clause.")

    for tbl in _iter_from_tables(from_exp):
        real = tbl.name
        alias = tbl.alias_or_name
        ctx.register(real, alias)
        from_tables.append((real, alias))

    join_nodes: list[tuple[str, str, Optional[exp.Expression], str]] = []
    for j in select.args.get("joins", []) or []:
        jt = j.this
        if isinstance(jt, exp.Table):
            real = jt.name
            alias = jt.alias_or_name
            ctx.register(real, alias)
            side = (j.args.get("side") or "").upper()
            kind = (j.args.get("kind") or "").upper()
            join_type = _join_type(side, kind)
            join_nodes.append((real, alias, j.args.get("on"), join_type))

    # ---- WHERE predicate ----------------------------------------------------
    where_pred: Optional[Predicate] = None
    where_exp = select.args.get("where")
    if where_exp is not None:
        where_pred = _convert_predicate(where_exp.this, ctx)

    # ---- Build logical tree (canonical, pre-optimization) -------------------
    # Base scans
    first_real, first_alias = from_tables[0]
    node: RANode = Scan(first_real, first_alias)

    # comma-separated additional FROM tables -> cross joins
    for real, alias in from_tables[1:]:
        node = Join(node, Scan(real, alias), None, "CROSS")

    join_conditions: list[Comparison] = []
    for real, alias, on_exp, join_type in join_nodes:
        # In some sqlglot versions the ON condition is wrapped; unwrap if needed.
        if on_exp is not None and hasattr(exp, "On") and isinstance(on_exp, getattr(exp, "On")):
            on_exp = on_exp.this
        cond = _convert_predicate(on_exp, ctx) if on_exp is not None else None
        if isinstance(cond, Comparison) and cond.is_join_predicate:
            join_conditions.append(cond)
        node = Join(node, Scan(real, alias), cond, join_type)

    # also collect join predicates that appear in WHERE (comma-join style)
    for p in flatten_conjuncts(where_pred):
        if isinstance(p, Comparison) and p.is_join_predicate:
            join_conditions.append(p)

    if where_pred is not None:
        node = Selection(where_pred, node)

    # ---- GROUP BY / aggregates ---------------------------------------------
    group_cols: list[str] = []
    group_exp = select.args.get("group")
    if group_exp is not None:
        for g in group_exp.expressions:
            group_cols.append(_col_label(g, ctx))

    aggregates = _collect_aggregates(select)
    if group_cols or aggregates:
        node = Aggregate(group_cols, aggregates, node)

    # ---- Projection ---------------------------------------------------------
    proj_cols, is_star = _projection_columns(select, ctx)
    node = Projection(proj_cols, node, is_star=is_star)

    # ---- ORDER BY -----------------------------------------------------------
    order_cols: list[str] = []
    order_exp = select.args.get("order")
    if order_exp is not None:
        for o in order_exp.expressions:
            target = o.this
            label = _col_label(target, ctx)
            direction = "DESC" if o.args.get("desc") else "ASC"
            order_cols.append(f"{label} {direction}")
        node = Sort(order_cols, node)

    return ParsedQuery(
        sql=sql,
        ast=root,
        ra_tree=node,
        alias_to_table=dict(ctx.alias_to_table),
        where=where_pred,
        join_conditions=join_conditions,
        projections=proj_cols,
        is_star=is_star,
        group_by=group_cols,
        aggregates=aggregates,
        order_by=order_cols,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _iter_from_tables(from_exp: exp.From):
    this = from_exp.this
    tables = []
    if isinstance(this, exp.Table):
        tables.append(this)
    # additional comma tables live in .expressions on older/newer sqlglot
    for e in from_exp.expressions or []:
        if isinstance(e, exp.Table):
            tables.append(e)
    return tables


def _join_type(side: str, kind: str) -> str:
    if kind == "CROSS":
        return "CROSS"
    if side == "LEFT":
        return "LEFT"
    if side == "RIGHT":
        return "RIGHT"
    if side == "FULL":
        return "FULL"
    return "INNER"


def _convert_operand(e: exp.Expression, ctx: QueryContext) -> Operand:
    if isinstance(e, exp.Column):
        return ctx.resolve_column(e.name, e.table or None)
    if isinstance(e, exp.Literal):
        if e.is_string:
            return Literal(e.this)
        val = e.this
        try:
            return Literal(int(val))
        except (ValueError, TypeError):
            try:
                return Literal(float(val))
            except (ValueError, TypeError):
                return Literal(val)
    if isinstance(e, exp.Boolean):
        return Literal(bool(e.this))
    if isinstance(e, exp.Null):
        return Literal(None)
    if isinstance(e, exp.Neg) and isinstance(e.this, exp.Literal):
        inner = _convert_operand(e.this, ctx)
        if isinstance(inner, Literal) and isinstance(inner.value, (int, float)):
            return Literal(-inner.value)
    # fallback: treat as opaque literal (its SQL text)
    return Literal(e.sql())


def _convert_predicate(e: Optional[exp.Expression], ctx: QueryContext) -> Predicate:
    if e is None:
        return TruePredicate()
    if isinstance(e, exp.Paren):
        return _convert_predicate(e.this, ctx)
    if isinstance(e, exp.And):
        parts = flatten_conjuncts(And([_convert_predicate(e.this, ctx), _convert_predicate(e.expression, ctx)]))
        return And(parts) if len(parts) > 1 else parts[0]
    if isinstance(e, exp.Or):
        return Or([_convert_predicate(e.this, ctx), _convert_predicate(e.expression, ctx)])
    for cls, op in _OP_MAP.items():
        if isinstance(e, cls):
            left = _convert_operand(e.this, ctx)
            right = _convert_operand(e.expression, ctx)
            if isinstance(left, ColumnRef):
                return Comparison(left, op, right)
            if isinstance(right, ColumnRef) and isinstance(left, Literal):
                # normalise '5 = x' to 'x = 5'
                flipped = {">": "<", "<": ">", ">=": "<=", "<=": ">="}.get(op, op)
                return Comparison(right, flipped, left)
            return UnknownPredicate(e.sql())
    if isinstance(e, exp.Is):
        col = _convert_operand(e.this, ctx)
        if isinstance(col, ColumnRef):
            negated = isinstance(e.expression, exp.Not)
            return NullCheck(col, negated=negated)
        return UnknownPredicate(e.sql())
    if isinstance(e, exp.Not):
        inner = e.this
        if isinstance(inner, exp.Is):
            col = _convert_operand(inner.this, ctx)
            if isinstance(col, ColumnRef):
                return NullCheck(col, negated=True)
        return UnknownPredicate(e.sql())
    if isinstance(e, exp.Between):
        col = _convert_operand(e.this, ctx)
        low = _convert_operand(e.args["low"], ctx)
        high = _convert_operand(e.args["high"], ctx)
        if isinstance(col, ColumnRef) and isinstance(low, Literal) and isinstance(high, Literal):
            return Between(col, low, high)
        return UnknownPredicate(e.sql())
    if isinstance(e, exp.In):
        col = _convert_operand(e.this, ctx)
        vals = [_convert_operand(v, ctx) for v in (e.expressions or [])]
        if isinstance(col, ColumnRef) and all(isinstance(v, Literal) for v in vals):
            return InList(col, vals)  # type: ignore[arg-type]
        return UnknownPredicate(e.sql())
    if isinstance(e, exp.Like):
        col = _convert_operand(e.this, ctx)
        pat = e.expression.sql()
        if isinstance(col, ColumnRef):
            return Like(col, pat)
        return UnknownPredicate(e.sql())
    return UnknownPredicate(e.sql())


def _collect_aggregates(select: exp.Select) -> list[str]:
    aggs: list[str] = []
    for e in select.expressions:
        target = e.this if isinstance(e, exp.Alias) else e
        for node in target.find_all(_AGG_FUNCS):
            aggs.append(node.sql())
    # de-dup preserving order
    seen: set[str] = set()
    out = []
    for a in aggs:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _projection_columns(select: exp.Select, ctx: QueryContext) -> tuple[list[str], bool]:
    cols: list[str] = []
    is_star = False
    for e in select.expressions:
        if isinstance(e, exp.Star):
            is_star = True
            cols.append("*")
            continue
        if isinstance(e, exp.Column) and isinstance(e.this, exp.Star):
            is_star = True
            cols.append(f"{e.table}.*" if e.table else "*")
            continue
        if isinstance(e, exp.Alias):
            cols.append(e.alias)
        elif isinstance(e, exp.Column):
            cols.append(_col_label(e, ctx))
        else:
            cols.append(e.sql())
    return cols, is_star


def _col_label(e: exp.Expression, ctx: QueryContext) -> str:
    if isinstance(e, exp.Column):
        ref = ctx.resolve_column(e.name, e.table or None)
        return ref.key
    if isinstance(e, exp.Alias):
        return e.alias
    return e.sql()
