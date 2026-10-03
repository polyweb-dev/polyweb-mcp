"""REST API for the FreeSearch providers: FastAPI app with OpenAPI docs.

Thin HTTP layer over the same composition root as the MCP server: adapters are
built in configured priority order and every request is routed through
:func:`freesearch.routing.select_route`. Responses are the provider-neutral
contract models, so the OpenAPI schema at ``/docs`` documents them directly.

Every search/fetch call also records read-only local telemetry (usage and
health observations) through :mod:`freesearch.monitoring`, the loopback
monitoring reads (``/stats``, ``/dashboard``) expose that telemetry, and the
Stage 5 control plane (:mod:`freesearch.control`) serves the ``/api/v1``
provider, secret, and routing-policy endpoints.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import adapter_factory, build_adapters, close_adapters
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.cryptography import SecretCodec, load_or_create_master_key
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    migrate_legacy_secrets_to_encrypted_db,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.mcp.server import _apply_parallel_seed
from freesearch.models.contracts import (
    CostPreset,
    FallbackPolicy,
    FetchRequest,
    FetchResponse,
    ProviderHealth,
    ProviderTraceItem,
    QuotaSnapshot,
    RoutingMode,
    SearchRequest,
    SearchResponse,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.control import (
    _build_with_resolved_secret,
    _resolve_secret,
    effective_config_for_name,
    register_control_routes,
    routing_policy,
)
from freesearch.services.aggregation import reciprocal_rank_fusion
from freesearch.services.monitoring import (
    MAX_RECENT_LIMIT,
    DashboardResponse,
    StatsResponse,
    clear_quota_poll_cache,
    collect_stats,
    effective_quota,
    refresh_quotas,
    resolve_database_path,
    tracked_call,
)
from freesearch.services.routing import RoutingError, select_route


async def _build_app_adapters(
    repository: SQLiteRepository,
    routes: list[ProviderAdapter],
    client: httpx.AsyncClient | None,
    store: AsyncSecretStore,
) -> None:
    """Build enabled adapters from app-scoped encrypted vault secrets."""

    for provider in ProviderName:
        config = await effective_config_for_name(repository, provider)
        if not config.enabled:
            continue
        key, _source = await _resolve_secret(provider, store)
        if key is None and provider is not ProviderName.KEENABLE:
            continue
        factory = adapter_factory(provider.value)
        if factory is None:
            continue
        try:
            routes.append(_build_with_resolved_secret(factory, client, key))
        except Exception:
            continue


def create_app(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
    secret_store: AsyncSecretStore | None = None,
) -> FastAPI:
    """Create the FastAPI app routing every operation to a configured adapter.

    After the repository opens, the default store is encrypted runtime settings
    backed by the local master key; injected ``secret_store`` values remain
    offline seams. On-demand adapter construction receives the resolved
    app-scoped vault key.
    """

    owns_client = adapters is None
    client = create_async_client() if owns_client else None
    routes = list(adapters) if adapters is not None else []
    # The repository is owned only when neither adapters nor a repository was
    # injected: the composition root then opens (and closes) its own database.
    owns_repository = repository is None and adapters is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo: SQLiteRepository | None = app.state.repository
        try:
            if owns_repository:
                repo = await SQLiteRepository.open(resolve_database_path(database))
                app.state.repository = repo
            if isinstance(repo, SQLiteRepository) and app.state._uses_default_secret_store:
                settings = get_settings()
                passphrase = (
                    settings.encryption_key.get_secret_value()
                    if settings.encryption_key is not None
                    else None
                )
                app.state.secret_store = EncryptedDbSecretStore(
                    repo,
                    SecretCodec(
                        load_or_create_master_key(
                            key_file=settings.encryption_key_file, passphrase_env=passphrase
                        )
                    ),
                )
            if (
                owns_repository
                and repo is not None
                and isinstance(app.state.secret_store, EncryptedDbSecretStore)
            ):
                await migrate_legacy_secrets_to_encrypted_db(
                    repository=repo,
                    encrypted_store=app.state.secret_store,
                )
            if adapters is None:
                if isinstance(repo, SQLiteRepository):
                    await _build_app_adapters(
                        repo,
                        routes,
                        app.state._client,
                        app.state.secret_store,
                    )
                else:
                    routes.extend(build_adapters(app.state._client))
            # Restore locally derived quota state before the first dashboard
            # read.  This hydrates Keenable's rolling-hour keyless counter and
            # applies any persisted Parallel monthly budget without requiring
            # a search/fetch request to happen first.
            await _apply_parallel_seed(routes, repo)
            yield
        finally:
            if owns_repository and repo is not None:
                clear_quota_poll_cache(repo, routes)
                app.state.repository = None
                await repo.close()
            else:
                clear_quota_poll_cache(repository, routes)
            await close_adapters(routes, client if owns_client else None)

    app = FastAPI(title="FreeSearch", version="0.1.0", lifespan=lifespan)
    app.state.repository = repository
    app.state._routes = routes
    app.state._client = client
    app.state.secret_store = secret_store
    app.state._uses_default_secret_store = secret_store is None
    app.state._control_lock = asyncio.Lock()
    register_control_routes(app)

    @app.exception_handler(ProviderOperationError)
    async def _provider_operation_error(_req: Request, exc: ProviderOperationError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": exc.error.message or f"{exc.error.provider} operation failed"},
        )

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest) -> SearchResponse:
        """Search the web through the best available provider or all providers concurrently."""
        if request.fanout or request.routing.mode is RoutingMode.FANOUT:
            return await _dispatch_fanout_search(
                request,
                routes=app.state._routes,
                repository=app.state.repository,
                secret_store=app.state.secret_store,
            )
        return await _dispatch(
            request,
            UsageOperation.SEARCH,
            lambda target, req: target.search(req),
            routes=app.state._routes,
            repository=app.state.repository,
            secret_store=app.state.secret_store,
        )

    @app.post("/fetch", response_model=FetchResponse)
    async def fetch(request: FetchRequest) -> FetchResponse:
        """Fetch a URL's content through the best available provider."""
        return await _dispatch(
            request,
            UsageOperation.FETCH,
            lambda target, req: target.fetch(req),
            routes=app.state._routes,
            repository=app.state.repository,
            secret_store=app.state.secret_store,
        )

    @app.get("/stats", response_model=StatsResponse)
    async def stats(limit: int = 20) -> StatsResponse:
        """Return the read-only, local-observed monitoring snapshot."""
        return await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
        )

    @app.get("/dashboard", response_model=DashboardResponse)
    async def dashboard(limit: int = 20) -> DashboardResponse:
        """Return the JSON snapshot the future React dashboard consumes."""
        snapshot = await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
        )
        return DashboardResponse(
            notice=snapshot.notice,
            usage_totals=snapshot.usage_totals,
            recent_usage=snapshot.recent_usage,
            latest_quota=snapshot.latest_quota,
            latest_health=snapshot.latest_health,
            generated_at=datetime.now(UTC),
        )

    return app


