"""Statistics provider — a thin, cached facade over the adapter's computed stats.

All numbers ultimately come from `DatabaseAdapter.get_statistics`, which computes
them with real SQL against the live Turso/libSQL data. Nothing is hardcoded.
"""
from __future__ import annotations

from typing import Optional

from ..database.adapter import ColumnStatistics, DatabaseAdapter, TableStatistics


class StatisticsProvider:
    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter

    def table_stats(self, real_table: str) -> TableStatistics:
        return self.adapter.get_statistics(real_table)

    def row_count(self, real_table: str) -> int:
        return self.table_stats(real_table).row_count

    def column_stats(self, real_table: str, column: str) -> Optional[ColumnStatistics]:
        return self.table_stats(real_table).columns.get(column)

    def resolve(
        self, alias: Optional[str], column: str, alias_to_table: dict[str, str]
    ) -> Optional[ColumnStatistics]:
        if alias is None:
            return None
        real = alias_to_table.get(alias, alias)
        return self.column_stats(real, column)
