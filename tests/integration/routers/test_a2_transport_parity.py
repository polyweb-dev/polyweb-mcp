"""A2 AC1/AC2: REST, MCP stdio and MCP HTTP share one execution and one attribution.

One project with two bound credentials is executed over all three transports
with the same request. The provider decision (binding and credential) must be
identical, and every usage row and trace span (root, child and fanout child)
must carry the verified project and the verified actor: the human account
over REST, the project API key over MCP. Caller-supplied identity in headers,
trace context or baggage never changes ownership and never grafts spans onto
another project's trace.

Fake adapters only; every database is temporary.
"""

from __future__ import annotations

import json
import secrets as stdlib_secrets
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from polyweb.configuration.config import get_settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.mcp.auth import build_http_app
from polyweb.mcp.server import create_server
from polyweb.models.credentials import CredentialOperation
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.a2_execution import RecordingAdapter, _seed_credential
from tests.fixtures.api_keys import ProjectKey, issue_project_key, key_for_account
from tests.fixtures.auth import TEMP_PASSWORD, auth_service_for, temp_email
from tests.fixtures.execution import account_id_from_headers, seed_member_project

_PROVIDERS = ("exa", "brave")


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "a2-parity.db")
    try:
        yield repo
    finally:
        await repo.close()


class _AdapterBook:
    """Routes execution's per-credential adapter construction to recording fakes."""

    def __init__(self) -> None:
        self.by_secret: dict[str, RecordingAdapter] = {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import polyweb.services.execution as execution_module

        def adapter_factory(name: str) -> Any:
            if name not in _PROVIDERS:
                return None

            def build(client: Any, api_key: Any = None) -> RecordingAdapter:
                del client
                assert api_key is not None
                adapter = self.by_secret[api_key.get_secret_value()]
                assert adapter.name == name
                return adapter

            return build

        monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)


async def _bind_project(
    repository: SQLiteRepository,
    store: EncryptedDbSecretStore,
    book: _AdapterBook,
    *,
    project_id: UUID,
    owner_id: UUID,
) -> dict[str, RecordingAdapter]:
    """Bind one private credential per provider; return provider -> its adapter."""

    from polyweb.models.observability import ActorType, ExecutionAttribution

    owner = ExecutionAttribution(
        project_id=project_id, actor_type=ActorType.HUMAN, actor_id=owner_id
    )
    adapters: dict[str, RecordingAdapter] = {}
    for priority, provider in enumerate(_PROVIDERS):
        secret = f"fake-{provider}-{uuid4().hex[:12]}"
        await _seed_credential(
            repository,
            store,
            owner,
            provider=provider,
            label=provider,
            secret=secret,
            operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
            priority=priority,
        )
        adapters[provider] = RecordingAdapter(provider)
        book.by_secret[secret] = adapters[provider]
    return adapters


async def _register(client: httpx.AsyncClient, prefix: str) -> dict[str, str]:
    email = temp_email(prefix)
    registered = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": TEMP_PASSWORD,
            "username": f"tester-{uuid4().hex[:8]}",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


def _http_factory(app: Any, base_url: str) -> Any:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"transport": httpx.ASGITransport(app=app), "base_url": base_url}
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        if auth is not None:
            kwargs["auth"] = auth
        return httpx.AsyncClient(**kwargs)

    return factory


def _rows(database: Path, sql: str) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(database)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _usage(database: Path) -> list[tuple[Any, ...]]:
    return _rows(
        database,
        "SELECT id, trace_id, project_id, actor_type, actor_id, provider, binding_id,"
        " credential_id FROM usage_events WHERE provider != 'aggregated' ORDER BY id",
    )


def _spans(database: Path, trace_ids: set[str]) -> list[tuple[Any, ...]]:
    rows = _rows(
        database,
        "SELECT trace_id, parent_span_id, name, project_id, actor_type, actor_id FROM trace_spans",
    )
    return [row for row in rows if row[0] in trace_ids]


