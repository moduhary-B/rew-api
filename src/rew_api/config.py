from __future__ import annotations

from functools import lru_cache

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="REW_",
        extra="ignore",
    )

    app_name: str = "Reviews API"
    environment: str = "development"
    database_url: str = "sqlite:///./rew_api.db"
    auto_create_schema: bool = False

    admin_api_key: str | None = None
    api_key_pepper: str = ""

    # Browser mode reads the temporary public-web key from the 2GIS page, so a
    # configured API key is not required. API mode remains available as an
    # optional, lighter transport for customers who have an official key.
    twogis_fetch_mode: Literal["browser", "api", "auto"] = "browser"
    twogis_reviews_api_key: str | None = None
    twogis_browser_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    # 2GIS currently challenges Chromium's classic headless mode. Docker runs
    # headed Chromium inside Xvfb, so no visible desktop is required on a server.
    twogis_browser_headless: bool = False
    http_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    http_retry_attempts: int = Field(default=3, ge=1, le=10)
    provider_request_delay_seconds: float = Field(default=0.35, ge=0, le=30)
    max_reviews_per_source: int = Field(default=5_000, ge=1, le=100_000)

    sync_delay_min_seconds: float = Field(default=20.0, ge=0, le=86_400)
    sync_delay_max_seconds: float = Field(default=60.0, ge=0, le=86_400)
    sync_interval_minutes: int = Field(default=1_440, ge=5, le=525_600)
    sync_overlap_minutes: int = Field(default=1_440, ge=0, le=43_200)
    sync_stale_after_minutes: int = Field(default=30, ge=1, le=1_440)

    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_delay_range(self) -> "Settings":
        if self.sync_delay_max_seconds < self.sync_delay_min_seconds:
            raise ValueError("sync_delay_max_seconds must be >= sync_delay_min_seconds")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
