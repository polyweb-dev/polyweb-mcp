"""MCP transport credential contracts on real HTTP and direct calls (P4, A1).

Every test uses an isolated database and stub adapters with call counters.
A1 (TASK-000041) made project API keys the only MCP credential: there is no
anonymous tool call and no human-JWT MCP access. Every rejected call, on the
HTTP transport, over stdio, and on every call of a persistent HTTP session,
must leave the provider call counters unchanged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
from freesearch.models.projects import BuiltinRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.api_keys import ApiKeyService
from freesearch.services.projects import ProjectService
from tests.fixtures.api_keys import (
    ProjectKey,
    archive_project,
    audit_rows,
    expire_key,
    issue_project_key,
)
from tests.fixtures.auth import (
    auth_service_for,
    grant_system_admin,
    http_jwt_service,
    raw_auth_headers,
    register_and_login,
    temp_email,
    temp_principal,
    test_settings,
)
from tests.fixtures.execution import seed_execution_user

_UNUSED_PROJECT = "00000000-0000-4000-8000-0000000000aa"


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
    repository: SQLiteRepository,
    adapter: _RecordingAdapter,
    prefix: str,
    *,
    scopes: set[str] | None = None,
) -> tuple[FastMCP, ProjectKey, str]:
    """A direct (stdio-style) server whose process credential is one project key."""

    key = await issue_project_key(repository, prefix=prefix, scopes=scopes)
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key.raw),
    )
    return server, key, str(key.project_id)


def _search(pid: str, query: str = "probe") -> dict[str, Any]:
    return {"request": {"project_id": pid, "query": query}}


def _fetch(pid: str) -> dict[str, Any]:
    return {"request": {"project_id": pid, "url": "https://example.com/probe"}}


@asynccontextmanager
async def _http_app(
    repository: SQLiteRepository, adapter: _RecordingAdapter
) -> AsyncIterator[tuple[Any, str]]:
    service = auth_service_for(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    http_app = build_http_app(server, auth_service=service, settings=service.settings)
    async with http_app.router.lifespan_context(http_app):
        _factory, base_url = _http_factory(http_app, service.settings.mcp_port)
        yield http_app, base_url


async def _raw_tool_call(
    http_app: Any,
    base_url: str,
    *,
    headers: dict[str, str],
    session_id: str,
    name: str,
    arguments: dict[str, Any],
) -> httpx.Response:
    transport = httpx.ASGITransport(app=http_app)
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as raw:
        return await raw.post(
            "/mcp",
            headers={
                **headers,
                "mcp-session-id": session_id,
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": "second-call",
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )


# --- direct (stdio process credential) ---------------------------------------


async def test_same_jwt_permits_rest_and_direct_tool_calls(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """A1 replacement: one project key serves REST and MCP; a human JWT serves neither MCP."""

    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="mcp-same")
    pid = str(key.project_id)
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        rest = client.post(
            "/search", json=_search(pid, "same key")["request"], headers=key.headers()
        )
        assert rest.status_code == 200
        pair = register_and_login(client, temp_email("mcp-human"))

    server = create_server(
        [adapter],
        repository=repository,
        auth_service=http_jwt_service(repository),
        stdio_token=key.key,
    )
    payload = _direct_payload(await server.call_tool("search", _search(pid, "same key")))
    assert payload["provider"] == "stubby"
    assert adapter.search_calls == 2

    human = create_server(
        [adapter],
        repository=repository,
        auth_service=http_jwt_service(repository),
        stdio_token=SecretStr(pair["access_token"]),
    )
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await human.call_tool("search", _search(pid))
    assert adapter.search_calls == 2


async def test_bad_tool_credential_causes_no_provider_call(repository: SQLiteRepository) -> None:
    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="mcp-bad")
    for bad in (
        "not-a-token",
        "fs_live_",
        "fs_live_" + "a" * 12 + "_" + "b" * 42,
        key.raw.upper(),
        key.raw + "x",
        " " + key.raw,
    ):
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(bad),
        )
        with pytest.raises(ToolError) as raised:
            await server.call_tool("search", _search(str(key.project_id)))
        assert str(raised.value).endswith(MCP_AUTH_ERROR)
        assert key.raw not in str(raised.value)

    assert adapter.search_calls == 0


async def test_refresh_credential_cannot_serve_tools(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """Neither human credential (refresh or access) is an MCP credential."""

    adapter = _RecordingAdapter("stubby")
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("mcp-refresh"))
    for credential in (pair["refresh_token"], pair["access_token"]):
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=http_jwt_service(repository),
            stdio_token=SecretStr(credential),
        )
        with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
            await server.call_tool("search", _search(_UNUSED_PROJECT))

    assert adapter.search_calls == 0


async def test_deactivated_account_loses_tool_access_at_once(
    repository: SQLiteRepository,
) -> None:
    """A1 replacement: a revoked key loses direct tool access on the very next call."""

    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(repository, adapter, "mcp-cutoff")
    assert _direct_payload(await server.call_tool("search", _search(pid, "before")))

    await ApiKeyService(repository).revoke(key.owner, key.project_id, key.api_key_id)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool("search", _search(pid, "after"))
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool("fetch", _fetch(pid))
    assert adapter.search_calls == 1
    assert adapter.fetch_calls == 0


async def test_stdio_absent_credential_rejects_before_provider_call(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="mcp-naked")
    server = create_server(
        [adapter], repository=repository, auth_service=auth_service_for(repository)
    )

    for tool, args in (
        ("search", _search(str(key.project_id))),
        ("fetch", _fetch(str(key.project_id))),
    ):
        with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
            await server.call_tool(tool, args)
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


async def test_stdio_handoff_serves_with_explicit_process_token(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, _key, pid = await _authed_direct(repository, adapter, "mcp-stdio")

    payload = _direct_payload(await server.call_tool("search", _search(pid, "stdio handoff")))
    assert payload["provider"] == "stubby"
    assert adapter.search_calls == 1


async def test_stdio_omitted_project_uses_the_key_project(repository: SQLiteRepository) -> None:
    adapter = _RecordingAdapter("stubby")
    server, _key, _pid = await _authed_direct(repository, adapter, "mcp-omit")

    payload = _direct_payload(await server.call_tool("search", {"request": {"query": "no pid"}}))
    assert payload["provider"] == "stubby"
    assert adapter.search_calls == 1


async def test_stdio_expired_credential_causes_no_provider_call(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(repository, adapter, "mcp-stale")
    assert _direct_payload(await server.call_tool("search", _search(pid)))

    await expire_key(repository, key)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool("search", _search(pid))
    assert adapter.search_calls == 1


async def test_stdio_revoked_family_causes_no_provider_call(
    repository: SQLiteRepository,
) -> None:
    """A1 replacement: rotation with overlap 0 revokes the old process key at once."""

    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(repository, adapter, "mcp-revoked")
    assert _direct_payload(await server.call_tool("search", _search(pid, "before")))

    from freesearch.models.projects import ProjectApiKeyRotate

    rotated = await ApiKeyService(repository).rotate(
        key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate(overlap_seconds=0)
    )

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool("search", _search(pid, "after"))
    assert adapter.search_calls == 1

    replacement = create_server(
        [adapter],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=rotated.key,
    )
    assert _direct_payload(await replacement.call_tool("search", _search(pid, "rotated")))
    assert adapter.search_calls == 2


async def test_stdio_wrong_project_and_archived_project_fail_before_provider(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(repository, adapter, "mcp-scope")
    other = await issue_project_key(repository, prefix="mcp-other")

    with pytest.raises(ToolError, match="project is unavailable"):
        await server.call_tool("search", _search(str(other.project_id)))
    with pytest.raises(ToolError, match="project is unavailable"):
        await server.call_tool("fetch", _fetch(str(other.project_id)))

    await archive_project(repository, key.project_id)
    with pytest.raises(ToolError, match="project is archived"):
        await server.call_tool("search", _search(pid))
    with pytest.raises(ToolError, match="project is archived"):
        await server.call_tool("search", {"request": {"query": "omitted pid"}})

    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0
    denied = await audit_rows(repository, scope="system", action="api_key.authorization_denied")
    reasons = sorted(row["detail_json"]["reason"] for row in denied)
    # R3: at most one event per (key, reason) per window, written off-path.
    assert reasons == ["project_archived", "wrong_project"]
    assert {row["actor_id"] for row in denied} == {str(key.api_key_id)}


async def test_stdio_tampered_secret_with_valid_prefix_is_denied_and_recorded(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="mcp-tamper")
    last = key.raw[-1]
    tampered = key.raw[:-1] + ("A" if last != "A" else "B")
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(tampered),
    )

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool("search", _search(str(key.project_id)))

    assert adapter.search_calls == 0
    events = await audit_rows(repository, scope="system", action="api_key.authentication_denied")
    assert len(events) == 1
    assert events[0]["category"] == "security"
    assert events[0]["outcome"] == "denied"
    assert events[0]["actor_type"] == "project_api_key"
    assert events[0]["actor_id"] == str(key.api_key_id)
    assert events[0]["target_id"] == key.prefix
    assert events[0]["detail_json"] == {"reason": "invalid_secret"}
    assert tampered[len("fs_live_") + 13 :] not in json.dumps(events, default=str)


async def test_run_stdio_server_allows_anonymous_tools_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stdio runner owns only the store lifecycle; each tool call verifies a key."""

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
    monkeypatch.setenv("FREESEARCH_DB", str(tmp_path / "main-stdio.db"))
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
    """A1 replacement: a key holds exactly its scopes, whatever its creator holds later."""

    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(
        repository, adapter, "mcp-scoped", scopes={"search.execute"}
    )
    # The creator gains system authority after issuing the key.
    await grant_system_admin(repository, key.owner.id)

    assert _direct_payload(await server.call_tool("search", _search(pid, "scoped")))
    with pytest.raises(ToolError, match="execution is not permitted"):
        await server.call_tool("fetch", _fetch(pid))
    assert adapter.search_calls == 1
    assert adapter.fetch_calls == 0
    denied = await audit_rows(repository, scope="system", action="api_key.authorization_denied")
    assert [row["detail_json"]["reason"] for row in denied] == ["wrong_scope"]


