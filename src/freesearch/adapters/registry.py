"""Adapter-owned construction registry shared by the REST and MCP transports.

This module is the canonical home of the provider constructor registry
(``_ADAPTERS``), the :func:`adapter_factory` control-plane seam, and the
:func:`build_adapters` / :func:`close_adapters` generation helpers. Both
transports consume it — :mod:`freesearch.routers.control` builds newly
configured adapters on demand under the app control lock, and
:mod:`freesearch.mcp.server` builds/tears down owned generations under its
lifespan refcount lock. ``freesearch.mcp.server`` re-exports these names so
existing ``freesearch.mcp.server.*`` lookup/patch paths keep working.
"""

from collections.abc import Callable, Sequence

import httpx

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.configuration.provider_config import get_provider_configs
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.secrets import ProviderName

_ADAPTERS: dict[ProviderName, Callable[[httpx.AsyncClient], ProviderAdapter]] = {
    ProviderName.BRAVE: BraveAdapter,
    ProviderName.EXA: ExaAdapter,
    ProviderName.FIRECRAWL: FirecrawlAdapter,
    ProviderName.KEENABLE: KeenableAdapter,
    ProviderName.PARALLEL: ParallelAdapter,
    ProviderName.TAVILY: TavilyAdapter,
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


def build_adapters(client: httpx.AsyncClient | None = None) -> list[ProviderAdapter]:
    """Return enabled adapters with a resolvable key, in configured priority order.

    Each adapter resolves its own credential through the shared resolver at
    construction; providers without a key (or disabled by configuration) are
    skipped so the server runs with whatever keys are present. Keenable operates
    in keyless public mode when unconfigured.
    """

    http_client = client or create_async_client()
    adapters: list[ProviderAdapter] = []
    for name, record in sorted(
        get_provider_configs().items(), key=lambda item: (item[1].priority, item[0].value)
    ):
        adapter_cls = _ADAPTERS.get(name)
        if adapter_cls is None or not record.enabled:
            continue
        try:
            if name is ProviderName.PARALLEL:
                adapters.append(
                    ParallelAdapter(http_client, free_seed=record.parallel_free_seed_usd)
                )
            elif name is ProviderName.EXA:
                adapters.append(
                    ExaAdapter(http_client, monthly_budget=record.exa_monthly_budget_usd)
                )
            else:
                adapters.append(adapter_cls(http_client))
        except Exception:
            continue  # provider without a configured key fails closed at construction
    return adapters
