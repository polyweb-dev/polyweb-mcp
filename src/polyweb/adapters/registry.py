"""Provider constructors for credential-scoped execution and resource cleanup.

Execution resolves A4 credential material before asking adapter_factory for
its constructor. No generation builds a provider-name singleton or infers an
execution credential from the process environment.
"""

from collections.abc import Callable, Sequence

import httpx

from polyweb.adapters.base import ProviderAdapter
from polyweb.adapters.brave import BraveAdapter
from polyweb.adapters.exa import ExaAdapter
from polyweb.adapters.firecrawl import FirecrawlAdapter
from polyweb.adapters.keenable import KeenableAdapter
from polyweb.adapters.parallel import ParallelAdapter
from polyweb.adapters.tavily import TavilyAdapter
from polyweb.adapters.tinyfish import TinyfishAdapter
from polyweb.adapters.youcom import YoucomAdapter
from polyweb.infrastructure.secrets import ProviderName

_ADAPTERS: dict[ProviderName, Callable[[httpx.AsyncClient], ProviderAdapter]] = {
    ProviderName.BRAVE: BraveAdapter,
    ProviderName.EXA: ExaAdapter,
    ProviderName.FIRECRAWL: FirecrawlAdapter,
    ProviderName.KEENABLE: KeenableAdapter,
    ProviderName.PARALLEL: ParallelAdapter,
    ProviderName.TAVILY: TavilyAdapter,
    ProviderName.TINYFISH: TinyfishAdapter,
    ProviderName.YOU: YoucomAdapter,
}


def adapter_factory(
    name: str,
) -> Callable[[httpx.AsyncClient], ProviderAdapter] | None:
    """Return the public constructor for a canonical provider, or ``None``.

    This is the control plane's construction seam: ``routers/control.py`` uses
    it to build an adapter on demand without importing the private
    ``_ADAPTERS`` registry. An unknown provider name yields ``None``.
    """

    try:
        provider = ProviderName(name)
    except ValueError:
        return None
    return _ADAPTERS.get(provider)


async def close_adapters(
    adapters: Sequence[ProviderAdapter],
    client: httpx.AsyncClient | None = None,
) -> None:
    """Close all adapters and optionally the shared HTTP client."""

    for adapter in adapters:
        await adapter.aclose()
    if client is not None:
        await client.aclose()
