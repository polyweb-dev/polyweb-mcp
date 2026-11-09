"""MCP trace identity and owner visibility on direct calls (P5 T5/T11, A1).

Every test uses an isolated database and stub adapters with an explicit stdio
project API key. A1 replaced human-JWT MCP access with project keys, so the
trace identity is now the key's project and the key itself as actor, and no
human account id is ever stamped on an MCP root. A rejected call writes no
root. Each key's traces stay inside its own project.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from polyweb.adapters.base import ProviderAdapter
from polyweb.mcp.auth import MCP_AUTH_ERROR
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
    def __init__(self, name: str = "exa") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
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
    repo = await SQLiteRepository.open(tmp_path / "mcp-traces.db")
    yield repo
    await repo.close()


def _rows(repository: SQLiteRepository) -> list[tuple[object, ...]]:
    import sqlite3

    con = sqlite3.connect(repository.database_path)
    try:
        return con.execute(
            "SELECT trace_id, parent_span_id, name, user_id, project_id, actor_type, actor_id,"
            " operation FROM trace_spans"
        ).fetchall()
    finally:
        con.close()


def _roots(repository: SQLiteRepository) -> list[tuple[object, ...]]:
    return [row for row in _rows(repository) if row[1] is None]


@pytest.fixture
def adapter_keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, ProviderAdapter]:
    import polyweb.services.execution as execution_module

    adapters: dict[str, ProviderAdapter] = {}

    def factory(name: str):
        if name not in {"exa", "brave"}:
            return None

        def build(client, api_key=None):
            assert api_key is not None
            adapter = adapters[api_key.get_secret_value()]
            assert adapter.name == name
            return adapter

        return build

    monkeypatch.setattr(execution_module, "adapter_factory", factory)
    return adapters


async def _authed_server(
    repository: SQLiteRepository,
    adapters: list[ProviderAdapter],
    prefix: str,
    adapter_keys: dict[str, ProviderAdapter],
) -> tuple[FastMCP, UUID, str]:
    key = await issue_project_key(repository, prefix=prefix)
    server = create_server(
        adapters,
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key.raw),
    )
    owner = ExecutionAttribution(
        project_id=key.project_id, actor_type=ActorType.HUMAN, actor_id=key.owner.id
    )
    store = _encrypted_store(repository)
    for adapter in adapters:
        secret = f"fake-{key.project_id}-{adapter.name}"
        await _seed_credential(
            repository,
            store,
            owner,
            provider=adapter.name,
            label=adapter.name,
            secret=secret,
            operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
            priority=0,
        )
        adapter_keys[secret] = adapter
    return server, key.api_key_id, str(key.project_id)


async def test_mcp_search_and_fetch_roots_carry_the_exact_account_uuid(
    repository: SQLiteRepository,
    adapter_keys: dict[str, ProviderAdapter],
) -> None:
    """Each tool call writes one root owned by the key's project and the key as actor."""

    server, key_id, pid = await _authed_server(
        repository, [_StubAdapter("exa")], "mcp-trace-id", adapter_keys
    )

    await server.call_tool("search", {"request": {"project_id": pid, "query": "mcp owned"}})
    await server.call_tool(
        "fetch", {"request": {"project_id": pid, "url": "https://example.com/mcp"}}
    )

    # Stash origin: exercise scoped list/detail reads as well as raw attribution.
    items = await repository.list_project_trace_summaries(project_id=UUID(pid))
    assert len(items) == 2
    assert {item.operation for item in items} == {"search", "fetch"}
    assert all(item.user_id is None for item in items)
    for item in items:
        detail = await repository.get_project_trace(item.trace_id, project_id=UUID(pid))
        assert detail is not None and detail.user_id is None
        detail_roots = [span for span in detail.spans if span.parent_span_id is None]
        assert len(detail_roots) == 1
        assert detail_roots[0].name in ("mcp search", "mcp fetch")
        assert detail_roots[0].parent_span_id is None
    roots = _roots(repository)
    assert len(roots) == 2
    assert {row[2] for row in roots} == {"mcp search", "mcp fetch"}
    for row in _rows(repository):
        assert row[4] == pid
        assert row[5] == "project_api_key"
        assert row[6] == str(key_id)
        # No human identity is forged onto a machine call.
        assert row[3] is None


