"""Stage 4 composition root: bind the shared contracts to a runnable MCP server.

Builds the enabled, key-configured adapters in priority order and exposes the
two provider-neutral tools (``search``, ``fetch``) over MCP (streamable HTTP or
stdio), routing each request through
:func:`freesearch.routing.select_route`. Every tool call also records read-only
local telemetry (usage and health observations) through
:mod:`freesearch.monitoring`, mirroring the REST path.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, TypedDict

import httpx
from mcp.server.fastmcp import FastMCP

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import (
    _ADAPTERS as _ADAPTERS,
)
from freesearch.adapters.registry import (
    adapter_factory as adapter_factory,
)
from freesearch.adapters.registry import (
    build_adapters,
    close_adapters,
)
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.cryptography import SecretCodec, load_or_create_master_key
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import (
    FetchRequest,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.monitoring import (
    clear_quota_poll_cache,
    effective_quota,
    refresh_quotas,
    resolve_database_path,
    tracked_call,
)
from freesearch.services.routing import select_route

# Canonical definitions live in :mod:`freesearch.adapters.registry`; the names
# above are re-exported here so ``freesearch.mcp.server.*`` lookup and patch
# paths (e.g. ``build_adapters``/``close_adapters`` in lifecycle tests) keep
# working. ``adapter_factory`` is consumed by ``routers/control.py``.

logger = logging.getLogger(__name__)


class _ServerState(TypedDict):
    """Tool-visible shared cells: the active repository and owned generation."""

    repository: SQLiteRepository | None
    client: httpx.AsyncClient | None
    routes: list[ProviderAdapter] | None
    secret_store: AsyncSecretStore | None


def _quota_state_changed(current: QuotaSnapshot | None, projected: QuotaSnapshot) -> bool:
    if current is None:
        return True
    return any(
        getattr(current, field, None) != getattr(projected, field, None)
        for field in (
            "source",
            "remaining",
            "limit",
            "reset_at",
            "unit_kind",
            "display_unit",
            "metadata",
        )
    )


async def _apply_parallel_seed(
    routes: Sequence[ProviderAdapter], repository: SQLiteRepository | None
) -> None:
    """Apply persisted Parallel seed state after the repository is available."""

    if repository is None:
        return
    from freesearch.routers.control import effective_config_for_name

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


def _encrypted_store(repository: SQLiteRepository) -> EncryptedDbSecretStore:
    """Build the local encrypted store used by OAuth balance polling."""

    settings = get_settings()
    passphrase = (
        settings.encryption_key.get_secret_value() if settings.encryption_key is not None else None
    )
    return EncryptedDbSecretStore(
        repository,
        SecretCodec(
            load_or_create_master_key(
                key_file=settings.encryption_key_file, passphrase_env=passphrase
            )
        ),
    )


async def _build_generation(
    state: _ServerState,
    *,
    database: str | Path | None,
    owns_repository: bool,
) -> None:
    """Create one owned generation (client, adapters, repository) and publish it.

    Adapters resolve their keys from the encrypted vault via the control-plane
    helpers; providers without a vault key are skipped (Keenable's keyless
    public tier excepted).
    """

    from freesearch.routers.control import (
        _build_with_resolved_secret,
        _resolve_secret,
        effective_config_for_name,
    )

    client = create_async_client()
    owned_routes: list[ProviderAdapter] = []
    try:
        if owns_repository:
            state["repository"] = await SQLiteRepository.open(resolve_database_path(database))
        repository = state["repository"]
        if isinstance(repository, SQLiteRepository):
            state["secret_store"] = _encrypted_store(repository)
        store = state["secret_store"]
        if isinstance(repository, SQLiteRepository) and store is not None:
            for provider in ProviderName:
                config = await effective_config_for_name(repository, provider)
                if not config.enabled:
                    continue
                key, _source = await _resolve_secret(provider, store)
                if key is None and provider is not ProviderName.KEENABLE:
                    continue
                factory = adapter_factory(provider.value)
                if factory is None:
                    logger.warning("no adapter factory for provider %s", provider.value)
                    continue
                try:
                    owned_routes.append(_build_with_resolved_secret(factory, client, key))
                except Exception:
                    continue
        else:
            owned_routes = build_adapters(client)
        await _apply_parallel_seed(owned_routes, repository)
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
    state["secret_store"] = None
    if owned_repo is not None:
        clear_quota_poll_cache(owned_repo, owned_routes or [])
        state["repository"] = None
        await owned_repo.close()
    await close_adapters(owned_routes or [], client)


async def _route_state(
    repository: SQLiteRepository | None,
    active: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore | None,
) -> tuple[dict[str, ProviderHealth], dict[str, QuotaSnapshot]]:
    """Collect routing state while degrading quota failures to unknown."""

    with suppress(Exception):
        await refresh_quotas(repository, active, secret_store=secret_store)
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
    stateless_http: bool = False,
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
    state: _ServerState = {
        "repository": repository,
        "client": None,
        "routes": routes,
        "secret_store": _encrypted_store(repository)
        if isinstance(repository, SQLiteRepository)
        else None,
    }
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

    server = FastMCP("freesearch", lifespan=lifespan, stateless_http=stateless_http)

    async def _route(request: SearchRequest | FetchRequest) -> ProviderAdapter:
        # The owned path routes through the current generation's adapters; the
        # injected path keeps the caller's eager list. An owned server that has
        # not entered a lifespan yet has no generation, hence no provider.
        active = state["routes"] if owns_client else routes
        if not active:
            raise RuntimeError(
                "no provider is configured: store a key in the encrypted vault "
                "(PUT /api/v1/providers/{id}/secret)"
            )
        repository = state["repository"]
        await _apply_parallel_seed(active, repository)
        health, quotas = await _route_state(repository, active, state["secret_store"])
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


def main(argv: Sequence[str] | None = None) -> None:
    """Run the MCP server over stdio or HTTP (streamable-http on loopback:8000)."""
    import argparse
    import os

    default_transport = os.getenv("FREESEARCH_MCP_TRANSPORT", "streamable-http")
    default_stateless = os.getenv("FREESEARCH_MCP_STATELESS", "").lower() in ("1", "true", "yes")

    parser = argparse.ArgumentParser(description="FreeSearch MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=default_transport,
        help="MCP transport protocol (default: streamable-http, env: FREESEARCH_MCP_TRANSPORT)",
    )
    parser.add_argument(
        "--stateless",
        action="store_true",
        default=default_stateless,
        help="Enable stateless mode for HTTP transport (env: FREESEARCH_MCP_STATELESS)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("FREESEARCH_MCP_HOST", "127.0.0.1"),
        help="HTTP host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FREESEARCH_MCP_PORT", "8000")),
        help="HTTP port (default: 8000)",
    )
    args = parser.parse_args(argv)

    server = create_server(stateless_http=args.stateless)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
