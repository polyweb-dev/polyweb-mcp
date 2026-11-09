"""P04 AC2: concurrent two-project MCP calls keep project/actor ownership.

Two project API keys (A1: MCP authenticates only with project keys), each
bound to exactly one project, issue concurrent single-path search, fanout
search, and fetch tool calls on real FastMCP servers backed by one temp
database and fake adapters. Every persisted span row and usage row must carry
the key's project and the key itself as the actor.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr

from polyweb.adapters.base import ProviderAdapter
from polyweb.mcp.server import _encrypted_store, create_server
from polyweb.models.contracts import (
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
from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ActorType, ExecutionAttribution
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.a2_execution import _seed_credential
from tests.fixtures.api_keys import issue_project_key
from tests.fixtures.auth import auth_service_for


class _StubAdapter(ProviderAdapter):
    """Fake provider; ``fail_query`` makes one fanout child fail on demand."""

    def __init__(self, name: str, *, fail_query: str | None = None) -> None:
        self._name = name
        self._fail_query = fail_query

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail_query is not None and self._fail_query in request.query:
            raise RuntimeError(f"{self._name} offline failure")
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url=f"https://example.com/{self._name}",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url, content="stub content", fetched_at=datetime.now(UTC)
            ),
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.FETCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> object:
    repo = await SQLiteRepository.open(tmp_path / "mcp-trace-attr.db")
    yield repo
    await repo.close()


async def test_concurrent_two_project_tool_calls_keep_full_ownership(
    repository: SQLiteRepository, auth_secret: str, monkeypatch: object
) -> None:
    adapters = [_StubAdapter("exa"), _StubAdapter("brave", fail_query="fail-me")]
    key_a = await issue_project_key(repository, prefix="mcp-alice")
    key_b = await issue_project_key(repository, prefix="mcp-bob")
    service_a = auth_service_for(repository)
    service_b = auth_service_for(repository)
    token_a, token_b = key_a.key, key_b.key
    pid_a, pid_b = str(key_a.project_id), str(key_b.project_id)
    store = _encrypted_store(repository)
    by_secret = {}
    for key in (key_a, key_b):
        # Credentials are created by the human project owner; execution must
        # still attribute every row to the verified project key, not the owner.
        owner = ExecutionAttribution(
            project_id=key.project_id, actor_type=ActorType.HUMAN, actor_id=key.owner.id
        )
        for provider in ("exa", "brave"):
            secret = f"fake-{key.project_id}-{provider}"
            await _seed_credential(
                repository,
                store,
                owner,
                provider=provider,
                label=provider,
                secret=secret,
                operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
                priority=0,
            )
            by_secret[secret] = _StubAdapter(
                provider, fail_query="fail-me" if provider == "brave" else None
            )

    import polyweb.services.execution as execution_module

    def adapter_factory(name: str):
        if name not in {"exa", "brave"}:
            return None

        def build(client, api_key=None):
            assert api_key is not None
            adapter = by_secret[api_key.get_secret_value()]
            assert adapter.name == name
            return adapter

        return build

    monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)

    server_a = create_server(
        adapters,
        repository=repository,
        auth_service=service_a,
        stdio_token=SecretStr(token_a.get_secret_value()),
    )
    server_b = create_server(
        adapters,
        repository=repository,
        auth_service=service_b,
        stdio_token=SecretStr(token_b.get_secret_value()),
    )

    await asyncio.gather(
        server_a.call_tool("search", {"request": {"project_id": pid_a, "query": "a-1"}}),
        server_a.call_tool("search", {"request": {"project_id": pid_a, "query": "a-2"}}),
        server_a.call_tool(
            "search", {"request": {"project_id": pid_a, "query": "a-fanout", "fanout": True}}
        ),
        server_a.call_tool(
            "fetch", {"request": {"project_id": pid_a, "url": "https://example.com/a"}}
        ),
        server_b.call_tool("search", {"request": {"project_id": pid_b, "query": "b-1"}}),
        server_b.call_tool("search", {"request": {"project_id": pid_b, "query": "b-2"}}),
        server_b.call_tool(
            "search",
            {"request": {"project_id": pid_b, "query": "b-fanout fail-me", "fanout": True}},
        ),
        server_b.call_tool(
            "fetch", {"request": {"project_id": pid_b, "url": "https://example.com/b"}}
        ),
    )

    con = sqlite3.connect(repository.database_path)
    spans = con.execute(
        "SELECT trace_id, parent_span_id, name, project_id, actor_type, actor_id FROM trace_spans"
    ).fetchall()
    usage = con.execute(
        "SELECT trace_id, project_id, actor_type, actor_id, provider, status FROM usage_events"
    ).fetchall()
    con.close()

    # Every persisted span row, root and child, is owned by one principal's
    # project — and the actor is that principal.
    assert spans, "no trace rows persisted"
    by_trace: dict[str, list[tuple]] = {}
    for row in spans:
        by_trace.setdefault(row[0], []).append(row)

    per_project: dict[str, int] = {pid_a: 0, pid_b: 0}
    for trace_id, rows in by_trace.items():
        projects = {row[3] for row in rows}
        assert len(projects) == 1, f"trace {trace_id} mixes projects: {projects}"
        project_id = next(iter(projects))
        expected_actor = str(key_a.api_key_id) if project_id == pid_a else str(key_b.api_key_id)
        per_project[project_id] += 1
        for row in rows:
            assert row[4] == "project_api_key"
            assert row[5] == expected_actor, f"trace {trace_id} actor mismatch: {row[5]}"
        roots = [row for row in rows if row[1] is None]
        assert len(roots) == 1
    # Four calls each: single, single, fanout, fetch.
    assert per_project == {pid_a: 4, pid_b: 4}

    # Usage rows carry the caller's project/actor and a trace owned by it.
    trace_project = {t: next(iter({row[3] for row in rows})) for t, rows in by_trace.items()}
    assert usage, "no usage rows persisted"
    for trace_id, project_id, actor_type, actor_id, _provider, _status in usage:
        assert trace_id in trace_project, f"usage row points at unknown trace {trace_id}"
        assert project_id == trace_project[trace_id]
        assert actor_type == "project_api_key"
        expected_actor = str(key_a.api_key_id) if project_id == pid_a else str(key_b.api_key_id)
        assert actor_id == expected_actor

    # The failing fanout run wrote one failure row plus a sibling success row
    # under the same trace — both owned by B.
    failure_rows = [row for row in usage if row[5] == "failure"]
    assert failure_rows, "the failing fanout provider produced no failure row"
    for row in failure_rows:
        assert row[1] == pid_b
        siblings = [u for u in usage if u[0] == row[0] and u[5] == "success"]
        assert siblings, "no sibling usage row shares the failed fanout trace"

    # Two providers per fanout call: each fanout trace carries rows for both.
    per_trace_providers: dict[str, set[str]] = {}
    for row in usage:
        per_trace_providers.setdefault(row[0], set()).add(row[4])
    fanout_rows = {
        t
        for t, providers in per_trace_providers.items()
        if "brave" in providers and "exa" in providers
    }
    assert len(fanout_rows) == 2