async def test_mcp_fanout_keeps_one_root_with_the_account_uuid(
    repository: SQLiteRepository,
    adapter_keys: dict[str, ProviderAdapter],
) -> None:
    server, key_id, pid = await _authed_server(
        repository, [_StubAdapter("exa"), _StubAdapter("brave")], "mcp-trace-fanout", adapter_keys
    )

    result = await server.call_tool(
        "search", {"request": {"project_id": pid, "query": "fanout", "fanout": True}}
    )
    assert result[1]["provider"] == "aggregated"

    items = await repository.list_project_trace_summaries(project_id=UUID(pid))
    assert len(items) == 1 and items[0].user_id is None
    roots = _roots(repository)
    assert len(roots) == 1
    assert {row[0] for row in _rows(repository)} == {roots[0][0]}
    assert {(row[4], row[5], row[6]) for row in _rows(repository)} == {
        (pid, "project_api_key", str(key_id))
    }


async def test_rejected_tool_call_writes_no_trace_root(repository: SQLiteRepository) -> None:
    key = await issue_project_key(repository, prefix="mcp-quiet")
    service = auth_service_for(repository)
    # No process credential at all: the call must fail before any root opens.
    server = create_server([_StubAdapter("exa")], repository=repository, auth_service=service)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": str(key.project_id), "query": "quiet"}},
        )

    # A malformed process credential is rejected the same way.
    forged = create_server(
        [_StubAdapter("exa")],
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(key.raw[:-1] + ("A" if key.raw[-1] != "A" else "B")),
    )
    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await forged.call_tool(
            "search",
            {"request": {"project_id": str(key.project_id), "query": "quiet"}},
        )

    assert _rows(repository) == []
    assert await repository.list_project_trace_summaries(project_id=key.project_id) == []


async def test_each_account_lists_only_its_own_mcp_traces(
    repository: SQLiteRepository,
    adapter_keys: dict[str, ProviderAdapter],
) -> None:
    server_a, key_a, pid_a = await _authed_server(
        repository, [_StubAdapter("exa")], "mcp-alice", adapter_keys
    )
    server_b, key_b, pid_b = await _authed_server(
        repository, [_StubAdapter("exa")], "mcp-bob", adapter_keys
    )
    assert key_a != key_b
    assert pid_a != pid_b

    await server_a.call_tool("search", {"request": {"project_id": pid_a, "query": "alice"}})
    await server_b.call_tool("search", {"request": {"project_id": pid_b, "query": "bob"}})

    by_project: dict[object, set[object]] = {}
    for row in _rows(repository):
        by_project.setdefault(row[4], set()).add(row[6])
    assert by_project == {pid_a: {str(key_a)}, pid_b: {str(key_b)}}
    items_a = await repository.list_project_trace_summaries(project_id=UUID(pid_a))
    items_b = await repository.list_project_trace_summaries(project_id=UUID(pid_b))
    assert len(items_a) == len(items_b) == 1
    assert items_a[0].user_id is items_b[0].user_id is None
    assert await repository.get_project_trace(items_a[0].trace_id, project_id=UUID(pid_b)) is None
    assert await repository.get_project_trace(items_b[0].trace_id, project_id=UUID(pid_a)) is None
    assert (
        await repository.get_project_trace(items_a[0].trace_id, project_id=UUID(pid_a)) is not None
    )
    assert (
        await repository.get_project_trace(items_b[0].trace_id, project_id=UUID(pid_b)) is not None
    )
    # A key naming the other key's project is refused before execution.
    with pytest.raises(ToolError, match="project is unavailable"):
        await server_a.call_tool("search", {"request": {"project_id": pid_b, "query": "steal"}})
    assert len(_roots(repository)) == 2
