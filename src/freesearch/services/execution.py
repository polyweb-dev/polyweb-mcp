"""Transport-independent project execution (TASK-000042).

One service executes every provider search and fetch for the REST API and the
MCP server: it resolves the project's enabled bindings to usable credentials
(private or explicitly granted system ones), builds per-credential adapters,
plans pin/fallback/fanout exactly as the pre-binding routing contract did, and
reserves strict pool/project capacity plus the provider rails before any
vendor call. Attribution (verified project, actor, binding, credential, pool)
stamps every usage row, health observation, quota snapshot, admission, rate
attempt, and trace span on the way.

Fail-closed rules: a missing enabled binding, an unusable credential, an
unknown provider adapter factory, an unreadable pool, a capacity-store
failure, or a terminal reservation replay rejects the execution before any
provider I/O; a project with no bindings never falls back to a global key.
The service never imports a transport module, so every projection (HTTP
statuses, MCP tool errors) stays with the caller.

The service reads ``upstream_quota_pools.constraints`` as the documented JSON
list of canonical ``RateConstraint`` entries (``rolling_window``,
``window_seconds``, ``limit``), or explicit operation/unit rate entries shaped
``{"kind": "rate", "algorithm": "trailing_window", "window": <"1s"|"1m"|"1h"|"1d"|seconds>,
"limit": <number>, "unit": "requests"|"urls", "operations": ["search", ...]?}``.
An optional ``operations`` list scopes an entry to independent operation
allowances; an entry without it is one shared allowance. Any unreadable or
unknown shape is refused instead of silently dropping a ceiling. One atomic
admission covers the native funds/rate obligation and the strict pool/project
windows with one attempt identity, so the capacity tables carry project,
credential, binding, pool, request, and the verified actor on every row.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.registry import adapter_factory
from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_config import ProviderConfig, ProviderConfigError
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.observability import (
    NO_OP_OBSERVABILITY,
    ObservabilityRuntime,
    SpanKindName,
    current_observability,
)
from freesearch.infrastructure.resilience import (
    ProviderOperationError,
    RetryBudget,
    consume_retry_budget,
    reset_retry_budget,
    set_retry_budget,
)
from freesearch.infrastructure.secrets import ProviderName
from freesearch.infrastructure.trace_payloads import (
    _annotate_root,
    _annotate_root_error,
    _operation_name,
    _request_attributes,
    _search_results_payload,
)
from freesearch.models.contracts import (
    CostPreset,
    FallbackPolicy,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderHealth,
    ProviderTraceItem,
    QuotaSnapshot,
    RoutingMode,
    SearchRequest,
    SearchResponse,
    UsageEvent,
    UsageOperation,
    UsageStatus,
    is_soft_quota_zero,
)
from freesearch.models.credentials import CredentialOperation
from freesearch.models.execution_failures import (
    ExecutionAllFailed,
    ExecutionAuthorityUnavailable,
    ExecutionBindingMissing,
    ExecutionError,
    ExecutionNotPermitted,
    ExecutionQueueExpired,
    ExecutionRequestInvalid,
    ExecutionStorageUnavailable,
)
from freesearch.models.observability import (
    TRACE_EVENT_PROVIDER_REQUEST,
    TRACE_EVENT_PROVIDER_RESPONSE,
    AttemptBinding,
    ExecutionAttribution,
    TraceAttribute,
    TraceOperation,
    TraceSpanName,
)
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    ApiKeyStatus,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
    ProjectRolloutState,
    ProjectStatus,
)
from freesearch.models.provider_limits import (
    DEFAULT_ATTEMPT_LEASE_SECONDS,
    LimitAdmission,
    LimitCallContext,
    LimitOperation,
    LimitStoreUnavailable,
    PoolRateConstraint,
    ProviderObservationScope,
)
from freesearch.models.providers import RateConstraint
from freesearch.models.schema_enums import PoolStatus
from freesearch.persistence.api_keys import ProjectApiKeyRepository
from freesearch.persistence.bindings import ProjectBindingRepository, StoredBinding
from freesearch.persistence.limit_repository import (
    StrictAttemptSpec,
    StrictReservation,
    StrictWindowSpec,
)
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    StoredAllocation,
    StoredPool,
    UpstreamPoolRepository,
)
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import begin_read_snapshot
from freesearch.services.aggregation import reciprocal_rank_fusion
from freesearch.services.api_keys import api_key_status, principal_for
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.credentials import (
    CredentialService,
    CredentialStorageUnavailable,
    ResolvedCredential,
)
from freesearch.services.execution_authority import (
    DEFAULT_MAX_CONCURRENCY,
    DispatchGrant,
    ExecutionAuthority,
    QueuePolicy,
)
from freesearch.services.execution_scope import execution_attribution
from freesearch.services.monitoring import (
    ProviderTiming,
    _adapter_auth_mode,
    _terminal_quota_402,
    add_queue_wait,
    normalize_degenerate_quota,
    tracked_call,
)
from freesearch.services.projects import ProjectStorageUnavailable
from freesearch.services.provider_runtime import (
    build_adapter_with_secret,
    effective_config_for_name,
    routing_policy,
    schedule_quota_refresh,
)

logger = logging.getLogger(__name__)

_DEFAULT_ADAPTER_CACHE_SIZE = 32
_WINDOW_NAMES: dict[str, int] = {"1s": 1, "1m": 60, "1h": 3600, "1d": 86400}

#: Adapter cache identity: provider, credential, credential generation,
#: OAuth token generation (0 for API keys), and transport config.
_AdapterKey = tuple[str, UUID, int, int, str]


@dataclass
class _AdmissionGate:
    """Per-project admission order gate released when the queue admits work."""

    lock: asyncio.Lock
    started_at: float
    released: bool = False
    on_release: Callable[[], None] | None = None
    admission_key: tuple[str, UUID, UUID] | None = None

    def release(self) -> None:
        if not self.released:
            self.released = True
            if self.on_release is not None:
                self.on_release()
            self.lock.release()


_ADMISSION_GATE: ContextVar[_AdmissionGate | None] = ContextVar(
    "freesearch_admission_gate", default=None
)
_RETRY_NOT_BEFORE: ContextVar[float | None] = ContextVar(
    "freesearch_retry_not_before", default=None
)


def _terminal_out_of_credits(exc: BaseException) -> ProviderOperationError | None:
    """Return the terminal vendor out-of-credits error, else ``None``.

    The vendor 402 normalizes to ``quota_exhausted`` with ``status_code=402``
    and ``retryable=False``; only that exact shape is a terminal transport,
    never classified as rate limiting or a generic failure.
    """

    if not _terminal_quota_402(exc):
        return None
    return cast(ProviderOperationError, exc)


def _escapes_fanout(exc: BaseException) -> bool:
    """Return whether one fanout leg failure must abort the whole request.

    A terminal vendor out-of-Credits 402 keeps its pre-binding contract, and a
    revoked actor authority applies to every leg of the request, so neither is
    folded into a handled per-leg outcome.
    """

    return isinstance(exc, ExecutionNotPermitted) or _terminal_out_of_credits(exc) is not None


def _operation_code(operation: UsageOperation) -> CredentialOperation:
    """Return the credential-operation name of a usage operation."""

    return CredentialOperation(operation.value)


def _execute_action(operation: UsageOperation | CredentialOperation) -> PermissionAction:
    """Return the project permission that authorizes one execution operation."""

    if operation.value == UsageOperation.SEARCH.value:
        return PermissionAction.SEARCH_EXECUTE
    return PermissionAction.FETCH_EXECUTE


def _config_fingerprint(config: ProviderConfig | None) -> str:
    """Return a stable identity of the transport-relevant provider config."""

    if config is None:
        return "default"
    return hashlib.sha256(config.model_dump_json().encode("utf-8")).hexdigest()


def _limit_operation(operation: UsageOperation) -> LimitOperation:
    """Return the limit-catalog operation of a usage operation."""

    return LimitOperation(operation.value)


def _floor_limit(value: Decimal) -> int:
    """Return the conservative integer ceiling of one declared constraint limit."""

    if value < 0:
        return 0
    return int(value)


def _window_seconds(value: object) -> int | None:
    """Return one declared window as whole seconds, or ``None`` when unreadable.

    Documented windows use the catalog names (``1s``..``1d``); a numeric window
    is whole seconds. Booleans and out-of-range values are unreadable.
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        seconds = _WINDOW_NAMES.get(value, -1)
    else:
        return None
    if 1 <= seconds <= 86400:
        return seconds
    return None


def _pool_rate_windows(pool: StoredPool, operation: UsageOperation) -> list[_PoolRateWindow]:
    """Read one pool's declared rate constraints into enforceable windows.

    The documented payload is a list of rate entries. Any unreadable list,
    entry, key, kind, algorithm, window, limit, unit, or operation selector is
    refused instead of silently dropping a cap. An entry without an
    ``operations`` selector is one shared allowance across every operation;
    an entry that declares a non-empty operation list is independent and only
    applies to those operations. Entries that collapse onto the same bucket
    keep the strictest limit.
    """

    if not isinstance(pool.constraints, list):
        raise ExecutionError("the upstream pool declares unreadable rate constraints")
    windows: list[_PoolRateWindow] = []
    for entry in pool.constraints:
        window = _rate_entry_window(entry, pool.id, operation)
        if window is not None:
            windows.append(window)
    strictest: dict[str, _PoolRateWindow] = {}
    for window in windows:
        prior = strictest.get(window.bucket_id)
        if prior is None or window.limit_units < prior.limit_units:
            strictest[window.bucket_id] = window
    return [strictest[key] for key in sorted(strictest)]


