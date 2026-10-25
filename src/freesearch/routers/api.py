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
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import adapter_factory, build_adapters, close_adapters
from freesearch.configuration.config import get_settings, require_transport_port
from freesearch.configuration.provider_config import ProviderConfigError
from freesearch.infrastructure.auth_asgi import BearerAuthMiddleware
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    load_secret_codec,
    migrate_legacy_secrets_to_encrypted_db,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.observability import (
    NO_OP_OBSERVABILITY,
    ObservabilityRuntime,
    SpanHandle,
    SpanKindName,
    build_observability,
    current_observability,
)
from freesearch.infrastructure.observability_asgi import ProviderTraceMiddleware
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.infrastructure.trace_payloads import (
    _annotate_root,
    _annotate_root_error,
    _operation_name,
    _request_attributes,
    _search_results_payload,
)
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
from freesearch.models.observability import (
    TRACE_EVENT_PROVIDER_REQUEST,
    TRACE_EVENT_PROVIDER_RESPONSE,
    TraceAttribute,
    TraceOperation,
    TraceRootSpan,
    TraceSpanName,
)
from freesearch.models.provider_limits import (
    LimitDeniedError,
    LimitStoreUnavailable,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.database_migrations import upgrade_database
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.auth import register_auth_routes, require_control_reader
from freesearch.routers.control import (
    _build_with_resolved_secret,
    _resolve_secret,
    clear_config_cache,
    effective_config_for_name,
    initialize_provider_configs,
    register_control_routes,
    routing_policy,
)
from freesearch.routers.credentials import register_credential_routes
from freesearch.routers.limits import limit_denial_response, register_limit_routes
from freesearch.routers.observability import register_observability_routes
from freesearch.routers.projects import register_project_routes
from freesearch.routers.settings import register_settings_routes
from freesearch.services.aggregation import reciprocal_rank_fusion
from freesearch.services.limits_sync import LimitSyncService
from freesearch.services.monitoring import (
    MAX_RECENT_LIMIT,
    DashboardResponse,
    StatsResponse,
    clear_quota_poll_cache,
    collect_stats,
    effective_quota,
    effective_quotas_batch,
    refresh_quotas,
    resolve_database_path,
    tracked_call,
)
from freesearch.services.provider_limits import ProviderLimitsService
from freesearch.services.routing import RoutingError, select_route
from freesearch.services.users import AuthService

# Route templates that receive a root server span. Extending provider-querying
# coverage means adding one entry here (plus its operation shape) — the
# middleware, exporter, storage, and UI need no change.
_TRACED_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/search"): TraceRootSpan.SEARCH.value,
    ("POST", "/fetch"): TraceRootSpan.FETCH.value,
}


def _install_default_secret_store(app: FastAPI, repo: SQLiteRepository | None) -> None:
    """Install the encrypted runtime-settings store for an owned repository.

    An injected secret store stays untouched, so offline compositions keep their
    seam.
    """

    if not isinstance(repo, SQLiteRepository) or not app.state._uses_default_secret_store:
        return
    app.state.secret_store = EncryptedDbSecretStore(
        repo,
        load_secret_codec(get_settings()),
    )


async def _build_app_adapters(
    repository: SQLiteRepository,
    routes: list[ProviderAdapter],
    client: httpx.AsyncClient | None,
    store: AsyncSecretStore,
) -> None:
    """Build credential-ready adapters from app-scoped encrypted vault secrets.

    An administrator OFF choice does not skip construction: each request
    filters the candidate list, so a later ON choice needs no restart. A
    missing Tavily key keeps the keyless public tier with its configured rail
    and PAYGO values instead of dropping the provider.
    """

    await initialize_provider_configs(repository)
    for provider in ProviderName:
        key, _source = await _resolve_secret(provider, store)
        if key is None and provider not in (ProviderName.KEENABLE, ProviderName.TAVILY):
            continue
        factory = adapter_factory(provider.value)
        if factory is None:
            continue
        try:
            if provider is ProviderName.TAVILY:
                config = await effective_config_for_name(repository, provider.value)
                routes.append(_build_with_resolved_secret(factory, client, key, config=config))
            else:
                routes.append(_build_with_resolved_secret(factory, client, key))
        except Exception:
            continue


async def _verify_access_token(app: FastAPI, token: str) -> UserPrincipal | None:
    """Verify one access JWT through the app's auth service."""

    service: AuthService | None = app.state.auth_service
    if service is None:
        return None
    return await service.verify_token(token)


async def _verify_refresh_token(app: FastAPI, token: str) -> UserPrincipal | None:
    """Verify one opaque refresh credential for the protected refresh route."""

    service: AuthService | None = app.state.auth_service
    if service is None:
        return None
    return await service.verify_refresh_token(token)


async def _reserve_registration(app: FastAPI, peer_address: str) -> int | None:
    """Reserve public-registration capacity before the endpoint runs."""

    service: AuthService | None = app.state.auth_service
    if service is None:
        raise RuntimeError("account authentication is not configured")
    return await service.reserve_registration(peer_address=peer_address)


