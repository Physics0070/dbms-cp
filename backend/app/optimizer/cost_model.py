"""Educational, explicit cost model — independent of SQLite's own planner.

The model expresses cost in abstract units combining estimated I/O and CPU work.
Every constant is configurable (see config.py / .env). Full formula documentation
lives in COST_MODEL.md.

Constants (from Settings):
    Cio  = cost_io_per_page       cost of touching one page of I/O
    Ccpu = cost_cpu_per_row       cost of processing one row in CPU
    Cop  = cost_cpu_per_operator  small per-operator/tuple overhead
    R    = rows_per_page          rows assumed to fit on one page

Helper:
    pages(n) = ceil(n / R)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import Settings, get_settings


@dataclass
class CostBreakdown:
    cpu: float = 0.0
    io: float = 0.0
    memory: float = 0.0

    @property
    def total(self) -> float:
        return self.cpu + self.io + self.memory

    def to_dict(self) -> dict:
        return {
            "cpu": round(self.cpu, 4),
            "io": round(self.io, 4),
            "memory": round(self.memory, 4),
            "total": round(self.total, 4),
        }

    def __add__(self, other: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(self.cpu + other.cpu, self.io + other.io, self.memory + other.memory)


class CostModel:
    def __init__(self, settings: Settings | None = None):
        self.cfg = settings or get_settings()

    # -- helpers -------------------------------------------------------------
    def pages(self, n_rows: float) -> float:
        return math.ceil(max(0.0, n_rows) / max(1, self.cfg.rows_per_page))

    # -- scan operators ------------------------------------------------------
    def seq_scan(self, n_rows: float) -> CostBreakdown:
        # Read every page, inspect every row.
        return CostBreakdown(
            cpu=n_rows * self.cfg.cost_cpu_per_row,
            io=self.pages(n_rows) * self.cfg.cost_io_per_page,
        )

    def index_scan(self, n_rows: float, matched_rows: float) -> CostBreakdown:
        # B-tree descent (log of table size) + reading the matching leaf pages.
        descent = math.log2(max(2.0, n_rows))
        return CostBreakdown(
            cpu=matched_rows * self.cfg.cost_cpu_per_row,
            io=(descent + self.pages(matched_rows)) * self.cfg.cost_io_per_page,
        )

    def index_probe(self, n_rows: float, matched_rows: float) -> CostBreakdown:
        # Cost of a *single* index lookup (used inside index-nested-loop join).
        descent = math.log2(max(2.0, n_rows))
        return CostBreakdown(
            cpu=matched_rows * self.cfg.cost_cpu_per_row,
            io=(descent + self.pages(matched_rows)) * self.cfg.cost_io_per_page,
        )

    # -- row operators -------------------------------------------------------
    def filter(self, input_rows: float) -> CostBreakdown:
        return CostBreakdown(cpu=input_rows * self.cfg.cost_cpu_per_row)

    def projection(self, input_rows: float) -> CostBreakdown:
        # Projection is cheap relative to a full row scan.
        return CostBreakdown(cpu=input_rows * self.cfg.cost_cpu_per_operator)

    def sort(self, input_rows: float) -> CostBreakdown:
        # Comparison sort: n log n CPU; the working set occupies memory pages.
        n = max(1.0, input_rows)
        return CostBreakdown(
            cpu=n * math.log2(max(2.0, n)) * self.cfg.cost_cpu_per_row,
            memory=self.pages(n) * self.cfg.cost_io_per_page,
        )

    def aggregate(self, input_rows: float, groups: float) -> CostBreakdown:
        # Hash aggregation: scan every input row, keep one entry per group.
        return CostBreakdown(
            cpu=input_rows * self.cfg.cost_cpu_per_row,
            memory=self.pages(groups) * self.cfg.cost_io_per_page,
        )

    # -- join self-costs (excluding children) --------------------------------
    def nested_loop_compare(self, outer_rows: float, inner_rows: float) -> CostBreakdown:
        return CostBreakdown(cpu=outer_rows * inner_rows * self.cfg.cost_cpu_per_operator)

    def hash_join_self(self, build_rows: float, probe_rows: float) -> CostBreakdown:
        return CostBreakdown(
            cpu=(build_rows + probe_rows) * self.cfg.cost_cpu_per_row,
            memory=self.pages(build_rows) * self.cfg.cost_io_per_page,
        )

    def merge_join_self(self, left_rows: float, right_rows: float) -> CostBreakdown:
        return CostBreakdown(cpu=(left_rows + right_rows) * self.cfg.cost_cpu_per_row)

    def output(self, rows: float) -> CostBreakdown:
        return CostBreakdown(cpu=rows * self.cfg.cost_cpu_per_operator)
