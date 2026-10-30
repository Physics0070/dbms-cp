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
    database_path: str = "optimizer_demo.db"   # SQLite file connected at startup
    allow_index_creation: bool = False          # False -> database opened read-only
    upload_dir: str = ""                        # empty -> backend/data/uploads (never served statically)
    max_upload_mb: int = 100                    # reject larger SQLite uploads
    allow_private_network: bool = False         # remote DB hosts that resolve to private/loopback IPs are blocked
    pg_statement_timeout_ms: int = 30000        # server-side cap per PostgreSQL statement
    pg_connect_timeout_s: int = 8
    allow_path_connect: bool = True             # False on hosted deployments: only uploads/startup DB

    # --- AI -----------------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_api_url: str = "https://api.openai.com/v1/chat/completions"
    openai_temperature: float = 0.2
    openai_timeout_s: float = 45.0

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
    min_estimated_gain_pct: float = 0.5  # below this a rewrite is not reported as an optimization

    # --- Misc ---------------------------------------------------------------
    history_limit: int = 200
    history_path: str = ""               # empty -> backend/query_history.json
    example_limit: int = 6               # example queries generated from the schema
    optimizer_version: str = "1.1.0"
    stats_cache_ttl: int = 300

    # --- AI copilot privacy -------------------------------------------------
    copilot_send_schema: bool = True     # False -> table/column names are obfuscated before any external call

    # --- Hardening ----------------------------------------------------------
    log_level: str = "INFO"
    max_request_mb: int = 10             # body cap for every endpoint except /api/database/upload
    request_timeout_s: float = 300.0     # 0 disables; client gets 504 (a running sync handler is not killed)
    rate_limit_per_min: int = 120        # per client IP on heavy endpoints; 0 disables
    api_token: str = ""                  # set -> every /api/* call except /api/health needs "Authorization: Bearer <token>"
    serve_frontend: bool = True          # serve frontend/dist (if built) from this server
    frontend_dist: str = ""              # empty -> ../frontend/dist relative to the repo
    # Comma-separated origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
