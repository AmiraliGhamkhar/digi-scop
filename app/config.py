"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated DigiScope settings.

    Secrets are represented by ``SecretStr`` so accidental logging does not reveal
    the manual-collection token.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "DigiScope"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_timezone: str = "Asia/Tehran"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str = "sqlite:///./data/digiscope.db"

    digikala_mcp_url: HttpUrl = HttpUrl("https://digikala-mcp.mmdju.workers.dev/mcp")
    mcp_protocol_version: str = "2024-11-05"
    mcp_request_timeout: float = Field(default=30.0, gt=0, le=120)
    mcp_max_retries: int = Field(default=3, ge=0, le=5)
    mcp_retry_base_seconds: float = Field(default=1.0, ge=0, le=30)
    mcp_max_retry_delay_seconds: float = Field(default=60.0, ge=0, le=120)

    collection_interval_minutes: int = Field(default=1440, ge=5, le=43_200)
    collection_enabled: bool = True
    default_ranking_limit: int = Field(default=10, ge=1, le=50)
    max_ranking_limit: int = Field(default=50, ge=1, le=100)
    price_history_products_per_run: int = Field(default=0, ge=0, le=30)
    collection_lock_dir: Path = Path("./data/locks")

    admin_token: SecretStr | None = None

    @field_validator("app_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @field_validator("admin_token", mode="before")
    @classmethod
    def empty_secret_is_none(cls, value: object) -> object:
        return None if value in (None, "") else value

    @model_validator(mode="after")
    def validate_limits_and_security(self) -> Settings:
        if self.default_ranking_limit > self.max_ranking_limit:
            raise ValueError("DEFAULT_RANKING_LIMIT cannot exceed MAX_RANKING_LIMIT")
        if self.app_env == "production" and self.collection_enabled and not self.admin_token:
            raise ValueError("ADMIN_TOKEN is required when collection is enabled in production")
        if (
            self.app_env == "production"
            and self.admin_token
            and len(self.admin_token.get_secret_value()) < 24
        ):
            raise ValueError("ADMIN_TOKEN must contain at least 24 characters in production")
        return self

    @property
    def admin_token_value(self) -> str | None:
        return self.admin_token.get_secret_value() if self.admin_token else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
