"""Unit tests for the MCP transport guard (P4, T3/T4/T13 parts).

Every test runs with no database and no network. A small service double
stands in for ``AuthService``, so these tests pin the transport seams only:
the SDK verifier shape, the per-call account check, the settings derivation,
the startup rejection of an unverified server, and the stdio credential rule.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr

from freesearch.mcp.auth import (
    MCP_AUTH_ERROR,
    LocalTokenVerifier,
    McpAuthenticationError,
    build_auth_settings,
    build_http_app,
    require_mcp_user,
    run_stdio_server,
)
from freesearch.mcp.server import create_server
from freesearch.models.users import UserPrincipal, UserRole
from tests.fixtures.auth import test_settings


def _principal() -> UserPrincipal:
    return UserPrincipal(
        id=uuid4(),
        email="mcp-unit@example.com",
        role=UserRole.AGENT,
        session_id=uuid4(),
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )


class _StubService:
    """Minimal ``AuthService`` double: one fixed answer for every token."""

    def __init__(self, principal: UserPrincipal | None) -> None:
        self._principal = principal
        self.seen: list[str] = []

    async def verify_token(self, token: str) -> UserPrincipal | None:
        self.seen.append(token)
        return self._principal


def _http_context(token: str, subject: str | None) -> Any:
    return AuthenticatedUser(
        AccessToken(token=token, client_id="client", scopes=[], subject=subject)
    )


async def test_verifier_returns_account_identity_for_live_token() -> None:
    principal = _principal()
    verifier = LocalTokenVerifier(_StubService(principal))  # type: ignore[arg-type]

    access = await verifier.verify_token("good-access")

    assert access is not None
    assert access.subject == str(principal.id)
    assert access.client_id == str(principal.id)
    assert access.scopes == []


async def test_verifier_returns_none_for_dead_token() -> None:
    verifier = LocalTokenVerifier(_StubService(None))  # type: ignore[arg-type]

    assert await verifier.verify_token("bad-token") is None


async def test_tool_call_without_any_credential_rejects() -> None:
    service = _StubService(_principal())

    with pytest.raises(McpAuthenticationError, match="authentication is required"):
        await require_mcp_user(service)  # type: ignore[arg-type]

    assert service.seen == []


async def test_tool_call_with_bad_stdio_credential_rejects() -> None:
    service = _StubService(None)

    with pytest.raises(McpAuthenticationError, match=MCP_AUTH_ERROR):
        await require_mcp_user(service, stdio_token=SecretStr("bad-token"))  # type: ignore[arg-type]

    assert service.seen == ["bad-token"]


async def test_tool_call_with_live_stdio_credential_serves() -> None:
    principal = _principal()
    service = _StubService(principal)

    result = await require_mcp_user(service, stdio_token=SecretStr("good-token"))  # type: ignore[arg-type]

    assert result == principal
    assert service.seen == ["good-token"]


async def test_tool_call_with_matching_http_subject_serves() -> None:
    principal = _principal()
    service = _StubService(principal)
    reset = auth_context_var.set(_http_context("good-access", str(principal.id)))
    try:
        result = await require_mcp_user(service)  # type: ignore[arg-type]
    finally:
        auth_context_var.reset(reset)

    assert result == principal


async def test_tool_call_with_foreign_http_subject_rejects() -> None:
    principal = _principal()
    service = _StubService(principal)
    reset = auth_context_var.set(_http_context("good-access", str(uuid4())))
    try:
        with pytest.raises(McpAuthenticationError, match=MCP_AUTH_ERROR):
            await require_mcp_user(service)  # type: ignore[arg-type]
    finally:
        auth_context_var.reset(reset)


def test_auth_settings_derive_from_transport_settings() -> None:
    settings = test_settings()

    auth_settings = build_auth_settings(settings)

    assert str(auth_settings.issuer_url).startswith("http://")
    assert str(auth_settings.resource_server_url).endswith("/mcp")


def test_auth_settings_explicit_overrides_win() -> None:
    settings = test_settings(
        auth_issuer_url="https://login.example.com",
        mcp_resource_url="https://api.example.com/mcp",
    )

    auth_settings = build_auth_settings(settings)

    assert str(auth_settings.issuer_url) == "https://login.example.com/"
    assert str(auth_settings.resource_server_url) == "https://api.example.com/mcp"


def test_http_app_rejects_server_without_verifier() -> None:
    server = create_server([])

    with pytest.raises(McpAuthenticationError, match="without account authentication"):
        build_http_app(server, auth_service=_StubService(_principal()), settings=test_settings())  # type: ignore[arg-type]


async def test_stdio_runner_rejects_absent_process_credential() -> None:
    server = create_server([])

    with pytest.raises(McpAuthenticationError, match="FREESEARCH_MCP_BEARER_TOKEN"):
        await run_stdio_server(
            server,
            auth_service=_StubService(_principal()),
            settings=test_settings(),  # type: ignore[arg-type]
        )
