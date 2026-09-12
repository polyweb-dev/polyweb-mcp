"""Stage 4 MCP server smoke tests: routing and tool shapes without network.

Drives the real FastMCP server with fake adapters so no provider keys or HTTP
calls are needed. ``build_adapters`` itself is covered indirectly: it fails
closed to an empty list without keys, which the no-provider guard surfaces.
"""

from datetime import UTC, datetime

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.secrets import ProviderName
from freesearch.mcp.server import _ADAPTERS, build_adapters, close_adapters, create_server
from freesearch.models.contracts import (
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


def test_adapters_registry_covers_all_providers() -> None:
    assert set(_ADAPTERS.keys()) == set(ProviderName)


async def test_close_adapters_cleans_up() -> None:
    closed: list[str] = []

    class _ClosingStub(_StubAdapter):
        async def aclose(self) -> None:
            closed.append(self.name)

    client = httpx.AsyncClient()
    await close_adapters([_ClosingStub("a"), _ClosingStub("b")], client)
    assert closed == ["a", "b"]
    assert client.is_closed


async def test_build_adapters_includes_keyless_keenable() -> None:
    client = httpx.AsyncClient()
    try:
        adapters = build_adapters(client)
        names = [adapter.name for adapter in adapters]
        assert "keenable" in names
    finally:
        await client.aclose()


async def test_server_lifespan_cleans_up() -> None:
    closed: list[str] = []

    class _ClosingStub(_StubAdapter):
        async def aclose(self) -> None:
            closed.append(self.name)

    server = create_server([_ClosingStub("test_provider")])
    async with server._mcp_server.lifespan(server):
        pass
    assert closed == ["test_provider"]


def test_create_server_stateless_http_flag() -> None:
    server_default = create_server([])
    assert server_default.settings.stateless_http is False

    server_stateless = create_server([], stateless_http=True)
    assert server_stateless.settings.stateless_http is True


def test_main_cli_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from freesearch.mcp.server import main

    invocations: list[tuple[str, bool, str, int]] = []

    def fake_run(self: object, transport: str = "stdio") -> None:
        settings = getattr(self, "settings", None)
        invocations.append((
            transport,
            getattr(settings, "stateless_http", False),
            getattr(settings, "host", ""),
            getattr(settings, "port", 0),
        ))

    from mcp.server.fastmcp import FastMCP
    monkeypatch.setattr(FastMCP, "run", fake_run)

    # 1. Test stdio dispatch
    main(["--transport", "stdio"])
    assert invocations[-1][0] == "stdio"

    # 2. Test streamable-http with stateless flag and custom port
    main(["--transport", "streamable-http", "--stateless", "--port", "8888"])
    assert invocations[-1] == ("streamable-http", True, "127.0.0.1", 8888)