async def _open_accounts(
    auth: AuthService,
    *,
    repo: SQLiteRepository | None,
    database: str | Path | None,
    owns_auth_service: bool,
) -> None:
    """Attach the app's repository to a composed auth service, then open it.

    An injected service always opens. A composed service opens when it has a real
    database: the app's repository, an explicit database argument, or the database
    it owns. A composition with only injected adapters keeps no account store, so
    it creates no stray database file.
    """

    if owns_auth_service and isinstance(repo, SQLiteRepository):
        auth.attach_repository(repo)
    if not owns_auth_service or auth.repository is not None or database is not None:
        await auth.open()


async def _teardown_app_lifespan(
    app: FastAPI,
    repo: SQLiteRepository | None,
    routes: list[ProviderAdapter],
    stop_limits: asyncio.Event,
    auth: AuthService,
    owns_repository: bool,
    repository: SQLiteRepository | None,
    owns_client: bool,
    client: httpx.AsyncClient | None,
) -> None:
    """Flush traces, stop the limit schedule, then close owned composition resources."""

    # Traces are force-flushed and shut down before the repository and
    # adapters close, so the last batch cannot race a closing database.
    runtime: ObservabilityRuntime = app.state.observability
    app.state.observability = NO_OP_OBSERVABILITY
    await asyncio.to_thread(runtime.shutdown)
    # The schedule task stops and is awaited before the repository and
    # adapters close, so no poll can race a closing database.
    await _stop_limits(app, stop_limits)
    if owns_repository and repo is not None:
        clear_quota_poll_cache(repo, routes)
        clear_config_cache(repo)
        app.state.repository = None
        await repo.close()
    else:
        clear_quota_poll_cache(repository, routes)
        clear_config_cache(repository)
    await auth.close()
    await close_adapters(routes, client if owns_client else None)


