"""Application configuration loaded from environment variables and ``.env``."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Provider-neutral runtime settings.

    Environment variables use the ``FREESEARCH_`` prefix. Provider credentials
    are resolved by :mod:`freesearch.secrets`, so they do not get copied into
    settings reprs, logs, or ordinary configuration dumps.
    """

    model_config = SettingsConfigDict(
        env_prefix="FREESEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=20.0, gt=0)
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    http_max_connections: int = Field(default=20, gt=0)
    http_max_keepalive_connections: int = Field(default=10, gt=0)
    user_agent: str = "FreeSearch/0.1"
    secret_service_name: str = "freesearch"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""

    return Settings()