def _rate_entry_window(
    entry: object, pool_id: UUID, operation: UsageOperation
) -> _PoolRateWindow | None:
    """Parse one declared rate entry, or refuse an unreadable/unknown shape."""

    try:
        if isinstance(entry, dict) and "window_seconds" in entry:
            declared = RateConstraint.model_validate(entry)
            if declared.algorithm != "rolling_window":
                raise ExecutionError("the upstream pool declares an unsupported rate algorithm")
            constraint = PoolRateConstraint(
                window=declared.window_seconds, limit=Decimal(declared.limit)
            )
        else:
            constraint = PoolRateConstraint.model_validate(entry)
    except ValidationError as error:
        raise ExecutionError("the upstream pool declares an invalid rate constraint") from error
    if constraint.operations is not None and operation.value not in constraint.operations:
        return None
    seconds = _window_seconds(constraint.window)
    if seconds is None:
        raise ExecutionError("the upstream pool declares an unreadable rate window")
    bucket_id = (
        f"pool:{pool_id}:{operation.value}:{seconds}"
        if constraint.operations is not None
        else f"pool:{pool_id}:{seconds}"
    )
    return _PoolRateWindow(
        bucket_id,
        seconds,
        _floor_limit(constraint.limit),
        constraint.unit,
    )


@dataclass(frozen=True)
class _PoolRateWindow:
    """One declared pool constraint read into an enforceable window."""

    bucket_id: str
    window_seconds: int
    limit_units: int
    declared_unit: str


@dataclass(frozen=True)
class _Leg:
    """One dispatchable plan leg: project binding to a usable credential."""

    binding: StoredBinding
    credential: ResolvedCredential
    pool: StoredPool | None
    allocation: StoredAllocation | None
    config: ProviderConfig
    lease: _AdapterLease
    context: ProjectContext
    #: Strictest project concurrency across every pool/operation allocation.
    project_max_concurrency: int | None = None

    @property
    def adapter(self) -> ProviderAdapter:
        return self.lease.adapter

    @property
    def provider(self) -> str:
        """Return the provider type the leg calls (the adapter's registry key)."""

        return self.credential.provider_type

    @property
    def binding_id(self) -> UUID:
        return self.binding.id

    @property
    def supports_search(self) -> bool:
        return self.adapter.capabilities.search

    @property
    def supports_fetch(self) -> bool:
        return self.adapter.capabilities.fetch


class _AdapterLease:
    """One request's borrow of a cached adapter.

    Releasing the last lease of a retired entry closes the adapter, so a
    config rewrite or credential generation change can stop new requests from
    using an obsolete adapter without closing one that is still in flight.
    """

    __slots__ = ("_cache", "_key", "_released", "adapter")

    def __init__(
        self,
        cache: CredentialAdapterCache,
        key: _AdapterKey,
        adapter: ProviderAdapter,
    ) -> None:
        self._cache = cache
        self._key = key
        self.adapter = adapter
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._cache.release(self._key)


class _CacheEntry:
    __slots__ = ("active", "adapter", "retired")

    def __init__(self, adapter: ProviderAdapter) -> None:
        self.adapter = adapter
        self.active = 0
        self.retired = False


class CredentialAdapterCache:
    """Per-credential adapter cache keyed by provider, credential, generation, config.

    Circuit breakers, cooldowns, and quota caches live on the adapter
    instance, so keying the cache by credential identity and generation
    isolates one credential's failures from an unrelated credential and picks
    up its rotation without a restart. The effective transport configuration
    is part of the key, so a dev-to-prod Tavily rail or a changed PAYGO mode
    builds a fresh adapter instead of serving the old one. Retired entries
    stay open until their last lease releases, preserving in-flight
    correctness; the bounded LRU only retires idle adapters early.
    """

    def __init__(self, max_entries: int = _DEFAULT_ADAPTER_CACHE_SIZE) -> None:
        self._lock = asyncio.Lock()
        self._max_entries = max(1, max_entries)
        self._entries: dict[_AdapterKey, _CacheEntry] = {}
        self._order: list[_AdapterKey] = []
        self._closing: set[asyncio.Task[None]] = set()

    async def lease(
        self,
        key: _AdapterKey,
        builder: Callable[[], ProviderAdapter],
    ) -> _AdapterLease:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _CacheEntry(builder())
                self._entries[key] = entry
                self._order.append(key)
            else:
                with suppress(ValueError):
                    self._order.remove(key)
                self._order.append(key)
            entry.active += 1
            self._trim_locked()
            return _AdapterLease(self, key, entry.adapter)

    def release(self, key: _AdapterKey) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.active = max(0, entry.active - 1)
        if entry.retired and entry.active == 0:
            self._entries.pop(key, None)
            with suppress(ValueError):
                self._order.remove(key)
            self._retire(entry.adapter)
        self._trim_locked()

    def retire_other_configs(
        self, provider: str, credential_id: UUID, generation: int, keep: _AdapterKey
    ) -> None:
        """Retire adapter entries of one credential/generation with another config."""

        for key in list(self._entries):
            if key == keep or key[:3] != (provider, credential_id, generation):
                continue
            self._retire_entry(key)

    def retire_other_generations(
        self, credential_id: UUID, generation: int, keep: _AdapterKey
    ) -> None:
        """Retire every older generation adapter of one credential."""

        for key in list(self._entries):
            if key == keep or key[1] != credential_id or key[2] == generation:
                continue
            self._retire_entry(key)

    def retire_other_tokens(
        self, credential_id: UUID, token_generation: int, keep: _AdapterKey
    ) -> None:
        """Retire adapters built for an older OAuth token generation."""

        for key in list(self._entries):
            if key == keep or key[1] != credential_id or key[3] == token_generation:
                continue
            self._retire_entry(key)

    def _retire_entry(self, key: _AdapterKey) -> None:
        entry = self._entries.get(key)
        if entry is None or entry.retired:
            return
        entry.retired = True
        if entry.active == 0:
            self._entries.pop(key, None)
            with suppress(ValueError):
                self._order.remove(key)
            self._retire(entry.adapter)

    def _trim_locked(self) -> None:
        while len(self._order) > self._max_entries:
            calm = next(
                (
                    key
                    for key in self._order
                    if self._entries.get(key) is not None and self._entries[key].active == 0
                ),
                None,
            )
            if calm is None:
                return
            self._retire_entry(calm)

    def _retire(self, adapter: ProviderAdapter) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._close(adapter))
        except RuntimeError:
            return
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    @staticmethod
    async def _close(adapter: ProviderAdapter) -> None:
        with suppress(Exception):
            await adapter.aclose()

    async def aclose(self) -> None:
        """Close every cached adapter; safe to call repeatedly."""

        async with self._lock:
            adapters, self._entries, self._order = (
                [entry.adapter for entry in self._entries.values()],
                {},
                [],
            )
        for adapter in adapters:
            with suppress(Exception):
                await adapter.aclose()
        pending, self._closing = list(self._closing), set()
        for task in pending:
            with suppress(Exception, asyncio.CancelledError):
                await task


@dataclass(frozen=True)
class _AttemptCapacity:
    """One dispatch's combined capacity reservation and its terminal hooks."""

    attempt_id: str
    admission: LimitAdmission | None
    strict: StrictReservation | None
    repository_limits: Any

    async def complete_dispatch(self) -> None:
        """Release this send's concurrency after a known upstream response."""
        await self.repository_limits.complete_dispatch(self.attempt_id)

    async def settle(self, outcome: str) -> None:
        """Settle the strict window debit; a native admission finalizes first."""

        if self.strict is not None:
            await self.repository_limits.settle_strict(
                attempt_id=self.strict.attempt_id,
                outcome=cast(Literal["completed", "failed", "uncertain"], outcome),
            )


