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
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, TypedDict

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import SecretStr

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
from freesearch.infrastructure.observability import (
    DEFAULT_FLUSH_TIMEOUT_MILLIS,
    NO_OP_OBSERVABILITY,
    ObservabilityRuntime,
    SpanKindName,
    build_observability,
    use_observability,
)
from freesearch.infrastructure.observability_asgi import flush_traces
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.infrastructure.trace_payloads import (
    _annotate_root,
    _annotate_root_error,
    _request_attributes,
)
from freesearch.mcp.auth import (
    LocalTokenVerifier,
    McpAuthenticationError,
    build_auth_settings,
    require_mcp_user,
    run_http_server,
    run_stdio_server,
)
from freesearch.models.contracts import (
    FetchRequest,
    FetchResponse,
    ProviderHealth,
    ProviderTraceItem,
    QuotaSnapshot,
    RoutingMode,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.models.observability import (
    TRACE_SCHEMA_VERSION,
    TraceAttribute,
    TraceRootSpan,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.aggregation import reciprocal_rank_fusion
from freesearch.services.limits_sync import LimitSyncService
from freesearch.services.monitoring import (
    clear_quota_poll_cache,
    resolve_database_path,
    tracked_call,
)
from freesearch.services.provider_limits import ProviderLimitsService
from freesearch.services.routing import select_route
from freesearch.services.users import AuthService

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
    limits: "ProviderLimitsService | None"
    limits_sync: "LimitSyncService | None"
    limits_task: "asyncio.Task[None] | None"
    limits_stop: asyncio.Event | None
    observability: ObservabilityRuntime


async def _start_limits_generation(state: _ServerState, routes: Sequence[ProviderAdapter]) -> None:
    """Seed the limit catalog and start ONE schedule task for this generation.

    A server without a repository has no limit store, so no task starts. The
    task is per generation, never per MCP session.
    """

    repository = state["repository"]
    if not isinstance(repository, SQLiteRepository):
        return
    limits = ProviderLimitsService(repository.limits)
    await limits.initialize()
    stop = asyncio.Event()
    sync = LimitSyncService(repository.limits, limits, lambda: state["routes"] or [])
    state["limits"] = limits
    state["limits_sync"] = sync
    state["limits_stop"] = stop
    state["limits_task"] = asyncio.create_task(sync.run(stop))


async def _stop_limits_generation(state: _ServerState) -> None:
    """Stop and await the schedule task before the repository and adapters close."""

    stop = state["limits_stop"]
    if stop is not None:
        stop.set()
    task = state["limits_task"]
    if task is not None:
        task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await task
    state["limits"] = None
    state["limits_sync"] = None
    state["limits_task"] = None
    state["limits_stop"] = None


def _trace_database(
    repository: SQLiteRepository | None, database: str | Path | None
) -> Path | None:
    """Return the database that owns this server's traces, else ``None``.

    An open repository is authoritative. Otherwise an explicitly supplied
    database is used; with neither, tracing stays a no-op instead of silently
    writing into a developer's default database.
    """

    if isinstance(repository, SQLiteRepository):
        return repository.database_path
    if database is None:
        return None
    return resolve_database_path(database)


def _mcp_root_attributes(
    principal: UserPrincipal, request: SearchRequest | FetchRequest
) -> dict[str, object]:
    """Root attributes for one authenticated MCP tool call.

    The operation, the schema version, and the account UUID are set at root
    creation, so the persisted root row carries its owner even when the call
    fails before the response projection runs.
    """

    attributes: dict[str, object] = {
        TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION,
        TraceAttribute.USER_ID: str(principal.id),
    }
    attributes.update(_request_attributes(request))
    return attributes


@asynccontextmanager
async def _authenticated_root(
    observability: ObservabilityRuntime,
    name: str,
    attributes: Mapping[str, object],
) -> AsyncIterator[None]:
    """Open one authenticated SERVER root around a tool body.

    The runtime is bound for the call, a failure annotates the root before it
    propagates, and one bounded flush runs after the root closes — the same
    contract the API trace middleware applies to a traced request.
    """

    with use_observability(observability):
        with observability.span(name, kind=SpanKindName.SERVER, attributes=attributes):
            try:
                yield
            except BaseException as error:
                _annotate_root_error(observability, error)
                raise
        await flush_traces(observability)


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
    """Apply persisted local quota settings after the repository is available."""

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
            if adapter.name == "exa":
                config = await effective_config_for_name(repository, adapter.name)
                setter = getattr(adapter, "set_monthly_budget", None)
                if callable(setter):
                    setter(config.exa_monthly_budget_usd)
                credits_setter = getattr(adapter, "set_manual_starting_credits", None)
                if callable(credits_setter):
                    credits_setter(config.exa_manual_starting_credits_usd)
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


async def _apply_tavily_config(
    routes: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    limits: "ProviderLimitsService | None",
) -> None:
    """Project the effective Tavily rail and PAYGO choice into the limit service.

    The calls run after the limits service exists, so a generation without a
    repository, a limit service, or a Tavily adapter stays a no-op.
    """

    if repository is None or limits is None:
        return
    adapter = next((route for route in routes if route.name == ProviderName.TAVILY.value), None)
    if adapter is None:
        return
    from freesearch.routers.control import effective_config_for_name

    config = await effective_config_for_name(repository, ProviderName.TAVILY.value)
    await limits.apply_tavily_config(config, auth_mode=adapter.limit_auth_mode)


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
    helpers; providers without a vault key are skipped (Keenable's and
    Tavily's keyless public tiers excepted).
    """

    from freesearch.routers.control import (
        _build_with_resolved_secret,
        _resolve_secret,
        effective_config_for_name,
        initialize_provider_configs,
    )

    client = create_async_client()
    owned_routes: list[ProviderAdapter] = []
    try:
        if owns_repository:
            state["repository"] = await SQLiteRepository.open(resolve_database_path(database))
        repository = state["repository"]
        if isinstance(repository, SQLiteRepository):
            state["secret_store"] = _encrypted_store(repository)
            await initialize_provider_configs(repository)
        store = state["secret_store"]
        if isinstance(repository, SQLiteRepository) and store is not None:
            # An administrator OFF choice does not skip construction: each
            # request filters the candidates, so a later ON choice needs no
            # server restart.
            for provider in ProviderName:
                key, _source = await _resolve_secret(provider, store)
                if key is None and provider not in (
                    ProviderName.KEENABLE,
                    ProviderName.TAVILY,
                ):
                    continue
                factory = adapter_factory(provider.value)
                if factory is None:
                    logger.warning("no adapter factory for provider %s", provider.value)
                    continue
                try:
                    if provider is ProviderName.TAVILY:
                        config = await effective_config_for_name(repository, provider.value)
                        owned_routes.append(
                            _build_with_resolved_secret(factory, client, key, config=config)
                        )
                    else:
                        owned_routes.append(_build_with_resolved_secret(factory, client, key))
                except Exception:
                    continue
        else:
            owned_routes = build_adapters(client)
        await _apply_parallel_seed(owned_routes, repository)
        await _start_limits_generation(state, owned_routes)
        with suppress(Exception):
            await _apply_tavily_config(owned_routes, repository, state["limits"])
        # The trace runtime belongs to this generation, so it is built only after
        # the repository that owns the trace table is open and migrated.
        state["observability"] = build_observability(
            get_settings(), database=_trace_database(state["repository"], database)
        )
    except BaseException:
        # A failed enter never increments: stop any schedule task, then close the
        # freshly built client and adapters so a failed open cannot leak a
        # partial generation.
        await _stop_limits_generation(state)
        await close_adapters(owned_routes, client)
        raise
    state["client"] = client
    state["routes"] = owned_routes


async def _close_traces(state: _ServerState) -> None:
    """Flush and close the generation's trace runtime.

    The flush and the shutdown both complete before the caller closes the
    repository that owns the ``trace_spans`` table, so no batch is lost and no
    exporter writes into a closed database.
    """

    runtime = state["observability"]
    state["observability"] = NO_OP_OBSERVABILITY
    if runtime is NO_OP_OBSERVABILITY:
        return
    await asyncio.to_thread(runtime.force_flush, DEFAULT_FLUSH_TIMEOUT_MILLIS)
    await asyncio.to_thread(runtime.shutdown)


async def _detach_generation(state: _ServerState, *, owns_repository: bool) -> None:
    """Detach the active generation from the state cells, then close it."""

    client = state["client"]
    owned_routes = state["routes"]
    owned_repo = state["repository"] if owns_repository else None
    await _stop_limits_generation(state)
    state["client"] = None
    state["routes"] = None
    state["secret_store"] = None
    await _close_traces(state)
    if owned_repo is not None:
        from freesearch.routers.control import clear_config_cache

        clear_quota_poll_cache(owned_repo, owned_routes or [])
        clear_config_cache(owned_repo)
        state["repository"] = None
        await owned_repo.close()
    await close_adapters(owned_routes or [], client)


async def _route_state(
    repository: SQLiteRepository | None,
    active: Sequence[ProviderAdapter],
    secret_store: AsyncSecretStore | None,
) -> tuple[dict[str, ProviderHealth], dict[str, QuotaSnapshot]]:
    """Collect routing state using batch lookups and non-blocking quota refresh."""

    if repository is None or not active:
        return {}, {}
    from freesearch.routers.api import _schedule_quota_refresh
    from freesearch.services.monitoring import effective_quotas_batch

    _schedule_quota_refresh(repository, active, secret_store)
    names = [candidate.name for candidate in active]
    health: dict[str, ProviderHealth] = {}
    try:
        if hasattr(repository, "latest_health_batch"):
            health = await repository.latest_health_batch(names)
        else:
            for candidate in active:
                observation = await repository.latest_health(candidate.name)
                if observation is not None:
                    health[candidate.name] = observation
    except Exception:
        pass

    quotas: dict[str, QuotaSnapshot] = {}
    try:
        if hasattr(repository, "latest_quota_batch"):
            quotas = await effective_quotas_batch(repository, names)
        else:
            from freesearch.services.monitoring import effective_quota

            for candidate in active:
                snapshot = await effective_quota(repository, candidate.name)
                if snapshot is not None:
                    quotas[candidate.name] = snapshot
    except Exception:
        pass

    return health, quotas


async def _accessible_routes(
    active: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    operation: UsageOperation,
) -> list[ProviderAdapter]:
    """Return the adapters whose current masks allow ``operation``.

    The request reads the current masks before route selection, so an earlier
    admin change applies to the next call without a restart.
    """

    from freesearch.routers.control import effective_config_for_name

    accessible: list[ProviderAdapter] = []
    for adapter in active:
        config = await effective_config_for_name(repository, adapter.name, strict=True)
        if config.allows(operation):
            accessible.append(adapter)
    return accessible


async def _mcp_fanout_search(
    request: SearchRequest,
    active: Sequence[ProviderAdapter],
    repository: SQLiteRepository | None,
    secret_store: AsyncSecretStore | None = None,
    limits: "ProviderLimitsService | None" = None,
) -> dict[str, Any]:
    """Execute concurrent fanout search across active adapters for MCP.

    Mirrors the REST fanout transport: a terminal Tavily out-of-Credits 402
    propagates even when another provider succeeds, after the pending fanout
    tasks are cancelled and awaited. FastMCP surfaces the original error text
    unchanged.
    """

    from freesearch.routers.api import (
        _fanout_failure_outcome,
        _fanout_outcomes,
        _terminal_tavily_402,
    )

    if request.routing.providers:
        required_names = set(request.routing.providers)
        active = [a for a in active if a.name in required_names]
    eligible = await _accessible_routes(active, repository, UsageOperation.SEARCH)
    health, quotas = await _route_state(repository, eligible, secret_store)
    fanout_req = request.model_copy(
        update={"routing": request.routing.model_copy(update={"mode": RoutingMode.FANOUT})}
    )
    candidates = select_route(fanout_req, eligible, health, quotas)
    if not candidates:
        raise RuntimeError("no eligible provider is available for search")

    async def _call(
        candidate_adapter: ProviderAdapter,
    ) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
        call_start = time.perf_counter()
        try:
            try:
                res = await tracked_call(
                    repository,
                    candidate_adapter,
                    lambda target: target.search(request),
                    operation=UsageOperation.SEARCH,
                    request=request,
                    limits=limits,
                )
                elapsed = int((time.perf_counter() - call_start) * 1000)
                return (candidate_adapter.name, res, elapsed, "success", len(res.results), None)
            except Exception as exc:
                elapsed = int((time.perf_counter() - call_start) * 1000)
                if _terminal_tavily_402(exc) is not None:
                    # The terminal out-of-Credits error is the transport: it
                    # re-raises out of the fanout and FastMCP carries the
                    # original message to the tool caller.
                    raise
                return _fanout_failure_outcome(candidate_adapter.name, exc, elapsed)
        except Exception as mc_exc:
            # Mirror of the guarded fanout invariant in routers/api.py: only
            # the terminal Tavily 402 escapes _call; any machinery failure in
            # the wrapper bookkeeping above converts to the handled outcome
            # tuple instead of a raised task error. MCP keeps its own tuple
            # shape and surface (no OpenTelemetry span in scope here).
            if _terminal_tavily_402(mc_exc) is not None:
                raise
            mc_elapsed = int((time.perf_counter() - call_start) * 1000)
            return _fanout_failure_outcome(candidate_adapter.name, mc_exc, mc_elapsed)

    tasks = [asyncio.ensure_future(_call(c.adapter)) for c in candidates]
    outcomes = await _fanout_outcomes(tasks)
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
        raise RuntimeError(f"all search providers failed: {first_err}")

    fused_results = reciprocal_rank_fusion(
        successful_results,
        limit=request.limit,
    )
    participating = [name for name, _ in successful_results]
    resp = SearchResponse(
        query=request.query,
        results=fused_results,
        provider="aggregated" if len(successful_results) > 1 else successful_results[0][0],
        total_results=len(fused_results),
        participating_providers=participating,
        waterfall=waterfall,
    )
    return resp.model_dump(mode="json")


async def _route_adapter(
    request: SearchRequest | FetchRequest,
    *,
    active: Sequence[ProviderAdapter] | None,
    state: _ServerState,
) -> ProviderAdapter:
    """Return the policy-ordered adapter for one tool request.

    The owned path routes through the current generation's adapters; the
    injected path keeps the caller's eager list. An owned server that has not
    entered a lifespan yet has no generation, hence no provider.
    """

    if not active:
        raise RuntimeError(
            "no provider is configured: store a key in the encrypted vault "
            "(PUT /api/v1/providers/{id}/secret)"
        )
    # Fast-path: a REQUIRE request with pinned providers skips unrequested
    # provider evaluation entirely (perf: eliminate route selection latency).
    preference = request.routing
    if preference.mode is RoutingMode.REQUIRE and preference.providers:
        required_names = set(preference.providers)
        matching = [adapter for adapter in active if adapter.name in required_names]
        if not matching:
            raise RuntimeError(
                f"no required provider is eligible: {', '.join(preference.providers)}"
            )
        active = matching
    repository = state["repository"]
    operation = (
        UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
    )
    eligible = await _accessible_routes(active, repository, operation)
    health, quotas = await _route_state(repository, eligible, state["secret_store"])
    candidates = select_route(request, eligible, health, quotas)
    if not candidates:
        raise RuntimeError(f"no eligible provider is available for {operation.value}")
    return candidates[0].adapter


async def _search_response(
    request: SearchRequest, active: Sequence[ProviderAdapter], state: _ServerState
) -> SearchResponse:
    """Run one search call and return its typed response."""

    if request.fanout or request.routing.mode is RoutingMode.FANOUT:
        payload = await _mcp_fanout_search(
            request,
            active,
            state["repository"],
            state["secret_store"],
            limits=state["limits"],
        )
        return SearchResponse.model_validate(payload)
    adapter = await _route_adapter(request, active=active, state=state)
    return await tracked_call(
        state["repository"],
        adapter,
        lambda target: target.search(request),
        operation=UsageOperation.SEARCH,
        request=request,
        limits=state["limits"],
    )


async def _fetch_response(
    request: FetchRequest, active: Sequence[ProviderAdapter], state: _ServerState
) -> FetchResponse:
    """Run one fetch call and return its typed response."""

    _require_single_url(request)
    adapter = await _route_adapter(request, active=active, state=state)
    return await tracked_call(
        state["repository"],
        adapter,
        lambda target: target.fetch(request),
        operation=UsageOperation.FETCH,
        request=request,
        limits=state["limits"],
    )


def _register_tools(
    server: FastMCP,
    *,
    state: _ServerState,
    owns_client: bool,
    routes: list[ProviderAdapter] | None,
    require_account: Callable[[], Awaitable[UserPrincipal]],
) -> None:
    """Register the two authenticated, traced tool bodies on ``server``."""

    def _active_routes() -> Sequence[ProviderAdapter] | None:
        return state["routes"] if owns_client else routes

    @server.tool()
    async def search(request: SearchRequest) -> dict[str, Any]:
        """Search the web through the best available provider or all providers concurrently."""
        # The account check precedes route selection, fanout, quota work, and
        # every adapter call, so a rejected caller cannot spend provider credit.
        principal = await require_account()
        active = _active_routes()
        if not active:
            raise RuntimeError("no provider is configured: set a FREESEARCH_*_API_KEY")
        observability = state["observability"]
        async with _authenticated_root(
            observability,
            TraceRootSpan.MCP_SEARCH.value,
            _mcp_root_attributes(principal, request),
        ):
            response = await _search_response(request, active, state)
            _annotate_root(observability, request, response)
        return response.model_dump(mode="json")

    @server.tool()
    async def fetch(request: FetchRequest) -> dict[str, Any]:
        """Fetch a URL's content through the best available provider."""
        principal = await require_account()
        active = _active_routes()
        if not active:
            raise RuntimeError("no provider is configured: set a FREESEARCH_*_API_KEY")
        observability = state["observability"]
        async with _authenticated_root(
            observability,
            TraceRootSpan.MCP_FETCH.value,
            _mcp_root_attributes(principal, request),
        ):
            response = await _fetch_response(request, active, state)
            _annotate_root(observability, request, response)
        return response.model_dump(mode="json")


def create_server(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
    stateless_http: bool = False,
    auth_service: AuthService | None = None,
    stdio_token: SecretStr | None = None,
) -> FastMCP:
    """Create the MCP server, routing every tool call to a configured adapter.

    Account authentication is explicit. A supplied ``auth_service`` arms the SDK
    Bearer verifier and the SDK auth settings, so the HTTP resource and the
    metadata routes need a live access JWT. Every tool body then verifies the
    same account and session family again. Only an explicit ``stdio_token``, or
    the SDK request auth context, can authorize a tool call.
    """

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
        "limits": None,
        "limits_sync": None,
        "limits_task": None,
        "limits_stop": None,
        # An injected composition has no generation lifecycle, so its trace
        # runtime is built here and lives as long as the injected repository.
        # The owned path builds a fresh runtime per generation instead.
        "observability": NO_OP_OBSERVABILITY
        if owns_client
        else build_observability(get_settings(), database=_trace_database(repository, database)),
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
                from freesearch.routers.control import clear_config_cache

                clear_quota_poll_cache(repository, routes or [])
                clear_config_cache(repository)
                await close_adapters(routes or [], None)
                # The injected repository stays open for its owner, so the
                # runtime is flushed (never closed) at each session exit.
                await flush_traces(state["observability"])

    server = FastMCP(
        "freesearch",
        lifespan=lifespan,
        stateless_http=stateless_http,
        # The SDK accepts a token verifier only together with auth settings, so
        # both stay absent in a composition that has no account store.
        token_verifier=LocalTokenVerifier(auth_service) if auth_service is not None else None,
        auth=build_auth_settings(get_settings()) if auth_service is not None else None,
    )

    async def _require_account() -> UserPrincipal:
        """Return the verified account of this tool call, or reject the call."""

        if auth_service is None:
            raise McpAuthenticationError("account authentication is not configured")
        return await require_mcp_user(auth_service, stdio_token=stdio_token)

    _register_tools(
        server,
        state=state,
        owns_client=owns_client,
        routes=routes,
        require_account=_require_account,
    )

    return server


def _require_single_url(request: FetchRequest) -> None:
    """Reject an executable batch fetch before admission and vendor I/O."""

    if request.url_count != 1:
        raise ValueError("this release executes exactly one URL per fetch request")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the MCP server over stdio or HTTP under the configured account guard."""
    import argparse
    import asyncio
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
        default=None,
        help="HTTP host override (env: FREESEARCH_MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port override (env: FREESEARCH_MCP_PORT)",
    )
    args = parser.parse_args(argv)

    # One settings object serves the session-family store, the advertised SDK
    # auth metadata, and the HTTP bind. An explicit command-line value wins over
    # the environment file, and no numeric fallback port exists.
    settings = get_settings()
    overrides: dict[str, Any] = {}
    if args.host:
        overrides["mcp_host"] = args.host
    if args.port is not None:
        overrides["mcp_port"] = args.port
    effective = settings.model_copy(update=overrides) if overrides else settings

    auth_service = AuthService(effective)
    server = create_server(
        stateless_http=args.stateless,
        auth_service=auth_service,
        stdio_token=effective.mcp_bearer_token,
    )
    if args.transport == "stdio":
        asyncio.run(run_stdio_server(server, auth_service=auth_service, settings=effective))
    else:
        asyncio.run(run_http_server(server, auth_service=auth_service, settings=effective))


if __name__ == "__main__":
    main()
