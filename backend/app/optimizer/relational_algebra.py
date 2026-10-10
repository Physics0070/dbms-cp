"""Relational algebra tree and the predicate expression model.

These structures are produced dynamically from a parsed SQL statement and carry
no assumptions about any particular schema. Every node serialises to a plain
dict for the API / React Flow visualiser.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional, Union


# ---------------------------------------------------------------------------
# Expression model (used inside Selection / Join predicates)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnRef:
    table: Optional[str]  # resolved base-table name (or alias) — may be None
    column: str

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}" if self.table else self.column

    def to_dict(self) -> dict:
        return {"kind": "column", "table": self.table, "column": self.column}

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.key


@dataclass(frozen=True)
class Literal:
    value: Any

    def to_dict(self) -> dict:
        return {"kind": "literal", "value": self.value}

    def __str__(self) -> str:  # pragma: no cover
        return repr(self.value)


Operand = Union[ColumnRef, Literal]


class Predicate:
    """Base class for boolean predicates."""

    def columns(self) -> list[ColumnRef]:
        return []

    def tables(self) -> set[str]:
        return {c.table for c in self.columns() if c.table}

    def to_dict(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def __str__(self) -> str:  # pragma: no cover
        return self.__class__.__name__


class TruePredicate(Predicate):
    """Represents 'no filter'."""

    def to_dict(self) -> dict:
        return {"type": "true"}

    def __str__(self) -> str:  # pragma: no cover
        return "TRUE"


@dataclass
class Comparison(Predicate):
    left: ColumnRef
    op: str  # '=', '!=', '>', '>=', '<', '<='
    right: Operand

    def columns(self) -> list[ColumnRef]:
        cols = [self.left]
        if isinstance(self.right, ColumnRef):
            cols.append(self.right)
        return cols

    @property
    def is_join_predicate(self) -> bool:
        return (
            isinstance(self.right, ColumnRef)
            and self.left.table is not None
            and self.right.table is not None
            and self.left.table != self.right.table
        )

    def to_dict(self) -> dict:
        return {
            "type": "comparison",
            "op": self.op,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "is_join": self.is_join_predicate,
        }

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.left} {self.op} {self.right}"


@dataclass
class Between(Predicate):
    col: ColumnRef
    low: Literal
    high: Literal

    def columns(self) -> list[ColumnRef]:
        return [self.col]

    def to_dict(self) -> dict:
        return {
            "type": "between",
            "col": self.col.to_dict(),
            "low": self.low.to_dict(),
            "high": self.high.to_dict(),
        }

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.col} BETWEEN {self.low} AND {self.high}"


@dataclass
class NullCheck(Predicate):
    col: ColumnRef
    negated: bool  # True => IS NOT NULL

    def columns(self) -> list[ColumnRef]:
        return [self.col]

    def to_dict(self) -> dict:
        return {"type": "null", "col": self.col.to_dict(), "negated": self.negated}

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.col} IS {'NOT ' if self.negated else ''}NULL"


@dataclass
class InList(Predicate):
    col: ColumnRef
    values: list[Literal]

    def columns(self) -> list[ColumnRef]:
        return [self.col]

    def to_dict(self) -> dict:
        return {
            "type": "in",
            "col": self.col.to_dict(),
            "values": [v.to_dict() for v in self.values],
        }

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.col} IN (...)"


@dataclass
class Like(Predicate):
    col: ColumnRef
    pattern: str

    def columns(self) -> list[ColumnRef]:
        return [self.col]

    def to_dict(self) -> dict:
        return {"type": "like", "col": self.col.to_dict(), "pattern": self.pattern}

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.col} LIKE {self.pattern!r}"


@dataclass
class And(Predicate):
    parts: list[Predicate]

    def columns(self) -> list[ColumnRef]:
        out: list[ColumnRef] = []
        for p in self.parts:
            out.extend(p.columns())
        return out

    def to_dict(self) -> dict:
        return {"type": "and", "parts": [p.to_dict() for p in self.parts]}

    def __str__(self) -> str:  # pragma: no cover
        return " AND ".join(f"({p})" for p in self.parts)


@dataclass
class Or(Predicate):
    parts: list[Predicate]

    def columns(self) -> list[ColumnRef]:
        out: list[ColumnRef] = []
        for p in self.parts:
            out.extend(p.columns())
        return out

    def to_dict(self) -> dict:
        return {"type": "or", "parts": [p.to_dict() for p in self.parts]}

    def __str__(self) -> str:  # pragma: no cover
        return " OR ".join(f"({p})" for p in self.parts)


@dataclass
class UnknownPredicate(Predicate):
    """A predicate we could parse structurally but not model precisely."""

    text: str

    def to_dict(self) -> dict:
        return {"type": "unknown", "text": self.text}


def flatten_conjuncts(pred: Optional[Predicate]) -> list[Predicate]:
    """Split an AND tree into a flat list of conjuncts (join order friendly)."""
    if pred is None or isinstance(pred, TruePredicate):
        return []
    if isinstance(pred, And):
        out: list[Predicate] = []
        for p in pred.parts:
            out.extend(flatten_conjuncts(p))
        return out
    return [pred]


def combine_conjuncts(preds: list[Predicate]) -> Optional[Predicate]:
    preds = [p for p in preds if p is not None and not isinstance(p, TruePredicate)]
    if not preds:
        return None
    if len(preds) == 1:
        return preds[0]
    return And(preds)


# ---------------------------------------------------------------------------
# Relational algebra nodes
# ---------------------------------------------------------------------------
_NODE_COUNTER = {"n": 0}


def _next_id() -> str:
    _NODE_COUNTER["n"] += 1
    return f"ra{_NODE_COUNTER['n']}"


class RANode:
    op: str = "Node"

    def __init__(self, children: Optional[list["RANode"]] = None):
        self.id = _next_id()
        self.children: list[RANode] = children or []

    # relations produced by this subtree (base-table names)
    def relations(self) -> set[str]:
        rels: set[str] = set()
        for c in self.children:
            rels |= c.relations()
        return rels

    def copy(self) -> "RANode":
        return copy.deepcopy(self)

    def _extra(self) -> dict:
        return {}

    def to_dict(self) -> dict:
        d = {"id": self.id, "op": self.op, "children": [c.to_dict() for c in self.children]}
        d.update(self._extra())
        return d

    def label(self) -> str:  # short human label
        return self.op


class Scan(RANode):
    op = "Scan"

    def __init__(self, table: str, alias: Optional[str] = None):
        super().__init__([])
        self.table = table
        self.alias = alias or table

    def relations(self) -> set[str]:
        return {self.alias}

    def _extra(self) -> dict:
        return {"table": self.table, "alias": self.alias}

    def label(self) -> str:
        return f"Scan {self.table}" + (f" AS {self.alias}" if self.alias != self.table else "")


class Selection(RANode):
    op = "Selection"

    def __init__(self, predicate: Predicate, child: RANode):
        super().__init__([child])
        self.predicate = predicate

    @property
    def child(self) -> RANode:
        return self.children[0]

    def _extra(self) -> dict:
        return {"predicate": self.predicate.to_dict(), "predicate_text": str(self.predicate)}

    def label(self) -> str:
        return f"σ {self.predicate}"


class Projection(RANode):
    op = "Projection"

    def __init__(self, columns: list[str], child: RANode, is_star: bool = False):
        super().__init__([child])
        self.columns = columns
        self.is_star = is_star

    @property
    def child(self) -> RANode:
        return self.children[0]

    def _extra(self) -> dict:
        return {"columns": self.columns, "is_star": self.is_star}

    def label(self) -> str:
        return "π " + ("*" if self.is_star else ", ".join(self.columns))


class Join(RANode):
    op = "Join"

    def __init__(
        self,
        left: RANode,
        right: RANode,
        condition: Optional[Predicate],
        join_type: str = "INNER",
    ):
        super().__init__([left, right])
        self.condition = condition
        self.join_type = join_type

    @property
    def left(self) -> RANode:
        return self.children[0]

    @property
    def right(self) -> RANode:
        return self.children[1]

    def _extra(self) -> dict:
        return {
            "join_type": self.join_type,
            "condition": self.condition.to_dict() if self.condition else None,
            "condition_text": str(self.condition) if self.condition else "cross",
        }

    def label(self) -> str:
        return f"⋈ {self.join_type} {self.condition or ''}"


class Aggregate(RANode):
    op = "Aggregate"

    def __init__(self, group_by: list[str], aggregates: list[str], child: RANode):
        super().__init__([child])
        self.group_by = group_by
        self.aggregates = aggregates

    @property
    def child(self) -> RANode:
        return self.children[0]

    def _extra(self) -> dict:
        return {"group_by": self.group_by, "aggregates": self.aggregates}

    def label(self) -> str:
        return f"Γ group_by={self.group_by} aggs={self.aggregates}"


class Sort(RANode):
    op = "Sort"

    def __init__(self, keys: list[str], child: RANode):
        super().__init__([child])
        self.keys = keys

    @property
    def child(self) -> RANode:
        return self.children[0]

    def _extra(self) -> dict:
        return {"keys": self.keys}

    def label(self) -> str:
        return f"Sort {self.keys}"