async def _order_routes(
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    preset: CostPreset,
) -> list[ProviderAdapter]:
    """Filter disabled adapters and sort by persisted priority.

    The sort is stable: adapters with equal persisted priority keep their
    startup order (``build_adapters`` already emits the configured
    ``(priority, name)`` order, and injected routes keep the caller's order),
    so the pinned single-candidate routing contracts are preserved.
    """

    await _apply_parallel_seed(routes, repository)
    enabled: list[tuple[int, ProviderAdapter]] = []
    for adapter in routes:
        config = await effective_config_for_name(repository, adapter.name)
        if config.enabled:
            enabled.append((config.priority, adapter))
    ordered = [adapter for _, adapter in sorted(enabled, key=lambda item: item[0])]
    return _pin_free_first(ordered, preset)


def _pin_free_first(ordered: list[ProviderAdapter], preset: CostPreset) -> list[ProviderAdapter]:
    """Pin Keenable to the candidate front when the preset is ``free_first``."""

    if preset is not CostPreset.FREE_FIRST:
        return ordered
    pinned = [adapter for adapter in ordered if adapter.name == "keenable"]
    rest = [adapter for adapter in ordered if adapter.name != "keenable"]
    return pinned + rest


async def _routing_state(
    repository: SQLiteRepository | None,
    routes: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore,
) -> tuple[dict[str, ProviderHealth], dict[str, QuotaSnapshot]]:
    """Refresh bounded quota state and collect health/quota maps for routing."""

    if repository is None:
        return {}, {}
    with suppress(Exception):
        await refresh_quotas(repository, routes, secret_store=secret_store)
    health: dict[str, ProviderHealth] = {}
    quotas: dict[str, QuotaSnapshot] = {}
    for adapter in routes:
        try:
            observation = await repository.latest_health(adapter.name)
            if observation is not None:
                health[adapter.name] = observation
            snapshot = await effective_quota(repository, adapter.name)
            if snapshot is not None:
                quotas[adapter.name] = snapshot
        except Exception:
            continue
    return health, quotas


