"""Application configuration loaded from environment variables and ``.env``."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from freesearch.infrastructure.secret_crypto import DEFAULT_KEY_FILE


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
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=20.0, gt=0)
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    http_max_connections: int = Field(default=20, gt=0)
    http_max_keepalive_connections: int = Field(default=10, gt=0)
    user_agent: str = "FreeSearch/0.1"
    secret_service_name: str = "freesearch"
    encryption_key: SecretStr | None = Field(default=None, repr=False)
    encryption_key_file: Path = DEFAULT_KEY_FILE


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""

    return Settings()
