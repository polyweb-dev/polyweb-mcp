"""REST API for the FreeSearch providers: FastAPI app with OpenAPI docs.

Thin HTTP layer over the shared project execution service: every search and
fetch resolves the verified project scope first, then runs the one
transport-independent execution path (bindings, strict caps, telemetry)
through :class:`freesearch.services.execution.ExecutionService`. Responses are
the provider-neutral contract models, so the OpenAPI schema at ``/docs``
documents them directly.

Every search/fetch call records usage, health, and quota telemetry through
:mod:`freesearch.services.monitoring`, the loopback monitoring reads
(``/stats``, ``/dashboard``) expose that telemetry, and the control plane
(:mod:`freesearch.routers.control`) serves the ``/api/v1`` provider
configuration and routing-policy endpoints. Credential mutations use the
credential-instance endpoints. Execution runs strictly through the project's
enabled credentials.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import close_adapters
from freesearch.configuration.config import get_settings, require_transport_port
from freesearch.infrastructure.auth_asgi import (
    OPERATION_ROUTES,
    BearerAuthMiddleware,
    current_verified_principal,
)
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    load_secret_codec,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.observability import (
    NO_OP_OBSERVABILITY,
    ObservabilityRuntime,
    bind_execution_attribution,
    bind_trace_capture,
    build_observability,
)
from freesearch.infrastructure.observability_asgi import (
    INGRESS_MONOTONIC_STATE_KEY,
    IngressDeadlineMiddleware,
    ProviderTraceMiddleware,
)
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import AsyncSecretStore
from freesearch.models.contracts import (
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
)
from freesearch.models.execution_failures import (
    ExecutionAuthorityUnavailable,
    ExecutionQueueExpired,
    ExecutionQueueSaturated,
)
from freesearch.models.observability import ExecutionAttribution, TraceRootSpan
from freesearch.models.projects import PermissionAction, ProjectApiKeyPrincipal, ProjectContext
from freesearch.models.provider_limits import (
    LimitDeniedError,
    LimitStoreUnavailable,
    SyncResult,
)
from freesearch.models.quota_api import USDProviderLimits
from freesearch.models.users import UserPrincipal
from freesearch.persistence.database_migrations import (
    DatabaseResetRequired,
    exit_if_database_reset_required,
    upgrade_database,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api_keys import register_api_key_routes
from freesearch.routers.auth import register_auth_routes, require_control_reader
from freesearch.routers.bindings import register_binding_routes
from freesearch.routers.control import register_control_routes
from freesearch.routers.credentials import register_project_credential_read_routes
from freesearch.routers.limits import limit_denial_response, register_limit_routes
from freesearch.routers.observability import register_observability_routes
from freesearch.routers.project_pools import router as project_pools_router
from freesearch.routers.project_routing import register_project_routing_routes
from freesearch.routers.projects import register_project_routes
from freesearch.routers.retention import register_retention_routes
from freesearch.routers.settings import register_settings_routes
from freesearch.routers.vault_keys import router as vault_keys_router
from freesearch.routers.vault_pools import router as vault_pools_router
from freesearch.services.api_keys import DEFAULT_USE_RECORDER, ApiKeyVerifier
from freesearch.services.authorization import human_principal
from freesearch.services.execution import (
    ExecutionAllFailed,
    ExecutionError,
    ExecutionNotPermitted,
    ExecutionRequestInvalid,
    ExecutionService,
    _terminal_out_of_credits,
)
from freesearch.services.execution_scope import (
    ExecutionForbidden,
    ExecutionProjectArchived,
    ExecutionProjectRequired,
    ExecutionScopeError,
    ExecutionStorageUnavailable,
    ExecutionUnauthenticated,
    execution_attribution,
    resolve_execution_boundary,
)
from freesearch.services.limits_sync import LimitSyncService
from freesearch.services.monitoring import (
    MAX_RECENT_LIMIT,
    DashboardResponse,
    StatsResponse,
    clear_quota_poll_cache,
    collect_stats,
    resolve_database_path,
)
from freesearch.services.provider_runtime import (
    clear_config_cache,
    initialize_provider_configs,
)
from freesearch.services.users import AuthService

logger = logging.getLogger(__name__)

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


def _execution_repository(app: FastAPI) -> SQLiteRepository | None:
    """Return the repository that owns projects, keys and execution scope."""

    repository: SQLiteRepository | None = app.state.repository
    return repository


async def _verify_api_key(app: FastAPI, token: str) -> ProjectApiKeyPrincipal | None:
    """Verify one project API key on an execution route; nothing is cached."""

    repository = _execution_repository(app)
    if repository is None:
        return None
    return await ApiKeyVerifier(repository).verify(token)


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
    # The per-credential adapters close with their cache first, so no poll can
    # race a closing database.
    execution = app.state.execution
    app.state.execution = None
    if execution is not None:
        await execution.aclose()
    # Queued API key bookkeeping (use stamps, denial events) finishes before
    # any repository closes, injected or owned.
    await DEFAULT_USE_RECORDER.drain()
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
            await _compose_runtime_generation(
                app,
                repo,
                routes=routes,
                owns_adapters=adapters is None,
                adapter_source=adapters,
                owns_client=owns_client,
                database=database,
                stop_limits=stop_limits,
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
    app.state.execution = None
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
        verify_api_key=lambda token: _verify_api_key(app, token),
        api_key_routes=OPERATION_ROUTES,
        registration_limit=lambda peer: _reserve_registration(app, peer),
    )
    # Added last, so arrival time is stamped before authentication and body
    # processing as well as before the handler's own deadline logic.
    app.add_middleware(IngressDeadlineMiddleware)
    register_auth_routes(app)
    register_project_routes(app)
    register_project_routing_routes(app)
    register_api_key_routes(app)
    register_settings_routes(app)
    register_retention_routes(app)
    register_project_credential_read_routes(app)
    app.include_router(vault_keys_router)
    app.include_router(vault_pools_router)
    app.include_router(project_pools_router)
    register_binding_routes(app)
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

    @app.exception_handler(ExecutionQueueSaturated)
    async def _queue_saturated(_: Any, exc: ExecutionQueueSaturated) -> JSONResponse:
        """Queue saturation is its own bounded-capacity refusal."""

        return JSONResponse(
            status_code=429,
            content={"detail": exc.detail},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.exception_handler(ExecutionQueueExpired)
    async def _queue_expired(_: Any, exc: ExecutionQueueExpired) -> JSONResponse:
        """An expired queue wait is retriable and distinct from rate denial."""

        return JSONResponse(
            status_code=429,
            content={"detail": exc.detail},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    @app.exception_handler(ExecutionAuthorityUnavailable)
    async def _authority_unavailable(_: Any, exc: ExecutionAuthorityUnavailable) -> JSONResponse:
        """No authority may dispatch a borrowed pool: fail closed, no bypass."""

        return JSONResponse(status_code=503, content={"detail": exc.detail})

    # Module-level handler: a terminal Tavily out-of-Credits error is a 402;
    # every other ProviderOperationError re-raises into the standard 500 flow.
    app.add_exception_handler(ProviderOperationError, _provider_operation_error)

    async def search(request: SearchRequest, http_request: Request) -> SearchResponse:
        """Search through the project's best available provider or all concurrently."""

        deadline = _request_deadline(http_request)
        try:
            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                attribution, context = await _resolve_execution(
                    app, request.project_id, PermissionAction.SEARCH_EXECUTE
                )
                return await _search_route(
                    app,
                    request,
                    attribution=attribution,
                    context=context,
                    deadline=deadline,
                )
        except TimeoutError as error:
            raise _deadline_expired() from error

    async def fetch(request: FetchRequest, http_request: Request) -> FetchResponse | JSONResponse:
        """Fetch a URL's content through the project's best available provider."""

        deadline = _request_deadline(http_request)
        try:
            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                attribution, context = await _resolve_execution(
                    app, request.project_id, PermissionAction.FETCH_EXECUTE
                )
                return await _fetch_route(
                    app,
                    request,
                    attribution=attribution,
                    context=context,
                    deadline=deadline,
                )
        except TimeoutError as error:
            raise _deadline_expired() from error

    app.post("/search", response_model=SearchResponse)(search)
    app.post("/fetch", response_model=FetchResponse)(fetch)

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
            spend_totals=snapshot.spend_totals,
            provider_limits=[
                USDProviderLimits.model_validate(row)
                for row in await _provider_limits(app.state.limits)
            ],
            generated_at=datetime.now(UTC),
        )

    return app