def create_app(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
    secret_store: AsyncSecretStore | None = None,
    auth_service: AuthService | None = None,
) -> FastAPI:
    """Create the FastAPI app routing every operation to a configured adapter.

    After the repository opens, the default store is encrypted runtime settings
    backed by the local master key; injected ``secret_store`` values remain
    offline seams. On-demand adapter construction receives the resolved
    app-scoped vault key.

    Account authentication reuses this app's operational repository without
    taking ownership of it. Only an injected ``auth_service`` keeps its own
    database and lifecycle.
    """

    owns_client = adapters is None
    client = create_async_client() if owns_client else None
    routes = list(adapters) if adapters is not None else []
    # The repository is owned only when neither adapters nor a repository was
    # injected: the composition root then opens (and closes) its own database.
    owns_repository = repository is None and adapters is None
    owns_auth_service = auth_service is None
    accounts = auth_service or AuthService(get_settings(), repository=repository, database=database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo: SQLiteRepository | None = app.state.repository
        stop_limits = asyncio.Event()
        auth: AuthService = app.state.auth_service
        try:
            if owns_repository:
                repo = await SQLiteRepository.open(resolve_database_path(database))
                app.state.repository = repo
            _install_default_secret_store(app, repo)
            # Account access is available before the first request: an owned
            # database is migrated by ``open`` and validated by ``upgrade``.
            await _open_accounts(
                auth, repo=repo, database=database, owns_auth_service=owns_auth_service
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
            elif isinstance(repo, SQLiteRepository):
                # Injected adapters with an owned database still need the
                # canonical provider records before the first request.
                await initialize_provider_configs(repo)
            # Restore locally derived quota state before the first dashboard
            # read.  This hydrates Keenable's rolling-hour keyless counter and
            # applies any persisted Parallel monthly budget without requiring
            # a search/fetch request to happen first.
            await _apply_parallel_seed(routes, repo)
            await _start_limits(app, repo, routes, stop_limits)
            trace_database = _trace_database(repo, database)
            if trace_database is not None and not isinstance(repo, SQLiteRepository):
                # An injected-adapters composition can still point at a trace
                # database; adopt it (upgrade + validate) before the exporter
                # starts writing. A failure here is not fatal: the exporter
                # reports a failed batch instead of failing user requests.
                with suppress(Exception):
                    await asyncio.to_thread(upgrade_database, trace_database)
            app.state.observability = build_observability(
                get_settings(),
                database=trace_database,
            )
            yield
        finally:
            await _teardown_app_lifespan(
                app,
                repo,
                routes,
                stop_limits,
                auth,
                owns_repository,
                repository,
                owns_client,
                client,
            )

    # The browser origin allowlist reaches the guard, the middleware, and the auth
    # router through this composition only. An empty allowlist keeps the
    # programmatic JSON pair and Bearer refresh contract for every client.
    browser_origins = frozenset(get_settings().auth_browser_origins)
    app = FastAPI(title="FreeSearch", version="0.1.0", lifespan=lifespan)
    app.state.repository = repository
    app.state._routes = routes
    app.state._client = client
    app.state.secret_store = secret_store
    app.state._uses_default_secret_store = secret_store is None
    app.state._control_lock = asyncio.Lock()
    app.state.limits = None
    app.state.limits_sync = None
    app.state._limits_task = None
    app.state.auth_service = accounts
    app.state._owns_auth_service = owns_auth_service
    app.state.auth_browser_origins = browser_origins
    # Tracing starts disabled and is enabled by the lifespan once the trace
    # database is known, so tests that never enter the lifespan stay no-op.
    app.state.observability = NO_OP_OBSERVABILITY
    app.add_middleware(
        ProviderTraceMiddleware,
        runtime_getter=lambda: app.state.observability,
        traced_routes=_TRACED_ROUTES,
    )
    # Added last, so the guard sits outside the trace middleware: a rejected
    # request can neither reach an endpoint nor open a provider trace root.
    app.add_middleware(
        BearerAuthMiddleware,
        browser_origins=browser_origins,
        verify_token=lambda token: _verify_access_token(app, token),
        verify_refresh_token=lambda token: _verify_refresh_token(app, token),
        registration_limit=lambda peer: _reserve_registration(app, peer),
    )
    register_auth_routes(app)
    register_project_routes(app)
    register_settings_routes(app)
    register_credential_routes(app)
    register_control_routes(app)
    register_limit_routes(app)
    register_observability_routes(app)

    @app.exception_handler(LimitDeniedError)
    async def _limit_denied(_: Any, exc: LimitDeniedError) -> JSONResponse:
        """Transport one local admission denial as 402 or 429 with Retry-After."""

        return limit_denial_response(exc)

    @app.exception_handler(LimitStoreUnavailable)
    async def _limit_store(_: Any, exc: LimitStoreUnavailable) -> JSONResponse:
        """Return a safe 503 before a metered vendor call when the store fails."""

        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # Module-level handler: a terminal Tavily out-of-Credits error is a 402;
    # every other ProviderOperationError re-raises into the standard 500 flow.
    app.add_exception_handler(ProviderOperationError, _provider_operation_error)

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest) -> SearchResponse:
        """Search the web through the best available provider or all providers concurrently."""
        observability = current_observability()
        with observability.span(TraceSpanName.BACKEND, attributes=_request_attributes(request)):
            if request.fanout or request.routing.mode is RoutingMode.FANOUT:
                return await _dispatch_fanout_search(
                    request,
                    routes=app.state._routes,
                    repository=app.state.repository,
                    secret_store=app.state.secret_store,
                    limits=app.state.limits,
                )
            return await _dispatch(
                request,
                UsageOperation.SEARCH,
                lambda target, req: target.search(req),
                routes=app.state._routes,
                repository=app.state.repository,
                secret_store=app.state.secret_store,
                limits=app.state.limits,
            )

    @app.post("/fetch", response_model=FetchResponse)
    async def fetch(request: FetchRequest) -> FetchResponse | JSONResponse:
        """Fetch a URL's content through the best available provider."""
        return await _execute_fetch(app, request)

    @app.get("/stats", response_model=StatsResponse)
    async def stats(
        _principal: Annotated[UserPrincipal, Depends(require_control_reader)],
        limit: int = 20,
    ) -> StatsResponse:
        """Return the read-only, local-observed monitoring snapshot."""
        return await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
            limits=app.state.limits,
        )

    @app.get("/dashboard", response_model=DashboardResponse)
    async def dashboard(
        _principal: Annotated[UserPrincipal, Depends(require_control_reader)],
        limit: int = 20,
    ) -> DashboardResponse:
        """Return the JSON snapshot the future React dashboard consumes."""
        snapshot = await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
            limits=app.state.limits,
        )
        return DashboardResponse(
            notice=snapshot.notice,
            usage_totals=snapshot.usage_totals,
            recent_usage=snapshot.recent_usage,
            latest_quota=snapshot.latest_quota,
            latest_health=snapshot.latest_health,
            crd_usage_totals=snapshot.crd_usage_totals,
            provider_limits=await _provider_limits(app.state.limits),
            generated_at=datetime.now(UTC),
        )

    return app


async def _start_limits(
    app: FastAPI,
    repo: SQLiteRepository | None,
    routes: Sequence[ProviderAdapter],
    stop: asyncio.Event,
) -> None:
    """Seed the catalog and start one schedule task for this runtime generation.

    A composition without a repository (injected adapters) has no limit store,
    so the schedule task does not start.
    """

    if not isinstance(repo, SQLiteRepository):
        return
    limits = ProviderLimitsService(repo.limits)
    await limits.initialize()
    adapter = next((route for route in routes if route.name == ProviderName.TAVILY.value), None)
    if adapter is not None:
        with suppress(Exception):
            config = await effective_config_for_name(repo, ProviderName.TAVILY.value)
            await limits.apply_tavily_config(config, auth_mode=adapter.limit_auth_mode)
    keenable = next((route for route in routes if route.name == ProviderName.KEENABLE.value), None)
    if keenable is not None:
        limits.apply_keenable_auth_mode(keenable.limit_auth_mode)
    app.state.limits = limits
    app.state.limits_sync = LimitSyncService(repo.limits, limits, lambda: routes)
    app.state._limits_task = asyncio.create_task(app.state.limits_sync.run(stop))


