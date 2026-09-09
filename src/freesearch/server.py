"""Stage 4 composition root: bind the shared contracts to a runnable MCP server.

Builds the enabled, key-configured adapters in priority order and exposes the
two provider-neutral tools (``search``, ``fetch``) over MCP (streamable HTTP on
loopback:8000), routing each request through
:func:`freesearch.routing.select_route`. Every tool call also records read-only
local telemetry (usage and health observations) through
:mod:`freesearch.monitoring`, mirroring the REST path.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, TypedDict

import httpx
from mcp.server.fastmcp import FastMCP

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.contracts import (
    FetchRequest,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    UsageOperation,
)
from freesearch.http import create_async_client
from freesearch.monitoring import (
    clear_quota_poll_cache,
    effective_quota,
    refresh_quotas,
    resolve_database_path,
    tracked_call,
)
from freesearch.provider_config import get_provider_configs
from freesearch.routing import select_route
from freesearch.secrets import ProviderName
from freesearch.storage import SQLiteRepository

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

    This is the control plane's construction seam: ``api.py`` uses it to build
    an adapter on demand without importing the private ``_ADAPTERS`` registry.
    An unknown provider name yields ``None``.
    """

    try:
        provider = ProviderName(name)
    except ValueError:
        return None
    return _ADAPTERS.get(provider)


class _ServerState(TypedDict):
    """Tool-visible shared cells: the active repository and owned generation."""

    repository: SQLiteRepository | None
    client: httpx.AsyncClient | None
    routes: list[ProviderAdapter] | None


async def close_adapters(
    adapters: Sequence[ProviderAdapter],
    client: httpx.AsyncClient | None = None,
) -> None:
    """Close all adapters and optionally the shared HTTP client."""

    for adapter in adapters:
        await adapter.aclose()
    if client is not None:
        await client.aclose()


def _quota_state_changed(current: QuotaSnapshot | None, projected: QuotaSnapshot) -> bool:
    if current is None:
        return True
    return any(
        getattr(current, field, None) != getattr(projected, field, None)
        for field in ("remaining", "limit", "unit_kind", "display_unit", "metadata")
    )


async def _apply_parallel_seed(
    routes: Sequence[ProviderAdapter], repository: SQLiteRepository | None
) -> None:
    """Apply persisted Parallel seed state after the repository is available."""

    if repository is None:
        return
    from freesearch.control import effective_config_for_name

    for adapter in routes:
        try:
            if adapter.name == "parallel":
                config = await effective_config_for_name(repository, adapter.name)
                setter = getattr(adapter, "set_free_seed", None)
                if callable(setter):
                    setter(config.parallel_free_seed_usd)
            hydrator = getattr(adapter, "hydrate_quota", None)
            if not callable(hydrator):
                continue
            snapshot = await hydrator(repository)
            if snapshot is not None:
                latest = await repository.latest_quota(adapter.name)
                if _quota_state_changed(latest, snapshot):
                    await repository.record_quota(snapshot)
        except Exception:
            continue


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
            else:
                adapters.append(adapter_cls(http_client))
        except Exception:
            continue  # provider without a configured key fails closed at construction
    return adapters


async def _build_generation(
    state: _ServerState,
    *,
    database: str | Path | None,
    owns_repository: bool,
) -> None:
    """Create one owned generation (client, adapters, repository) and publish it."""

    client = create_async_client()
    owned_routes: list[ProviderAdapter] = []
    try:
        owned_routes = build_adapters(client)
        if owns_repository:
            state["repository"] = await SQLiteRepository.open(resolve_database_path(database))
        await _apply_parallel_seed(owned_routes, state["repository"])
    except BaseException:
        # A failed enter never increments: close the freshly built client and
        # adapters so a failed open cannot leak a partial generation.
        await close_adapters(owned_routes, client)
        raise
    state["client"] = client
    state["routes"] = owned_routes


async def _detach_generation(state: _ServerState, *, owns_repository: bool) -> None:
    """Detach the active generation from the state cells, then close it."""

    client = state["client"]
    owned_routes = state["routes"]
    owned_repo = state["repository"] if owns_repository else None
    state["client"] = None
    state["routes"] = None
    if owned_repo is not None:
        clear_quota_poll_cache(owned_repo, owned_routes or [])
        state["repository"] = None
        await owned_repo.close()
    await close_adapters(owned_routes or [], client)