async def test_creator_demotion_and_removal_neither_kill_nor_widen_the_key(
    repository: SQLiteRepository,
) -> None:
    adapter = _RecordingAdapter("stubby")
    server, key, pid = await _authed_direct(
        repository, adapter, "mcp-creator", scopes={"search.execute"}
    )
    successor = temp_principal(await seed_execution_user(repository, "mcp-successor"))
    projects = ProjectService(repository)
    from freesearch.models.projects import ProjectMemberAdd

    await projects.add_member(
        key.owner,
        key.project_id,
        ProjectMemberAdd(user_id=successor.id, initial_role=BuiltinRole.PROJECT_ADMIN.value),
    )
    await projects.remove_role(
        successor, key.project_id, key.owner.id, BuiltinRole.PROJECT_ADMIN.value
    )
    assert _direct_payload(await server.call_tool("search", _search(pid, "after demotion")))

    await projects.remove_member(successor, key.project_id, key.owner.id)
    assert _direct_payload(await server.call_tool("search", _search(pid, "after removal")))
    with pytest.raises(ToolError, match="execution is not permitted"):
        await server.call_tool("fetch", _fetch(pid))
    assert adapter.search_calls == 2
    assert adapter.fetch_calls == 0


# --- Streamable HTTP ---------------------------------------------------------


