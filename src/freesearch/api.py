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
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException

from freesearch.adapters.base import ProviderAdapter
from freesearch.config import get_settings
from freesearch.contracts import (
    CostPreset,
    FallbackPolicy,
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.control import (
    effective_config_for_name,
    register_control_routes,
    routing_policy,
)
from freesearch.http import create_async_client
from freesearch.monitoring import (
    MAX_RECENT_LIMIT,
    DashboardResponse,
    StatsResponse,
    collect_stats,
    resolve_database_path,
    tracked_call,
)
from freesearch.routing import RoutingError, select_route
from freesearch.secrets import KeyringSecretStore, SecretStore
from freesearch.server import build_adapters, close_adapters
from freesearch.storage import SQLiteRepository


def create_app(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
    secret_store: SecretStore | None = None,
) -> FastAPI:
    """Create the FastAPI app routing every operation to a configured adapter.

    The default secret store is the OS keyring under
    ``Settings.secret_service_name``, keeping control-plane secret writes and
    the adapters' own credential resolution on the same service; an injected
    ``secret_store`` is a test-only seam (offline doubles) and is never used by
    the production composition root. On-demand adapter construction resolves
    credentials through the global provider secret resolver (environment >
    ``.env`` > keyring), and a failed construction degrades to an actionable
    503 rather than failing the request.
    """

    owns_client = adapters is None
    client = create_async_client() if owns_client else None
    routes = list(adapters) if adapters is not None else build_adapters(client)
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
            yield
        finally:
            if owns_repository and repo is not None:
                app.state.repository = None
                await repo.close()
            await close_adapters(routes, client if owns_client else None)

    app = FastAPI(title="FreeSearch", version="0.1.0", lifespan=lifespan)
    app.state.repository = repository
    app.state._routes = routes
    app.state._client = client
    app.state.secret_store = secret_store or KeyringSecretStore(get_settings().secret_service_name)
    app.state._control_lock = asyncio.Lock()
    register_control_routes(app)

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest) -> SearchResponse:
        """Search the web through the best available provider."""
        return await _dispatch(
            request,
            UsageOperation.SEARCH,
            lambda target, req: target.search(req),
            routes=app.state._routes,
            repository=app.state.repository,
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
        return DashboardResponse(**snapshot.model_dump(), generated_at=datetime.now(UTC))

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


async def _plan_route(
    request: SearchRequest | FetchRequest,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
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
            detail="no provider is configured: set a FREESEARCH_*_API_KEY",
        )
    policy = await routing_policy(repository)
    ordered = await _order_routes(routes, repository, policy.cost_optimization_preset)
    if policy.fallback_policy is FallbackPolicy.FIRST_ONLY:
        ordered = ordered[:1]
    try:
        candidates = select_route(request, ordered, {}, {})
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
) -> ResponseT:
    """Run the routed adapter call for the best policy-ordered candidate.

    The candidate ordering applies the persisted enablement, priority, cost
    preset, and fallback policy; adapter failures propagate unchanged so the
    REST 500 / MCP ToolError contracts are preserved (no cross-adapter retry
    on failure, pinned by the offline BDD failure scenario).
    """

    attempts = await _plan_route(request, routes, repository)
    return await tracked_call(
        repository,
        attempts[0],
        lambda target: invoke(target, request),
        operation=operation,
    )


def _clamped_limit(limit: int) -> int:
    """Clamp a requested recent-usage limit into ``[1, MAX_RECENT_LIMIT]``."""

    return min(max(limit, 1), MAX_RECENT_LIMIT)


def main() -> None:
    """Serve the API with uvicorn on loopback:8001 (Swagger at /docs).

    The app default secret store is the OS keyring under
    ``Settings.secret_service_name``, so control-plane secret writes and the
    adapters' credential resolution share one service; injected secret stores
    are a test-only seam. On-demand adapter construction resolves credentials
    through the global provider secret resolver and degrades to 503 when a
    provider cannot be constructed.
    """
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