async def _stop_limits(app: FastAPI, stop: asyncio.Event) -> None:
    """Stop and await the schedule task before the repository and adapters close."""

    stop.set()
    task = getattr(app.state, "_limits_task", None)
    if task is not None:
        task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await task
    app.state._limits_task = None
    app.state.limits = None
    app.state.limits_sync = None


async def _provider_limits(
    limits: ProviderLimitsService | None,
) -> list[Any]:
    """Read every provider card payload best effort; a failure yields none."""

    if limits is None:
        return []
    with suppress(Exception):
        return await limits.dashboard_views()
    return []


def _require_single_url(request: FetchRequest) -> None:
    """Reject an executable batch fetch before admission and vendor I/O."""

    if request.url_count != 1:
        raise HTTPException(
            status_code=422,
            detail="this release executes exactly one URL per fetch request",
        )


async def _order_routes(
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    preset: CostPreset,
    operation: UsageOperation,
) -> list[ProviderAdapter]:
    """Filter inaccessible adapters and sort by persisted priority.

    A candidate stays only when ``config.allows(operation)`` holds, so the
    admin mask, the system support mask, and the global gate all apply before
    any provider call. The sort is stable: adapters with equal persisted
    priority keep their startup order (``build_adapters`` already emits the
    configured ``(priority, name)`` order, and injected routes keep the
    caller's order), so the pinned single-candidate routing contracts are
    preserved.
    """

    eligible: list[tuple[int, ProviderAdapter]] = []
    for adapter in routes:
        config = await effective_config_for_name(repository, adapter.name, strict=True)
        if config.allows(operation):
            eligible.append((config.priority, adapter))
    ordered = [adapter for _, adapter in sorted(eligible, key=lambda item: item[0])]
    return _pin_free_first(ordered, preset)


def _pin_free_first(ordered: list[ProviderAdapter], preset: CostPreset) -> list[ProviderAdapter]:
    """Pin Keenable to the candidate front when the preset is ``free_first``."""

    if preset is not CostPreset.FREE_FIRST:
        return ordered
    pinned = [adapter for adapter in ordered if adapter.name == "keenable"]
    rest = [adapter for adapter in ordered if adapter.name != "keenable"]
    return pinned + rest


def _trace_database(repo: SQLiteRepository | None, database: str | Path | None) -> Path | None:
    """Return the database that owns this app's traces, else ``None``.

    An open repository is authoritative (the real server, and any injected
    per-test database). Otherwise an explicitly supplied ``database`` is used;
    with neither, tracing stays a no-op — an injected-adapters composition must
    not silently write into a developer's default database.
    """

    if isinstance(repo, SQLiteRepository):
        return repo.database_path
    if database is None:
        return None
    return resolve_database_path(database)


def _provider_request_event(request: SearchRequest | FetchRequest) -> dict[str, Any]:
    """Outbound provider input event: content yes, credentials/headers never."""

    if isinstance(request, SearchRequest):
        return {
            "query": request.query,
            "limit": request.limit,
            "mode": request.mode,
            "language": request.language,
            "country_code": request.country_code,
            "domains": list(request.domains),
        }
    return {
        "url": str(request.url),
        "max_chars": request.max_chars,
        "pdf_pages": request.pdf_pages,
        "json_extract": request.json_extract,
        "enhanced": request.enhanced,
    }


def _provider_response_event(response: SearchResponse | FetchResponse) -> dict[str, Any]:
    """Normalized provider response event (bounded; the root holds full output)."""

    if isinstance(response, SearchResponse):
        return {
            "result_count": len(response.results),
            "results": [item.model_dump() for item in _search_results_payload(response)],
        }
    document = response.document
    return {
        "result_count": 1,
        "url": str(document.url),
        "title": document.title,
        "content_length": len(document.content),
    }


def _result_count(response: SearchResponse | FetchResponse) -> int:
    """Return how many results the caller received."""

    return len(response.results) if isinstance(response, SearchResponse) else 1


def _annotate_root_request_identity(
    observability: ObservabilityRuntime,
    request: SearchRequest | FetchRequest,
    provider: ProviderAdapter,
) -> None:
    """Keep the request identity on a failed root span.

    The success path projects the same fields from the response. A failure
    never reaches that projection, so the Activity row would lose its title
    and the Provider column would show a dash.
    """

    attributes: dict[str, object] = {
        TraceAttribute.OPERATION: _operation_name(request).value,
        TraceAttribute.PROVIDER: provider.name,
    }
    if isinstance(request, SearchRequest):
        attributes[TraceAttribute.REQUEST_QUERY] = request.query
    observability.annotate_root(attributes)


