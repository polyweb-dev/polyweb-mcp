"""MCP trace identity and owner visibility on direct calls (P5, T5, T11).

Every test uses an isolated database and stub adapters with explicit stdio
credentials. Each authenticated tool call writes one SERVER root with the
exact account UUID. A rejected call writes no root. Each account lists only
its own MCP traces through the repository owner reads.
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

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.auth import MCP_AUTH_ERROR
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
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.auth import mcp_account_token
from tests.fixtures.execution import seed_token_project


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
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


async def _authed_server(
    repository: SQLiteRepository, adapters: list[ProviderAdapter], prefix: str
) -> tuple[FastMCP, UUID, str]:
    service, token, _email = await mcp_account_token(repository, prefix)
    principal = await service.verify_token(token.get_secret_value())
    assert principal is not None
    server = create_server(
        adapters,
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    pid = str((await seed_token_project(repository, token)).project_id)
    return server, UUID(str(principal.id)), pid


async def test_mcp_search_and_fetch_roots_carry_the_exact_account_uuid(
    repository: SQLiteRepository,
) -> None:
    server, owner, pid = await _authed_server(repository, [_StubAdapter("stubby")], "mcp-trace-id")

    await server.call_tool("search", {"request": {"project_id": pid, "query": "mcp owned"}})
    await server.call_tool(
        "fetch", {"request": {"project_id": pid, "url": "https://example.com/mcp"}}
    )

    items = await repository.list_trace_summaries(user_id=owner)
    assert len(items) == 2
    assert all(item.user_id == str(owner) for item in items)
    assert {item.operation for item in items} == {"search", "fetch"}

    for item in items:
        detail = await repository.get_trace(item.trace_id, user_id=owner)
        assert detail is not None
        assert detail.user_id == str(owner)
        root = detail.spans[0]
        assert root.parent_span_id is None
        assert root.name in ("mcp search", "mcp fetch")


async def test_mcp_fanout_keeps_one_root_with_the_account_uuid(
    repository: SQLiteRepository,
) -> None:
    server, owner, pid = await _authed_server(
        repository, [_StubAdapter("alpha"), _StubAdapter("beta")], "mcp-trace-fanout"
    )

    result = await server.call_tool(
        "search", {"request": {"project_id": pid, "query": "fanout", "fanout": True}}
    )
    assert result[1]["provider"] == "aggregated"

    items = await repository.list_trace_summaries(user_id=owner)
    assert len(items) == 1
    assert items[0].user_id == str(owner)


async def test_rejected_tool_call_writes_no_trace_root(repository: SQLiteRepository) -> None:
    service, _token, _email = await mcp_account_token(repository, "mcp-quiet")
    server = create_server([_StubAdapter("stubby")], repository=repository, auth_service=service)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {
                "request": {
                    "project_id": "00000000-0000-4000-8000-0000000000aa",
                    "query": "quiet",
                }
            },
        )

    service2, token2, _email2 = await mcp_account_token(repository, "mcp-quiet-two")
    principal = await service2.verify_token(token2.get_secret_value())
    assert principal is not None
    assert await repository.list_trace_summaries(user_id=str(principal.id)) == []


async def test_each_account_lists_only_its_own_mcp_traces(
    repository: SQLiteRepository,
) -> None:
    server_a, owner_a, pid_a = await _authed_server(
        repository, [_StubAdapter("stubby")], "mcp-alice"
    )
    server_b, owner_b, pid_b = await _authed_server(repository, [_StubAdapter("stubby")], "mcp-bob")
    assert owner_a != owner_b

    await server_a.call_tool("search", {"request": {"project_id": pid_a, "query": "alice"}})
    await server_b.call_tool("search", {"request": {"project_id": pid_b, "query": "bob"}})

    items_a = await repository.list_trace_summaries(user_id=owner_a)
    items_b = await repository.list_trace_summaries(user_id=owner_b)
    assert len(items_a) == 1
    assert len(items_b) == 1
    assert items_a[0].user_id == str(owner_a)
    assert items_b[0].user_id == str(owner_b)
    assert await repository.get_trace(items_a[0].trace_id, user_id=owner_b) is None
    assert await repository.get_trace(items_b[0].trace_id, user_id=owner_a) is None