async def _search_route(
    app: FastAPI,
    request: SearchRequest,
    *,
    attribution: ExecutionAttribution,
    context: ProjectContext,
    deadline: float | None = None,
) -> SearchResponse:
    """REST search body: the shared execution service with one mapping layer."""

    execution: ExecutionService | None = app.state.execution
    if execution is None:
        # A composition without the execution service cannot execute safely:
        # fail closed before any binding or provider read happens.
        raise HTTPException(status_code=503, detail="execution is temporarily unavailable")
    try:
        return await execution.search(
            request, attribution=attribution, context=context, deadline=deadline
        )
    except ExecutionAllFailed as error:
        raise HTTPException(status_code=500, detail=error.detail) from error
    except ExecutionRequestInvalid as error:
        raise HTTPException(status_code=422, detail=error.detail) from error
    except ExecutionNotPermitted as error:
        # Live authority was revoked after the boundary admitted the request.
        raise HTTPException(status_code=403, detail="execution is not permitted") from error
    except (ExecutionQueueSaturated, ExecutionQueueExpired) as error:
        raise HTTPException(
            status_code=429,
            detail=error.detail,
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except ExecutionError as error:
        raise HTTPException(status_code=503, detail=error.detail) from error


async def _fetch_route(
    app: FastAPI,
    request: FetchRequest,
    *,
    attribution: ExecutionAttribution,
    context: ProjectContext,
    deadline: float | None = None,
) -> FetchResponse | JSONResponse:
    """REST fetch body: the shared execution service with one mapping layer."""

    execution: ExecutionService | None = app.state.execution
    if execution is None:
        raise HTTPException(status_code=503, detail="execution is temporarily unavailable")
    try:
        return await execution.fetch(
            request, attribution=attribution, context=context, deadline=deadline
        )
    except ExecutionRequestInvalid as error:
        raise HTTPException(status_code=422, detail=error.detail) from error
    except ExecutionNotPermitted as error:
        # Live authority was revoked after the boundary admitted the request.
        raise HTTPException(status_code=403, detail="execution is not permitted") from error
    except (ExecutionQueueSaturated, ExecutionQueueExpired) as error:
        raise HTTPException(
            status_code=429,
            detail=error.detail,
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except ExecutionError as error:
        raise HTTPException(status_code=503, detail=error.detail) from error
    except ProviderOperationError as exc:
        return _fetch_provider_error_response(exc)


async def _compose_runtime_generation(
    app: FastAPI,
    repo: SQLiteRepository | None,
    *,
    routes: list[ProviderAdapter],
    owns_adapters: bool,
    adapter_source: Sequence[ProviderAdapter] | None,
    owns_client: bool,
    database: str | Path | None,
    stop_limits: asyncio.Event,
) -> None:
    """Build one runtime generation: adapters, limit rails, execution, tracing.

    The compose step belongs to the lifespan: the quota state hydrates, the
    limit schedule starts, and the shared execution service (repository,
    encrypted credential slots, and limit rails) comes up before requests.
    """

    del adapter_source
    if isinstance(repo, SQLiteRepository):
        await initialize_provider_configs(repo)
    await _start_limits(app, repo, routes, stop_limits)
    # The execution service is the one path shared with MCP; it needs the
    # repository, the encrypted store (credential slots), and the limit rails,
    # so it starts after them and closes in teardown.
    if isinstance(repo, SQLiteRepository) and isinstance(
        app.state.secret_store, EncryptedDbSecretStore
    ):
        app.state.execution = ExecutionService(
            repository=repo,
            secret_store=app.state.secret_store,
            client=app.state._client if owns_client else None,
            limits=app.state.limits,
        )
    trace_database = _trace_database(repo, database)
    if trace_database is not None and not isinstance(repo, SQLiteRepository):
        # An injected-adapters composition can still point at a trace database;
        # adopt it (upgrade + validate) before the exporter starts writing. A
        # failure here is not fatal: the exporter reports a failed batch
        # instead of failing user requests.
        with suppress(Exception):
            await _prepare_trace_database(trace_database)
    app.state.observability = build_observability(get_settings(), database=trace_database)


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
    from freesearch.services.provider_limits import ProviderLimitsService

    limits = ProviderLimitsService(repo.limits)
    await limits.initialize()
    apply_keenable_auth_mode(routes, limits)
    app.state.limits = limits

    async def sync_system_credentials(provider: str, now: datetime) -> SyncResult | None:
        # The execution service starts after the limit rails, so the manual
        # refresh resolves it per call; without one there is nothing to poll.
        execution = getattr(app.state, "execution", None)
        if execution is None:
            return None
        result: SyncResult = await execution.sync_system_limits(provider, now)
        return result

    app.state.limits_sync = LimitSyncService(
        repo.limits, limits, lambda: routes, credential_sync=sync_system_credentials
    )
    # Credential-scoped observations are scheduled only by admitted execution
    # and by the admin's manual refresh, which polls the provider's active
    # vault credentials. There is no global vendor polling schedule.


def apply_keenable_auth_mode(routes: Sequence[ProviderAdapter], limits: Any) -> None:
    """Project Keenable's keyless-or-keyed rail choice into the limit service."""

    from freesearch.infrastructure.secrets import ProviderName as _ProviderName

    adapter = next((route for route in routes if route.name == _ProviderName.KEENABLE.value), None)
    if adapter is not None:
        limits.apply_keenable_auth_mode(adapter.limit_auth_mode)


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


async def _provider_limits(limits: Any) -> list[Any]:
    """Read every provider card payload best effort; a failure yields none."""

    if limits is None:
        return []
    try:
        cards = await limits.dashboard_views()
    except Exception:
        return []
    return list(cards)


def _clamped_limit(limit: int) -> int:
    """Clamp a requested recent-usage limit into ``[1, MAX_RECENT_LIMIT]``."""

    return min(max(limit, 1), MAX_RECENT_LIMIT)


async def _prepare_trace_database(trace_database: Path) -> None:
    """Upgrade the trace database, logging the reset instructions when it is refused."""

    try:
        await asyncio.to_thread(upgrade_database, trace_database)
    except DatabaseResetRequired as error:
        logger.warning("trace database refused: %s", error)
        raise


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


_DEADLINE_HEADER = "x-freesearch-deadline-ms"


def _deadline_expired() -> HTTPException:
    """Return the retriable REST refusal for an elapsed logical deadline."""

    return HTTPException(
        status_code=429,
        detail="the execution request deadline expired before dispatch",
        headers={"Retry-After": "1"},
    )


def _request_deadline(request: Request) -> float:
    """Translate the ingress instant and forwarded deadline to monotonic time.

    The server's configured logical request timeout is the outer bound and it
    starts at arrival, before authentication and body processing. A client
    deadline can only shorten it. An absent, malformed, non-positive, or
    oversized header therefore falls back to the server bound instead of
    extending the request or raising ``OverflowError``. A deadline already in
    the past maps to "now", so queued work expires before any provider attempt.
    """

    settings = get_settings()
    server_ms = max(1, int(settings.execution_request_timeout_seconds * 1000))
    ingress = getattr(request.state, INGRESS_MONOTONIC_STATE_KEY, None)
    elapsed_ms = (
        0 if not isinstance(ingress, (int, float)) else int((time.monotonic() - ingress) * 1000)
    )
    remaining_ms = max(0, server_ms - elapsed_ms)
    raw = request.headers.get(_DEADLINE_HEADER)
    if raw is not None and len(raw) <= 32:
        try:
            deadline_ms = int(raw)
        except (TypeError, ValueError):
            deadline_ms = 0
        if deadline_ms > 0:
            remaining_ms = min(remaining_ms, deadline_ms - int(time.time() * 1000))
    return time.monotonic() + max(0.0, remaining_ms / 1000.0)


def _execution_scope_http_error(error: ExecutionScopeError) -> HTTPException:
    """Map one scope failure onto its generic REST status without the reason."""

    if isinstance(error, ExecutionUnauthenticated):
        return HTTPException(
            status_code=401,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(error, ExecutionStorageUnavailable):
        return HTTPException(status_code=503, detail="execution is temporarily unavailable")
    if isinstance(error, ExecutionProjectRequired):
        return HTTPException(status_code=422, detail="project_id is required")
    if isinstance(error, ExecutionProjectArchived):
        return HTTPException(status_code=409, detail="project is archived")
    if isinstance(error, ExecutionForbidden):
        return HTTPException(status_code=403, detail="execution is not permitted")
    return HTTPException(status_code=404, detail="project is unavailable")


async def _resolve_execution(
    app: FastAPI, project_id: Any, action: PermissionAction
) -> tuple[ExecutionAttribution, ProjectContext]:
    """Resolve the request's execution scope and bind its trusted telemetry.

    This is the first step of every provider-executing route — before route
    planning, admission, or provider I/O — so a rejected request leaves no
    usage rows and no attributed trace spans. A human session executes through
    its live project membership; a project API key executes only in its own
    project with its own scopes. The project trace policy is resolved here too,
    once, so every span of the request carries the same immutable capture and
    sampling decision. The resolved context (with the guard-verified
    principal) flows to the execution service, which re-authorizes it against
    live state before any credential is resolved.
    """

    verified = current_verified_principal()
    principal = human_principal(verified) if isinstance(verified, UserPrincipal) else verified
    repository = _execution_repository(app)
    try:
        boundary = await resolve_execution_boundary(
            repository,
            principal,
            project_id=project_id,
            action=action,
        )
    except ExecutionScopeError as error:
        raise _execution_scope_http_error(error) from error
    attribution = execution_attribution(boundary.context)
    bind_execution_attribution(attribution)
    bind_trace_capture(boundary.trace_policy)
    return attribution, boundary.context


def _provider_operation_error(request: Request, exc: Exception) -> Response:
    """Transport one :class:`ProviderOperationError` through its REST contract.

    A terminal provider out-of-credits error (e.g. Tavily, Firecrawl) is an HTTP
    402, and a normalized upstream rate error is a 429 carrying its parsed
    Retry-After delay. Every other provider error re-raises into the standard
    500 flow.
    """

    del request
    if isinstance(exc, ProviderOperationError):
        rate = _provider_rate_response(exc)
        if rate is not None:
            return rate
    return _provider_operation_error_response(exc)


def _provider_operation_error_response(exc: Exception) -> JSONResponse:
    """Return the response for one :class:`ProviderOperationError`.

    A terminal provider out-of-credits error (e.g. Tavily, Firecrawl) is an HTTP 402
    with the safe message and named provider. Every other error re-raises, so
    FastAPI's standard 500 flow stays untouched for all providers.
    """

    terminal = _terminal_out_of_credits(exc)
    if terminal is not None:
        return JSONResponse(
            status_code=402,
            content={"detail": terminal.error.message, "provider": terminal.error.provider},
        )
    raise exc


def _fetch_provider_error_response(exc: ProviderOperationError) -> JSONResponse:
    """Return the structured HTTP response for a fetch ProviderOperationError.

    Terminal out-of-credits errors map to HTTP 402 with detail and provider name.
    Upstream rate limits map to HTTP 429. All other upstream provider rejections
    (target site blocked, bot_blocked, fetch_failed, upstream 403/500) map to
    HTTP 502 Bad Gateway with structured diagnostics.
    """

    terminal = _terminal_out_of_credits(exc)
    if terminal is not None:
        return JSONResponse(
            status_code=402,
            content={"detail": terminal.error.message, "provider": terminal.error.provider},
        )
    rate = _provider_rate_response(exc)
    if rate is not None:
        return rate
    return JSONResponse(
        status_code=502,
        content={
            "detail": exc.error.message,
            "provider": exc.error.provider,
            "code": exc.error.code,
            "status_code": exc.error.status_code,
        },
    )


def _provider_rate_response(exc: ProviderOperationError) -> JSONResponse | None:
    """Project one normalized upstream rate error into a safe HTTP 429.

    The delay comes only from the adapter's parsed numeric Retry-After detail;
    an absent or malformed value keeps the response retriable without inventing
    a delay. Provider message content is not reflected beyond the normalized
    error object already used for local denials.
    """

    if exc.error.status_code != 429 and exc.error.code != "rate_limited":
        return None
    retry_after = _provider_retry_after_seconds(exc)
    headers = None if retry_after is None else {"Retry-After": str(retry_after)}
    return JSONResponse(
        status_code=429,
        content={
            "detail": exc.error.message,
            "provider": exc.error.provider,
            "code": exc.error.code,
            "status_code": 429,
        },
        headers=headers,
    )


def _provider_retry_after_seconds(exc: ProviderOperationError) -> int | None:
    """Return a positive whole-second upstream Retry-After delay, else ``None``."""

    details = exc.error.details if isinstance(exc.error.details, dict) else {}
    raw = details.get("retry_after_seconds")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = int(raw)
    return value if value >= 1 else None


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
    exit_if_database_reset_required(resolve_database_path(None))

    uvicorn.run(
        create_app(),
        host=effective.api_host,
        port=require_transport_port(effective, transport="api"),
    )


if __name__ == "__main__":
    main()