_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _schedule_quota_refresh(
    repository: SQLiteRepository | None,
    routes: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore | None,
) -> None:
    """Schedule asynchronous quota polling out-of-band without blocking the request hot path."""

    if repository is None or not routes:
        return
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(refresh_quotas(repository, routes, secret_store=secret_store))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except RuntimeError:
        pass


async def _routing_state(
    repository: SQLiteRepository | None,
    routes: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore,
) -> tuple[dict[str, ProviderHealth], dict[str, QuotaSnapshot]]:
    """Refresh bounded quota state in background and collect health/quota maps for routing."""

    if repository is None or not routes:
        return {}, {}
    _schedule_quota_refresh(repository, routes, secret_store)
    provider_names = [adapter.name for adapter in routes]
    health: dict[str, ProviderHealth] = {}
    try:
        if hasattr(repository, "latest_health_batch"):
            health = await repository.latest_health_batch(provider_names)
        else:
            for adapter in routes:
                observation = await repository.latest_health(adapter.name)
                if observation is not None:
                    health[adapter.name] = observation
    except Exception:
        pass

    quotas: dict[str, QuotaSnapshot] = {}
    try:
        if hasattr(repository, "latest_quota_batch"):
            quotas = await effective_quotas_batch(repository, provider_names)
        else:
            for adapter in routes:
                snapshot = await effective_quota(repository, adapter.name)
                if snapshot is not None:
                    quotas[adapter.name] = snapshot
    except Exception:
        pass

    return health, quotas


def _usage_operation(request: SearchRequest | FetchRequest) -> UsageOperation:
    """Return the usage operation of a provider-querying request."""

    return UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH


async def _plan_route(
    request: SearchRequest | FetchRequest,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore,
) -> tuple[ProviderAdapter, ...]:
    """Return the ordered adapters to attempt for ``request``.

    The in-memory routes are filtered by effective access, sorted by persisted
    priority, pinned for the cost preset, truncated by the fallback policy,
    and finally ranked by ``select_route``. A single candidate path stays
    identical to the pre-control routing contract.
    """

    if not routes:
        raise HTTPException(
            status_code=503,
            detail=(
                "no provider is configured: store a key in the encrypted vault "
                "(PUT /api/v1/providers/{id}/secret)"
            ),
        )

    # Fast-path for explicit provider requirement
    preference = request.routing
    if preference.mode is RoutingMode.REQUIRE and preference.providers:
        required_names = set(preference.providers)
        matching = [adapter for adapter in routes if adapter.name in required_names]
        if not matching:
            raise HTTPException(
                status_code=503,
                detail=f"no required provider is eligible: {', '.join(preference.providers)}",
            )
        routes = tuple(matching)

    operation = _usage_operation(request)
    policy = await routing_policy(repository)
    try:
        ordered = await _order_routes(
            routes, repository, policy.cost_optimization_preset, operation
        )
    except ProviderConfigError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if policy.fallback_policy is FallbackPolicy.FIRST_ONLY:
        ordered = ordered[:1]
    health_snapshots, quota_snapshots = await _routing_state(repository, ordered, secret_store)
    try:
        candidates = select_route(request, ordered, health_snapshots, quota_snapshots)
    except RoutingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not candidates:
        raise HTTPException(
            status_code=503,
            detail=f"no eligible provider is available for {operation.value}",
        )
    # A per-request allow_fallback=false already truncates inside select_route;
    # the global first_only policy truncates above.
    chained = request.routing.allow_fallback and policy.fallback_policy is FallbackPolicy.CHAINED
    if chained:
        return tuple(candidate.adapter for candidate in candidates)
    return (candidates[0].adapter,)


