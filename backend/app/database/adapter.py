"""Database abstraction layer.

The optimizer depends *only* on this interface, never on a specific engine directly.
Swapping databases means writing a new adapter, not touching the optimizer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Schema value objects (schema-agnostic — no table/column names baked in)
# ---------------------------------------------------------------------------
@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool
    default: Optional[str] = None


@dataclass
class Index:
    name: str
    columns: list[str]
    unique: bool
    origin: str = ""  # 'c' created, 'u' unique constraint, 'pk' primary key


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_update: str = ""
    on_delete: str = ""


@dataclass
class TableSchema:
    name: str
    columns: list[Column] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)

    @property
    def primary_key(self) -> list[str]:
        return [c.name for c in self.columns if c.primary_key]

    def column(self, name: str) -> Optional[Column]:
        for c in self.columns:
            if c.name.lower() == name.lower():
                return c
        return None


# ---------------------------------------------------------------------------
# Statistics value objects (all values *computed* from the live database)
# ---------------------------------------------------------------------------
@dataclass
class ColumnStatistics:
    column: str
    data_type: str
    distinct_count: int
    null_count: int
    null_fraction: float
    min_value: Any = None
    max_value: Any = None
    most_common: list[tuple[Any, int]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "column": self.column,
            "data_type": self.data_type,
            "distinct_count": self.distinct_count,
            "null_count": self.null_count,
            "null_fraction": round(self.null_fraction, 6),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "most_common": [
                {"value": v, "count": c} for v, c in self.most_common
            ],
        }


@dataclass
class TableStatistics:
    table: str
    row_count: int
    columns: dict[str, ColumnStatistics]
    collected_at: str
    source: str = "Computed from the connected database"

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "row_count": self.row_count,
            "collected_at": self.collected_at,
            "source": self.source,
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
        }


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------
class DatabaseAdapter(ABC):
    """Every capability the optimizer needs from a database."""

    @abstractmethod
    def get_tables(self) -> list[str]:
        ...

    @abstractmethod
    def get_columns(self, table: str) -> list[Column]:
        ...

    @abstractmethod
    def get_indexes(self, table: str) -> list[Index]:
        ...

    @abstractmethod
    def get_foreign_keys(self, table: str) -> list[ForeignKey]:
        ...

    @abstractmethod
    def get_table_schema(self, table: str) -> TableSchema:
        ...

    @abstractmethod
    def get_schema(self) -> dict[str, TableSchema]:
        ...

    @abstractmethod
    def get_statistics(self, table: str, use_cache: bool = True) -> TableStatistics:
        ...

    @abstractmethod
    def execute_readonly(
        self, sql: str, params: Optional[list] = None, limit: Optional[int] = None
    ) -> tuple[list[str], list[tuple]]:
        """Return (column_names, rows). Implementations MUST guarantee read-only."""
        ...

    @abstractmethod
    def explain_query(self, sql: str) -> list[dict]:
        """SQLite EXPLAIN QUERY PLAN, parsed into structured rows."""
        ...

    @abstractmethod
    def explain_bytecode(self, sql: str) -> list[dict]:
        """SQLite EXPLAIN (low-level bytecode)."""
        ...

    @abstractmethod
    def benchmark_query(
        self, sql: str, warmup: int = 2, runs: int = 5
    ) -> dict:
        ...