async def _plan_route(
    request: SearchRequest | FetchRequest,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore,
) -> tuple[ProviderAdapter, ...]:
    """Return the ordered adapters to attempt for ``request``.

    The in-memory routes are filtered by the persisted enablement, sorted by
    persisted priority, pinned for the cost preset, truncated by the fallback
    policy, and finally ranked by ``select_route``. A single candidate path
    stays identical to the pre-control routing contract.
    """

    if not routes:
        raise HTTPException(
            status_code=503,
            detail=(
                "no provider is configured: store a key in the encrypted vault "
                "(PUT /api/v1/providers/{id}/secret)"
            ),
        )
    policy = await routing_policy(repository)
    ordered = await _order_routes(routes, repository, policy.cost_optimization_preset)
    if policy.fallback_policy is FallbackPolicy.FIRST_ONLY:
        ordered = ordered[:1]
    health_snapshots, quota_snapshots = await _routing_state(repository, ordered, secret_store)
    try:
        candidates = select_route(request, ordered, health_snapshots, quota_snapshots)
    except RoutingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # A per-request allow_fallback=false already truncates inside select_route;
    # the global first_only policy truncates above.
    chained = request.routing.allow_fallback and policy.fallback_policy is FallbackPolicy.CHAINED
    if chained:
        return tuple(candidate.adapter for candidate in candidates)
    return (candidates[0].adapter,)


async def _dispatch[
    RequestT: (SearchRequest, FetchRequest),
    ResponseT: (
        SearchResponse,
        FetchResponse,
    ),
](
    request: RequestT,
    operation: UsageOperation,
    invoke: Callable[[ProviderAdapter, RequestT], Awaitable[ResponseT]],
    *,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore,
) -> ResponseT:
    """Run the routed adapter call for the best policy-ordered candidate.

    The candidate ordering applies the persisted enablement, priority, cost
    preset, and fallback policy; adapter failures propagate unchanged so the
    REST 500 / MCP ToolError contracts are preserved (no cross-adapter retry
    on failure, pinned by the offline BDD failure scenario).
    """

    attempts = await _plan_route(request, routes, repository, secret_store)
    return await tracked_call(
        repository,
        attempts[0],
        lambda target: invoke(target, request),
        operation=operation,
    )