async def _route_state(
    repository: SQLiteRepository | None, active: Sequence[ProviderAdapter]
) -> tuple[dict[str, ProviderHealth], dict[str, QuotaSnapshot]]:
    """Collect routing state while degrading quota failures to unknown."""

    with suppress(Exception):
        await refresh_quotas(repository, active)
    health: dict[str, ProviderHealth] = {}
    quotas: dict[str, QuotaSnapshot] = {}
    if repository is None:
        return health, quotas
    for candidate in active:
        try:
            observation = await repository.latest_health(candidate.name)
            if observation is not None:
                health[candidate.name] = observation
            snapshot = await effective_quota(repository, candidate.name)
            if snapshot is not None:
                quotas[candidate.name] = snapshot
        except Exception:
            continue
    return health, quotas


def create_server(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
) -> FastMCP:
    """Create the MCP server, routing every tool call to a configured adapter."""

    owns_client = adapters is None
    routes = list(adapters) if adapters is not None else None
    # Same ownership rule as the REST app: only a fully self-constructed server
    # owns (opens and closes) its telemetry repository.
    owns_repository = repository is None and adapters is None
    # The tools read shared resources through these cells. A server that owns
    # its adapters starts with none: every refcount 0→1 transition builds a
    # fresh generation (HTTP client, adapters, repository) into the cells and
    # every 1→0 transition detaches exactly that generation for teardown, so
    # sequential sessions — and sessions entering during a still-running
    # teardown — never inherit closed or stale resources.
    state: _ServerState = {"repository": repository, "client": None, "routes": routes}
    # Streamable-HTTP MCP runs one lifespan per concurrent session, so the
    # owned resources are refcounted (serialized by a lock): the first enter
    # builds the generation and the last exit tears it down.
    lock = asyncio.Lock()
    refcount = 0

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[None]:
        nonlocal refcount
        if owns_client:
            # Concurrent enters serialize here; a failed generation build
            # propagates without incrementing, so the cells stay empty.
            async with lock:
                if refcount == 0:
                    await _build_generation(
                        state, database=database, owns_repository=owns_repository
                    )
                refcount += 1
        try:
            yield
        finally:
            if owns_client:
                async with lock:
                    refcount -= 1
                    last_exit = refcount == 0
                # Teardown happens outside the lock, exactly once, on the
                # last exit: intermediate exits keep everything usable, and
                # detaching under the lock lets a session that enters during
                # a delayed teardown build its own fresh generation.
                if last_exit:
                    await _detach_generation(state, owns_repository=owns_repository)
            else:
                clear_quota_poll_cache(repository, routes or [])
                await close_adapters(routes or [], None)

    server = FastMCP("freesearch", lifespan=lifespan)

    async def _route(request: SearchRequest | FetchRequest) -> ProviderAdapter:
        # The owned path routes through the current generation's adapters; the
        # injected path keeps the caller's eager list. An owned server that has
        # not entered a lifespan yet has no generation, hence no provider.
        active = state["routes"] if owns_client else routes
        if not active:
            raise RuntimeError("no provider is configured: set a FREESEARCH_*_API_KEY")
        repository = state["repository"]
        await _apply_parallel_seed(active, repository)
        health, quotas = await _route_state(repository, active)
        return select_route(request, active, health, quotas)[0].adapter

    @server.tool()
    async def search(request: SearchRequest) -> dict[str, Any]:
        """Search the web through the best available provider."""
        adapter = await _route(request)
        response = await tracked_call(
            state["repository"],
            adapter,
            lambda target: target.search(request),
            operation=UsageOperation.SEARCH,
        )
        return response.model_dump(mode="json")

    @server.tool()
    async def fetch(request: FetchRequest) -> dict[str, Any]:
        """Fetch a URL's content through the best available provider."""
        adapter = await _route(request)
        response = await tracked_call(
            state["repository"],
            adapter,
            lambda target: target.fetch(request),
            operation=UsageOperation.FETCH,
        )
        return response.model_dump(mode="json")

    return server


def main() -> None:
    """Run the MCP server over HTTP (streamable-http on loopback:8000)."""
    create_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