async def _execute_fetch(app: FastAPI, request: FetchRequest) -> FetchResponse | JSONResponse:
    """Execute a fetch request through route planning, dispatch, and graceful error handling."""

    observability = current_observability()
    with observability.span(TraceSpanName.BACKEND, attributes=_request_attributes(request)):
        _require_single_url(request)
        try:
            return await _dispatch(
                request,
                UsageOperation.FETCH,
                lambda target, req: target.fetch(req),
                routes=app.state._routes,
                repository=app.state.repository,
                secret_store=app.state.secret_store,
                limits=app.state.limits,
            )
        except ProviderOperationError as exc:
            return _fetch_provider_error_response(exc)


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
    limits: ProviderLimitsService | None = None,
) -> ResponseT:
    """Run the routed adapter call for the best policy-ordered candidate.

    The candidate ordering applies the persisted enablement, priority, cost
    preset, and fallback policy; adapter failures propagate unchanged so the
    REST 500 / MCP ToolError contracts are preserved (no cross-adapter retry
    on failure, pinned by the offline BDD failure scenario).

    The request shape reaches the common execution seam as an additive keyword,
    so the local funds and rate gate can price the request after the unchanged
    route selection.

    Trace shape: ``freesearch.route`` (planning), ``freesearch.provider``
    (one client span per attempted provider, with request/response events), and
    ``freesearch.results`` (response projection). With a single candidate there
    is nothing to fuse, so the results stage is the projection and root summary
    annotation itself.
    """

    observability = current_observability()
    with observability.span(TraceSpanName.ROUTE, attributes=_request_attributes(request)):
        attempts = await _plan_route(request, routes, repository, secret_store)

    last_error: ProviderOperationError | None = None
    for attempt_idx, provider in enumerate(attempts):
        is_last = attempt_idx == len(attempts) - 1
        with observability.span(
            TraceSpanName.PROVIDER,
            kind=SpanKindName.CLIENT,
            attributes={
                TraceAttribute.OPERATION: _operation_name(request).value,
                TraceAttribute.PROVIDER: provider.name,
                TraceAttribute.ROUTING_CANDIDATE_COUNT: len(attempts),
            },
        ) as provider_span:
            provider_span.add_event(
                TRACE_EVENT_PROVIDER_REQUEST, attributes=_provider_request_event(request)
            )
            try:
                response = await tracked_call(
                    repository,
                    provider,
                    lambda target: invoke(target, request),
                    operation=operation,
                    request=request,
                    limits=limits,
                )
            except ProviderOperationError as error:
                provider_span.record_exception(error)
                last_error = error
                if is_last:
                    _annotate_root_error(observability, error)
                    _annotate_root_request_identity(observability, request, provider)
                    raise
                continue
            except Exception as error:
                _annotate_root_error(observability, error)
                _annotate_root_request_identity(observability, request, provider)
                raise
            provider_span.add_event(
                TRACE_EVENT_PROVIDER_RESPONSE, attributes=_provider_response_event(response)
            )
        with observability.span(
            TraceSpanName.RESULTS,
            attributes={TraceAttribute.OPERATION: _operation_name(request).value},
        ) as results_span:
            results_span.set_attributes(
                {TraceAttribute.RESPONSE_RESULT_COUNT: _result_count(response)}
            )
            _annotate_root(observability, request, response)
        return response

    if last_error is not None:
        raise last_error
    raise RuntimeError("route planning produced zero attempts")


def _terminal_quota_402(exc: BaseException) -> ProviderOperationError | None:
    """Return the terminal provider out-of-credits error, else ``None``.

    The vendor 402 normalizes to ``quota_exhausted`` with ``status_code=402``
    and ``retryable=False``; only that exact shape is a terminal transport,
    never classified as rate limiting or a generic failure.
    """

    if not isinstance(exc, ProviderOperationError):
        return None
    if (
        exc.error.provider in ("tavily", "firecrawl", "exa")
        and exc.error.code == "quota_exhausted"
        and exc.error.status_code == 402
    ):
        return exc
    return None


# Retain alias for backwards compatibility
_terminal_tavily_402 = _terminal_quota_402


async def _provider_operation_error(request: Request, exc: Exception) -> Response:
    """Transport one :class:`ProviderOperationError` through its REST contract.

    A terminal provider out-of-credits error (e.g. Tavily, Firecrawl) is an HTTP 402
    with the safe message and named provider. Every other error re-raises, so
    FastAPI's standard 500 flow stays untouched for all providers.
    """

    return _provider_operation_error_response(exc)


def _provider_operation_error_response(exc: Exception) -> JSONResponse:
    """Return the response for one :class:`ProviderOperationError`.

    A terminal provider out-of-credits error (e.g. Tavily, Firecrawl) is an HTTP 402
    with the safe message and named provider. Every other error re-raises, so
    FastAPI's standard 500 flow stays untouched for all providers.
    """

    terminal = _terminal_quota_402(exc)
    if terminal is None:
        raise exc
    return JSONResponse(
        status_code=402,
        content={"detail": terminal.error.message, "provider": terminal.error.provider},
    )


def _fetch_provider_error_response(exc: ProviderOperationError) -> JSONResponse:
    """Return the structured HTTP response for a fetch ProviderOperationError.

    Terminal out-of-credits errors map to HTTP 402 with detail and provider name.
    Upstream rate limits map to HTTP 429. All other upstream provider rejections
    (target site blocked, bot_blocked, fetch_failed, upstream 403/500) map to
    HTTP 502 Bad Gateway with structured diagnostics.
    """

    terminal = _terminal_quota_402(exc)
    if terminal is not None:
        return JSONResponse(
            status_code=402,
            content={"detail": terminal.error.message, "provider": terminal.error.provider},
        )
    if exc.error.status_code == 429 or exc.error.code == "rate_limited":
        return JSONResponse(
            status_code=429,
            content={
                "detail": exc.error.message,
                "provider": exc.error.provider,
                "code": exc.error.code,
                "status_code": 429,
            },
        )
    return JSONResponse(
        status_code=502,
        content={
            "detail": exc.error.message,
            "provider": exc.error.provider,
            "code": exc.error.code,
            "status_code": exc.error.status_code,
        },
    )


