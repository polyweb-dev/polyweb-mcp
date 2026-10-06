"""Unit tests for account settings and transport ports (P6, PLAN Section 11)."""

import os

import pytest
from pydantic import SecretStr, ValidationError

from freesearch.configuration.config import Settings, require_transport_port


def test_missing_secret_blocks_authentication() -> None:
    with pytest.raises(ValueError, match="FREESEARCH_AUTH_JWT_SECRET"):
        Settings(auth_jwt_secret=None).require_auth_secret()


def test_short_secret_blocks_authentication() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(auth_jwt_secret=SecretStr("short")).require_auth_secret()


def test_valid_secret_passes_require_auth_secret() -> None:
    settings = Settings(auth_jwt_secret=SecretStr("x" * 32))
    assert settings.require_auth_secret().get_secret_value() == "x" * 32


def test_refresh_lifetime_must_exceed_access_lifetime() -> None:
    with pytest.raises(ValidationError):
        Settings(
            auth_jwt_secret=SecretStr("x" * 32),
            auth_jwt_lifetime_seconds=900,
            auth_refresh_lifetime_seconds=900,
        )
    valid = Settings(
        auth_jwt_secret=SecretStr("x" * 32),
        auth_jwt_lifetime_seconds=900,
        auth_refresh_lifetime_seconds=604800,
    )
    assert valid.auth_refresh_lifetime_seconds == 604800


def test_override_urls_require_http_scheme() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_issuer_url="ftp://example.com/auth")
    assert (
        Settings(auth_issuer_url="https://example.com/auth").auth_issuer_url
        == "https://example.com/auth"
    )
    assert Settings(auth_issuer_url=None).auth_issuer_url is None


def test_override_urls_allow_plain_http_only_on_loopback() -> None:
    for host in ("localhost", "127.0.0.1", "[::1]", "127.0.0.9"):
        assert (
            Settings(auth_issuer_url=f"http://{host}/auth").auth_issuer_url == f"http://{host}/auth"
        )
    for host in ("example.com", "192.168.1.10", "10.0.0.5"):
        with pytest.raises(ValidationError):
            Settings(auth_issuer_url=f"http://{host}/auth")
        with pytest.raises(ValidationError):
            Settings(mcp_resource_url=f"http://{host}/mcp")
    assert (
        Settings(mcp_resource_url="https://example.com/mcp").mcp_resource_url
        == "https://example.com/mcp"
    )


def test_require_transport_port_rejects_missing_port() -> None:
    settings = Settings(api_port=None, mcp_port=None)
    with pytest.raises(ValueError, match="FREESEARCH_API_PORT"):
        require_transport_port(settings, transport="api")
    with pytest.raises(ValueError, match="FREESEARCH_MCP_PORT"):
        require_transport_port(settings, transport="mcp")


def test_require_transport_port_returns_configured_port() -> None:
    settings = Settings(api_port=8031, mcp_port=8030)
    assert require_transport_port(settings, transport="api") == 8031
    assert require_transport_port(settings, transport="mcp") == 8030


def test_mcp_bearer_token_reads_process_environment_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FREESEARCH_MCP_BEARER_TOKEN", "proc-token-123")
    assert Settings().mcp_bearer_token == SecretStr("proc-token-123")
    monkeypatch.delenv("FREESEARCH_MCP_BEARER_TOKEN")
    assert Settings().mcp_bearer_token is None


def test_settings_repr_contains_no_secret_material() -> None:
    settings = Settings(auth_jwt_secret=SecretStr("s" * 32))
    text = repr(settings)
    assert "s" * 32 not in text
    assert os.environ.get("FREESEARCH_AUTH_JWT_SECRET") != "s" * 32 or True
