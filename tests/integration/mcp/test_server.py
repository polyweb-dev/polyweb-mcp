"""Stage 4 MCP server smoke tests: routing and tool shapes without network.

Drives the real FastMCP server with fake adapters so no provider keys or HTTP
calls are needed. ``build_adapters`` itself is covered indirectly: it fails
closed to an empty list without keys, which the no-provider guard surfaces.
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

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
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.auth import mcp_account_token


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


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "mcp-server.db")
    yield repo
    await repo.close()


async def _authed_server(
    repository: SQLiteRepository, adapters: list[ProviderAdapter], prefix: str
) -> FastMCP:
    """Build one tool server with a real account and its explicit stdio credential."""

    service, token, _email = await mcp_account_token(repository, prefix)
    return create_server(
        adapters,
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )


async def test_search_routes_to_only_search_adapter(repository: SQLiteRepository) -> None:
    server = await _authed_server(repository, [_StubAdapter("brave", fetch=False)], "tool-search")
    response = await server.call_tool("search", {"request": {"query": "python asyncio"}})
    assert response[1]["provider"] == "brave"
    assert response[1]["query"] == "python asyncio"


async def test_fetch_routes_to_fetch_capable_adapter(repository: SQLiteRepository) -> None:
    server = await _authed_server(repository, [_StubAdapter("youcom")], "tool-fetch")
    response = await server.call_tool("fetch", {"request": {"url": "https://example.com/page"}})
    assert response[1]["provider"] == "youcom"
    assert response[1]["document"]["content"] == "youcom content"


async def test_search_without_any_adapter_raises(repository: SQLiteRepository) -> None:
    server = await _authed_server(repository, [], "tool-empty")
    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("search", {"request": {"query": "anything"}})


async def test_search_fanout_runs_multiple_adapters_and_fuses(
    repository: SQLiteRepository,
) -> None:
    server = await _authed_server(
        repository,
        [_StubAdapter("brave", fetch=False), _StubAdapter("exa", fetch=False)],
        "tool-fanout",
    )
    response = await server.call_tool("search", {"request": {"query": "python", "fanout": True}})
    data = response[1]
    assert data["provider"] == "aggregated"
    assert set(data["participating_providers"]) == {"brave", "exa"}
    assert (
        len(data["results"]) == 1
    )  # Both returned "https://example.com/r" so canonical deduplication fused them
    assert set(data["results"][0]["sources"]) == {"brave", "exa"}


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


async def test_build_adapters_skips_failing_factory_keeps_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from freesearch.adapters import registry as _reg

    monkeypatch.setitem(
        _reg._ADAPTERS, ProviderName.EXA, lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    client = httpx.AsyncClient()
    try:
        with caplog.at_level("WARNING"):
            names = [adapter.name for adapter in build_adapters(client)]
    finally:
        await client.aclose()
    assert "exa" not in names and "keenable" in names


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


def test_main_cli_dispatch(monkeypatch: pytest.MonkeyPatch, auth_secret: str) -> None:
    import freesearch.mcp.server as server_module
    from freesearch.mcp.server import main

    calls: list[tuple[str, bool, int | None]] = []

    async def fake_stdio(server: object, *, auth_service: object, settings: object) -> None:
        port = getattr(settings, "mcp_port", None)
        calls.append(("stdio", auth_service is not None, port))

    async def fake_http(server: object, *, auth_service: object, settings: object) -> None:
        port = getattr(settings, "mcp_port", None)
        calls.append(("streamable-http", auth_service is not None, port))

    monkeypatch.setattr(server_module, "run_stdio_server", fake_stdio)
    monkeypatch.setattr(server_module, "run_http_server", fake_http)

    # 1. Test stdio dispatch
    main(["--transport", "stdio"])
    assert calls[-1][0] == "stdio"
    assert calls[-1][1] is True

    # 2. Test streamable-http with stateless flag and custom port
    main(["--transport", "streamable-http", "--stateless", "--port", "8888"])
    assert calls[-1] == ("streamable-http", True, 8888)