async def _dispatch_fanout_search(
    request: SearchRequest,
    *,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore,
) -> SearchResponse:
    """Execute search across all eligible configured providers concurrently and fuse results."""
    if not routes:
        raise HTTPException(
            status_code=503,
            detail=(
                "no provider is configured: store a key in the encrypted vault "
                "(PUT /api/v1/providers/{id}/secret)"
            ),
        )
    policy = await routing_policy(repository)
    ordered = await _order_routes(routes, repository, policy.cost_optimization_preset)
    health_snapshots, quota_snapshots = await _routing_state(repository, ordered, secret_store)
    fanout_request = request.model_copy(
        update={"routing": request.routing.model_copy(update={"mode": RoutingMode.FANOUT})}
    )
    try:
        candidates = select_route(fanout_request, ordered, health_snapshots, quota_snapshots)
    except RoutingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not candidates:
        raise HTTPException(status_code=503, detail="no eligible provider is available for search")

    overall_start = time.perf_counter()

    async def _call(
        candidate_adapter: ProviderAdapter,
    ) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
        call_start = time.perf_counter()
        try:
            res = await tracked_call(
                repository,
                candidate_adapter,
                lambda target: target.search(request),
                operation=UsageOperation.SEARCH,
            )
            elapsed = int((time.perf_counter() - call_start) * 1000)
            return (candidate_adapter.name, res, elapsed, "success", len(res.results), None)
        except Exception as exc:
            elapsed = int((time.perf_counter() - call_start) * 1000)
            status = "failed"
            status_code = getattr(getattr(exc, "error", None), "status_code", None)
            if status_code == 429:
                status = "rate_limited"
            return (candidate_adapter.name, None, elapsed, status, 0, str(exc))

    tasks = [_call(c.adapter) for c in candidates]
    outcomes = await asyncio.gather(*tasks)

    successful_results: list[tuple[str, SearchResponse]] = []
    errors: list[str] = []
    waterfall: list[ProviderTraceItem] = []

    for name, res, elapsed, status, count, err in outcomes:
        waterfall.append(
            ProviderTraceItem(
                provider=name,
                latency_ms=elapsed,
                status=status,
                results_count=count,
                cost_credits=0.0,
                error=err,
            )
        )
        if res is not None:
            successful_results.append((name, res))
        elif err is not None:
            errors.append(err)

    if not successful_results:
        first_err = errors[0] if errors else "all providers failed"
        raise HTTPException(
            status_code=500,
            detail=f"all search providers failed: {first_err}",
        )

    fused_results = reciprocal_rank_fusion(
        successful_results,
        limit=request.limit,
    )
    participating = [name for name, _ in successful_results]
    total_elapsed_ms = int((time.perf_counter() - overall_start) * 1000)

    if repository is not None:
        with suppress(Exception):
            await repository.record_usage(
                UsageEvent(
                    provider="aggregated",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("0"),
                    observed_at=datetime.now(UTC),
                    latency_ms=total_elapsed_ms,
                    status=UsageStatus.SUCCESS,
                    metadata={
                        "participating_providers": participating,
                        "fused_count": len(fused_results),
                    },
                )
            )

    return SearchResponse(
        query=request.query,
        results=fused_results,
        provider="aggregated" if len(successful_results) > 1 else successful_results[0][0],
        total_results=len(fused_results),
        participating_providers=participating,
        waterfall=waterfall,
    )


def _clamped_limit(limit: int) -> int:
    """Clamp a requested recent-usage limit into ``[1, MAX_RECENT_LIMIT]``."""

    return min(max(limit, 1), MAX_RECENT_LIMIT)


def main(argv: Sequence[str] | None = None) -> None:
    """Serve the API with uvicorn (Swagger at /docs).

    The default store encrypts provider and OAuth secrets in local SQLite.
    Injected stores remain available for offline tests.

    The bind address is loopback by default for local development; containers
    override it with ``--host 0.0.0.0`` (or ``FREESEARCH_API_HOST``).
    """
    import argparse
    import os

    import uvicorn

    parser = argparse.ArgumentParser(description="FreeSearch REST API")
    parser.add_argument(
        "--host",
        default=os.getenv("FREESEARCH_API_HOST", "127.0.0.1"),
        help="HTTP host (default: 127.0.0.1, env: FREESEARCH_API_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FREESEARCH_API_PORT", "8001")),
        help="HTTP port (default: 8001, env: FREESEARCH_API_PORT)",
    )
    args = parser.parse_args(argv)

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