class ExecutionService:
    """The one execution path shared by REST and MCP."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        secret_store: EncryptedDbSecretStore,
        client: Any = None,
        limits: Any = None,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        observability: ObservabilityRuntime = NO_OP_OBSERVABILITY,
        max_cache_adapters: int = _DEFAULT_ADAPTER_CACHE_SIZE,
        rollout_state: ProjectRolloutState | None = None,
        authority: ExecutionAuthority | None = None,
        host_authority: bool = True,
        retry_backoff: Callable[[], float] | None = None,
        retry_sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._secret_store = secret_store
        self._limits = limits
        self._account_id = account_id
        # One authority per database. A standalone transport that must forward
        # instead of hosting passes ``host_authority=False``; a borrowed pool
        # then fails closed rather than starting a second fair queue.
        self._authority = (
            authority
            if authority is not None
            else ExecutionAuthority(
                repository,
                limits=limits,
                default_max_wait_ms=get_settings().execution_queue_max_wait_ms,
                default_max_requests=get_settings().execution_queue_max_requests,
                default_max_bytes=get_settings().execution_queue_max_bytes,
                default_max_concurrency=get_settings().execution_queue_max_concurrency,
                default_project_max_concurrency=(get_settings().execution_project_max_concurrency),
                lease_seconds=get_settings().execution_authority_lease_seconds,
                recovery_seconds=get_settings().execution_authority_recovery_seconds,
            )
            if host_authority
            else None
        )
        self._retry_backoff = retry_backoff or (lambda: random.uniform(0.01, 0.05))
        self._retry_sleep = retry_sleep or asyncio.sleep
        # The credential seam enforces the configured projects rollout gate on
        # every resolution; an unknown rollout state fails execution closed.
        self._credentials = CredentialService(
            repository,
            secret_store,
            account_id=account_id,
            rollout_state=(
                rollout_state
                if rollout_state is not None
                else get_settings().projects_rollout_state
            ),
        )
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._adapter_cache = CredentialAdapterCache(max_entries=max_cache_adapters)
        self._client = client
        self._admission_locks: dict[UUID, asyncio.Lock] = {}
        self._quota_tasks: set[asyncio.Task[Any]] = set()
        self._owns_client = client is None
        self._closed = False
        # The observability argument exists for compositions that pre-build a
        # runtime; every span call resolves the active runtime per request, so
        # a root span bound to a request is never replaced.
        del observability

    # ------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        """Close cached credential adapters and any owned HTTP client."""

        self._closed = True
        tasks = list(self._quota_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        authority = self._authority
        self._authority = None
        if authority is not None:
            await authority.aclose()
        await self._adapter_cache.aclose()
        client = self._client
        self._client = None
        if self._owns_client and client is not None:
            with suppress(Exception):
                await client.aclose()

    @property
    def credentials(self) -> CredentialService:
        """Trusted credential resolution owned by this service."""

        return self._credentials

    @property
    def repository(self) -> SQLiteRepository:
        """The operational repository the service resolves scope and capacity on."""

        return self._repository

    @property
    def limits(self) -> Any:
        """The provider-rails limit service (may be unset in a lean composition)."""

        return self._limits

    def set_limits(self, limits: Any) -> None:
        """Attach the rails after a generation that starts them lazily."""

        self._limits = limits

    # -------------------------------------------------------------- public

    async def search(
        self,
        request: SearchRequest,
        *,
        attribution: ExecutionAttribution,
        context: ProjectContext,
        deadline: float | None = None,
    ) -> SearchResponse:
        """Execute one search request inside the verified ``context``.

        ``deadline`` is one monotonic end-to-end instant shared by queue wait,
        every retry, and every fallback leg of this logical request.
        """

        deadline = self._logical_deadline(deadline)
        budget_token = set_retry_budget(RetryBudget(1))

        async def run() -> SearchResponse:
            observability = current_observability()
            with observability.span(TraceSpanName.BACKEND, attributes=_request_attributes(request)):
                if request.fanout or request.routing.mode is RoutingMode.FANOUT:
                    return await self._fanout_search(
                        request, attribution=attribution, context=context, deadline=deadline
                    )
                return cast(
                    SearchResponse,
                    await self._single(
                        request,
                        UsageOperation.SEARCH,
                        attribution=attribution,
                        context=context,
                        deadline=deadline,
                    ),
                )

        try:
            return await self._admitted(
                context.project_id,
                run,
                deadline=deadline,
                payload_bytes=len(request.model_dump_json().encode("utf-8")),
            )
        finally:
            reset_retry_budget(budget_token)

    async def fetch(
        self,
        request: FetchRequest,
        *,
        attribution: ExecutionAttribution,
        context: ProjectContext,
        deadline: float | None = None,
    ) -> FetchResponse:
        """Execute one fetch request inside the verified ``context``."""

        if request.url_count != 1:
            raise ExecutionRequestInvalid("this release executes exactly one URL per fetch request")
        deadline = self._logical_deadline(deadline)
        budget_token = set_retry_budget(RetryBudget(1))

        async def run() -> FetchResponse:
            observability = current_observability()
            with observability.span(TraceSpanName.BACKEND, attributes=_request_attributes(request)):
                return cast(
                    FetchResponse,
                    await self._single(
                        request,
                        UsageOperation.FETCH,
                        attribution=attribution,
                        context=context,
                        deadline=deadline,
                    ),
                )

        try:
            return await self._admitted(
                context.project_id,
                run,
                deadline=deadline,
                payload_bytes=len(request.model_dump_json().encode("utf-8")),
            )
        finally:
            reset_retry_budget(budget_token)

    async def _admitted[ResultT](
        self,
        project_id: UUID,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        deadline: float,
        payload_bytes: int,
    ) -> ResultT:
        """Serialize one project's admission through its first queue entry.

        Resolution is slower than enqueueing, so without this gate a later
        request could reach the bounded queue before an earlier one and steal
        its slot. The gate orders admission, not dispatch: it is released the
        moment the first queue entry is appended, and all provider work stays
        concurrent. A genuine admission waiter is counted in the same
        authority-wide count/byte budget as queued work and is bounded by the
        logical request deadline and the configured queue wait; the count
        transfers to the queue entry rather than being released in a gap.
        """

        lock = self._admission_locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._admission_locks[project_id] = lock
        reservation = (
            self._authority.reserve_admission(project_id=project_id, payload_bytes=payload_bytes)
            if self._authority is not None and lock.locked()
            else None
        )
        wait_seconds = (
            self._authority.default_max_wait_seconds
            if self._authority is not None
            else get_settings().execution_queue_max_wait_ms / 1000.0
        )
        remaining = self._remaining_before_deadline(deadline)
        timeout = wait_seconds if remaining is None else max(0.0, min(wait_seconds, remaining))
        gate = _AdmissionGate(
            lock=lock,
            started_at=(self._authority.now() if self._authority is not None else time.monotonic()),
            on_release=(None if reservation is None else reservation.release),
            admission_key=(None if reservation is None else reservation.key),
        )
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except TimeoutError as error:
            if reservation is not None:
                reservation.release()
            raise ExecutionQueueExpired(
                "the execution admission wait bound expired before dispatch"
            ) from error
        except BaseException:
            if reservation is not None:
                reservation.release()
            raise
        token = _ADMISSION_GATE.set(gate)
        try:
            return await operation()
        finally:
            _ADMISSION_GATE.reset(token)
            if reservation is not None:
                reservation.release()
            gate.release()

    def _logical_deadline(self, deadline: float | None) -> float:
        """Return one server-bounded deadline for the whole logical request."""

        now = self._authority.now() if self._authority is not None else time.monotonic()
        server = now + max(0.001, get_settings().execution_request_timeout_seconds)
        return server if deadline is None else min(deadline, server)

    def _remaining_before_deadline(self, deadline: float | None) -> float | None:
        """Return remaining seconds until ``deadline``, or ``None`` when absent."""

        if deadline is None:
            return None
        now = self._authority.now() if self._authority is not None else time.monotonic()
        return deadline - now

    # ---------------------------------------------------------- resolution

    @staticmethod
    def _retry_allowed(error: ProviderOperationError) -> bool:
        """Return whether this logical request may retry one provider attempt."""

        return bool(error.error.retryable) and not _terminal_out_of_credits(error)

    @staticmethod
    def _retry_after_seconds(error: ProviderOperationError) -> float | None:
        """Return the provider's declared Retry-After delay, or ``None``."""

        details = error.error.details if isinstance(error.error.details, dict) else {}
        retry_after = details.get("retry_after_seconds")
        if isinstance(retry_after, bool) or not isinstance(retry_after, (int, float)):
            return None
        return max(0.0, float(retry_after))

    def _retry_delay(self, error: ProviderOperationError) -> tuple[float, bool]:
        """Return ``(delay, announced)`` for one retry.

        ``announced`` is true when the vendor supplied Retry-After, so the
        delay is exact and must never be shortened or jittered; otherwise the
        delay is the bounded injectable backoff. A missing header uses real
        time, leaving the virtual queue clock untouched.
        """

        retry_after = self._retry_after_seconds(error)
        if retry_after is not None:
            return retry_after, True
        return max(0.0, self._retry_backoff()), False

    def _deadline_passed(self, deadline: float | None) -> bool:
        remaining = self._remaining_before_deadline(deadline)
        return remaining is not None and remaining <= 0

    async def _defer_retry(self, leg: _Leg, delay: float, announced: bool) -> None:
        """Defer one retry on the queue clock or a bounded real backoff.

        A pooled leg requeues on the authority's injected monotonic clock, so
        the delay is observable to the scheduler. An unpooled leg has no
        scheduler, so an announced Retry-After waits in real time; a missing
        header always uses the bounded injectable backoff and never moves the
        virtual clock.
        """

        if announced and leg.pool is not None and self._authority is not None:
            _RETRY_NOT_BEFORE.set(self._authority.now() + delay)
            return
        await self._retry_sleep(delay)

    @staticmethod
    def _provider_subset(request: SearchRequest | FetchRequest) -> frozenset[str] | None:
        """Return the required provider subset read before any provider config.

        Only REQUIRE (and FANOUT with providers) excludes other providers.
        AUTO/PREFER still inspect every eligible provider, so their malformed
        configuration remains a visible failure instead of a silent reroute.
        """

        preference = request.routing
        if preference.providers and preference.mode in (RoutingMode.REQUIRE, RoutingMode.FANOUT):
            return frozenset(preference.providers)
        return None

    async def _usable_legs(
        self,
        context: ProjectContext,
        operation: CredentialOperation,
        *,
        providers: frozenset[str] | None = None,
    ) -> list[_Leg]:
        """Resolve the enabled bindings of this project to dispatchable legs.

        One session reads the bindings, the usable credential of each, its
        upstream pool link, pool row, and project allocation; secret
        resolution then runs the trusted grant-aware service seam. A binding
        whose credential is unusable, factory unknown, pool missing/disabled,
        or secret unreadable is skipped, never guessed: an empty result fails
        closed and the caller answers a missing binding. ``providers`` is the
        required routing subset: an unrelated provider's configuration and
        adapter are never read or validated for a request that cannot select
        it.
        """

        legs: list[_Leg] = []
        try:
            legs = await self._resolve_legs(context, operation, providers=providers)
        except (CredentialStorageUnavailable, ProjectStorageUnavailable, OperationalError) as error:
            # A failed credential or authorization store (or a rollout state
            # that disables the credential seam) is a store failure:
            # constrained execution cannot proceed, so the transports answer 503.
            raise ExecutionStorageUnavailable("the credential store is unavailable") from error
        return legs

    async def _schedule_quotas(self, legs: Sequence[_Leg]) -> None:
        """Keep adapters leased for the entire scoped background refresh."""
        if self._closed:
            return
        leases: list[_AdapterLease] = []
        task: asyncio.Task[Any] | None = None
        try:
            for leg in legs:
                leases.append(await self._lease_adapter(leg.credential, leg.config))
            scopes = {
                id(leg.adapter): ProviderObservationScope(
                    credential_id=leg.credential.credential_id,
                    upstream_pool_id=leg.pool.id if leg.pool is not None else None,
                    credential_generation=leg.credential.generation,
                )
                for leg in legs
            }
            task = schedule_quota_refresh(
                self._repository,
                [leg.adapter for leg in legs],
                self._secret_store,
                scopes=scopes,
                limits=self._limits,
            )
            if task is None:
                return
            self._quota_tasks.add(task)

            def finished(done: asyncio.Task[Any]) -> None:
                self._quota_tasks.discard(done)
                for lease in leases:
                    lease.release()

            task.add_done_callback(finished)
        finally:
            if task is None:
                for lease in leases:
                    lease.release()

    async def _resolve_legs(
        self,
        context: ProjectContext,
        operation: CredentialOperation,
        *,
        providers: frozenset[str] | None = None,
    ) -> list[_Leg]:
        """Read one project's enabled bindings and map each onto a leg.

        The live actor authorization runs first, in the same read snapshot as
        the binding rows, so no credential material is resolved for an actor
        whose authority was revoked after the boundary admitted the request.
        """

        legs: list[_Leg] = []
        try:
            async with self._repository.session() as session:
                await begin_read_snapshot(session)
                context = await self._live_context_in_session(session, context, operation)
                bindings = await ProjectBindingRepository(session).list_for_project(
                    project_id=context.project_id
                )
                allocations = await PoolAllocationRepository(session).list_for_project(
                    project_id=context.project_id
                )
            caps = [
                allocation.max_concurrency
                for allocation in allocations
                if allocation.max_concurrency is not None
            ]
            project_cap = min(caps) if caps else None
            for binding in bindings:
                leg = await self._resolve_binding(
                    context,
                    binding,
                    operation,
                    providers=providers,
                    project_max_concurrency=project_cap,
                )
                if leg is not None:
                    legs.append(leg)
        except BaseException:
            _release_legs(legs)
            raise
        return legs

    async def _resolve_binding(
        self,
        context: ProjectContext,
        binding: StoredBinding,
        operation: CredentialOperation,
        *,
        providers: frozenset[str] | None,
        project_max_concurrency: int | None = None,
    ) -> _Leg | None:
        """Resolve one enabled binding, or return ``None`` when it is unusable."""

        if operation not in binding.enabled_operations:
            return None
        credential: ResolvedCredential | None = None
        pool: StoredPool | None = None
        allocation: StoredAllocation | None = None
        # One short session resolves the credential, its pool link and the
        # project allocation. The provider configuration lookup runs after it
        # closes: it opens its own settings sessions, and nesting that lookup
        # under this one could exhaust a bounded SQLite pool at high
        # concurrency.
        async with self._repository.session() as session:
            await begin_read_snapshot(session)
            usable = await self._credentials.usable_credential_in_session(
                session,
                project_id=context.project_id,
                credential_id=binding.credential_id,
                operation=operation,
            )
            if usable is None:
                return None
            if providers is not None and usable.provider_type not in providers:
                return None
            if adapter_factory(usable.provider_type) is None:
                return None
            pools = UpstreamPoolRepository(session)
            link = await pools.pool_for_credential(credential_id=usable.id, operation=operation)
            if link is not None:
                try:
                    pool = await pools.get_pool(account_id=self._account_id, pool_id=link.pool_id)
                except ValueError as error:
                    raise ExecutionError(
                        "the upstream pool declares unreadable constraints"
                    ) from error
                if pool is None or pool.status is not PoolStatus.ACTIVE:
                    return None
                if not pool.constraints_valid:
                    raise ExecutionError("the upstream pool declares unreadable constraints")
            if pool is not None:
                allocation = await PoolAllocationRepository(session).get(
                    project_id=context.project_id,
                    pool_id=pool.id,
                    operation=operation,
                )
            credential = await self._credentials.resolve_material_in_session(
                session,
                context,
                usable.id,
                operation=operation,
                expected_generation=usable.generation,
                usable=usable,
            )
        if credential is None:
            return None
        try:
            config = await effective_config_for_name(
                self._repository, credential.provider_type, strict=True
            )
        except ProviderConfigError as error:
            raise ExecutionError(str(error)) from error
        return _Leg(
            binding=binding,
            credential=credential,
            pool=pool,
            allocation=allocation,
            config=config,
            lease=await self._lease_adapter(credential, config),
            context=context,
            project_max_concurrency=project_max_concurrency,
        )

    async def _lease_adapter(
        self, credential: ResolvedCredential, config: ProviderConfig | None = None
    ) -> _AdapterLease:
        """Lease the cached adapter of one credential and configuration."""

        if self._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        fingerprint = _config_fingerprint(config)
        token_generation = credential.token_generation or 0
        key = (
            credential.provider_type,
            credential.credential_id,
            credential.generation,
            token_generation,
            fingerprint,
        )

        def build() -> ProviderAdapter:
            factory = adapter_factory(credential.provider_type)
            if factory is None:
                raise ExecutionError(
                    f"no provider adapter is available for {credential.provider_type}"
                )
            client = self._client if self._client is not None else self._own_client()
            tavily_config = (
                config if credential.provider_type == ProviderName.TAVILY.value else None
            )
            return build_adapter_with_secret(
                factory,
                client,
                credential.secret.get_secret_value(),
                config=tavily_config,
            )

        lease = await self._adapter_cache.lease(key, build)
        self._adapter_cache.retire_other_configs(
            credential.provider_type, credential.credential_id, credential.generation, key
        )
        self._adapter_cache.retire_other_generations(
            credential.credential_id, credential.generation, key
        )
        self._adapter_cache.retire_other_tokens(
            credential.credential_id,
            token_generation,
            key,
        )
        return lease

    def _own_client(self) -> Any:
        """Build and remember the process-owned HTTP client for adapters.

        A composition that supplied a client keeps ownership; the service
        without one builds its own and closes it with the service.
        """

        if not self._owns_client:
            raise ExecutionError("the adapter composition supplied no HTTP client")
        self._client = create_async_client()
        return self._client

    # ------------------------------------------------------------ planning

    async def _plan(
        self,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        legs: Sequence[_Leg],
    ) -> list[tuple[_Leg, ProviderAdapter]]:
        """Order and select legs with the pre-binding routing semantics.

        Eligibility is the adapter capability and the provider mask, then
        health and a hard quota per credential rank. The persisted provider
        priority, binding priority, route label, and binding id give the
        deterministic pre-health order; the health rank and provider
        preference re-rank exactly as ``select_route`` did, a REQUIRE
        preference filters providers, and the free-first cost preset pins the
        keyless system rail ahead of paid ones under stable ties.
        """

        preference = request.routing
        candidates = [leg for leg in legs if self._leg_allows(leg, request, operation)]
        if not candidates:
            raise ExecutionBindingMissing(
                "no required provider is eligible: " + ", ".join(sorted(preference.providers))
                if preference.mode is RoutingMode.REQUIRE and preference.providers
                else f"no eligible provider is available for {operation.value}"
            )
        if preference.binding_id is not None:
            pinned = [leg for leg in candidates if leg.binding.id == preference.binding_id]
            if not pinned:
                raise ExecutionBindingMissing(
                    "the pinned binding is not enabled and usable for this project"
                )
            candidates = pinned
        if preference.mode is RoutingMode.REQUIRE and preference.providers:
            required = set(preference.providers)
            candidates = [leg for leg in candidates if leg.provider in required]
            if not candidates:
                raise ExecutionBindingMissing(
                    "no required provider is eligible: " + ", ".join(sorted(required))
                )
        if preference.mode is RoutingMode.FANOUT and preference.providers:
            required = set(preference.providers)
            candidates = [leg for leg in candidates if leg.provider in required]
            if not candidates:
                raise ExecutionBindingMissing("no eligible provider is available for fanout")
        policy = await routing_policy(self._repository)
        health, quotas = await self._health_and_quota(candidates)
        usable = [leg for leg in candidates if not self._leg_blocked(leg, health, quotas)]
        if not usable:
            quota_denied = any(self._leg_quota_blocked(leg, quotas) for leg in candidates)
            if preference.mode is RoutingMode.REQUIRE and preference.providers and quota_denied:
                raise ExecutionBindingMissing(
                    "no required provider is eligible: " + ", ".join(sorted(preference.providers))
                )
            raise ExecutionBindingMissing(
                "no required provider is eligible: " + ", ".join(sorted(preference.providers))
                if preference.mode is RoutingMode.REQUIRE and preference.providers
                else f"no eligible provider is available for {operation.value}"
            )
        ordered = self._rank(usable, preference.providers, policy, health)
        if preference.mode is RoutingMode.FANOUT:
            return [(leg, leg.adapter) for leg in ordered]
        if not preference.allow_fallback or (policy.fallback_policy is FallbackPolicy.FIRST_ONLY):
            ordered = ordered[:1]
        return [(leg, leg.adapter) for leg in ordered]

    def _leg_allows(
        self, leg: _Leg, request: SearchRequest | FetchRequest, operation: UsageOperation
    ) -> bool:
        """Return whether one leg supports the operation (mask and capability)."""

        supports = leg.supports_search if isinstance(request, SearchRequest) else leg.supports_fetch
        return bool(supports and leg.config.allows(operation))

    async def _health_and_quota(
        self, legs: Sequence[_Leg]
    ) -> tuple[dict[UUID, ProviderHealth], dict[UUID, QuotaSnapshot]]:
        """Read per-credential health and quota observations for the plan.

        Provider-wide outage facts (unattributed rows) apply to every
        credential through the union read, while a credential's own degraded
        observation never blocks its siblings; reads degrade to no snapshot.
        """

        health: dict[UUID, ProviderHealth] = {}
        quotas: dict[UUID, QuotaSnapshot] = {}
        providers = sorted({leg.provider for leg in legs})
        shared_health: dict[str, ProviderHealth] = {}
        if providers:
            try:
                health_batch = getattr(self._repository, "latest_health_batch", None)
                if callable(health_batch):
                    shared_health = await health_batch(providers)
            except Exception:
                shared_health = {}
        for leg in legs:
            try:
                observation = await self._repository.latest_health(
                    leg.provider, credential_id=leg.credential.credential_id
                )
                if observation is None:
                    observation = shared_health.get(leg.provider)
                if observation is not None:
                    health[leg.binding_id] = observation
            except Exception:
                pass
            try:
                latest_quota = await self._repository.latest_quota(
                    leg.provider,
                    credential_id=leg.credential.credential_id,
                    pool_id=leg.pool.id if leg.pool is not None else None,
                )
                if latest_quota is not None:
                    quotas[leg.binding_id] = normalize_degenerate_quota(latest_quota)
            except Exception:
                pass
        return health, quotas

    @staticmethod
    def _leg_blocked(
        leg: _Leg, health: Mapping[UUID, ProviderHealth], quotas: Mapping[UUID, QuotaSnapshot]
    ) -> bool:
        """Exclude a leg that is credential-unavailable or hard-exhausted."""

        observation = health.get(leg.binding_id)
        if observation is not None and observation.status is HealthStatus.UNAVAILABLE:
            return True
        return ExecutionService._leg_quota_blocked(leg, quotas)

    @staticmethod
    def _leg_quota_blocked(leg: _Leg, quotas: Mapping[UUID, QuotaSnapshot]) -> bool:
        """Return whether a hard funds/quota zero blocks one leg."""

        quota = quotas.get(leg.binding_id)
        if quota is None:
            return False
        return (
            quota.remaining == Decimal("0")
            and quota.limit is not None
            and quota.limit > Decimal("0")
            and not is_soft_quota_zero(leg.provider, quota)
        )

    @staticmethod
    def _rank(
        all_legs: Sequence[_Leg],
        preference: tuple[str, ...],
        policy: Any,
        health: Mapping[UUID, ProviderHealth],
    ) -> list[_Leg]:
        """Rank legs by health, provider preference, then configured order.

        The precedence mirrors ``select_route``: healthier first, preferred
        providers first, and inside a tie the free-first pin (for that preset),
        the persisted provider priority, binding priority, route label, and
        binding id break deterministically. Adapters were ranked by name alone
        before; a binding's exact credential is now part of the rank, so two
        credentials of one provider are both addressable.
        """

        health_order = (
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNKNOWN,
        )
        pin_free_first = policy.cost_optimization_preset is CostPreset.FREE_FIRST

        def _key(leg: _Leg) -> tuple[int, int, int, int, int, str, str]:
            observation = health.get(leg.binding_id)
            rank = HealthStatus.UNKNOWN if observation is None else observation.status
            return (
                health_order.index(rank),
                0 if leg.provider in preference else 1,
                0 if pin_free_first and leg.provider == "keenable" else 1,
                leg.config.priority,
                leg.binding.priority,
                leg.binding.route_label,
                str(leg.binding.id),
            )

        return sorted(all_legs, key=_key)

    # ------------------------------------------------------------ attempts

    def _binding_of(self, leg: _Leg) -> AttemptBinding:
        """Return the telemetry binding trio of one attempt."""
        return AttemptBinding(
            binding_id=leg.binding.id,
            credential_id=leg.credential.credential_id,
            pool_id=leg.pool.id if leg.pool is not None else None,
        )

    def _rails_context(
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        attribution: ExecutionAttribution,
        *,
        attempt_id: str | None = None,
    ) -> LimitCallContext:
        """Build the rails admission context of one dispatch attempt.

        The rails admission and the strict reservation share this one attempt
        id; there is no second strict identity to double count concurrency.
        The trusted identity rides both: the admission writes
        project/credential/binding/pool attribution and the actor reaches the
        durable capacity rows.
        """

        trace_id = current_observability().current_trace_id()
        return LimitCallContext(
            provider=leg.provider,
            operation=_limit_operation(operation),
            auth_mode=_adapter_auth_mode(leg.adapter),
            attempt_id=attempt_id or uuid4().hex,
            request=request,
            requested_at=datetime.now(UTC),
            credential_generation=leg.credential.generation,
            project_id=attribution.project_id,
            credential_id=leg.credential.credential_id,
            binding_id=leg.binding.id,
            upstream_pool_id=leg.pool.id if leg.pool is not None else None,
            request_id=trace_id,
            actor_type=attribution.actor_type,
            actor_id=attribution.actor_id,
        )

    def _strict_spec(
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        attribution: ExecutionAttribution,
    ) -> StrictAttemptSpec | None:
        """Build the strict pool/project reservation of one attempt, or ``None``.

        Windows come from the project allocation (its effective ceiling) plus
        the pool's declared rate constraints (the strictest declared limit per
        window wins); concurrency caps come from the pool row and the
        allocation, with finite defaults when the configuration declares none.
        Without any window or cap the leg is unconstrained at strict scope and
        the provider rails still apply.

        With loans enabled the allocation's base rate is a contention
        entitlement, not a service bucket: every actual attempt debits ONE
        durable absolute-ceiling window whose limit is ``max_rate``. Base and
        loan grants alike are bounded by it, so an authority replacement
        cannot partition the ceiling. Strict mode uses the base rate, which is
        also its effective ceiling, on the same single bucket.
        """

        windows: list[StrictWindowSpec] = []
        pool_id = leg.pool.id if leg.pool is not None else None
        allocation = leg.allocation
        if allocation is not None and pool_id is not None:
            # One stable absolute-ceiling identity for both loans modes. The
            # ceiling value may change with the policy, but the bucket cannot:
            # toggling loans must not hide the current window's earlier
            # attempts from the new policy's accounting.
            bucket = f"project:{allocation.project_id}:{pool_id}:{operation.value}"
            windows.append(
                StrictWindowSpec(
                    bucket_id=f"{bucket}:ceiling",
                    window_seconds=allocation.rate_window_seconds,
                    limit_units=allocation.effective_max_rate,
                )
            )
        if pool_id is not None and leg.pool is not None:
            for declared in _pool_rate_windows(leg.pool, operation):
                windows.append(
                    StrictWindowSpec(
                        bucket_id=declared.bucket_id,
                        window_seconds=declared.window_seconds,
                        limit_units=declared.limit_units,
                    )
                )
        if not windows and leg.pool is None:
            return None
        trace_id = current_observability().current_trace_id()
        return StrictAttemptSpec(
            project_id=attribution.project_id,
            credential_id=leg.credential.credential_id,
            binding_id=leg.binding.id,
            pool_id=pool_id,
            request_id=trace_id,
            windows=tuple(windows),
            pool_max_concurrency=(
                DEFAULT_MAX_CONCURRENCY if leg.pool is None else leg.pool.max_concurrency
            )
            or DEFAULT_MAX_CONCURRENCY,
            project_max_concurrency=(
                DEFAULT_MAX_CONCURRENCY
                if leg.allocation is None or leg.allocation.max_concurrency is None
                else leg.allocation.max_concurrency
            ),
            units_per_attempt=Decimal("1"),
            lease_seconds=DEFAULT_ATTEMPT_LEASE_SECONDS,
            actor_type=attribution.actor_type,
            actor_id=attribution.actor_id,
        )

    async def _live_context_in_session(
        self,
        session: Any,
        context: ProjectContext,
        operation: UsageOperation | CredentialOperation,
    ) -> ProjectContext:
        """Re-authorize the verified actor against current durable state.

        ``context.effective_permissions`` is a request snapshot and is never
        the authority here. A human needs an active account and user, an
        active membership, and a current project role granting the execute
        permission. A project API key is re-read: it must exist, be neither
        revoked nor expired, belong to this project, and hold the execute
        scope. Either way the project must exist in this account and be
        active, and the live identity must be the one the request was
        attributed to. Every read joins the caller's session, so binding
        resolution shares the snapshot instead of opening another connection.
        """

        principal = context.principal
        if isinstance(principal, ProjectApiKeyPrincipal):
            stored = await ProjectApiKeyRepository(session).get(
                project_id=principal.project_id, api_key_id=principal.api_key_id
            )
            if (
                stored is None
                or stored.project_id != context.project_id
                or api_key_status(stored, datetime.now(UTC)) is not ApiKeyStatus.ACTIVE
            ):
                raise ExecutionNotPermitted("execution is no longer permitted")
            principal = principal_for(stored)
        live = await self._authorization.resolve_project_context_in_session(
            session, principal, context.project_id
        )
        if live is None:
            raise ExecutionNotPermitted("execution is no longer permitted")
        project = await ProjectRepository(session).get_project(
            project_id=context.project_id, account_id=self._account_id
        )
        if project is None or project.status is not ProjectStatus.ACTIVE:
            raise ExecutionNotPermitted("execution is no longer permitted")
        decision = self._authorization.decide_in_context(live, action=_execute_action(operation))
        if not decision.allowed or execution_attribution(live) != execution_attribution(context):
            raise ExecutionNotPermitted("execution is no longer permitted")
        return live

    def _capacity_hooks(
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        attribution: ExecutionAttribution,
        deadline: float | None = None,
    ) -> tuple[
        LimitCallContext,
        Callable[[], Awaitable[Any]],
        Callable[[str], Awaitable[None]],
        Callable[[Any], Awaitable[None]],
        Callable[[str, str], Awaitable[None]],
    ]:
        """Return the attempt seam: fair grant, then one atomic reservation."""

        return _AttemptSeam(self, leg, request, operation, attribution, deadline=deadline).hooks()

    def _queue_policy(
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        attribution: ExecutionAttribution,
        *,
        deadline: float | None,
    ) -> QueuePolicy:
        """Describe one attempt's queue bounds and fairness entitlement."""

        allocation = leg.allocation
        payload_bytes = len(request.model_dump_json().encode("utf-8"))
        gate = _ADMISSION_GATE.get()
        not_before = _RETRY_NOT_BEFORE.get()
        _RETRY_NOT_BEFORE.set(None)
        return QueuePolicy(
            provider=leg.provider,
            project_id=attribution.project_id,
            operation=_operation_code(operation),
            weight=1 if allocation is None else max(1, allocation.weight),
            base_rate=0 if allocation is None else max(0, allocation.base_rate),
            rate_window_seconds=3600 if allocation is None else allocation.rate_window_seconds,
            max_rate=None if allocation is None else allocation.max_rate,
            borrow_enabled=False if allocation is None else allocation.borrow_enabled,
            best_effort=False if allocation is None else allocation.best_effort,
            max_concurrency=None if allocation is None else allocation.max_concurrency,
            max_queued_requests=None if allocation is None else allocation.max_queued_requests,
            max_queued_bytes=None if allocation is None else allocation.max_queued_bytes,
            max_queue_wait_ms=None if allocation is None else allocation.max_queue_wait_ms,
            pool_max_concurrency=None if leg.pool is None else leg.pool.max_concurrency,
            pool_max_queued_requests=None if leg.pool is None else leg.pool.max_queued_requests,
            project_max_concurrency=leg.project_max_concurrency,
            payload_bytes=payload_bytes,
            deadline=deadline,
            admitted_at=None if gate is None else gate.started_at,
            not_before=not_before,
            on_admitted=(None if gate is None or gate.released else gate.release),
            admission_key=None if gate is None else gate.admission_key,
        )

    async def _single(
        self,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        *,
        attribution: ExecutionAttribution,
        context: ProjectContext,
        deadline: float | None = None,
    ) -> SearchResponse | FetchResponse:
        """Run one dispatched attempt chain over the project's bindings.

        The chain applies provider masks, capability, health, and the fallback
        policy; each leg reserves its own strict capacity and passes through
        the shared telemetry wrapper. Per-attempt failure shapes mirror the
        pre-binding transport: a ProviderOperationError on the last leg re-raises
        unchanged after failure telemetry.
        """

        legs = await self._usable_legs(
            context, _operation_code(operation), providers=self._provider_subset(request)
        )
        if not legs:
            if request.routing.mode is RoutingMode.REQUIRE and request.routing.providers:
                raise ExecutionBindingMissing("no required provider is configured for this project")
            raise ExecutionBindingMissing("no provider is configured for this project")
        try:
            observable = current_observability()
            with observable.span(TraceSpanName.ROUTE, attributes=_request_attributes(request)):
                chain = await self._plan(request, operation, legs)
            last_error: ProviderOperationError | None = None
            # One logical retry budget is shared by service retries, adapter
            # runners, fallback legs, and fanout siblings. A request that has
            # already retried once never gets another free retry downstream.
            for index, (leg, _adapter) in enumerate(chain):
                is_last = index == len(chain) - 1
                retried = False
                while True:
                    try:
                        response = await self._invoke_attempt(
                            leg,
                            request,
                            operation,
                            attribution=attribution,
                            candidates=len(chain),
                            deadline=deadline,
                        )
                    except ProviderOperationError as error:
                        if (
                            not retried
                            and self._retry_allowed(error)
                            and not self._deadline_passed(deadline)
                        ):
                            delay, announced = self._retry_delay(error)
                            remaining = self._remaining_before_deadline(deadline)
                            if announced and remaining is not None and delay >= remaining:
                                # The vendor's own delay would outlive the
                                # logical request: refuse the retry instead of
                                # shortening Retry-After.
                                last_error = error
                                if is_last:
                                    _annotate_root_error(observable, error)
                                    _annotate_attempt_identity(
                                        observable, request, leg, _operation_name(request).value
                                    )
                                    raise
                                break
                            if not consume_retry_budget():
                                last_error = error
                                if is_last:
                                    _annotate_root_error(observable, error)
                                    _annotate_attempt_identity(
                                        observable, request, leg, _operation_name(request).value
                                    )
                                    raise
                                break
                            retried = True
                            await self._defer_retry(leg, delay, announced)
                            continue
                        last_error = error
                        if is_last:
                            _annotate_root_error(observable, error)
                            _annotate_attempt_identity(
                                observable, request, leg, _operation_name(request).value
                            )
                            raise
                        break
                    except Exception as error:
                        # Only a normalized provider failure is a routing candidate
                        # for the next binding. An unexpected crash (for example a
                        # local programming error) propagates immediately: silently
                        # treating it as a failed leg could turn a broken primary
                        # into a successful fallback answer.
                        _annotate_root_error(observable, error)
                        _annotate_attempt_identity(
                            observable, request, leg, _operation_name(request).value
                        )
                        raise
                    with observable.span(
                        TraceSpanName.RESULTS,
                        attributes={
                            TraceAttribute.OPERATION: _operation_name(request).value,
                            TraceAttribute.RESPONSE_RESULT_COUNT: (
                                len(response.results) if isinstance(response, SearchResponse) else 1
                            ),
                        },
                    ):
                        _annotate_root(observable, request, response)
                    return response
                continue
            # The chain guarantees at least one attempt, so this is unreachable.
            if last_error is not None:
                raise last_error
            raise ExecutionError("route planning produced zero attempts")
        finally:
            _release_legs(legs)

    # ------------------------------------------------------ fanout semantics

    async def _fanout_search(
        self,
        request: SearchRequest,
        *,
        attribution: ExecutionAttribution,
        context: ProjectContext,
        deadline: float | None = None,
    ) -> SearchResponse:
        """Execute concurrent search across every eligible leg and fuse results.

        Trace shape: one root with a ``freesearch.route`` planning span, one
        concurrent ``freesearch.provider`` client span per leg, and a single
        ``freesearch.results`` span around the reciprocal-rank-fusion
        assembly. A handled provider failure marks that child ERROR and the
        root ``partial``; a terminal vendor out-of-Credits 402 propagates even
        when another leg succeeds, after the pending tasks are cancelled and
        awaited — the pre-binding fanout contract, now with one attempt per
        binding leg and identical behavior over REST and MCP.
        """

        observable = current_observability()
        legs = await self._usable_legs(
            context, CredentialOperation.SEARCH, providers=self._provider_subset(request)
        )
        if not legs:
            # Same contract as a single-provider call: a project with no
            # usable binding has no provider configured.
            raise ExecutionBindingMissing(
                "no eligible provider: no provider is configured for this project"
            )
        try:
            fanout_request = request.model_copy(
                update={"routing": request.routing.model_copy(update={"mode": RoutingMode.FANOUT})}
            )
            with observable.span(TraceSpanName.ROUTE, attributes=_request_attributes(request)):
                chain = await self._plan(fanout_request, UsageOperation.SEARCH, legs)
                candidates = [leg for leg, _adapter in chain]

            overall_start = time.perf_counter()
            tasks = [
                asyncio.ensure_future(
                    self._fanout_leg_call(
                        leg,
                        request,
                        attribution=attribution,
                        candidates_count=len(candidates),
                        deadline=deadline,
                    )
                )
                for leg in candidates
            ]
            outcomes = await _fanout_outcomes(tasks)
            waterfall, successful_results, errors = _fanout_waterfall(outcomes)
            if not successful_results:
                first_err = errors[0] if errors else "all providers failed"
                failure = ExecutionAllFailed(f"all search providers failed: {first_err}")
                _annotate_root_error(observable, failure)
                raise failure
            with observable.span(
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
                with suppress(Exception):
                    await self._repository.record_usage(
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
                        ),
                        attribution=attribution,
                        trace_id=observable.current_trace_id(),
                    )
                response = SearchResponse(
                    query=request.query,
                    results=fused_results,
                    provider=(
                        "aggregated" if len(successful_results) > 1 else successful_results[0][0]
                    ),
                    total_results=len(fused_results),
                    participating_providers=participating,
                    waterfall=waterfall,
                )
                results_span.set_attributes(
                    {TraceAttribute.RESPONSE_RESULT_COUNT: len(fused_results)}
                )
                _annotate_root(observable, request, response)
            return response
        finally:
            _release_legs(legs)

    async def _fanout_leg_call(
        self,
        leg: _Leg,
        request: SearchRequest,
        *,
        attribution: ExecutionAttribution,
        candidates_count: int,
        deadline: float | None = None,
    ) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
        """Run one fanout leg, converting handled failures to the outcome tuple.

        Only the terminal vendor 402 escapes: the surrounding outcome collector
        cancels the pending legs and re-raises it, mirroring the pre-binding
        fanout contract.
        """

        timing = ProviderTiming()
        attributes = {
            TraceAttribute.OPERATION: TraceOperation.SEARCH.value,
            TraceAttribute.PROVIDER: leg.provider,
            TraceAttribute.ROUTING_MODE: RoutingMode.FANOUT.value,
            TraceAttribute.ROUTING_CANDIDATE_COUNT: candidates_count,
        }

        async def call(target: ProviderAdapter) -> SearchResponse:
            observable = current_observability()
            with observable.span(
                TraceSpanName.PROVIDER,
                kind=SpanKindName.CLIENT,
                attributes=attributes,
            ) as span:
                span.add_event(
                    TRACE_EVENT_PROVIDER_REQUEST,
                    attributes=_provider_request_event(request),
                )
                response = await target.search(request)
                span.add_event(
                    TRACE_EVENT_PROVIDER_RESPONSE,
                    attributes=_provider_response_event(response),
                )
                return response

        try:
            response = await self._tracked_attempt(
                leg,
                request,
                UsageOperation.SEARCH,
                call,
                attribution=attribution,
                deadline=deadline,
                timing=timing,
            )
        except Exception as exc:
            elapsed = timing.latency_ms
            if _escapes_fanout(exc):
                raise
            return _handled_outcome(leg.provider, exc, elapsed)
        elapsed = timing.latency_ms
        return (
            leg.provider,
            response,
            elapsed,
            "success",
            len(response.results),
            None,
        )

    async def _tracked_attempt[ResponseT: (SearchResponse, FetchResponse)](
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        call: Callable[[ProviderAdapter], Awaitable[ResponseT]],
        *,
        attribution: ExecutionAttribution,
        deadline: float | None = None,
        timing: ProviderTiming | None = None,
    ) -> ResponseT:
        """Run one attempt around the shared telemetry-and-capacity wrapper."""

        rails_context, reserve, settle, release, resolve_dispatch = self._capacity_hooks(
            leg, request, operation, attribution, deadline=deadline
        )

        def require_deadline() -> None:
            if self._deadline_passed(deadline):
                raise ExecutionQueueExpired(
                    "the execution request deadline expired before the provider call"
                )

        async def bounded_call(target: ProviderAdapter) -> ResponseT:
            remaining = self._remaining_before_deadline(deadline)
            if remaining is None:
                return await call(target)
            try:
                return await asyncio.wait_for(call(target), timeout=remaining)
            except TimeoutError as error:
                raise ExecutionQueueExpired(
                    "the execution request deadline expired during the provider call"
                ) from error

        try:
            response = await tracked_call(
                self._repository,
                leg.adapter,
                bounded_call,
                operation=operation,
                attribution=attribution,
                request=request,
                limits=self._limits,
                binding=self._binding_of(leg),
                reserve=reserve,
                settle=settle,
                release=release,
                context=rails_context,
                resolve_dispatch=resolve_dispatch,
                timing=timing,
                pre_send=require_deadline,
            )
            # A request-triggered observer runs only after a dispatched,
            # admitted leg succeeded. Denied scopes/plans/capacity never poll.
            await self._schedule_quotas([leg])
            return response
        except LimitStoreUnavailable as error:
            # The telemetry wrapper reports every pre-send refusal as a store
            # failure, which also keeps it out of provider health. A revoked
            # actor or binding found by revalidation keeps its domain type,
            # so transports preserve the actual refusal reason.
            if isinstance(error.__cause__, ExecutionError):
                raise error.__cause__ from None
            raise

    async def _invoke_attempt(
        self,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        *,
        attribution: ExecutionAttribution,
        candidates: int,
        deadline: float | None = None,
    ) -> SearchResponse | FetchResponse:
        """Run one attempt under its provider client span with request/response events.

        The provider span opens inside the send closure, after queue wait and
        admission, so its duration measures the actual provider operation. The
        span always records the failure before it propagates, so a
        per-credential child stays observable whichever error shape arrives.
        """

        attributes = {
            TraceAttribute.OPERATION: _operation_name(request).value,
            TraceAttribute.PROVIDER: leg.provider,
            TraceAttribute.ROUTING_MODE: request.routing.mode.value,
            TraceAttribute.ROUTING_CANDIDATE_COUNT: candidates,
        }

        async def span_call(target: ProviderAdapter) -> SearchResponse | FetchResponse:
            observable = current_observability()
            with observable.span(
                TraceSpanName.PROVIDER,
                kind=SpanKindName.CLIENT,
                attributes=attributes,
            ) as provider_span:
                provider_span.add_event(
                    TRACE_EVENT_PROVIDER_REQUEST, attributes=_provider_request_event(request)
                )
                return await self._span_provider_call(provider_span, target, request)

        return cast(
            SearchResponse | FetchResponse,
            await self._tracked_attempt(
                leg,
                request,
                operation,
                span_call,
                attribution=attribution,
                deadline=deadline,
            ),
        )

    @staticmethod
    async def _span_provider_call[ResultT](
        provider_span: Any, target: ProviderAdapter, request: SearchRequest | FetchRequest
    ) -> ResultT:
        """Run the provider operation and annotate its span without queue time."""

        response: SearchResponse | FetchResponse
        try:
            if isinstance(request, SearchRequest):
                response = await target.search(request)
            else:
                response = await target.fetch(request)
        except Exception as error:
            provider_span.record_exception(error)
            raise
        provider_span.add_event(
            TRACE_EVENT_PROVIDER_RESPONSE, attributes=_provider_response_event(response)
        )
        return cast(ResultT, response)


