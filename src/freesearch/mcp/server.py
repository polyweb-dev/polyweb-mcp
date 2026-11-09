"""Composition root of the MCP server: the shared contracts over MCP surfaces.

Exposes the two provider-neutral tools (``search``,
``fetch``) over MCP (streamable HTTP or stdio). Every tool call resolves its
verified project scope first and then runs the one transport-independent
execution path (bindings, strict caps, telemetry) through
:class:`freesearch.services.execution.ExecutionService`, mirroring the REST
path exactly. Telemetry writes (usage and health observations) go through
:mod:`freesearch.services.monitoring`, so the tool reads the same project
attribution the REST transport stamps.
"""

import asyncio
import logging
import time
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

import httpx
from mcp.server.fastmcp import Context, FastMCP
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import (
    _ADAPTERS as _ADAPTERS,
)
from freesearch.adapters.registry import (
    adapter_factory as adapter_factory,
)
from freesearch.adapters.registry import (
    close_adapters,
)
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    load_secret_codec,
)
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.observability import (
    DEFAULT_FLUSH_TIMEOUT_MILLIS,
    NO_OP_OBSERVABILITY,
    ObservabilityRuntime,
    SpanKindName,
    bind_execution_attribution,
    bind_trace_capture,
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
    MCP_AUTH_ERROR,
    McpAuthenticationError,
    resolve_tool_principal,
    run_http_server,
    run_stdio_server,
    tool_credential,
)
from freesearch.models.contracts import (
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
)
from freesearch.models.observability import (
    TRACE_SCHEMA_VERSION,
    ExecutionAttribution,
    TraceAttribute,
    TraceRootSpan,
)
from freesearch.models.projects import PermissionAction, ProjectContext, ProjectTracePolicy
from freesearch.persistence.database_migrations import exit_if_database_reset_required
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.api_keys import DEFAULT_USE_RECORDER
from freesearch.services.execution import (
    ExecutionError,
    ExecutionRequestInvalid,
    ExecutionService,
)
from freesearch.services.execution_forward import (
    ExecutionForwarder,
    ExecutionForwardError,
    deadline_from_timeout,
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
from freesearch.services.monitoring import clear_quota_poll_cache, resolve_database_path
from freesearch.services.provider_limits import ProviderLimitsService
from freesearch.services.provider_runtime import (
    clear_config_cache,
    initialize_provider_configs,
)
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
    execution: "ExecutionService | None"
    forwarder: "ExecutionForwarder | None"
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
    keenable = next((route for route in routes if route.name == ProviderName.KEENABLE.value), None)
    if keenable is not None:
        limits.apply_keenable_auth_mode(keenable.limit_auth_mode)
    stop = asyncio.Event()
    sync = LimitSyncService(repository.limits, limits, lambda: state["routes"] or [])
    state["limits"] = limits
    state["limits_sync"] = sync
    state["limits_stop"] = stop
    state["limits_task"] = None


async def _start_injected_limits(state: _ServerState, routes: Sequence[ProviderAdapter]) -> None:
    """Start the limit service of an injected composition, mirroring REST.

    ``create_app`` with injected adapters and a repository seeds the catalog,
    projects the Tavily and Keenable rails, and starts one schedule task in its
    lifespan; an injected MCP server does the same on its first session enter.
    Without a repository there is no limit store, so nothing starts.
    """

    # Same order and error handling as the REST lifespan and the owned MCP
    # generation: restore local quota settings, then start the limit service,
    # then project the Tavily rail best effort.
    await _start_limits_generation(state, routes)
    # Every execution attempt takes the rails, so an eager (injected) or a
    # freshly built (owned) execution service adopts the started rails.
    if state["execution"] is None:
        repository, store = state["repository"], state["secret_store"]
        if isinstance(repository, SQLiteRepository) and isinstance(store, EncryptedDbSecretStore):
            state["execution"] = ExecutionService(
                repository=repository, secret_store=store, limits=state["limits"]
            )
    elif state["execution"] is not None:
        state["execution"].set_limits(state["limits"])


def _take_limit_cells(
    state: _ServerState,
) -> tuple[asyncio.Event | None, "asyncio.Task[None] | None"]:
    """Detach the limit cells: return the stop event and task, set all to None."""

    stop = state["limits_stop"]
    task = state["limits_task"]
    state["limits"] = None
    state["limits_sync"] = None
    state["limits_task"] = None
    state["limits_stop"] = None
    return stop, task


async def _stop_limits_task(stop: asyncio.Event | None, task: "asyncio.Task[None] | None") -> None:
    """Signal, cancel, and await one schedule task."""

    if stop is not None:
        stop.set()
    if task is not None:
        task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await task


async def _stop_limits_generation(state: _ServerState) -> None:
    """Stop and await the schedule task before the repository and adapters close."""

    await _stop_limits_task(state["limits_stop"], state["limits_task"])
    _take_limit_cells(state)


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


def _mcp_root_attributes(request: SearchRequest | FetchRequest) -> dict[str, object]:
    """Root attributes for one MCP tool call.

    The verified project and API key identity are stamped by the bound
    execution attribution. The schema version and operation are still present
    when a provider call fails.
    """

    attributes: dict[str, object] = {TraceAttribute.SCHEMA_VERSION: TRACE_SCHEMA_VERSION}
    attributes.update(_request_attributes(request))
    return attributes


@asynccontextmanager
async def _tool_root(
    observability: ObservabilityRuntime,
    name: str,
    attributes: Mapping[str, object],
    *,
    attribution: ExecutionAttribution,
    trace_policy: ProjectTracePolicy,
) -> AsyncIterator[None]:
    """Open one SERVER root around a tool body.

    The runtime is bound for the call, and the verified execution attribution
    and the project trace policy resolved at the boundary are bound before the
    root span starts, so the attribution processor stamps ownership and the
    immutable capture/sampling decision on the root and every child. A failure
    annotates the root before it propagates, and one bounded flush runs after
    the root closes — the same contract the API trace middleware applies to a
    traced request.
    """

    with use_observability(observability):
        bind_execution_attribution(attribution)
        bind_trace_capture(trace_policy)
        with observability.span(name, kind=SpanKindName.SERVER, attributes=attributes):
            try:
                yield
            except BaseException as error:
                _annotate_root_error(observability, error)
                raise
        await flush_traces(observability)


def _execution_tool_error(error: ExecutionScopeError) -> Exception:
    """Map one scope failure onto a generic tool error without its reason."""

    if isinstance(error, ExecutionUnauthenticated):
        return McpAuthenticationError(MCP_AUTH_ERROR)
    if isinstance(error, ExecutionStorageUnavailable):
        return RuntimeError("execution is temporarily unavailable")
    if isinstance(error, ExecutionProjectRequired):
        return RuntimeError("project_id is required")
    if isinstance(error, ExecutionProjectArchived):
        return RuntimeError("project is archived")
    if isinstance(error, ExecutionForbidden):
        return RuntimeError("execution is not permitted")
    return RuntimeError("project is unavailable")


def _encrypted_store(repository: SQLiteRepository) -> EncryptedDbSecretStore:
    """Build the local encrypted store used by OAuth balance polling."""

    return EncryptedDbSecretStore(
        repository,
        load_secret_codec(get_settings()),
    )


async def _build_generation(
    state: _ServerState,
    *,
    database: str | Path | None,
    owns_repository: bool,
) -> None:
    """Create one owned generation (client, adapters, repository) and publish it.

    Adapters resolve their keys from the encrypted vault via the shared
    runtime seam; providers without a vault key are skipped (Keenable's and
    Tavily's keyless public tiers excepted). The generation also owns the
    execution service, so its per-credential adapters close with it.
    """

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
        await _start_limits_generation(state, owned_routes)
        if (
            isinstance(repository, SQLiteRepository)
            and isinstance(store, EncryptedDbSecretStore)
            and get_settings().execution_authority_url is None
            and (get_settings().execution_mcp_standalone or database is not None)
        ):
            state["execution"] = ExecutionService(
                repository=repository,
                secret_store=store,
                client=client,
                limits=state["limits"],
            )
        # The trace runtime belongs to this generation, so it is built only after
        # the repository that owns the trace table is open and migrated.
        state["observability"] = build_observability(
            get_settings(), database=_trace_database(state["repository"], database)
        )
    except BaseException:
        # A failed enter never increments: stop any schedule task, then close
        # the freshly built client and adapters so a failed open cannot leak a
        # partial generation.
        execution = state["execution"]
        state["execution"] = None
        if execution is not None:
            await execution.aclose()
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


#: Trace closers of injected compositions, keyed by their server. An injected
#: runtime lives as long as its owner's repository, so only the owner closes it.
_INJECTED_TRACE_CLOSERS: weakref.WeakKeyDictionary[FastMCP, Callable[[], Awaitable[None]]] = (
    weakref.WeakKeyDictionary()
)


async def shutdown_injected_observability(server: FastMCP) -> None:
    """Flush and shut down an injected composition's trace runtime.

    This is the embedder/test teardown seam for injected compositions
    (``create_server`` called with adapters and a caller-owned repository).
    Such a server builds one trace runtime that each session exit only
    flushes, because the caller owns the repository; the caller invokes this
    once, after its last session and before closing that repository, to stop
    the span exporter. A server that owns its generations closes its runtime
    itself, so this is a no-op for it; repeated calls are no-ops too.
    """

    closer = _INJECTED_TRACE_CLOSERS.pop(server, None)
    if closer is not None:
        await closer()


async def _detach_generation(state: _ServerState, *, owns_repository: bool) -> None:
    """Detach the active generation from the state cells, then close it."""

    client = state["client"]
    owned_routes = state["routes"]
    owned_repo = state["repository"] if owns_repository else None
    execution = state["execution"]
    state["execution"] = None
    await _stop_limits_generation(state)
    state["client"] = None
    state["routes"] = None
    state["secret_store"] = None
    await _close_traces(state)
    if execution is not None:
        await execution.aclose()
    # Queued API key bookkeeping finishes before any repository can close.
    await DEFAULT_USE_RECORDER.drain()
    if owned_repo is not None:
        clear_quota_poll_cache(owned_repo, owned_routes or [])
        clear_config_cache(owned_repo)
        state["repository"] = None
        await owned_repo.close()
    await close_adapters(owned_routes or [], client)


def _mapped_execution_error(error: ExecutionError | Exception) -> Exception:
    """Map the execution service's planning failures onto tool errors."""

    if isinstance(error, ExecutionStorageUnavailable):
        return RuntimeError("execution is temporarily unavailable")
    if isinstance(error, ExecutionRequestInvalid):
        return ValueError(error.detail)
    if isinstance(error, ExecutionError):
        return RuntimeError(error.detail)
    return error


async def _tool_body(
    state: _ServerState,
    request: SearchRequest | FetchRequest,
    *,
    root_name: str,
    attribution: ExecutionAttribution,
    trace_policy: ProjectTracePolicy,
    context: ProjectContext,
    operation: Literal["search", "fetch"],
    credential: SecretStr | None,
    deadline_ms: int | None = None,
) -> dict[str, Any]:
    """Run one tool body around its root span over the shared execution path.

    ``context`` carries the verified principal resolved by the boundary (over
    HTTP the guard's principal of this request, over stdio a fresh per-call
    verification); the execution service authorizes against live state from it.
    When a forwarding target is configured, the call goes to the API-hosted
    authority with the original credential, the admission deadline established
    before scope resolution, and the trace id of this tool call; this process
    never opens a provider call for it.
    """

    forwarder = state["forwarder"]
    execution = state["execution"]
    if forwarder is None and execution is None:
        raise RuntimeError("execution is temporarily unavailable")
    observability = state["observability"]
    response: SearchResponse | FetchResponse
    async with _tool_root(
        observability,
        root_name,
        _mcp_root_attributes(request),
        attribution=attribution,
        trace_policy=trace_policy,
    ):
        try:
            if forwarder is not None:
                if credential is None:
                    raise McpAuthenticationError(MCP_AUTH_ERROR)
                if deadline_ms is None:
                    deadline_ms = deadline_from_timeout(
                        get_settings().execution_forward_timeout_seconds
                    )
                trace_id = observability.current_trace_id()
                parent_span_id = observability.current_span_id()
                if operation == "search":
                    response = await forwarder.search(
                        cast(SearchRequest, request),
                        credential=credential,
                        trace_id=trace_id,
                        parent_span_id=parent_span_id,
                        deadline_ms=deadline_ms,
                    )
                else:
                    response = await forwarder.fetch(
                        cast(FetchRequest, request),
                        credential=credential,
                        trace_id=trace_id,
                        parent_span_id=parent_span_id,
                        deadline_ms=deadline_ms,
                    )
            else:
                remaining = (
                    None
                    if deadline_ms is None
                    else max(0.001, (deadline_ms - int(time.time() * 1000)) / 1000.0)
                )
                deadline = None if remaining is None else time.monotonic() + remaining
                if operation == "search":
                    response = await execution.search(  # type: ignore[union-attr]
                        cast(SearchRequest, request),
                        attribution=attribution,
                        context=context,
                        deadline=deadline,
                    )
                else:
                    response = await execution.fetch(  # type: ignore[union-attr]
                        cast(FetchRequest, request),
                        attribution=attribution,
                        context=context,
                        deadline=deadline,
                    )
        except ExecutionForwardError as error:
            raise RuntimeError(str(error)) from error
        except ExecutionError as error:
            raise _mapped_execution_error(error) from error
        _annotate_root(observability, request, response)
    return response.model_dump(mode="json")


def _register_tools(
    server: FastMCP,
    *,
    state: _ServerState,
    owns_client: bool,
    routes: list[ProviderAdapter] | None,
    stdio_key: SecretStr | None,
) -> None:
    """Register the key-authenticated, traced Search and Fetch tools on ``server``."""

    del owns_client, routes

    async def _resolve_scope(
        request: SearchRequest | FetchRequest,
        action: PermissionAction,
        ctx: Context | None,  # type: ignore[type-arg]
    ) -> tuple[ExecutionAttribution, ProjectTracePolicy, ProjectContext]:
        """Take this call's verified key principal and resolve its scope before routing.

        Runs on every tool call, so a persistent session is rechecked each time:
        over HTTP from the guard's verification of the call's own request, over
        stdio by verifying the process key again. The project trace policy is
        resolved here, once, so the provider call's spans share one immutable
        capture and sampling decision.
        """

        repository = state["repository"]
        principal = await resolve_tool_principal(ctx, stdio_key=stdio_key, repository=repository)
        if repository is None:
            raise RuntimeError("execution is temporarily unavailable")
        try:
            boundary = await resolve_execution_boundary(
                repository, principal, project_id=request.project_id, action=action
            )
        except ExecutionScopeError as error:
            raise _execution_tool_error(error) from error
        return execution_attribution(boundary.context), boundary.trace_policy, boundary.context

    @server.tool()
    async def search(
        request: SearchRequest,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Search the web through the best available provider or all providers concurrently."""
        deadline_ms = deadline_from_timeout(get_settings().execution_forward_timeout_seconds)
        try:
            async with asyncio.timeout(
                max(0.001, (deadline_ms - int(time.time() * 1000)) / 1000.0)
            ):
                attribution, trace_policy, context = await _resolve_scope(
                    request, PermissionAction.SEARCH_EXECUTE, ctx
                )
        except TimeoutError as error:
            raise RuntimeError("the execution request deadline expired before dispatch") from error
        return await _tool_body(
            state,
            request,
            root_name=TraceRootSpan.MCP_SEARCH.value,
            attribution=attribution,
            trace_policy=trace_policy,
            context=context,
            operation="search",
            credential=tool_credential(ctx, stdio_key=stdio_key),
            deadline_ms=deadline_ms,
        )

    @server.tool()
    async def fetch(
        request: FetchRequest,
        ctx: Context,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Fetch a URL's content through the best available provider."""
        deadline_ms = deadline_from_timeout(get_settings().execution_forward_timeout_seconds)
        try:
            async with asyncio.timeout(
                max(0.001, (deadline_ms - int(time.time() * 1000)) / 1000.0)
            ):
                attribution, trace_policy, context = await _resolve_scope(
                    request, PermissionAction.FETCH_EXECUTE, ctx
                )
        except TimeoutError as error:
            raise RuntimeError("the execution request deadline expired before dispatch") from error
        return await _tool_body(
            state,
            request,
            root_name=TraceRootSpan.MCP_FETCH.value,
            attribution=attribution,
            trace_policy=trace_policy,
            context=context,
            operation="fetch",
            credential=tool_credential(ctx, stdio_key=stdio_key),
            deadline_ms=deadline_ms,
        )


def create_server(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
    stateless_http: bool = False,
    auth_service: AuthService | None = None,
    stdio_token: SecretStr | None = None,
) -> FastMCP:
    """Create project-API-key Search/Fetch tools over a configured adapter set.

    Every tool call verifies its project API key and resolves the key's project
    scope before routing: over HTTP the key comes from that call's own
    ``Authorization`` header, over stdio from ``stdio_token`` (the process
    credential channel). ``auth_service`` only supplies the account store's
    lifecycle to the HTTP transport. A call without a valid key is rejected as
    a tool error before any provider access.
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
    # The encrypted runtime store is built eagerly, so a store-backed execution
    # service can also be eager: session-enter only starts the limit schedule
    # and builds the trace runtime.
    encrypted_store: AsyncSecretStore | None = (
        _encrypted_store(repository) if isinstance(repository, SQLiteRepository) else None
    )
    settings = get_settings()
    authority_url = settings.execution_authority_url
    # Topology is explicit: a forwarded deployment uses the API-hosted
    # authority and never builds a local one. Local hosting is reserved for an
    # explicit exclusive deployment (the setting) or for an in-process
    # embedding that explicitly supplied its own repository/database, which is
    # never the production MCP launch path.
    standalone_authority = (
        bool(settings.execution_mcp_standalone)
        or not owns_client
        or repository is not None
        or database is not None
    )
    execution: ExecutionService | None = (
        ExecutionService(
            repository=repository,
            secret_store=encrypted_store,
            host_authority=True,
        )
        if isinstance(repository, SQLiteRepository)
        and isinstance(encrypted_store, EncryptedDbSecretStore)
        and authority_url is None
        and standalone_authority
        else None
    )
    forwarder = (
        ExecutionForwarder(
            authority_url,
            timeout_seconds=settings.execution_forward_timeout_seconds,
        )
        if authority_url
        else None
    )
    state: _ServerState = {
        "repository": repository,
        "client": None,
        "routes": routes,
        "secret_store": encrypted_store,
        "limits": None,
        "limits_sync": None,
        "limits_task": None,
        "limits_stop": None,
        "execution": execution,
        "forwarder": forwarder,
        # An injected composition has no generation lifecycle, so its trace
        # runtime is built here and lives as long as the injected repository.
        # The owned path builds a fresh runtime per generation instead.
        "observability": NO_OP_OBSERVABILITY
        if owns_client
        else build_observability(get_settings(), database=_trace_database(repository, database)),
    }
    # Streamable-HTTP MCP runs one lifespan per concurrent session, so the
    # owned resources are refcounted (serialized by a lock): the first enter
    # builds the generation and the last exit tears it down. An injected
    # composition refcounts its limit service the same way: like the REST app
    # with injected adapters and a repository, the first enter seeds the limit
    # catalog and starts one schedule task, and the last exit stops it.
    lock = asyncio.Lock()
    refcount = 0

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[None]:
        nonlocal refcount
        # Concurrent enters serialize here; a failed build propagates without
        # incrementing, so the cells stay empty.
        async with lock:
            if refcount == 0:
                if owns_client:
                    await _build_generation(
                        state, database=database, owns_repository=owns_repository
                    )
                else:
                    await _start_injected_limits(state, routes or [])
                if state["forwarder"] is None:
                    authority_url = get_settings().execution_authority_url
                    if authority_url:
                        state["forwarder"] = ExecutionForwarder(
                            authority_url,
                            timeout_seconds=get_settings().execution_forward_timeout_seconds,
                        )
            refcount += 1
        try:
            yield
        finally:
            limit_stop: asyncio.Event | None = None
            limit_task: asyncio.Task[None] | None = None
            retiring_execution: ExecutionService | None = None
            retiring_forwarder: ExecutionForwarder | None = None
            async with lock:
                refcount -= 1
                last_exit = refcount == 0
                if last_exit and not owns_client:
                    # Detach the limit cells under the lock, so a session that
                    # enters while the old task is still stopping starts a
                    # fresh limit generation the old stop cannot wipe.
                    limit_stop, limit_task = _take_limit_cells(state)
                    retiring_execution = state["execution"]
                    state["execution"] = None
                if last_exit:
                    retiring_forwarder = state["forwarder"]
                    state["forwarder"] = None
            if owns_client:
                # Teardown happens outside the lock, exactly once, on the
                # last exit: intermediate exits keep everything usable, and
                # detaching under the lock lets a session that enters during
                # a delayed teardown build its own fresh generation.
                if last_exit:
                    await _detach_generation(state, owns_repository=owns_repository)
            else:
                if last_exit:
                    # Mirrors the REST shutdown: the schedule task stops and is
                    # awaited, the caches clear, then the adapters close.
                    await _stop_limits_task(limit_stop, limit_task)
                    if retiring_execution is not None:
                        await retiring_execution.aclose()
                    if state["execution"] is None:
                        clear_quota_poll_cache(repository, routes or [])
                        clear_config_cache(repository)
                        await close_adapters(routes or [], None)
                # The injected repository stays open for its owner, so the
                # runtime is flushed (never closed) and queued API key
                # bookkeeping is drained at each session exit.
                await flush_traces(state["observability"])
                await DEFAULT_USE_RECORDER.drain()
            if retiring_forwarder is not None:
                await retiring_forwarder.aclose()

    server = FastMCP(
        "freesearch",
        lifespan=lifespan,
        stateless_http=stateless_http,
    )

    del auth_service  # The transports own the account-store lifecycle.
    _register_tools(
        server,
        state=state,
        owns_client=owns_client,
        routes=routes,
        stdio_key=stdio_token,
    )
    if not owns_client:
        _INJECTED_TRACE_CLOSERS[server] = lambda: _close_traces(state)

    return server


def main(argv: Sequence[str] | None = None) -> None:
    """Run the MCP server over stdio or HTTP; every tool call needs a project API key."""
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
    exit_if_database_reset_required(resolve_database_path(None))

    auth_service = AuthService(effective)
    # Only stdio reads the process credential channel; an HTTP server never
    # holds a process key, so no HTTP call can fall back to one.
    stdio = args.transport == "stdio"
    server = create_server(
        stateless_http=args.stateless,
        auth_service=auth_service,
        stdio_token=effective.mcp_bearer_token if stdio else None,
    )
    if args.transport == "stdio":
        asyncio.run(run_stdio_server(server, auth_service=auth_service, settings=effective))
    else:
        asyncio.run(run_http_server(server, auth_service=auth_service, settings=effective))


if __name__ == "__main__":
    main()