def _fanout_failure_outcome(
    adapter_name: str,
    exc: Exception,
    elapsed_ms: int,
    *,
    provider_span: SpanHandle | None = None,
) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
    """Return the handled-failure outcome tuple for one fanout candidate.

    A vendor 429 keeps its distinctive outcome status; every other handled
    failure stays ``failed``. The tuple shape matches the pre-terminal
    ``asyncio.gather`` contract. A provider span in scope records the failure
    observably first, without ever failing the outcome path.
    """

    with suppress(Exception):
        if provider_span is not None:
            provider_span.record_exception(exc)
    status = "failed"
    if getattr(getattr(exc, "error", None), "status_code", None) == 429:
        status = "rate_limited"
    return (adapter_name, None, elapsed_ms, status, 0, str(exc))


def _fanout_waterfall(
    outcomes: Sequence[tuple[str, SearchResponse | None, int, str, int, str | None]],
) -> tuple[list[ProviderTraceItem], list[tuple[str, SearchResponse]], list[str]]:
    """Split handled fanout outcome tuples into the fusion waterfall inputs.

    The splitter is a pure helper of :func:`_dispatch_fanout_search`; the
    guarded ``_call`` closure keeps the fanout invariant branches, and the
    project cyclomatic budget needs this loop body out of the dispatch
    function.
    """

    waterfall: list[ProviderTraceItem] = []
    successful_results: list[tuple[str, SearchResponse]] = []
    errors: list[str] = []
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
    return waterfall, successful_results, errors


async def _fanout_outcomes[T](tasks: list[asyncio.Task[T]]) -> list[T]:
    """Await fanout tasks in candidate order, honoring a terminal 402.

    Tasks either complete with an outcome tuple or raise the terminal Tavily
    402 (the surrounding ``_call`` returns the tuple form for every other
    failure, so local admission denials keep the former gather semantics).
    The first exception therefore is the terminal error: its re-raise cancels
    the pending tasks and awaits their settlement before propagation, so no
    provider call races the closing request. Without a terminal, outcomes
    come back in the original candidate order — the same order
    ``asyncio.gather`` produced before.
    """

    if not tasks:
        return []
    task_index = {task: index for index, task in enumerate(tasks)}
    outcomes_by_index: dict[int, T] = {}
    pending: set[asyncio.Task[T]] = set(tasks)
    terminal: BaseException | None = None
    while pending and terminal is None:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error is None:
                outcomes_by_index[task_index[task]] = task.result()
            elif terminal is None:
                # ``_call`` only ever re-raises the terminal Tavily 402; every
                # other failure already took the outcome-tuple form.
                terminal = error
    if terminal is not None:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise terminal
    return [outcomes_by_index[index] for index in range(len(tasks))]


