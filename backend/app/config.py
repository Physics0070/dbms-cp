"""Central configuration.

Every tunable is loaded from the environment (via `.env`) so that *nothing*
about the optimizer's behaviour is hardcoded in the modules that use it.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database -----------------------------------------------------------
    turso_database_url: str = ""
    turso_auth_token: str = ""
    local_db_path: str = "optimizer_demo.db"

    # --- AI -----------------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- Seed generation ----------------------------------------------------
    seed: int = 42
    customer_count: int = 2000
    order_count: int = 8000
    product_count: int = 500

    # --- Cost model tunables ------------------------------------------------
    cost_io_per_page: float = 1.0
    cost_cpu_per_row: float = 0.01
    cost_cpu_per_operator: float = 0.0025
    rows_per_page: int = 100

    # --- Selectivity fallbacks ----------------------------------------------
    default_eq_selectivity: float = 0.1
    default_range_selectivity: float = 0.3333
    default_join_selectivity: float = 0.1

    # --- Statistics collection ----------------------------------------------
    mcv_limit: int = 10                  # most-common-values kept per column
    mcv_min_distinct_cap: int = 50       # always histogram columns with <= this many distinct values
    mcv_distinct_ratio: float = 0.05     # ...or <= this fraction of the row count

    # --- Plan search --------------------------------------------------------
    exhaustive_join_threshold: int = 6   # <= N relations: enumerate; > N: System-R DP
    max_candidates: int = 12             # candidate plans returned to the client

    # --- Benchmarking -------------------------------------------------------
    benchmark_warmup: int = 2
    benchmark_runs: int = 5
    equivalence_row_cap: int = 50000     # max rows compared when verifying a rewrite

    # --- Misc ---------------------------------------------------------------
    history_limit: int = 200
    optimizer_version: str = "1.1.0"
    stats_cache_ttl: int = 300
    frontend_origin: str = "http://localhost:5173"

    @property
    def use_remote(self) -> bool:
        return bool(self.turso_database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
