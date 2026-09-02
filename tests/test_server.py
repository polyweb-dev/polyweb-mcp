"""Stage 4 MCP server smoke tests: routing and tool shapes without network.

Drives the real FastMCP server with fake adapters so no provider keys or HTTP
calls are needed. ``build_adapters`` itself is covered indirectly: it fails
closed to an empty list without keys, which the no-provider guard surfaces.
"""

from datetime import UTC, datetime

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)
from freesearch.server import create_server


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=fetch, cost_estimate=True)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/r",
                    snippet="snippet",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
            currency="queries",
        )

    async def health(self) -> None:
        pass

    async def quota(self) -> None:
        pass


async def test_search_routes_to_only_search_adapter() -> None:
    server = create_server([_StubAdapter("brave", fetch=False)])
    response = await server.call_tool("search", {"request": {"query": "python asyncio"}})
    assert response[1]["provider"] == "brave"
    assert response[1]["query"] == "python asyncio"


async def test_fetch_routes_to_fetch_capable_adapter() -> None:
    server = create_server([_StubAdapter("youcom")])
    response = await server.call_tool("fetch", {"request": {"url": "https://example.com/page"}})
    assert response[1]["provider"] == "youcom"
    assert response[1]["document"]["content"] == "youcom content"


async def test_search_without_any_adapter_raises() -> None:
    server = create_server([])
    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("search", {"request": {"query": "anything"}})