async def _dispatch_fanout_search(
    request: SearchRequest,
    *,
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore,
    limits: ProviderLimitsService | None = None,
) -> SearchResponse:
    """Execute search across all eligible configured providers concurrently and fuse results.

    Trace shape: one root with a ``freesearch.route`` planning span, one
    concurrent ``freesearch.provider`` client span per candidate, and a single
    ``freesearch.results`` span around the RRF assembly — never one trace per
    provider. A handled provider failure marks that child ERROR and the root
    ``partial`` (the caller still received a response).

    A terminal Tavily out-of-Credits 402 is preserved even when another
    provider succeeds: the remaining fanout tasks are cancelled and awaited,
    then the error propagates to the request-level 402 transport instead of a
    fused response.
    """
    if not routes:
        raise HTTPException(
            status_code=503,
            detail=(
                "no provider is configured: store a key in the encrypted vault "
                "(PUT /api/v1/providers/{id}/secret)"
            ),
        )

    fanout_routes = routes
    if request.routing.providers:
        required_names = set(request.routing.providers)
        matching = [adapter for adapter in routes if adapter.name in required_names]
        if not matching:
            raise HTTPException(
                status_code=503,
                detail="no eligible provider is available for fanout",
            )
        fanout_routes = matching

    observability = current_observability()
    with observability.span(TraceSpanName.ROUTE, attributes=_request_attributes(request)):
        policy = await routing_policy(repository)
        try:
            ordered = await _order_routes(
                fanout_routes, repository, policy.cost_optimization_preset, UsageOperation.SEARCH
            )
        except ProviderConfigError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        health_snapshots, quota_snapshots = await _routing_state(repository, ordered, secret_store)
        fanout_request = request.model_copy(
            update={"routing": request.routing.model_copy(update={"mode": RoutingMode.FANOUT})}
        )
        try:
            candidates = select_route(fanout_request, ordered, health_snapshots, quota_snapshots)
        except RoutingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not candidates:
            raise HTTPException(
                status_code=503, detail="no eligible provider is available for search"
            )

    overall_start = time.perf_counter()

    async def _call(
        candidate_adapter: ProviderAdapter,
    ) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
        call_start = time.perf_counter()
        provider_span: SpanHandle | None = None
        try:
            with observability.span(
                TraceSpanName.PROVIDER,
                kind=SpanKindName.CLIENT,
                attributes={
                    TraceAttribute.OPERATION: TraceOperation.SEARCH.value,
                    TraceAttribute.PROVIDER: candidate_adapter.name,
                    TraceAttribute.ROUTING_MODE: RoutingMode.FANOUT.value,
                    TraceAttribute.ROUTING_CANDIDATE_COUNT: len(candidates),
                },
            ) as provider_span:
                provider_span.add_event(
                    TRACE_EVENT_PROVIDER_REQUEST, attributes=_provider_request_event(request)
                )
                try:
                    res = await tracked_call(
                        repository,
                        candidate_adapter,
                        lambda target: target.search(request),
                        operation=UsageOperation.SEARCH,
                        request=request,
                        limits=limits,
                    )
                except Exception as exc:
                    elapsed = int((time.perf_counter() - call_start) * 1000)
                    if _terminal_quota_402(exc) is not None:
                        # The terminal out-of-Credits error is the transport: the
                        # span context records it once as it re-raises (the same
                        # shape as the single-path provider failure), and the
                        # request-level 402 handler turns it into the body.
                        raise
                    provider_span.record_exception(exc)
                    return _fanout_failure_outcome(candidate_adapter.name, exc, elapsed)
                provider_span.add_event(
                    TRACE_EVENT_PROVIDER_RESPONSE, attributes=_provider_response_event(res)
                )
                elapsed = int((time.perf_counter() - call_start) * 1000)
                return (candidate_adapter.name, res, elapsed, "success", len(res.results), None)
        except Exception as exc:
            # The guarded fanout invariant (see _fanout_outcomes): only the
            # terminal Tavily 402 escapes _call. Machinery failures outside the
            # tracked_call try (span bookkeeping, event serialization) convert
            # to the handled outcome tuple, never to a raised task error; the
            # outcome path records the exception on its provider span.
            # CancelledError is a BaseException, so a cancelled task still
            # surfaces as cancelled and _fanout_outcomes skips it.
            if _terminal_quota_402(exc) is not None:
                raise
            return _fanout_failure_outcome(
                candidate_adapter.name,
                exc,
                int((time.perf_counter() - call_start) * 1000),
                provider_span=provider_span,
            )

    tasks = [asyncio.ensure_future(_call(c.adapter)) for c in candidates]
    outcomes = await _fanout_outcomes(tasks)

    waterfall, successful_results, errors = _fanout_waterfall(outcomes)

    if not successful_results:
        first_err = errors[0] if errors else "all providers failed"
        failure = HTTPException(
            status_code=500,
            detail=f"all search providers failed: {first_err}",
        )
        _annotate_root_error(observability, failure)
        raise failure

    with observability.span(
        TraceSpanName.RESULTS,
        attributes={
            TraceAttribute.OPERATION: TraceOperation.SEARCH.value,
            TraceAttribute.ROUTING_CANDIDATE_COUNT: len(candidates),
        },
    ) as results_span:
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

        response = SearchResponse(
            query=request.query,
            results=fused_results,
            provider="aggregated" if len(successful_results) > 1 else successful_results[0][0],
            total_results=len(fused_results),
            participating_providers=participating,
            waterfall=waterfall,
        )
        results_span.set_attributes({TraceAttribute.RESPONSE_RESULT_COUNT: len(fused_results)})
        _annotate_root(observability, request, response)
    return response


def _clamped_limit(limit: int) -> int:
    """Clamp a requested recent-usage limit into ``[1, MAX_RECENT_LIMIT]``."""

    return min(max(limit, 1), MAX_RECENT_LIMIT)


def main(argv: Sequence[str] | None = None) -> None:
    """Serve the API with uvicorn (Swagger at /docs).

    The default store encrypts provider and OAuth secrets in local SQLite.
    Injected stores remain available for offline tests.

    The bind address is loopback by default for local development; containers
    override it with ``--host 0.0.0.0`` (or ``FREESEARCH_API_HOST``). The port
    comes from ``FREESEARCH_API_PORT`` or from an explicit ``--port`` value, and
    no numeric fallback exists, so a missing port stops the launch.
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="FreeSearch REST API")
    parser.add_argument(
        "--host",
        default=None,
        help="HTTP host override (env: FREESEARCH_API_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port override (env: FREESEARCH_API_PORT)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    overrides: dict[str, Any] = {}
    if args.host:
        overrides["api_host"] = args.host
    if args.port is not None:
        overrides["api_port"] = args.port
    effective = settings.model_copy(update=overrides) if overrides else settings

    uvicorn.run(
        create_app(),
        host=effective.api_host,
        port=require_transport_port(effective, transport="api"),
    )


if __name__ == "__main__":
    main()
