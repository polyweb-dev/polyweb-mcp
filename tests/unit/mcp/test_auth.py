"""Unit tests for the MCP transport credential seams (P4, A1 TASK-000041).

Every test runs with no database and no network. The shared API key verifier
is replaced by a recording double, so these tests pin the transport seams only:
which credential a tool call presents (its own HTTP header, or the stdio
process key), the per-call verification, the fail-closed mapping, the settings
derivation and the stdio runner lifecycle. A1 removed anonymous tool calls and
human-JWT MCP access; the original test names are kept with the new oracle.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

import polyweb.mcp.auth as mcp_auth
from polyweb.infrastructure.auth_asgi import BearerAuthMiddleware
from polyweb.mcp.auth import (
    MCP_AUTH_ERROR,
    MCP_ROUTES,
    McpAuthenticationError,
    build_auth_settings,
    build_http_app,
    require_mcp_api_key,
    run_stdio_server,
    tool_credential,
)
from polyweb.mcp.server import create_server
from polyweb.models.projects import ProjectApiKeyPrincipal
from tests.fixtures.auth import test_settings

_STDIO_KEY = "fs_live_stdiostdiostd_" + "s" * 43
_HTTP_KEY = "fs_live_httphttphttp_" + "h" * 43


def _principal() -> ProjectApiKeyPrincipal:
    return ProjectApiKeyPrincipal(
        api_key_id=uuid4(), project_id=uuid4(), scopes=frozenset({"search.execute"})
    )


class _StubService:
    """Minimal ``AuthService`` double for the transport lifecycle."""

    def __init__(self) -> None:
        self.repository = object()
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _RecordingVerifier:
    """Stands in for ``ApiKeyVerifier``; records every raw credential it sees."""

    answer: ProjectApiKeyPrincipal | None = None
    error: Exception | None = None
    seen: list[str] = []  # noqa: RUF012 - reset by the fixture for every test

    def __init__(self, repository: object, **_: object) -> None:
        self.repository = repository

    async def verify(self, credential: str | SecretStr | None) -> ProjectApiKeyPrincipal | None:
        raw = credential.get_secret_value() if isinstance(credential, SecretStr) else credential
        type(self).seen.append(str(raw))
        if type(self).error is not None:
            raise type(self).error  # type: ignore[misc]
        return type(self).answer


@pytest.fixture
def verifier(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingVerifier]:
    _RecordingVerifier.answer = None
    _RecordingVerifier.error = None
    _RecordingVerifier.seen = []
    monkeypatch.setattr(mcp_auth, "ApiKeyVerifier", _RecordingVerifier)
    return _RecordingVerifier


def _http_ctx(headers: list[tuple[bytes, bytes]]) -> Any:
    request = SimpleNamespace(scope={"type": "http", "headers": headers})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _stdio_ctx() -> Any:
    return SimpleNamespace(request_context=SimpleNamespace(request=None))


async def test_verifier_returns_account_identity_for_live_token(
    verifier: type[_RecordingVerifier],
) -> None:
    principal = _principal()
    verifier.answer = principal

    result = await require_mcp_api_key(object(), SecretStr(_STDIO_KEY))  # type: ignore[arg-type]

    assert result == principal
    assert verifier.seen == [_STDIO_KEY]


async def test_verifier_returns_none_for_dead_token(verifier: type[_RecordingVerifier]) -> None:
    verifier.answer = None

    with pytest.raises(McpAuthenticationError, match=MCP_AUTH_ERROR):
        await require_mcp_api_key(object(), SecretStr(_STDIO_KEY))  # type: ignore[arg-type]


async def test_tool_call_without_any_credential_rejects(
    verifier: type[_RecordingVerifier],
) -> None:
    verifier.answer = _principal()

    assert tool_credential(_stdio_ctx(), stdio_key=None) is None
    with pytest.raises(McpAuthenticationError, match="authentication is required"):
        await require_mcp_api_key(object(), None)  # type: ignore[arg-type]

    assert verifier.seen == []


async def test_tool_call_with_bad_stdio_credential_rejects(
    verifier: type[_RecordingVerifier],
) -> None:
    credential = tool_credential(_stdio_ctx(), stdio_key=SecretStr("bad-token"))

    with pytest.raises(McpAuthenticationError, match=MCP_AUTH_ERROR):
        await require_mcp_api_key(object(), credential)  # type: ignore[arg-type]

    assert verifier.seen == ["bad-token"]


async def test_tool_call_with_live_stdio_credential_serves(
    verifier: type[_RecordingVerifier],
) -> None:
    principal = _principal()
    verifier.answer = principal

    credential = tool_credential(None, stdio_key=SecretStr(_STDIO_KEY))
    result = await require_mcp_api_key(object(), credential)  # type: ignore[arg-type]

    assert result == principal
    assert verifier.seen == [_STDIO_KEY]


async def test_tool_call_with_matching_http_subject_serves(
    verifier: type[_RecordingVerifier],
) -> None:
    principal = _principal()
    verifier.answer = principal
    ctx = _http_ctx([(b"authorization", f"Bearer {_HTTP_KEY}".encode())])

    credential = tool_credential(ctx, stdio_key=SecretStr(_STDIO_KEY))
    result = await require_mcp_api_key(object(), credential)  # type: ignore[arg-type]

    # The HTTP call uses its own header; the process key is never consulted.
    assert result == principal
    assert verifier.seen == [_HTTP_KEY]


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"authorization", b"Token abc")],
        [(b"authorization", b"Bearer one"), (b"authorization", b"Bearer two")],
        [(b"authorization", b"Bearer ")],
    ],
)
def test_tool_call_with_foreign_http_subject_rejects(headers: list[tuple[bytes, bytes]]) -> None:
    """An HTTP call without its own single Bearer key never falls back to the stdio key."""

    assert tool_credential(_http_ctx(headers), stdio_key=SecretStr(_STDIO_KEY)) is None


async def test_optional_tool_identity_allows_anonymous_and_verifies_stdio_token(
    verifier: type[_RecordingVerifier],
) -> None:
    """A1 replacement: there is no anonymous tool identity; a verifier crash fails closed."""

    assert not hasattr(mcp_auth, "optional_mcp_user")
    assert not hasattr(mcp_auth, "require_mcp_user")
    assert not hasattr(mcp_auth, "LocalTokenVerifier")
    verifier.error = RuntimeError(f"storage failure {_STDIO_KEY}")

    with pytest.raises(McpAuthenticationError) as raised:
        await require_mcp_api_key(object(), SecretStr(_STDIO_KEY))  # type: ignore[arg-type]

    assert str(raised.value) == MCP_AUTH_ERROR
    assert _STDIO_KEY not in str(raised.value)


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


def test_http_app_exposes_public_transport_without_sdk_auth() -> None:
    """The HTTP guard accepts project API keys on /mcp only, never a human JWT."""

    server = create_server([])
    app = build_http_app(
        server,
        auth_service=_StubService(),  # type: ignore[arg-type]
        settings=test_settings(),
    )
    assert app.routes
    assert server.settings.auth is None
    guards = [m for m in app.user_middleware if m.cls is BearerAuthMiddleware]
    assert len(guards) == 1
    options = guards[0].kwargs
    assert options["verify_token"] is None
    assert options["api_key_routes"] == MCP_ROUTES
    assert options["public_routes"] == frozenset()


async def test_stdio_runner_allows_anonymous_tools_without_process_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1: the stdio runner owns only the store lifecycle; tools verify each call."""

    server = create_server([])
    service = _StubService()

    async def run() -> None:
        return None

    monkeypatch.setattr(server, "run_stdio_async", run)
    await run_stdio_server(
        server,
        auth_service=service,  # type: ignore[arg-type]
        settings=test_settings(),
    )

    assert service.opened
    assert service.closed