class _GrantedReservation:
    """One reservation that also owns its fair-queue grant lifetime."""

    __slots__ = ("grant", "inner")

    def __init__(self, inner: Any, grant: DispatchGrant) -> None:
        self.inner = inner
        self.grant = grant

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def finish(self) -> None:
        """Release the queue's in-flight slot after the send settles."""

        self.grant.finish()


class _AttemptSeam:
    """One leg's fair-queue and atomic-capacity seam for a single send."""

    def __init__(
        self,
        service: ExecutionService,
        leg: _Leg,
        request: SearchRequest | FetchRequest,
        operation: UsageOperation,
        attribution: ExecutionAttribution,
        *,
        deadline: float | None,
    ) -> None:
        self._service = service
        self._leg = leg
        self._request = request
        self._operation = operation
        self._attribution = attribution
        self._deadline = deadline
        self._rails_context = service._rails_context(leg, request, operation, attribution)
        self._limits = service._limits
        self._auth_mode = self._rails_context.auth_mode
        self._supports_native = self._limits is not None and self._limits.supports(
            leg.provider, self._rails_context.operation, self._auth_mode
        )
        self._repository_limits = service._repository.limits
        self._authority = service._authority
        self._pool_id = leg.pool.id if leg.pool is not None else None

    def hooks(
        self,
    ) -> tuple[
        LimitCallContext,
        Callable[[], Awaitable[Any]],
        Callable[[str], Awaitable[None]],
        Callable[[Any], Awaitable[None]],
        Callable[[str, str], Awaitable[None]],
    ]:
        return (
            self._rails_context,
            self.reserve,
            _noop_settle,
            self.release,
            self.resolve_dispatch,
        )

    async def reserve(self) -> Any:
        """Enter the fair queue, reserve capacity, and recheck live authority."""

        service = self._service
        if service._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        if self._pool_id is None:
            gate = _ADMISSION_GATE.get()
            if gate is not None:
                gate.release()
        reservation: Any = None
        try:
            reservation = await self._granted(self._leg)
            return reservation
        except LimitStoreUnavailable as error:
            raise ExecutionAuthorityUnavailable(
                "the execution authority capacity store is unavailable"
            ) from error
        except BaseException:
            if reservation is not None:
                await asyncio.shield(
                    _release_capacity(reservation, self._repository_limits, self._limits)
                )
            raise

    async def _granted(self, current: _Leg) -> Any:
        if self._pool_id is not None and self._authority is not None:
            policy = self._service._queue_policy(
                current,
                self._request,
                self._operation,
                self._attribution,
                deadline=self._deadline,
            )
            return await self._authority.dispatch(
                pool_id=self._pool_id,
                operation=_operation_code(self._operation),
                policy=policy,
                attempt=lambda grant: self._dispatch_current(current, grant),
            )
        if self._pool_id is not None:
            # Pool capacity must never be dispatched without the one fenced
            # authority; a composition without it fails closed.
            raise ExecutionAuthorityUnavailable(
                "the execution authority is not hosted by this process"
            )
        return await self._dispatch_current(current, None)

    async def _live_leg_check(self, leg: _Leg) -> None:
        """Recheck the complete dispatch-relevant snapshot before one send.

        This is the single final pre-send gate (there is no second, partial
        revalidation path). It re-reads live actor authority, the binding's
        revision and enabled operations, the credential identity/generation,
        the credential's pool link, the pool's status/revision/limits, the
        project allocation revision/limits, and the effective provider
        configuration. A queued call whose policy changed while it waited
        therefore fails closed instead of dispatching a stale plan.
        """

        service = self._service
        operation = _operation_code(self._operation)
        try:
            async with service._repository.session() as session:
                await begin_read_snapshot(session)
                context = await service._live_context_in_session(
                    session, leg.context, self._operation
                )
                if execution_attribution(context) != self._attribution:
                    raise ExecutionNotPermitted("execution is no longer permitted")
                binding = await ProjectBindingRepository(session).get(
                    project_id=context.project_id, binding_id=leg.binding.id
                )
                if (
                    binding is None
                    or operation not in binding.enabled_operations
                    or binding.version != leg.binding.version
                ):
                    raise ExecutionBindingMissing("the binding is no longer enabled and usable")
                usable = await service._credentials.usable_credential_in_session(
                    session,
                    project_id=context.project_id,
                    credential_id=leg.credential.credential_id,
                    operation=operation,
                )
                if usable is None or usable.generation != leg.credential.generation:
                    raise ExecutionBindingMissing(
                        "the credential is no longer usable for this attempt"
                    )
                material = await service._credentials.resolve_material_in_session(
                    session,
                    context,
                    usable.id,
                    operation=operation,
                    expected_generation=usable.generation,
                    usable=usable,
                )
                if (
                    material is None
                    or material.generation != leg.credential.generation
                    or material.token_generation != leg.credential.token_generation
                    or material.secret.get_secret_value()
                    != leg.credential.secret.get_secret_value()
                ):
                    raise ExecutionBindingMissing("the credential material changed before dispatch")
                project_allocations = await PoolAllocationRepository(session).list_for_project(
                    project_id=context.project_id
                )
                caps = [
                    allocation.max_concurrency
                    for allocation in project_allocations
                    if allocation.max_concurrency is not None
                ]
                if service._authority is not None:
                    service._authority.update_project_cap(
                        context.project_id, min(caps) if caps else None
                    )
                pools = UpstreamPoolRepository(session)
                link = await pools.pool_for_credential(credential_id=usable.id, operation=operation)
                if leg.pool is None:
                    if link is not None:
                        raise ExecutionBindingMissing(
                            "the provider configuration changed before dispatch"
                        )
                else:
                    if link is None or link.pool_id != leg.pool.id:
                        raise ExecutionBindingMissing(
                            "the provider configuration changed before dispatch"
                        )
                    pool = await pools.get_pool(account_id=service._account_id, pool_id=leg.pool.id)
                    if pool is None or pool.status is not PoolStatus.ACTIVE:
                        raise ExecutionBindingMissing(
                            "the provider configuration changed before dispatch"
                        )
                    if pool != leg.pool:
                        raise ExecutionBindingMissing(
                            "the provider configuration changed before dispatch"
                        )
                    allocation = await PoolAllocationRepository(session).get(
                        project_id=context.project_id,
                        pool_id=leg.pool.id,
                        operation=operation,
                    )
                    if allocation != leg.allocation:
                        raise ExecutionBindingMissing(
                            "the provider configuration changed before dispatch"
                        )
        except (
            CredentialStorageUnavailable,
            ProjectStorageUnavailable,
            OperationalError,
        ) as error:
            raise ExecutionStorageUnavailable("the credential store is unavailable") from error
        try:
            config = await effective_config_for_name(service._repository, leg.provider, strict=True)
        except ProviderConfigError as error:
            raise ExecutionError(str(error)) from error
        if config != leg.config or not service._leg_allows(leg, self._request, self._operation):
            raise ExecutionBindingMissing("the provider configuration changed before dispatch")

    async def _dispatch_current(self, current: _Leg, grant: DispatchGrant | None) -> Any:
        reservation: Any = None
        completed = False
        try:
            if self._service._closed:
                raise ExecutionAuthorityUnavailable("the execution authority is stopped")
            # Final live permission, binding, credential, pool/allocation
            # revision, and configuration check immediately before the atomic
            # capacity admission.
            await self._live_leg_check(current)
            self._require_deadline()
            reservation = await self._reserve_current(current, grant)
            # The admission itself can consume time; a request whose logical
            # deadline passed while reserving must not reach the provider. The
            # reservation is provably unsent, so it is released.
            if self._service._deadline_passed(self._deadline):
                await _release_capacity(reservation, self._repository_limits, self._limits)
                raise ExecutionQueueExpired(
                    "the execution queue wait bound expired before dispatch"
                )
            await self._record_dispatch(current, _attempt_id(reservation), reservation)
            # The recovery record write is the last await before the provider
            # send begins. A deadline that elapsed during that write proves the
            # send never started, so release the reservation instead of
            # charging an uncertain upstream attempt.
            if self._service._deadline_passed(self._deadline):
                await _release_capacity(reservation, self._repository_limits, self._limits)
                await self.resolve_dispatch(_attempt_id(reservation), "failed")
                raise ExecutionQueueExpired(
                    "the execution request deadline expired before the provider call"
                )
            completed = True
            if grant is not None and reservation is not None:
                return _GrantedReservation(reservation, grant)
            if grant is not None:
                grant.finish()
            return reservation
        except BaseException:
            if reservation is not None:
                await asyncio.shield(
                    _release_capacity(reservation, self._repository_limits, self._limits)
                )
            raise
        finally:
            if grant is not None:
                grant.started.set()
                if not completed:
                    grant.finish()

    def _require_deadline(self) -> None:
        """Refuse dispatch when the logical request deadline already passed."""

        if self._service._deadline_passed(self._deadline):
            raise ExecutionQueueExpired("the execution request deadline expired before dispatch")

    async def _reserve_current(self, current: _Leg, grant: DispatchGrant | None) -> Any:
        if grant is not None:
            add_queue_wait(grant.queue_wait_ms)
        self._require_deadline()
        spec = self._service._strict_spec(
            current, self._request, self._operation, self._attribution
        )
        attempt_id = uuid4().hex
        attempt_context = self._service._rails_context(
            current,
            self._request,
            self._operation,
            self._attribution,
            attempt_id=attempt_id,
        )
        reservation = await self._admit(current, attempt_context, spec, attempt_id)
        return reservation

    async def _admit(
        self,
        current: _Leg,
        attempt_context: LimitCallContext,
        spec: StrictAttemptSpec | None,
        attempt_id: str,
    ) -> Any:
        limits = self._limits
        if self._supports_native:
            assert limits is not None
            return await limits.admit_attempt(attempt_context, spec)
        if spec is None:
            return None
        strict = await self._repository_limits.reserve_strict(
            attempt_id=attempt_id,
            provider=self._leg.provider,
            operation=_limit_operation(self._operation),
            auth_mode=self._auth_mode,
            spec=spec,
        )
        if strict.state != "reserved":
            raise ExecutionError(
                "the capacity reservation replayed as settled; a fresh attempt is required"
            )
        return _AttemptCapacity(
            attempt_id=attempt_id,
            admission=None,
            strict=strict,
            repository_limits=self._repository_limits,
        )

    async def _record_dispatch(self, current: _Leg, attempt_id: str, reservation: Any) -> None:
        if self._pool_id is None or self._authority is None or reservation is None:
            return
        await self._authority.record_dispatch(
            attempt_id=attempt_id,
            request_id=(
                current_observability().current_trace_id() or self._attribution.project_id.hex
            ),
            project_id=self._attribution.project_id,
            pool_id=self._pool_id,
            operation=_operation_code(self._operation),
            actor_type=self._attribution.actor_type,
            actor_id=self._attribution.actor_id,
            credential_id=current.credential.credential_id,
            binding_id=current.binding.id,
        )

    async def release(self, reservation: Any) -> None:
        """Undo a reservation proven never to reach the vendor."""

        await _release_capacity(reservation, self._repository_limits, self._limits)

    async def resolve_dispatch(self, attempt_id: str, outcome: str) -> None:
        """Resolve the authority recovery record after the attempt settles."""

        if self._pool_id is not None and self._authority is not None:
            await self._authority.resolve_dispatch(
                project_id=self._attribution.project_id,
                attempt_id=attempt_id,
                outcome=outcome,
            )


