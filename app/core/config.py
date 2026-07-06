"""Application configuration via Pydantic v2 settings.

Settings are loaded from environment variables (and an optional ``.env`` file).
``get_settings`` is memoised so the settings object is parsed exactly once and
shared as an application-wide singleton (cheap dependency for the DI container).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    """Deployment environment. Drives log verbosity and resource selection."""

    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"


class Settings(BaseSettings):
    """Strongly-typed, validated application settings.

    Every field carries a default suitable for a local MVP run, so the app
    boots with zero configuration. Production overrides everything via env vars.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,  # allow constructing Settings(field_name=...) in tests
    )

    # --- Application ---
    app_env: AppEnv = Field(default=AppEnv.DEV, alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    # --- Database ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/agent.db", alias="DATABASE_URL"
    )

    # --- LLM ---
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")

    # --- Memory ---
    memory_session_window: int = Field(default=30, ge=1, le=200, alias="MEMORY_SESSION_WINDOW")

    # --- Telegram (optional transport) ---
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    @field_validator("app_log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        """Accept case-insensitive log levels and validate against stdlib names."""
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"invalid log level {value!r}; expected one of {sorted(allowed)}")
        return upper

    @property
    def is_prod(self) -> bool:
        return self.app_env is AppEnv.PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (parsed once, then cached)."""
    return Settings()