async def test_rest_and_mcp_stdio_and_http_share_decisions_and_verified_attribution(
    repository: SQLiteRepository, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = repository.database_path
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    book = _AdapterBook()
    book.install(monkeypatch)
    # Project B: an unrelated tenant with its own key, bindings and a real trace.
    key_b = await issue_project_key(repository, prefix="parity-b")
    adapters_b = await _bind_project(
        repository, store, book, project_id=key_b.project_id, owner_id=key_b.owner.id
    )
    server_b = create_server(
        list(adapters_b.values()),
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key_b.raw),
    )
    await server_b.call_tool(
        "search", {"request": {"project_id": str(key_b.project_id), "query": "b-own"}}
    )
    b_traces = {row[1] for row in _usage(database)}
    assert len(b_traces) == 1
    b_trace = next(iter(b_traces))

    app = create_app([RecordingAdapter("exa")], repository=repository, secret_store=store)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await _register(client, "parity-a")
            human_id = account_id_from_headers(headers)
            project = await seed_member_project(repository, headers)
            pid = str(project.project_id)
            adapters_a = await _bind_project(
                repository, store, book, project_id=project.project_id, owner_id=human_id
            )
            key_a: ProjectKey = await key_for_account(repository, human_id, project.project_id)
            span_id = stdlib_secrets.token_hex(8)
            forged_headers = {
                **headers,
                # Graft attempt onto project B's trace and forged ownership claims.
                "traceparent": f"00-{b_trace}-{span_id}-01",
                "baggage": (
                    f"project_id={key_b.project_id},actor_id={key_b.api_key_id},"
                    "actor_type=project_api_key"
                ),
                "x-project-id": str(key_b.project_id),
                "x-actor-id": str(key_b.api_key_id),
                "x-actor-type": "project_api_key",
            }
            transcripts: dict[str, list[tuple[Any, ...]]] = {}

            before = {row[0] for row in _usage(database)}
            single = await client.post(
                "/search", json={"project_id": pid, "query": "parity"}, headers=forged_headers
            )
            assert single.status_code == 200, single.text
            fanout = await client.post(
                "/search",
                json={"project_id": pid, "query": "parity-fanout", "fanout": True},
                headers=forged_headers,
            )
            assert fanout.status_code == 200, fanout.text
            transcripts["rest"] = [row for row in _usage(database) if row[0] not in before]
            rest_provider = single.json()["provider"]

    stdio = create_server(
        [RecordingAdapter("exa")],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key_a.raw),
    )
    before = {row[0] for row in _usage(database)}
    stdio_single = await stdio.call_tool(
        "search", {"request": {"project_id": pid, "query": "parity"}}
    )
    await stdio.call_tool(
        "search", {"request": {"project_id": pid, "query": "parity-fanout", "fanout": True}}
    )
    transcripts["stdio"] = [row for row in _usage(database) if row[0] not in before]

    service = auth_service_for(repository)
    http_server = create_server(
        [RecordingAdapter("exa")], repository=repository, auth_service=service
    )
    http_app = build_http_app(http_server, auth_service=service, settings=service.settings)
    before = {row[0] for row in _usage(database)}
    async with http_app.router.lifespan_context(http_app):
        base_url = f"http://localhost:{service.settings.mcp_port or 8000}"
        async with (
            streamablehttp_client(
                f"{base_url}/mcp",
                headers=key_a.headers(),
                httpx_client_factory=_http_factory(http_app, base_url),
            ) as (read, write, _session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            http_single = await session.call_tool(
                "search", {"request": {"project_id": pid, "query": "parity"}}
            )
            assert http_single.isError is not True
            http_fanout = await session.call_tool(
                "search", {"request": {"project_id": pid, "query": "parity-fanout", "fanout": True}}
            )
            assert http_fanout.isError is not True
    transcripts["http"] = [row for row in _usage(database) if row[0] not in before]

    # AC1: one provider decision for the same request on every transport.
    http_provider = json.loads(http_single.content[0].text)["provider"]
    assert rest_provider == stdio_single[1]["provider"] == http_provider
    decisions = {
        name: sorted((row[5], row[6], row[7]) for row in rows) for name, rows in transcripts.items()
    }
    assert decisions["rest"] == decisions["stdio"] == decisions["http"], decisions
    # single (1 leg) + fanout (2 legs) per transport.
    assert all(len(rows) == 3 for rows in transcripts.values()), transcripts
    bound = {row[6] for rows in transcripts.values() for row in rows}
    assert len(bound) == 2, "the fanout did not run across both bound credentials"

    # AC2: ownership is the verified principal of each transport.
    expected = {
        "rest": (pid, "human", str(human_id)),
        "stdio": (pid, "project_api_key", str(key_a.api_key_id)),
        "http": (pid, "project_api_key", str(key_a.api_key_id)),
    }
    for name, rows in transcripts.items():
        assert {(row[2], row[3], row[4]) for row in rows} == {expected[name]}, name
        traces = {row[1] for row in rows}
        assert b_trace not in traces, f"{name} execution grafted onto project B's trace"
        spans = _spans(database, traces)
        assert spans, f"{name} wrote no spans"
        assert {(row[3], row[4], row[5]) for row in spans} == {expected[name]}, name
        roots = [row for row in spans if row[1] is None]
        assert len(roots) == len(traces) == 2, (name, roots)
        children = [row for row in spans if row[1] is not None and row[2] == "polyweb.provider"]
        assert len(children) == 3, (name, children)

    # Project B's trace keeps exactly B's ownership; nothing else lands in it.
    b_spans = _spans(database, {b_trace})
    assert {(row[3], row[4], row[5]) for row in b_spans} == {
        (str(key_b.project_id), "project_api_key", str(key_b.api_key_id))
    }
    assert sum(adapter.search_calls for adapter in adapters_b.values()) == 1
    assert sum(adapter.search_calls for adapter in adapters_a.values()) == 9


async def test_mcp_key_naming_another_project_reaches_no_provider_over_both_mcp_transports(
    repository: SQLiteRepository, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    book = _AdapterBook()
    book.install(monkeypatch)
    key_a = await issue_project_key(repository, prefix="cross-a")
    key_b = await issue_project_key(repository, prefix="cross-b")
    adapters_a = await _bind_project(
        repository, store, book, project_id=key_a.project_id, owner_id=key_a.owner.id
    )
    adapters_b = await _bind_project(
        repository, store, book, project_id=key_b.project_id, owner_id=key_b.owner.id
    )
    stolen = {"request": {"project_id": str(key_b.project_id), "query": "steal"}}

    stdio = create_server(
        [RecordingAdapter("exa")],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key_a.raw),
    )
    with pytest.raises(ToolError):
        await stdio.call_tool("search", stolen)

    service = auth_service_for(repository)
    http_server = create_server(
        [RecordingAdapter("exa")], repository=repository, auth_service=service
    )
    http_app = build_http_app(http_server, auth_service=service, settings=service.settings)
    async with http_app.router.lifespan_context(http_app):
        base_url = f"http://localhost:{service.settings.mcp_port or 8000}"
        async with (
            streamablehttp_client(
                f"{base_url}/mcp",
                headers=key_a.headers(),
                httpx_client_factory=_http_factory(http_app, base_url),
            ) as (read, write, _session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("search", stolen)
            assert result.isError is True

    usage = _usage(repository.database_path)
    assert sum(adapter.search_calls for adapter in adapters_a.values()) == 0
    assert sum(adapter.search_calls for adapter in adapters_b.values()) == 0
    assert usage == []
