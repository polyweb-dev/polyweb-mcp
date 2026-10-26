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
from tests.fixtures.api_keys import issue_project_key
from tests.fixtures.auth import auth_service_for


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


async def _authed_server(
    repository: SQLiteRepository, adapters: list[ProviderAdapter], prefix: str
) -> tuple[FastMCP, UUID, str]:
    key = await issue_project_key(repository, prefix=prefix)
    server = create_server(
        adapters,
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(key.raw),
    )
    return server, key.api_key_id, str(key.project_id)


async def test_mcp_search_and_fetch_roots_carry_the_exact_account_uuid(
    repository: SQLiteRepository,
) -> None:
    """Each tool call writes one root owned by the key's project and the key as actor."""

    server, key_id, pid = await _authed_server(repository, [_StubAdapter("stubby")], "mcp-trace-id")

    await server.call_tool("search", {"request": {"project_id": pid, "query": "mcp owned"}})
    await server.call_tool(
        "fetch", {"request": {"project_id": pid, "url": "https://example.com/mcp"}}
    )

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
) -> None:
    server, key_id, pid = await _authed_server(
        repository, [_StubAdapter("alpha"), _StubAdapter("beta")], "mcp-trace-fanout"
    )

    result = await server.call_tool(
        "search", {"request": {"project_id": pid, "query": "fanout", "fanout": True}}
    )
    assert result[1]["provider"] == "aggregated"

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
    server = create_server([_StubAdapter("stubby")], repository=repository, auth_service=service)

    with pytest.raises(ToolError, match=MCP_AUTH_ERROR):
        await server.call_tool(
            "search",
            {"request": {"project_id": str(key.project_id), "query": "quiet"}},
        )

    # A malformed process credential is rejected the same way.
    forged = create_server(
        [_StubAdapter("stubby")],
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


async def test_each_account_lists_only_its_own_mcp_traces(
    repository: SQLiteRepository,
) -> None:
    server_a, key_a, pid_a = await _authed_server(repository, [_StubAdapter("stubby")], "mcp-alice")
    server_b, key_b, pid_b = await _authed_server(repository, [_StubAdapter("stubby")], "mcp-bob")
    assert key_a != key_b
    assert pid_a != pid_b

    await server_a.call_tool("search", {"request": {"project_id": pid_a, "query": "alice"}})
    await server_b.call_tool("search", {"request": {"project_id": pid_b, "query": "bob"}})

    by_project: dict[object, set[object]] = {}
    for row in _rows(repository):
        by_project.setdefault(row[4], set()).add(row[6])
    assert by_project == {pid_a: {str(key_a)}, pid_b: {str(key_b)}}
    # A key naming the other key's project is refused before execution.
    with pytest.raises(ToolError, match="project is unavailable"):
        await server_a.call_tool("search", {"request": {"project_id": pid_b, "query": "steal"}})
    assert len(_roots(repository)) == 2
