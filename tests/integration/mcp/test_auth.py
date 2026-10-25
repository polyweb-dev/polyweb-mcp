"""MCP transport guard contracts on real HTTP and direct calls (P4, T3/T4/T13).

Every test uses an isolated database and stub adapters. Tests cover anonymous
Search/Fetch, optional verified account context, and guarded unknown paths. A
rejected tool call reaches no provider.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.auth import (
    MCP_AUTH_ERROR,
    build_http_app,
    run_stdio_server,
)
from freesearch.mcp.server import create_server
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    http_jwt_service,
    mcp_account_token,
    raw_auth_headers,
    register_and_login,
    temp_email,
    test_settings,
)
from tests.fixtures.execution import seed_execution_project, seed_token_project


class _RecordingAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
        self._name = name
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="stub result",
                    url="https://example.com/stub",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url, content="stub content", fetched_at=datetime.now(UTC)
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "mcp-auth.db")
    yield repo
    await repo.close()


def _http_factory(app: Any, port: int | None) -> Any:
    """Build an httpx factory that routes the SDK client into one ASGI app.

    The base URL carries the configured port, so the Host header satisfies
    the SDK rebinding check for loopback hosts.
    """

    base_url = f"http://localhost:{port or 8000}"

    def _factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "transport": httpx.ASGITransport(app=app),
            "base_url": base_url,
        }
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return _factory, base_url


def _tool_payload(result: Any) -> dict[str, Any]:
    """Unwrap one SDK session tool result to its JSON dict."""

    assert result.isError is not True
    return json.loads(result.content[0].text)


def _direct_payload(result: Any) -> dict[str, Any]:
    """Unwrap one direct ``call_tool`` tuple to its result dict."""

    assert isinstance(result, tuple)
    assert isinstance(result[1], dict)
    return result[1]


async def _authed_direct(
    repository: SQLiteRepository, adapter: _RecordingAdapter, prefix: str
) -> tuple[FastMCP, SecretStr, str, str]:
    service, token, email = await mcp_account_token(repository, prefix)
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    pid = str((await seed_token_project(repository, token)).project_id)
    return server, token, email, pid


async def test_same_jwt_permits_rest_and_direct_tool_calls(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("mcp-same"))
        headers = raw_auth_headers(pair["access_token"])
        pid = str(
            (
                await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            ).project_id
        )
        rest = client.post(
            "/search", json={"project_id": pid, "query": "same jwt"}, headers=headers
        )
        assert rest.status_code == 200

    server = create_server(
        [adapter],
        repository=repository,
        auth_service=http_jwt_service(repository),
        stdio_token=SecretStr(pair["access_token"]),
    )
    payload = _direct_payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "same jwt"}})
    )
    assert payload["provider"] == "stubby"


async def test_mcp_http_session_rejects_anonymous_search_and_fetch(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    service = http_jwt_service(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    http_app = build_http_app(server, auth_service=service, settings=service.settings)
    async with http_app.router.lifespan_context(http_app):
        factory, base_url = _http_factory(http_app, service.settings.mcp_port)
        async with (
            streamablehttp_client(f"{base_url}/mcp", httpx_client_factory=factory) as (
                read,
                write,
                session_id,
            ),
            ClientSession(read, write) as session,
        ):
            assert session_id is not None
            await session.initialize()
            search = await session.call_tool(
                "search",
                {
                    "request": {
                        "project_id": "00000000-0000-4000-8000-0000000000aa",
                        "query": "http probe",
                    }
                },
            )
            fetch = await session.call_tool(
                "fetch",
                {
                    "request": {
                        "project_id": "00000000-0000-4000-8000-0000000000aa",
                        "url": "https://example.com/http",
                    }
                },
            )
    assert search.isError is True
    assert fetch.isError is True
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


async def test_mcp_http_keeps_invalid_bearer_and_unknown_paths_guarded(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    service = http_jwt_service(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    http_app = build_http_app(server, auth_service=service, settings=service.settings)
    transport = httpx.ASGITransport(app=http_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        invalid = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer invalid-token"},
            json={"jsonrpc": "2.0", "id": 1},
        )
        assert invalid.status_code == 401
        assert invalid.headers["www-authenticate"] == "Bearer"

        unknown = await client.get("/no-such-route")
        assert unknown.status_code == 401

    with TestClient(create_app([adapter], repository=repository)) as rest:
        pair = register_and_login(rest, temp_email("mcp-meta"))
        headers = raw_auth_headers(pair["access_token"])
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.get("/no-such-route", headers=headers)).status_code == 404
        assert (
            await client.get("/.well-known/oauth-protected-resource/mcp", headers=headers)
        ).status_code == 404


async def test_mcp_port_holds_no_public_auth_exception(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    service = http_jwt_service(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    http_app = build_http_app(server, auth_service=service, settings=service.settings)
    transport = httpx.ASGITransport(app=http_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        register = await client.post(
            "/auth/register", json={"email": "mcp-public@example.com", "password": "x"}
        )
        assert register.status_code == 401
        assert register.headers["www-authenticate"] == "Bearer"

        login = await client.post(
            "/auth/jwt/login", data={"username": "mcp-public@example.com", "password": "x"}
        )
        assert login.status_code == 401
        assert login.headers["www-authenticate"] == "Bearer"

    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


async def test_bad_tool_credential_causes_no_provider_call(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    service = http_jwt_service(repository)
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr("not-a-token"),
    )
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": "00000000-0000-4000-8000-0000000000aa", "query": "quiet"}},
        )

    assert adapter.search_calls == 0


async def test_refresh_credential_cannot_serve_tools(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("mcp-refresh"))
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=http_jwt_service(repository),
        stdio_token=SecretStr(pair["refresh_token"]),
    )
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": "00000000-0000-4000-8000-0000000000aa", "query": "quiet"}},
        )

    assert adapter.search_calls == 0


async def test_stateful_session_rechecks_family_after_logout(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    rest_app = create_app([adapter], repository=repository)
    with TestClient(rest_app) as client:
        pair = register_and_login(client, temp_email("mcp-stateful"))
        headers = raw_auth_headers(pair["access_token"])
        pid = str(
            (
                await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            ).project_id
        )

    service = http_jwt_service(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    http_app = build_http_app(server, auth_service=service, settings=service.settings)
    base_url = f"http://localhost:{service.settings.mcp_port or 8000}"
    async with http_app.router.lifespan_context(http_app):
        factory, _ = _http_factory(http_app, service.settings.mcp_port)
        async with (
            streamablehttp_client(
                f"{base_url}/mcp",
                headers=headers,
                httpx_client_factory=factory,
            ) as (read, write, get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            first = _tool_payload(
                await session.call_tool(
                    "search", {"request": {"project_id": pid, "query": "before logout"}}
                )
            )
            assert first["provider"] == "stubby"
            session_id = get_session_id()
            assert session_id

        with TestClient(rest_app) as client:
            assert client.post("/auth/jwt/logout", headers=headers).status_code == 204

        transport = httpx.ASGITransport(app=http_app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as raw:
            stale = await raw.post(
                "/mcp",
                headers={**headers, "mcp-session-id": session_id},
                json={
                    "jsonrpc": "2.0",
                    "id": "stale-1",
                    "method": "tools/call",
                    "params": {"name": "search", "arguments": {"request": {"query": "x"}}},
                },
            )
            assert stale.status_code == 401
            assert stale.headers["www-authenticate"] == "Bearer"


async def test_deactivated_account_loses_tool_access_at_once(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, _token, email, pid = await _authed_direct(repository, adapter, "mcp-cutoff")
    payload = _direct_payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "before"}})
    )
    assert payload["provider"] == "stubby"

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        account = await database.get_by_email(email)
        assert account is not None
        account.is_active = False
        await session.commit()

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": "00000000-0000-4000-8000-0000000000aa", "query": "after"}},
        )

    assert adapter.search_calls == 1


async def test_stdio_absent_credential_rejects_before_provider_call(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    service, _token, _email = await mcp_account_token(repository, "mcp-naked")
    server = create_server([adapter], repository=repository, auth_service=service)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {
                "request": {
                    "project_id": "00000000-0000-4000-8000-0000000000aa",
                    "query": "anonymous stdio",
                }
            },
        )
    assert adapter.search_calls == 0


async def test_stdio_handoff_serves_with_explicit_process_token(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, _token, _email, pid = await _authed_direct(repository, adapter, "mcp-stdio")

    payload = _direct_payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "stdio handoff"}})
    )
    assert payload["provider"] == "stubby"
    assert adapter.search_calls == 1


async def test_stdio_expired_credential_causes_no_provider_call(
    repository: SQLiteRepository,
) -> None:
    import jwt as pyjwt

    adapter = _RecordingAdapter("stubby")
    service, token, _email = await mcp_account_token(repository, "mcp-stale")
    live = pyjwt.decode(token.get_secret_value(), options={"verify_signature": False})
    now = datetime.now(UTC)
    stale = pyjwt.encode(
        {
            "sub": live["sub"],
            "aud": ["freesearch:auth"],
            "sid": live["sid"],
            "iat": int((now - timedelta(seconds=100)).timestamp()),
            "exp": int((now - timedelta(seconds=10)).timestamp()),
        },
        service.settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(stale),
    )
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": "00000000-0000-4000-8000-0000000000aa", "query": "quiet"}},
        )

    assert adapter.search_calls == 0


async def test_stdio_revoked_family_causes_no_provider_call(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    service, token, _email = await mcp_account_token(repository, "mcp-revoked")
    pid = str((await seed_token_project(repository, token)).project_id)
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    assert _direct_payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "before"}})
    )

    principal = await service.verify_token(token.get_secret_value())
    assert principal is not None
    await service.logout(principal)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": "00000000-0000-4000-8000-0000000000aa", "query": "after"}},
        )

    assert adapter.search_calls == 1


async def test_run_stdio_server_allows_anonymous_tools_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "stdio-guard.db"
    from freesearch.services.users import AuthService

    service = AuthService(test_settings(), database=database)
    server = create_server([])

    async def run() -> None:
        return None

    monkeypatch.setattr(server, "run_stdio_async", run)
    await run_stdio_server(server, auth_service=service, settings=test_settings())

    assert database.exists()


def test_main_stdio_dispatch_reads_process_token(
    monkeypatch: pytest.MonkeyPatch, auth_secret: str, tmp_path: Path
) -> None:
    import freesearch.mcp.server as server_module
    from freesearch.mcp.server import main

    monkeypatch.setenv("FREESEARCH_MCP_BEARER_TOKEN", "process-token-value")
    calls: list[tuple[str, bool]] = []

    async def fake_stdio(server: object, *, auth_service: object, settings: object) -> None:
        token = getattr(settings, "mcp_bearer_token", None)
        calls.append(
            ("stdio", token is not None and token.get_secret_value() == "process-token-value")
        )

    monkeypatch.setattr(server_module, "run_stdio_server", fake_stdio)
    main(["--transport", "stdio"])

    assert calls == [("stdio", True)]


async def test_admin_tool_role_keeps_search_access(repository: SQLiteRepository) -> None:
    adapter = _RecordingAdapter("stubby")
    service, token, _email = await mcp_account_token(repository, "mcp-admin", role=UserRole.ADMIN)
    pid = str((await seed_token_project(repository, token)).project_id)
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    payload = _direct_payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "admin tool"}})
    )
    assert payload["provider"] == "stubby"
