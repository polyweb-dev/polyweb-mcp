"""Application configuration loaded from environment variables and ``.env``."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Final, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from freesearch.infrastructure.browser_auth import normalize_origin
from freesearch.infrastructure.cryptography import DEFAULT_KEY_FILE
from freesearch.models.projects import ProjectRolloutState

_MCP_BEARER_TOKEN_ENVIRONMENT_VARIABLE = "FREESEARCH_MCP_BEARER_TOKEN"

#: Host names that count as local development for the HTTPS override rule.
_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "::1"})


def _is_loopback_host(host: str | None) -> bool:
    """Return whether a URL host names the local machine."""

    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized in _LOOPBACK_HOSTS:
        return True
    return normalized.startswith("127.")


#: Minimum secret material accepted for the access-token signing key.
AUTH_JWT_SECRET_MIN_BYTES = 32


def _parse_browser_origins(value: Any) -> list[str]:
    """Normalize the browser origin allowlist, or reject an invalid entry.

    A settings file can supply a JSON array or a comma-separated list. Every
    entry must be an exact origin: scheme, host, and optional port only. No
    wildcard, userinfo, path, query, or fragment is accepted, and HTTPS is
    mandatory outside loopback development.
    """

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as invalid:
                raise ValueError("browser origins must be a list of exact origins") from invalid
        else:
            value = text.split(",")
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("browser origins must be a list of exact origins")
    origins: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("browser origins must be exact origin strings")
        normalized = normalize_origin(item)
        if normalized is None:
            raise ValueError("browser origins must be exact http or https origins")
        if normalized not in origins:
            origins.append(normalized)
    return origins


class Settings(BaseSettings):
    """Provider-neutral runtime settings.

    Environment variables use the ``FREESEARCH_`` prefix. Provider credentials
    are resolved by :mod:`freesearch.secrets`, so they do not get copied into
    settings reprs, logs, or ordinary configuration dumps."""

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
    encryption_key: SecretStr | None = Field(default=None, repr=False)
    encryption_key_file: Path = DEFAULT_KEY_FILE
    encryption_retired_key_files: list[Path] = Field(default_factory=list)
    encryption_retired_keys: list[SecretStr] = Field(default_factory=list, repr=False)

    # Account and token settings. ``auth_jwt_secret`` is required at auth
    # composition, not at settings construction, so unrelated reads (monitoring,
    # trace export) keep working in a composition without accounts.
    auth_jwt_secret: SecretStr | None = Field(default=None, repr=False)
    auth_jwt_lifetime_seconds: int = Field(default=900, gt=0)
    auth_refresh_lifetime_seconds: int = Field(default=604800, gt=0)
    auth_issuer_url: str | None = None
    mcp_resource_url: str | None = None
    # Exact browser origins allowed to use cookie transport. An empty list is the
    # default and keeps the programmatic JSON pair plus Bearer refresh contract.
    auth_browser_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # The stdio credential is read from the process environment only: the local
    # environment file must never supply an account credential.
    mcp_bearer_token: SecretStr | None = Field(default=None, repr=False)

    # Transport binds. A port is required when its transport starts; no numeric
    # fallback exists, so the worktree ``.env`` stays authoritative.
    api_host: str = "127.0.0.1"
    api_port: int | None = Field(default=None, ge=1, le=65535)
    mcp_host: str = "127.0.0.1"
    mcp_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="before")
    @classmethod
    def _process_environment_only(cls, data: Any) -> Any:
        """Read the stdio credential from the process environment only.

        The value is overwritten after the environment file is loaded, so a
        local ``.env`` entry can never become an account credential.
        """

        if isinstance(data, dict):
            raw = os.environ.get(_MCP_BEARER_TOKEN_ENVIRONMENT_VARIABLE)
            data["mcp_bearer_token"] = raw or None
        return data

    @model_validator(mode="after")
    def _refresh_outlives_access(self) -> "Settings":
        """Reject a refresh lifetime that cannot outlive one access token."""

        if self.auth_refresh_lifetime_seconds <= self.auth_jwt_lifetime_seconds:
            raise ValueError("auth refresh lifetime must exceed the access lifetime")
        return self

    @field_validator("auth_issuer_url", "mcp_resource_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        """Accept only absolute HTTP or HTTPS override URLs.

        A plain HTTP override is permitted for loopback development only. An
        advertised issuer or resource URL outside loopback must use HTTPS, so a
        proxy can never publish a cleartext credential endpoint."""

        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlsplit(stripped)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("override URLs must use the http or https scheme")
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
            raise ValueError("override URLs must use https outside loopback development")
        return stripped.rstrip("/")

    @field_validator("auth_browser_origins", mode="before")
    @classmethod
    def _exact_browser_origins(cls, value: Any) -> list[str]:
        """Accept only an exact origin allowlist.

        A wildcard, a path, userinfo, a fragment, the opaque origin ``null``, or
        a cleartext non-loopback origin raises ``ValueError``, so a misconfigured
        allowlist stops startup instead of widening cookie trust.
        """

        return _parse_browser_origins(value)

    def require_auth_secret(self) -> SecretStr:
        """Return the access-token signing key, or reject production startup.

        Section 7 requires at least 32 random bytes of secret material. The check
        lives here rather than in the model so settings construction stays usable
        for compositions that never authenticate a request.
        """

        secret = self.auth_jwt_secret
        if secret is None or not secret.get_secret_value():
            raise ValueError("FREESEARCH_AUTH_JWT_SECRET is required for account authentication")
        material = secret.get_secret_value().encode("utf-8")
        if len(material) < AUTH_JWT_SECRET_MIN_BYTES:
            raise ValueError(
                f"FREESEARCH_AUTH_JWT_SECRET must hold at least "
                f"{AUTH_JWT_SECRET_MIN_BYTES} bytes of secret material"
            )
        return secret

    # Trace persistence seam. ``database`` keeps spans in the local SQLite
    # ``trace_spans`` table; ``none`` disables tracing entirely (a no-op
    # runtime). Future exporters (OTLP, Langfuse, LangSmith) plug into
    # ``freesearch.infrastructure.observability.build_span_processors``
    # without touching any route, service, or adapter call site.
    otel_processor: Literal["database", "none"] = "database"
    otel_service_name: str = "freesearch"

    # Projects architecture rollout gate. Defaults to preview mode.
    projects_rollout_state: ProjectRolloutState = ProjectRolloutState.PROJECTS_PREVIEW


def require_transport_port(settings: Settings, *, transport: str) -> int:
    """Return a configured transport port, or reject a start without one.

    Section 7 removes the numeric fallback ports from the launch paths: the
    worktree ``.env`` (or an explicit CLI override) must supply the value.
    """

    port = settings.api_port if transport == "api" else settings.mcp_port
    if port is None:
        raise ValueError(
            f"FREESEARCH_{transport.upper()}_PORT is required to start the {transport} transport"
        )
    return port


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""

    return Settings()