def _attempt_id(reservation: Any) -> str:
    """Return the attempt identity of a native or strict reservation."""

    if reservation is None:
        return ""
    strict = getattr(reservation, "strict", None)
    return str(
        getattr(reservation, "attempt_id", None) or getattr(strict, "attempt_id", None) or ""
    )


def _release_legs(legs: Sequence[_Leg]) -> None:
    """Return every resolved adapter lease; retired entries close when idle."""

    for leg in legs:
        leg.lease.release()


async def _release_capacity(reservation: Any, repository_limits: Any, limits: Any) -> None:
    """Undo a reservation that provably never reached the vendor."""

    try:
        strict = getattr(reservation, "strict", None)
        if strict is not None:
            await repository_limits.release_strict(
                attempt_id=strict.attempt_id,
                bucket_ids=tuple(getattr(strict, "bucket_ids", ())),
            )
        admission = getattr(reservation, "admission", None)
        if admission is not None and limits is not None:
            with suppress(Exception):
                await limits.release_admission(admission)
        if strict is None and admission is None:
            attempt_id = getattr(reservation, "attempt_id", None)
            if attempt_id:
                await repository_limits.release_strict(
                    attempt_id=attempt_id,
                    bucket_ids=tuple(getattr(reservation, "bucket_ids", ())),
                )
    except Exception:
        # The durable row stays open; restart treats it as uncertain rather
        # than pretending it never happened.
        return


