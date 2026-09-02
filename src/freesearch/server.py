"""Stage 4 composition root: bind the shared contracts to a runnable MCP server.

Builds the enabled, key-configured adapters in priority order and exposes the
two provider-neutral tools (``search``, ``fetch``) over MCP (streamable HTTP on
loopback:8000), routing each request through
:func:`freesearch.routing.select_route`.
"""

from collections.abc import Callable, Sequence
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.contracts import FetchRequest, SearchRequest
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_configs
from freesearch.routing import select_route
from freesearch.secrets import ProviderName

_ADAPTERS: dict[ProviderName, Callable[[httpx.AsyncClient], ProviderAdapter]] = {
    ProviderName.BRAVE: BraveAdapter,
    ProviderName.EXA: ExaAdapter,
    ProviderName.TAVILY: TavilyAdapter,
    ProviderName.YOU: YoucomAdapter,
}


def build_adapters() -> list[ProviderAdapter]:
    """Return enabled adapters with a resolvable key, in configured priority order.

    Each adapter resolves its own credential through the shared resolver at
    construction; providers without a key (or disabled by configuration) are
    skipped so the server runs with whatever keys are present.
    """

    client = create_async_client()
    adapters: list[ProviderAdapter] = []
    for name, record in sorted(
        get_provider_configs().items(), key=lambda item: (item[1].priority, item[0].value)
    ):
        adapter_cls = _ADAPTERS.get(name)
        if adapter_cls is None or not record.enabled:
            continue
        try:
            adapters.append(adapter_cls(client))
        except Exception:
            continue  # provider without a configured key fails closed at construction
    return adapters


def create_server(adapters: Sequence[ProviderAdapter] | None = None) -> FastMCP:
    """Create the MCP server, routing every tool call to a configured adapter."""

    server = FastMCP("freesearch")
    routes = list(adapters) if adapters is not None else build_adapters()

    def _route(request: SearchRequest | FetchRequest) -> ProviderAdapter:
        if not routes:
            raise RuntimeError("no provider is configured: set a FREESEARCH_*_API_KEY")
        return select_route(request, routes, {}, {})[0].adapter

    @server.tool()
    async def search(request: SearchRequest) -> dict[str, Any]:
        """Search the web through the best available provider."""
        response = await _route(request).search(request)
        return response.model_dump(mode="json")

    @server.tool()
    async def fetch(request: FetchRequest) -> dict[str, Any]:
        """Fetch a URL's content through the best available provider."""
        response = await _route(request).fetch(request)
        return response.model_dump(mode="json")

    return server


def main() -> None:
    """Run the MCP server over HTTP (streamable-http on loopback:8000)."""
    create_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
