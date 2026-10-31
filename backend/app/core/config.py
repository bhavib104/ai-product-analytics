"""Application configuration.

All settings come from environment variables, optionally loaded from a local
``.env`` file.  Nothing secret is hard-coded.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "AI Product Analytics & Decision Intelligence Copilot"
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    log_format: str = Field(default="text", description="'text' or 'json'")
    api_v1_prefix: str = "/api/v1"

    # --- Data paths --------------------------------------------------------
    data_dir: Path = Path("./data")
    duckdb_path: Path = Path("./data/product_analytics.duckdb")
    app_db_path: Path = Path("./data/app.db")

    # --- Synthetic data ----------------------------------------------------
    data_seed: int = 42
    data_start_date: date = date(2026, 5, 4)
    data_end_date: date = date(2026, 10, 30)
    data_num_users: int = 5000

    # --- CORS --------------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- LLM ---------------------------------------------------------------
    llm_provider: str = "deterministic"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_input_usd_per_1m: float = 0.15
    openai_output_usd_per_1m: float = 0.60

    # --- SQL safety --------------------------------------------------------
    sql_max_rows: int = 500
    sql_timeout_seconds: int = 8
    sql_max_joins: int = 3
    sql_max_subquery_depth: int = 2
    sql_max_ast_nodes: int = 250
    sql_memory_limit: str = "512MB"
    sql_threads: int = 2

    # --- AI bounds ---------------------------------------------------------
    ai_max_tool_calls: int = 6
    ai_tool_timeout_seconds: int = 20
    ai_total_timeout_seconds: int = 60
    ai_max_output_tokens: int = 900

    # --- Admin -------------------------------------------------------------
    admin_api_token: str | None = None

    @field_validator("data_end_date")
    @classmethod
    def _end_after_start(cls, value: date, info):
        start = info.data.get("data_start_date")
        if start and value <= start:
            raise ValueError("DATA_END_DATE must be after DATA_START_DATE")
        return value

    @field_validator("sql_max_rows")
    @classmethod
    def _row_cap(cls, value: int) -> int:
        return max(10, min(int(value), 2000))

    @field_validator("sql_timeout_seconds")
    @classmethod
    def _timeout_cap(cls, value: int) -> int:
        return max(1, min(int(value), 60))

    @property
    def as_of_date(self) -> date:
        """The analytical 'today' — the last date present in the dataset."""
        return self.data_end_date

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self.app_db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "quarantine").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