async def _noop_settle(_outcome: str) -> None:
    """Nothing to settle when the attempt holds no strict reservation."""


async def _noop_release(_reservation: Any) -> None:
    """Nothing to release when the attempt holds no strict reservation."""


def _annotate_attempt_identity(
    observability: ObservabilityRuntime,
    request: SearchRequest | FetchRequest,
    leg: _Leg,
    operation: str,
) -> None:
    """Keep the request identity on a failed root span.

    The success path projects the same fields from the response. A failure
    never reaches that projection, so the Activity row would lose its title
    and the Provider column would show a dash.
    """

    attributes: dict[str, object] = {
        TraceAttribute.OPERATION: operation,
        TraceAttribute.PROVIDER: leg.provider,
    }
    if isinstance(request, SearchRequest):
        attributes[TraceAttribute.REQUEST_QUERY] = request.query
    observability.annotate_root(attributes)


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


def _handled_outcome(
    provider: str,
    exc: Exception,
    elapsed_ms: int,
    *,
    provider_span: Any | None = None,
) -> tuple[str, SearchResponse | None, int, str, int, str | None]:
    """Return the handled-failure outcome tuple for one fanout leg.

    A vendor 429 keeps its distinctive outcome status; every other handled
    failure stays ``failed``. A provider span in scope records the failure
    observably first, without ever failing the outcome path.
    """

    with suppress(Exception):
        if provider_span is not None:
            provider_span.record_exception(exc)
    status = "failed"
    if getattr(getattr(exc, "error", None), "status_code", None) == 429:
        status = "rate_limited"
    return (provider, None, elapsed_ms, status, 0, str(exc))