async def test_mcp_http_session_rejects_anonymous_search_and_fetch(
    repository: SQLiteRepository,
) -> None:
    """No credential, a human JWT or a malformed key cannot even open the transport."""

    adapter = _RecordingAdapter("stubby")
    async with _http_app(repository, adapter) as (http_app, base_url):
        transport = httpx.ASGITransport(app=http_app)
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "1"},
            },
        }
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            for headers in (
                {},
                {"Authorization": "Bearer not-a-key"},
                {"Authorization": "Bearer fs_live_short"},
            ):
                rejected = await client.post(
                    "/mcp",
                    headers={**headers, "accept": "application/json, text/event-stream"},
                    json=initialize,
                )
                assert rejected.status_code == 401
                assert rejected.headers["www-authenticate"] == "Bearer"
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


async def test_mcp_http_keeps_invalid_bearer_and_unknown_paths_guarded(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="mcp-paths")
    with TestClient(create_app([adapter], repository=repository)) as rest:
        pair = register_and_login(rest, temp_email("mcp-meta"))
    async with _http_app(repository, adapter) as (http_app, base_url):
        transport = httpx.ASGITransport(app=http_app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            invalid = await client.post(
                "/mcp",
                headers={"Authorization": "Bearer invalid-token"},
                json={"jsonrpc": "2.0", "id": 1},
            )
            assert invalid.status_code == 401
            assert invalid.headers["www-authenticate"] == "Bearer"

            human = await client.post(
                "/mcp",
                headers=raw_auth_headers(pair["access_token"]),
                json={"jsonrpc": "2.0", "id": 1},
            )
            assert human.status_code == 401

            assert (await client.get("/no-such-route")).status_code == 401
            for headers in (raw_auth_headers(pair["access_token"]), key.headers()):
                assert (await client.get("/no-such-route", headers=headers)).status_code == 401
                assert (
                    await client.get("/.well-known/oauth-protected-resource/mcp", headers=headers)
                ).status_code == 401
    assert adapter.search_calls == 0


async def test_mcp_port_holds_no_public_auth_exception(repository: SQLiteRepository) -> None:
    adapter = _RecordingAdapter("stubby")
    async with _http_app(repository, adapter) as (http_app, base_url):
        transport = httpx.ASGITransport(app=http_app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
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


_SECOND_CALL_CASES = ["revoked", "expired", "archived", "wrong_project", "foreign_key_header"]


@pytest.mark.parametrize("change", _SECOND_CALL_CASES)
async def test_stateful_session_rechecks_family_after_logout(
    repository: SQLiteRepository, change: str
) -> None:
    """A1/AC6: every call of one persistent session re-verifies the key.

    The first call succeeds. After the change, a second call in the SAME
    session (same ``mcp-session-id``) fails and reaches no provider.
    """

    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix=f"mcp-session-{change}")
    other = await issue_project_key(repository, prefix=f"mcp-session-other-{change}")
    pid = str(key.project_id)
    async with _http_app(repository, adapter) as (http_app, base_url):
        factory, _ = _http_factory(http_app, None)
        factory, _ = _http_factory(http_app, int(base_url.rsplit(":", 1)[1]))
        async with (
            streamablehttp_client(
                f"{base_url}/mcp", headers=key.headers(), httpx_client_factory=factory
            ) as (read, write, get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            first = _tool_payload(await session.call_tool("search", _search(pid, "first")))
            assert first["provider"] == "stubby"
            session_id = get_session_id()
            assert session_id

            headers = key.headers()
            arguments = _search(pid, "second")
            if change == "revoked":
                await ApiKeyService(repository).revoke(key.owner, key.project_id, key.api_key_id)
            elif change == "expired":
                await expire_key(repository, key)
            elif change == "archived":
                await archive_project(repository, key.project_id)
            elif change == "wrong_project":
                arguments = _search(str(other.project_id), "second")
            else:
                # Another project's valid key presented on this session's id
                # must never execute in this session's project.
                headers = other.headers()

            second = await _raw_tool_call(
                http_app,
                base_url,
                headers=headers,
                session_id=session_id,
                name="search",
                arguments=arguments,
            )
            if change in {"revoked", "expired"}:
                assert second.status_code == 401
                assert second.headers["www-authenticate"] == "Bearer"
            else:
                assert second.status_code == 200, second.text
                assert '"isError":true' in second.text.replace(" ", "")
                expected = {
                    "archived": "project is archived",
                    "wrong_project": "project is unavailable",
                    "foreign_key_header": "project is unavailable",
                }[change]
                assert expected in second.text
            assert key.raw not in second.text
            assert other.raw not in second.text

    assert adapter.search_calls == 1
    assert adapter.fetch_calls == 0


# --- R4: MCP HTTP verifies the key once per request, at the guard ---------------


class _InjectPrincipal:
    """ASGI wrapper that publishes a fixed principal on every request scope."""

    def __init__(self, app: Any, principal: object) -> None:
        self.app = app
        self.principal = principal

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and self.principal is not None:
            scope.setdefault("state", {})["user"] = self.principal
        await self.app(scope, receive, send)


@asynccontextmanager
async def _unguarded_app(
    repository: SQLiteRepository, adapter: _RecordingAdapter, principal: object
) -> AsyncIterator[tuple[Any, str]]:
    """The SDK transport without the key guard, optionally injecting a principal."""

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Mount

    server = create_server(
        [adapter], repository=repository, auth_service=auth_service_for(repository)
    )
    inner = server.streamable_http_app()
    app = Starlette(
        routes=[Mount("/", app=inner)],
        middleware=[Middleware(_InjectPrincipal, principal=principal)],
        lifespan=lambda _app: inner.router.lifespan_context(inner),
    )
    async with app.router.lifespan_context(app):
        _factory, base_url = _http_factory(app, None)
        yield app, base_url


async def _one_session_call(
    app: Any, base_url: str, headers: dict[str, str], arguments: dict[str, Any]
) -> Any:
    factory, _ = _http_factory(app, int(base_url.rsplit(":", 1)[1]))
    async with (
        streamablehttp_client(f"{base_url}/mcp", headers=headers, httpx_client_factory=factory) as (
            read,
            write,
            _session_id,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool("search", arguments)


async def test_http_tool_call_does_not_verify_the_key_a_second_time(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every ApiKeyVerifier run over HTTP is a guard run; the tool adds none."""

    import freesearch.mcp.auth as mcp_auth_module
    from freesearch.services.api_keys import ApiKeyVerifier

    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix="r4-once")
    verifies: list[int] = []
    guard_runs: list[int] = []
    tool_verifies: list[int] = []
    original_verify = ApiKeyVerifier.verify
    original_guard = mcp_auth_module._verify_guard_key
    original_require = mcp_auth_module.require_mcp_api_key

    async def _spy_verify(self: ApiKeyVerifier, credential: Any) -> Any:
        verifies.append(1)
        return await original_verify(self, credential)

    async def _spy_guard(service: Any, token: str) -> Any:
        guard_runs.append(1)
        return await original_guard(service, token)

    async def _spy_require(repository: Any, credential: Any) -> Any:
        tool_verifies.append(1)
        return await original_require(repository, credential)

    monkeypatch.setattr(ApiKeyVerifier, "verify", _spy_verify)
    monkeypatch.setattr(mcp_auth_module, "_verify_guard_key", _spy_guard)
    monkeypatch.setattr(mcp_auth_module, "require_mcp_api_key", _spy_require)
    async with _http_app(repository, adapter) as (http_app, base_url):
        factory, _ = _http_factory(http_app, int(base_url.rsplit(":", 1)[1]))
        async with (
            streamablehttp_client(
                f"{base_url}/mcp", headers=key.headers(), httpx_client_factory=factory
            ) as (read, write, _session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            first = _tool_payload(await session.call_tool("search", _search(str(key.project_id))))
            second = _tool_payload(await session.call_tool("search", _search(str(key.project_id))))
    assert first["provider"] == second["provider"] == "stubby"
    assert adapter.search_calls == 2
    assert guard_runs, "the guard never verified the key"
    # No verification outside the guard: the tool used the guard's principal.
    assert len(verifies) == len(guard_runs), (len(verifies), len(guard_runs))
    assert tool_verifies == []


@pytest.mark.parametrize("injected", ["none", "human", "revoked_key"])
async def test_http_tool_call_without_a_guard_key_principal_is_rejected(
    repository: SQLiteRepository, injected: str
) -> None:
    """A valid key header alone never authenticates a tool call; only the guard does."""

    from uuid import uuid4

    from freesearch.models.projects import ProjectApiKeyPrincipal
    from freesearch.models.users import UserPrincipal

    adapter = _RecordingAdapter("stubby")
    key = await issue_project_key(repository, prefix=f"r4-{injected}")
    principal: object = None
    if injected == "human":
        principal = UserPrincipal(
            id=key.owner.id,
            email=key.owner.email,
            session_id=uuid4(),
            is_active=True,
            is_verified=False,
        )
    elif injected == "revoked_key":
        await ApiKeyService(repository).revoke(key.owner, key.project_id, key.api_key_id)
        principal = ProjectApiKeyPrincipal(
            api_key_id=key.api_key_id,
            project_id=key.project_id,
            scopes=frozenset({"search.execute", "fetch.execute"}),
        )
    async with _unguarded_app(repository, adapter, principal) as (app, base_url):
        result = await _one_session_call(app, base_url, key.headers(), _search(str(key.project_id)))
        if injected == "human":
            human_only = await _one_session_call(
                app,
                base_url,
                {},
                _search(str(key.project_id)),
            )
            assert human_only.isError is True
    assert result.isError is True
    text = json.dumps([item.model_dump() for item in result.content])
    assert "authentication is required" in text
    assert key.raw not in text
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0