def _fanout_waterfall(
    outcomes: Sequence[tuple[str, SearchResponse | None, int, str, int, str | None]],
) -> tuple[list[ProviderTraceItem], list[tuple[str, SearchResponse]], list[str]]:
    """Split handled fanout outcome tuples into the fusion waterfall inputs."""

    waterfall: list[ProviderTraceItem] = []
    successful_results: list[tuple[str, SearchResponse]] = []
    errors: list[str] = []
    for provider, response, elapsed, status, count, error in outcomes:
        waterfall.append(
            ProviderTraceItem(
                provider=provider,
                latency_ms=elapsed,
                status=status,
                results_count=count,
                cost_credits=0.0,
                error=error,
            )
        )
        if response is not None:
            successful_results.append((provider, response))
        elif error is not None:
            errors.append(error)
    return waterfall, successful_results, errors


async def _fanout_outcomes[T](tasks: list[asyncio.Task[T]]) -> list[T]:
    """Await fanout tasks in candidate order, honoring a terminal 402.

    Tasks either complete with an outcome tuple or raise the terminal
    out-of-Credits 402 (the leg callable returns the tuple form for every
    other failure, so local admission denials keep the gather semantics). The
    first exception therefore is the terminal error: its re-raise cancels the
    pending tasks and awaits their settlement before propagation, so no
    provider call races the closing request. A parent cancellation follows the
    same rule for every child, including ones already running, so the caller's
    ``finally`` never releases an adapter lease under a live child.
    """

    if not tasks:
        return []
    try:
        return await _collect_fanout_outcomes(tasks)
    except asyncio.CancelledError:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
        raise


async def _collect_fanout_outcomes[T](tasks: list[asyncio.Task[T]]) -> list[T]:
    """Collect ordered fanout outcomes and clean up after a terminal error."""

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
                terminal = error
    if terminal is not None:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise terminal
    return [outcomes_by_index[index] for index in range(len(tasks))]


__all__ = [
    "ExecutionAllFailed",
    "ExecutionAuthorityUnavailable",
    "ExecutionBindingMissing",
    "ExecutionError",
    "ExecutionNotPermitted",
    "ExecutionRequestInvalid",
    "ExecutionService",
    "ExecutionStorageUnavailable",
]
