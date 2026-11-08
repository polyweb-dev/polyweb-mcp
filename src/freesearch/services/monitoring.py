"""Read-only monitoring telemetry: recording and JSON snapshot reads.

Recording is best-effort by contract: a monitoring failure must never fail the
user-facing request it observes, so every repository write is wrapped and
swallowed with a payload-free warning. Reads assemble the ``StatsResponse``
contract served by ``/stats`` and the ``DashboardResponse`` contract served by
``/dashboard``: the same snapshot plus a ``generated_at`` instant, serialized
as JSON for the future React dashboard. Every entry is a privacy projection,
so request ids, metadata, query text, and diagnostic messages never leave the
storage layer.
"""

import asyncio
import contextlib
import contextvars
import inspect
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import COST_USD_PER_REQUEST, FREE_CREDITS_USD, brave_spend_usd
from freesearch.infrastructure.observability import current_observability
from freesearch.infrastructure.resilience import (
    ProviderOperationError,
    install_dispatch_observer,
    reset_dispatch_observer,
)
from freesearch.infrastructure.secrets import AsyncSecretStore, ProviderName
from freesearch.models.contracts import (
    ContractModel,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderError,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    SearchResponse,
    UnitKind,
    UsageEvent,
    UsageOperation,
    UsageStatus,
    is_soft_quota_zero,
)
from freesearch.models.execution_failures import ExecutionError
from freesearch.models.observability import AttemptBinding, ExecutionAttribution
from freesearch.models.projects import PermissionAction
from freesearch.models.provider_limits import (
    AuthMode,
    CRDUsageTotal,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    LimitStoreUnavailable,
    ProviderObservationScope,
    local_rate_denial,
)
from freesearch.models.quota_api import USDProviderLimits, USDUsageTotal
from freesearch.models.users import UserPrincipal
from freesearch.persistence.storage import LegacyUsageTotal, SQLiteRepository, UsageTotal
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.control_access import require_project_permission, run_control_read
from freesearch.services.control_errors import ControlStorageUnavailable

if TYPE_CHECKING:
    from freesearch.services.provider_limits import ProviderLimitsService

logger = logging.getLogger(__name__)

#: Queue wait accumulated by the authority for the attempt in this task.
_QUEUE_WAIT_MS: contextvars.ContextVar[int] = contextvars.ContextVar(
    "freesearch_queue_wait_ms", default=-1
)


def add_queue_wait(milliseconds: int) -> None:
    """Accumulate one scheduler grant's wait for the current request task."""

    current = _QUEUE_WAIT_MS.get()
    _QUEUE_WAIT_MS.set(max(0, current) + max(0, milliseconds))


def consume_queue_wait() -> int | None:
    """Return and clear the request task's accumulated queue wait."""

    value = _QUEUE_WAIT_MS.get()
    _QUEUE_WAIT_MS.set(-1)
    return None if value < 0 else value


CANONICAL_PROVIDER_NAMES: frozenset[str] = frozenset(provider.value for provider in ProviderName)

MONITORING_NOTICE = (
    "Usage, quota, and health shown here are local-observed only; vendor /usage "
    # The en dash below is contractual: the monitoring tests assert the
    # "10 to 15 min" vendor-lag wording with an en dash verbatim.
    "endpoints lag 10–15 min, so balances can drift until reconciliation runs."  # noqa: RUF001
)
DEFAULT_RECENT_LIMIT: int = 20
MAX_RECENT_LIMIT: int = 100
DEFAULT_DB_FILENAME: str = "freesearch.db"
DB_ENV_VAR: str = "FREESEARCH_DB"
# Vendor quota endpoints are account reads, not request instrumentation.
QUOTA_POLL_TTL_SECONDS: int = 120
QUOTA_FAILURE_BACKOFF_SECONDS: int = 5
_quota_poll_cache: dict[tuple[int, int, str], datetime] = {}
_quota_failure_cache: dict[tuple[int, int, str], datetime] = {}
_quota_poll_locks: dict[tuple[int, int, str], asyncio.Lock] = {}


def _quota_ttl_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_POLL_TTL_SECONDS")
    try:
        configured = int(raw) if raw is not None else QUOTA_POLL_TTL_SECONDS
    except ValueError:
        configured = QUOTA_POLL_TTL_SECONDS
    return max(60, min(300, configured))


def _quota_failure_backoff_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_FAILURE_BACKOFF_SECONDS")
    try:
        configured = int(raw) if raw is not None else QUOTA_FAILURE_BACKOFF_SECONDS
    except ValueError:
        configured = QUOTA_FAILURE_BACKOFF_SECONDS
    return max(1, min(30, configured))


def clear_quota_poll_cache(
    repository: SQLiteRepository | None = None,
    adapters: Sequence[ProviderAdapter] = (),
) -> None:
    """Evict bounded-poll state when a repository or adapter generation closes."""

    if repository is None and not adapters:
        _quota_poll_cache.clear()
        _quota_failure_cache.clear()
        _quota_poll_locks.clear()
        return
    repository_id = id(repository) if repository is not None else None
    adapter_ids = {id(adapter) for adapter in adapters}
    all_keys = set(_quota_poll_cache) | set(_quota_failure_cache) | set(_quota_poll_locks)
    keys = [
        key
        for key in all_keys
        if (repository_id is None or key[0] == repository_id)
        and (not adapter_ids or key[1] in adapter_ids)
    ]
    for key in keys:
        _quota_poll_cache.pop(key, None)
        _quota_failure_cache.pop(key, None)
        _quota_poll_locks.pop(key, None)


class ProviderUsageTotal(ContractModel):
    """Aggregated usage units for one provider and operation."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int
    unit_kind: UnitKind | None = None

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        _drop_unknown_units(payload)
        return payload


class RecentUsageEntry(ContractModel):
    """Privacy-projected recent usage event: no request id, no metadata."""

    provider: str
    operation: UsageOperation
    units: Decimal
    observed_at: datetime
    latency_ms: int | None = None
    status: UsageStatus = UsageStatus.SUCCESS
    unit_kind: UnitKind | None = None
    display_unit: str | None = None

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        _drop_unknown_units(payload)
        return payload


class LatestHealthEntry(ContractModel):
    """Privacy-projected health observation: no diagnostic message."""

    provider: str
    status: HealthStatus
    checked_at: datetime


def _drop_unknown_units(payload: dict[str, Any]) -> None:
    if payload.get("unit_kind") is None:
        payload.pop("unit_kind", None)
        payload.pop("display_unit", None)


class StatsResponse(ContractModel):
    """Read-only monitoring snapshot served by the stats and dashboard reads."""

    notice: str
    usage_totals: list[ProviderUsageTotal]
    recent_usage: list[RecentUsageEntry]
    latest_quota: list[QuotaSnapshot]
    latest_health: list[LatestHealthEntry]
    spend_totals: list[USDUsageTotal] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _serialize_compat(self, handler: Any) -> Any:
        payload = handler(self)
        for snapshot in payload.get("latest_quota", []):
            _drop_unknown_units(snapshot)
        for total in payload.get("usage_totals", []):
            _drop_unknown_units(total)
        for event in payload.get("recent_usage", []):
            _drop_unknown_units(event)
        return payload


class DashboardResponse(StatsResponse):
    """JSON dashboard snapshot: the stats read plus its generation instant."""

    generated_at: AwareDatetime
    provider_limits: list[USDProviderLimits] = Field(default_factory=list)


class ProjectUsageResponse(ContractModel):
    """Project-scoped usage totals and a privacy-projected recent ledger."""

    project_id: UUID
    totals: list[ProviderUsageTotal] = Field(default_factory=list)
    recent_usage: list[RecentUsageEntry] = Field(default_factory=list)
    generated_at: AwareDatetime


def _environment_file_value(name: str) -> str | None:
    """Return one entry from the local ``.env`` file, or ``None``.

    The file is parsed directly instead of through the settings loader so this
    resolver stays importable from persistence and the database CLI without a
    configuration dependency, and so a missing file is not an error.
    """

    path = Path(".env")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator and key.strip() == name:
            stripped = value.strip().strip('"').strip("'")
            return stripped or None
    return None


def resolve_database_path(database: str | Path | None = None) -> Path:
    """Return the telemetry database path.

    Precedence: the process ``FREESEARCH_DB`` variable, an explicit argument, the
    local environment file, then the filename default. Process environment wins
    over the file so a worktree can override its own ``.env`` entry.
    """

    from_environment = os.environ.get(DB_ENV_VAR)
    if from_environment:
        return Path(from_environment)
    if database is not None:
        return Path(database)
    from_file = _environment_file_value(DB_ENV_VAR)
    if from_file:
        return Path(from_file)
    return Path(DEFAULT_DB_FILENAME)


def _response_instant(response: SearchResponse | FetchResponse) -> datetime:
    """Return the instant the adapter produced ``response``.

    ``response.usage.observed_at`` is authoritative when the adapter reported
    usage. Without a usage event a fetch still carries ``document.fetched_at``;
    anything else falls back to the recording time.
    """

    if response.usage is not None:
        return response.usage.observed_at
    if isinstance(response, FetchResponse):
        return response.document.fetched_at
    return datetime.now(UTC)


def _estimated_gap_event(response: SearchResponse | FetchResponse) -> UsageEvent | None:
    """Turn an explicit vendor-metering gap into a local estimated event."""

    gap = response.usage_gap
    if not isinstance(gap, dict):
        return None
    raw_units = gap.get("units")
    try:
        units = raw_units if isinstance(raw_units, Decimal) else Decimal(str(raw_units))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not units.is_finite() or units < 0:
        return None
    operation = (
        UsageOperation.SEARCH if isinstance(response, SearchResponse) else UsageOperation.FETCH
    )
    return UsageEvent(
        provider=response.provider,
        operation=operation,
        units=units,
        unit_kind=UnitKind.USD,
        display_unit="USD",
        observed_at=_response_instant(response),
        metadata={"estimated": True, "metering_gap": True},
    )


async def record_response_telemetry(
    repository: SQLiteRepository | None,
    response: SearchResponse | FetchResponse,
    *,
    attribution: ExecutionAttribution,
    latency_ms: int | None = None,
    status: UsageStatus = UsageStatus.SUCCESS,
    binding: AttemptBinding | None = None,
    queue_wait_ms: int | None = None,
) -> None:
    """Persist ``response.usage`` and a healthy observation; never raise.

    Telemetry failures are logged without payload, response content, or
    exception text (which may embed query or URL data) and then swallowed, so a
    monitoring outage can never fail the user request being observed. Usage and
    health persistence are independent: a rejected usage write must never skip
    the healthy observation. When usage is present, the measured ``latency_ms``
    and ``status`` are attached to the stored event, which is owned by the
    execution ``attribution`` and linked to the request trace when one is live.
    The credential/binding/pool ``binding`` attributes both writes to the exact
    attempt that produced them.
    """

    if repository is None:
        return
    try:
        usage = response.usage or _estimated_gap_event(response)
        if usage is not None:
            metadata = dict(usage.metadata)
            if queue_wait_ms is not None:
                metadata["queue_wait_ms"] = max(0, queue_wait_ms)
            measured = usage.model_copy(
                update={"latency_ms": latency_ms, "status": status, "metadata": metadata}
            )
            await repository.record_usage(
                measured,
                attribution=attribution,
                trace_id=current_observability().current_trace_id(),
                credential_id=binding.credential_id if binding is not None else None,
                binding_id=binding.binding_id if binding is not None else None,
                pool_id=binding.pool_id if binding is not None else None,
            )
    except Exception:
        logger.warning("response telemetry could not be persisted")
    try:
        await repository.record_health(
            ProviderHealth(
                provider=response.provider,
                status=HealthStatus.HEALTHY,
                checked_at=_response_instant(response),
                message=None,
            ),
            credential_id=binding.credential_id if binding is not None else None,
        )
    except Exception:
        logger.warning("response telemetry could not be persisted")


async def record_failure_telemetry(
    repository: SQLiteRepository | None,
    *,
    provider: str | None,
    credential_id: UUID | None = None,
) -> None:
    """Persist a degraded health observation for ``provider``; never raise.

    This helper records health only; the zero-unit failure usage event is
    written by :func:`_record_failure_usage` from :func:`tracked_call`. A call
    through one credential fails that credential, never an unrelated one: the
    degraded observation is credential-scoped when the binding is known.
    """

    if repository is None or provider is None:
        return
    try:
        await repository.record_health(
            ProviderHealth(
                provider=provider,
                status=HealthStatus.DEGRADED,
                checked_at=datetime.now(UTC),
                message=None,
            ),
            credential_id=credential_id,
        )
    except Exception:
        logger.warning("failure telemetry could not be persisted")


async def _record_failure_usage(
    repository: SQLiteRepository | None,
    *,
    attribution: ExecutionAttribution,
    provider: str,
    operation: UsageOperation,
    latency_ms: int | None,
    binding: AttemptBinding | None = None,
    queue_wait_ms: int | None = None,
) -> None:
    """Persist a zero-unit failure usage event for a failed call; never raise."""

    if repository is None:
        return
    try:
        metadata = {"queue_wait_ms": max(0, queue_wait_ms)} if queue_wait_ms is not None else {}
        await repository.record_usage(
            UsageEvent(
                provider=provider,
                operation=operation,
                units=Decimal("0"),
                observed_at=datetime.now(UTC),
                latency_ms=latency_ms,
                status=UsageStatus.FAILURE,
                metadata=metadata,
            ),
            attribution=attribution,
            trace_id=current_observability().current_trace_id(),
            credential_id=binding.credential_id if binding is not None else None,
            binding_id=binding.binding_id if binding is not None else None,
            pool_id=binding.pool_id if binding is not None else None,
        )
    except Exception:
        logger.warning("failure usage telemetry could not be persisted")


def _measured_latency_ms(adapter_name: str, latency_ms: int) -> int | None:
    """Attach the measured latency only for the canonical provider surface.

    Usage rows recorded through :func:`tracked_call` for canonical providers
    (the control plane and routing registry) carry the measured latency and
    status; adapters outside that registry (synthetic doubles and custom
    integrations) keep the verbatim usage contract pinned by the Stage 4.5
    ledger tests. Direct :func:`record_response_telemetry` callers are never
    instrumented."""

    return latency_ms if adapter_name in CANONICAL_PROVIDER_NAMES else None


class ProviderTiming:
    """Actual provider-send time shared across retries and child tasks.

    The mutable object travels with the attempt, so an adapter runner's send
    observations update the same accumulator the parent task reads. Queue
    wait, admission, retry backoff, and settlement are never included.
    """

    __slots__ = ("_open_started", "first_send_at", "seconds")

    def __init__(self) -> None:
        self.seconds = 0.0
        self.first_send_at: float | None = None
        self._open_started: float | None = None

    def begin_send(self) -> None:
        """Mark one actual send as started."""

        now = time.perf_counter()
        if self.first_send_at is None:
            self.first_send_at = now
        self._open_started = now

    def end_send(self) -> None:
        """Finish the currently open send and accumulate its duration."""

        if self._open_started is None:
            return
        self.seconds += max(0.0, time.perf_counter() - self._open_started)
        self._open_started = None

    def finish_open_send(self) -> None:
        """Close an unresolved send at its current elapsed time."""

        self.end_send()

    @property
    def latency_ms(self) -> int:
        """Return the accumulated actual send duration in whole milliseconds."""

        return int(max(0.0, self.seconds) * 1000)


class _DispatchSend:
    """One actual upstream send observed inside an adapter call."""

    __slots__ = (
        "error",
        "finalized",
        "outcome",
        "reservation",
        "resolved",
        "response",
        "started",
    )

    def __init__(self, reservation: Any) -> None:
        self.reservation = reservation
        self.finalized = False
        self.resolved = False
        self.started = False
        self.outcome = "open"
        self.response: Any = None
        self.error: BaseException | None = None

    @property
    def attempt_id(self) -> str:
        return str(
            getattr(self.reservation, "attempt_id", None)
            or getattr(getattr(self.reservation, "strict", None), "attempt_id", "")
        )


class _CapacityCharger:
    """Charge every actual provider send and finalize each logical attempt once.

    A runner adapter may retry internally; each retry calls ``begin`` before
    its HTTP operation, so a cap with no room denies the resend before it is
    sent. The same exception may reuse an idempotent reservation id (a caller
    hook that keeps one attempt id); those sends group under one attempt and
    settle once. Distinct attempt ids are charged and settled independently.
    """

    def __init__(
        self,
        *,
        reserve: Callable[[], Awaitable[Any]],
        settle: Callable[[str], Awaitable[None]] | None,
        release: Callable[[Any], Awaitable[None]] | None,
        limits: "ProviderLimitsService | None",
        request: SearchRequest | FetchRequest | None,
        resolve_dispatch: Callable[[str, str], Awaitable[None]] | None = None,
        timing: ProviderTiming | None = None,
    ) -> None:
        self._reserve = reserve
        self._settle = settle
        self._release = release
        self._limits = limits
        self._request = request
        self._resolve_dispatch = resolve_dispatch
        self._timing = timing or ProviderTiming()
        self._sends: list[_DispatchSend] = []
        #: ``perf_counter`` instant of the first actual provider send (after
        #: admission/queue wait), so measured latency excludes queue time.
        self.provider_started_at: float | None = None

    @property
    def timing(self) -> ProviderTiming:
        """The shared actual-send accumulator of this attempt."""

        return self._timing

    def mark_started(self, token: object) -> None:
        """Mark a non-runner send as actually starting now."""

        if isinstance(token, _DispatchSend):
            token.started = True
            self._timing.begin_send()
            if self.provider_started_at is None:
                self.provider_started_at = time.perf_counter()

    async def begin(self, *, mark_started: bool = True) -> object:
        reservation = await _reserve_attempt(self._reserve)
        if getattr(reservation, "idempotent", False):
            native = getattr(reservation, "admission", None)
            if native is not None:
                # A native replay can identify an existing reservation, but
                # cannot fund an additional send. Execution retries must obtain
                # a fresh combined admission through the service.
                raise local_rate_denial(
                    native.provider,
                    operation=native.operation,
                    reasons=["attempt_requires_fresh_identity"],
                )
            charge_next = getattr(reservation, "charge_next_dispatch", None)
            if callable(charge_next):
                reservation = await charge_next()
        if self.provider_started_at is None:
            self.provider_started_at = time.perf_counter()
        send = _DispatchSend(reservation)
        # The runner observer calls begin immediately before the actual HTTP
        # operation, so this send has started. The non-runner path marks the
        # send explicitly after its pre-send deadline check instead.
        if mark_started:
            send.started = True
            self._timing.begin_send()
        self._sends.append(send)
        return send

    async def end(
        self,
        token: object,
        *,
        result: object | None = None,
        error: BaseException | None = None,
        retryable: bool = False,
    ) -> None:
        if not isinstance(token, _DispatchSend):
            return
        self._timing.end_send()
        if error is not None or retryable:
            token.outcome = "failure"
            token.error = error or ProviderOperationError(
                ProviderError(
                    provider="upstream",
                    code="http_error",
                    message="retryable upstream response",
                    retryable=True,
                    status_code=getattr(result, "status_code", None),
                )
            )
            if not token.started:
                # The deadline/pre-send check refused before any provider
                # operation: release the reservation and close its recovery
                # record as failed, never as an uncertain upstream attempt.
                await self._release_unsent(token)
                return
            # A received HTTP response proves that this send completed. Settle
            # its own debit and release both durable and fair-queue
            # concurrency before the runner attempts a retry; otherwise the
            # retry queues behind the slot this send already finished holding.
            # Transport failures have uncertain receipts and retain their hold.
            if retryable and (
                result is not None
                or getattr(getattr(error, "error", None), "status_code", None) is not None
            ):
                complete = getattr(token.reservation, "complete_dispatch", None)
                if getattr(token.reservation, "admission", None) is None and callable(complete):
                    # Keep the strict reservation replayable for the runner's
                    # same-identity retry, but mark the known completed send
                    # dispatch-complete so durable concurrency is free, and
                    # release the fair-queue slot it was holding.
                    await complete()
                    token.finalized = True
                    await self._resolve(token, "failed")
                else:
                    await self._failure(token, token.error)
                    token.finalized = True
                    await self._resolve(token, "failed")
            elif (
                error is not None
                and getattr(getattr(error, "error", None), "status_code", None) is None
            ):
                token.outcome = "open"
            return
        token.outcome = "success"
        token.response = result

    async def finalize(
        self,
        *,
        response: SearchResponse | FetchResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        groups: dict[str, _DispatchSend] = {}
        for send in self._sends:
            groups[send.attempt_id] = send
        for send in groups.values():
            if send.finalized:
                continue
            if send.outcome == "open":
                if not send.started:
                    await self._release_unsent(send)
                    continue
                self._timing.finish_open_send()
                await self._uncertain(send, error=error)
                await self._resolve(send, "uncertain")
            elif send.outcome == "success":
                await self._success(send, response)
                await self._resolve(send, "completed")
            else:
                await self._failure(send, send.error or error)
                await self._resolve(send, "failed")

    async def _release_unsent(self, send: _DispatchSend) -> None:
        """Undo a reservation that provably never began a provider send."""

        if send.finalized:
            return
        send.finalized = True
        send.outcome = "released"
        if self._release is not None:
            with contextlib.suppress(Exception):
                await self._release(send.reservation)
        await self._resolve(send, "failed")

    async def _resolve(self, send: _DispatchSend, outcome: str) -> None:
        """Resolve the authority recovery record and free the fair-queue slot."""

        if send.resolved:
            return
        send.resolved = True
        try:
            attempt_id = send.attempt_id
            if attempt_id and self._resolve_dispatch is not None:
                with contextlib.suppress(Exception):
                    await self._resolve_dispatch(attempt_id, outcome)
        finally:
            finish = getattr(send.reservation, "finish", None)
            if callable(finish):
                finish()

    async def _success(
        self, send: _DispatchSend, response: SearchResponse | FetchResponse | None
    ) -> None:
        admission = getattr(send.reservation, "admission", None)
        if admission is not None and self._limits is not None and response is not None:
            await self._limits.record_success(admission, response, request=self._request)
            return
        if admission is not None and self._limits is not None:
            await self._limits.record_uncertain(
                admission, reason="missing_response", upstream_complete=True
            )
            return
        await _settle_reservation(send.reservation, "completed", self._settle)

    async def _failure(self, send: _DispatchSend, error: BaseException | None) -> None:
        admission = getattr(send.reservation, "admission", None)
        if admission is not None and self._limits is not None:
            await _finalize_native_failure(self._limits, admission, error, request=self._request)
            return
        await _settle_reservation(send.reservation, "failed", self._settle)

    async def _uncertain(self, send: _DispatchSend, *, error: BaseException | None) -> None:
        admission = getattr(send.reservation, "admission", None)
        if admission is not None and self._limits is not None:
            with contextlib.suppress(Exception):
                await self._limits.record_uncertain(admission, reason="cancelled")
            return
        await _settle_reservation(send.reservation, "uncertain", self._settle)


async def _settle_reservation(
    reservation: Any,
    outcome: str,
    settle: Callable[[str], Awaitable[None]] | None,
) -> None:
    """Settle one reservation through its own hook when it provides one."""

    own = getattr(reservation, "settle", None)
    if callable(own):
        await own(outcome)
        return
    if settle is not None:
        await settle(outcome)


async def _finalize_native_failure(
    limits: "ProviderLimitsService",
    admission: Any,
    error: BaseException | None,
    *,
    request: SearchRequest | FetchRequest | None,
) -> None:
    """Record one dispatched native failure with the existing charge policy."""

    if error is None:
        await limits.record_failure(
            admission,
            ProviderError(
                provider=admission.provider,
                code="upstream_error",
                message="upstream call failed",
                retryable=False,
            ),
        )
        return
    provider_error = getattr(error, "error", None)
    if not isinstance(provider_error, ProviderError):
        await limits.record_failure(
            admission,
            ProviderError(
                provider=admission.provider,
                code=type(error).__name__,
                message="local call failure",
                retryable=False,
            ),
        )
        return
    details = provider_error.details if isinstance(provider_error.details, dict) else {}
    await limits.record_failure(
        admission,
        provider_error,
        charged_native=_charged_native(details),
        charged_document=bool(details.get("charged_document")),
    )


async def _finalize_capacity_path(
    *,
    charger: _CapacityCharger | None,
    admission: Any,
    limits: "ProviderLimitsService | None",
    cancelled: bool,
    failure: BaseException | None,
    response: SearchResponse | FetchResponse | None,
    request: SearchRequest | FetchRequest | None,
) -> None:
    """Finalize the capacity obligations of one call exactly once."""

    if charger is not None:
        await asyncio.shield(charger.finalize(response=response, error=failure))
        return
    if admission is None or limits is None:
        return
    with contextlib.suppress(Exception):
        if cancelled:
            await asyncio.shield(limits.record_uncertain(admission, reason="cancelled"))
        elif failure is not None:
            if isinstance(failure, Exception):
                await asyncio.shield(_finalize_failure(limits, admission, failure, request=request))
        elif response is not None:
            await asyncio.shield(limits.record_success(admission, response, request=request))


async def _dispatch_provider_call[ResponseT](
    *,
    charger: _CapacityCharger | None,
    runner: object | None,
    adapter: ProviderAdapter,
    call: Callable[[ProviderAdapter], Awaitable[ResponseT]],
    pre_send: Callable[[], None] | None,
) -> ResponseT:
    """Run one adapter call with the correct per-send charging shape."""

    if charger is not None and runner is not None:
        if pre_send is not None:
            pre_send()
        observer_token = install_dispatch_observer(charger)
        try:
            return await call(adapter)
        finally:
            reset_dispatch_observer(observer_token)
    if charger is not None:
        send = await charger.begin(mark_started=False)
        try:
            if pre_send is not None:
                pre_send()
            charger.mark_started(send)
            response = await call(adapter)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await charger.end(send, error=exc, retryable=False)
            raise
        else:
            await charger.end(send, result=response)
            return response
    if pre_send is not None:
        pre_send()
    return await call(adapter)


async def tracked_call[ResponseT: (SearchResponse, FetchResponse)](
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    call: Callable[[ProviderAdapter], Awaitable[ResponseT]],
    *,
    operation: UsageOperation,
    attribution: ExecutionAttribution,
    request: SearchRequest | FetchRequest | None = None,
    limits: "ProviderLimitsService | None" = None,
    binding: AttemptBinding | None = None,
    reserve: Callable[[], Awaitable[Any]] | None = None,
    settle: Callable[[str], Awaitable[None]] | None = None,
    release: Callable[[Any], Awaitable[None]] | None = None,
    context: "LimitCallContext | None" = None,
    resolve_dispatch: Callable[[str, str], Awaitable[None]] | None = None,
    timing: ProviderTiming | None = None,
    pre_send: Callable[[], None] | None = None,
) -> ResponseT:
    """Await ``call(adapter)`` recording success and failure telemetry around it.

    A routing failure never reaches this helper, so it records no telemetry.
    Adapter failures record a zero-unit failure usage event with the measured
    latency plus a degraded observation, then re-raise the original error;
    successful responses record the measured latency and success status with
    their usage event (when present) and a healthy observation.

    When ``limits`` is supplied, a durable funds and rate admission runs after
    the unchanged route selection and before the vendor call. A local denial is
    raised before any vendor I/O, so it consumes no rate capacity and never
    counts as a provider health failure. A vendor 429 additionally records a
    credential-scoped rate-state cooldown carrying the vendor Retry-After
    delay; a local denial never records one.

    The optional ``reserve``/``settle``/``release`` triple owns the strict
    pool+project reservation. Every actual upstream send is charged with a
    fresh attempt identity, including retries inside the adapter's resilience
    runner. A cancellation retains an uncertain send's debit; only a
    provably non-dispatched reservation is released.
    """

    provider_timing = timing or ProviderTiming()
    credential_id = binding.credential_id if binding is not None else None
    upstream_pool_id = (
        context.upstream_pool_id
        if context is not None and context.upstream_pool_id is not None
        else (binding.pool_id if binding is not None else None)
    )
    admission: Any = None
    charger: _CapacityCharger | None = None
    if reserve is None:
        admission = await _admit_call(limits, adapter, operation, request, context=context)
        provider_timing.begin_send()
    else:
        charger = _CapacityCharger(
            reserve=reserve,
            settle=settle,
            release=release,
            limits=limits,
            request=request,
            resolve_dispatch=resolve_dispatch,
            timing=provider_timing,
        )
    response: ResponseT | None = None
    cancelled = False
    runner = getattr(adapter, "dispatch_runner", None)
    try:
        response = await _dispatch_provider_call(
            charger=charger,
            runner=runner,
            adapter=adapter,
            call=call,
            pre_send=pre_send,
        )
    except asyncio.CancelledError:
        cancelled = True
        await _finalize_capacity_path(
            charger=charger,
            admission=admission,
            limits=limits,
            cancelled=True,
            failure=None,
            response=None,
            request=request,
        )
        raise
    except BaseException as exc:
        await _finalize_capacity_path(
            charger=charger,
            admission=admission,
            limits=limits,
            cancelled=False,
            failure=exc,
            response=None,
            request=request,
        )
        if isinstance(exc, (ExecutionError, LimitDeniedError, LimitStoreUnavailable)):
            # A local admission/store/queue failure is not provider health and
            # writes no usage event, whether it happened before the first send
            # or before a retry.
            raise
        if charger is None:
            provider_timing.end_send()
        await _record_failure_telemetry_for(
            repository,
            adapter,
            attribution,
            operation,
            provider_timing.latency_ms,
            binding,
            exc,
            request=request,
            limits=limits,
            credential_id=credential_id,
            upstream_pool_id=upstream_pool_id,
        )
        raise
    await _finalize_capacity_path(
        charger=charger,
        admission=admission,
        limits=limits,
        cancelled=cancelled,
        failure=None,
        response=response,
        request=request,
    )
    if response is None:  # pragma: no cover - a completed call always has one
        raise LimitStoreUnavailable(adapter.name)
    if charger is None:
        provider_timing.end_send()
    await _record_success_telemetry_for(
        repository,
        adapter,
        attribution,
        operation,
        provider_timing.latency_ms,
        binding,
        response,
        request=request,
        limits=limits,
        credential_id=credential_id,
        upstream_pool_id=upstream_pool_id,
    )
    return response


async def _record_success_telemetry_for(
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    attribution: ExecutionAttribution,
    operation: UsageOperation,
    latency_ms: int,
    binding: AttemptBinding | None,
    response: SearchResponse | FetchResponse,
    *,
    request: SearchRequest | FetchRequest | None,
    limits: "ProviderLimitsService | None",
    credential_id: UUID | None,
    upstream_pool_id: UUID | None,
) -> None:
    """Record success telemetry and local quota state for one completed call."""

    await record_response_telemetry(
        repository,
        response,
        attribution=attribution,
        latency_ms=_measured_latency_ms(adapter.name, latency_ms),
        binding=binding,
        queue_wait_ms=consume_queue_wait(),
    )
    await _record_adapter_quota(
        repository,
        adapter,
        "quota_after_success",
        response,
        operation=operation,
        credential_id=credential_id,
        upstream_pool_id=upstream_pool_id,
    )


async def _record_failure_telemetry_for(
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    attribution: ExecutionAttribution,
    operation: UsageOperation,
    latency_ms: int,
    binding: AttemptBinding | None,
    failure: BaseException,
    *,
    request: SearchRequest | FetchRequest | None,
    limits: "ProviderLimitsService | None",
    credential_id: UUID | None,
    upstream_pool_id: UUID | None,
) -> None:
    """Record failure telemetry, health, cooldown, and terminal 402 state."""

    exc = failure
    if not isinstance(exc, Exception):
        return
    await _record_failure_usage(
        repository,
        attribution=attribution,
        provider=adapter.name,
        operation=operation,
        latency_ms=_measured_latency_ms(adapter.name, latency_ms),
        binding=binding,
        queue_wait_ms=consume_queue_wait(),
    )
    await record_failure_telemetry(
        repository,
        provider=adapter.name,
        credential_id=credential_id,
    )
    await _record_vendor_cooldown(
        limits,
        adapter,
        exc,
        credential_id=credential_id,
        upstream_pool_id=upstream_pool_id,
    )
    status = getattr(getattr(exc, "error", None), "status_code", None)
    await _record_adapter_quota(
        repository,
        adapter,
        "quota_after_error",
        status,
        operation=operation,
        credential_id=credential_id,
        upstream_pool_id=upstream_pool_id,
    )
    if _terminal_quota_402(exc) and limits is not None:
        with contextlib.suppress(Exception):
            await limits.record_terminal_402(
                adapter.name,
                _adapter_auth_mode(adapter),
                credential_id=credential_id,
                upstream_pool_id=upstream_pool_id,
            )


async def _reserve_attempt(reserve: Callable[[], Awaitable[Any]] | None) -> Any:
    """Reserve strict capacity for one attempt, or raise a typed failure.

    A denial (window or concurrency shortage) propagates unchanged before any
    vendor I/O; a store failure becomes :class:`LimitStoreUnavailable`, so a
    failed capacity check rejects the execution instead of admitting blindly.
    """

    if reserve is None:
        return None
    try:
        return await reserve()
    except LimitStoreUnavailable:
        raise
    except ExecutionError:
        # A typed local refusal (queue expiry, revoked authority, changed
        # binding) keeps its own shape so transports can project it.
        raise
    except LimitDeniedError:
        raise
    except Exception as error:
        raise LimitStoreUnavailable("pool cap reservation") from error


def _adapter_auth_mode(adapter: ProviderAdapter) -> AuthMode:
    """Return an adapter's limit rail, defaulting to the keyed rail."""

    mode = getattr(adapter, "limit_auth_mode", None)
    return mode if isinstance(mode, AuthMode) else AuthMode.KEYED


async def _admit_call(
    limits: "ProviderLimitsService | None",
    adapter: ProviderAdapter,
    operation: UsageOperation,
    request: SearchRequest | FetchRequest | None,
    *,
    context: "LimitCallContext | None" = None,
) -> Any:
    """Reserve funds and rate capacity for one call, or raise a local denial.

    An execution service supplies ``context`` with its own attempt id and the
    trusted attribution; the legacy path builds an unattributed context.
    """

    if limits is None or operation is UsageOperation.COST_ESTIMATE:
        return None
    auth_mode = _adapter_auth_mode(adapter)
    limit_operation = LimitOperation(operation.value)
    if not limits.supports(adapter.name, limit_operation, auth_mode):
        # A synthetic adapter without a catalog record stays ungated.
        return None
    if context is not None:
        if (
            context.provider != adapter.name
            or context.operation is not limit_operation
            or context.auth_mode is not auth_mode
        ):
            # Abort on a mismatched preview context; legacy owns its context.
            raise LimitStoreUnavailable(adapter.name)
        attempt_context: LimitCallContext = context
    else:
        attempt_context = LimitCallContext(
            provider=adapter.name,
            operation=limit_operation,
            auth_mode=auth_mode,
            attempt_id=uuid4().hex,
            request=request,
            requested_at=datetime.now(UTC),
        )
    try:
        return await limits.admit(attempt_context)
    except LimitDeniedError:
        raise
    except Exception as error:
        raise LimitStoreUnavailable(adapter.name) from error


async def _finalize_failure(
    limits: "ProviderLimitsService | None",
    admission: Any,
    error: Exception,
    *,
    request: SearchRequest | FetchRequest | None,
) -> None:
    """Finalize or release one failed admission with its confirmed charge."""

    if limits is None or admission is None:
        return
    provider_error = getattr(error, "error", None)
    if provider_error is None:
        await limits.record_failure(
            admission,
            ProviderError(
                provider=admission.provider,
                code=type(error).__name__,
                message="local call failure",
                retryable=False,
            ),
        )
        return
    details = provider_error.details if isinstance(provider_error.details, dict) else {}
    await limits.record_failure(
        admission,
        provider_error,
        charged_native=_charged_native(details),
        charged_document=bool(details.get("charged_document")),
    )


def _terminal_quota_402(exc: BaseException) -> bool:
    """Return whether one failure is a terminal vendor out-of-credits 402.

    The shape mirrors ``_terminal_quota_402`` in ``routers/api.py``: a
    ``ProviderOperationError`` whose stored error names ``code="quota_exhausted"``
    and ``status_code=402`` for providers with credit pools (Tavily, Firecrawl).
    The monitoring layer must not import from the router, so the predicate is
    repeated here.
    """

    if not isinstance(exc, ProviderOperationError):
        return False
    error = exc.error
    return (
        error.provider in ("tavily", "firecrawl", "exa")
        and error.code == "quota_exhausted"
        and error.status_code == 402
    )


# Retain alias for Tavily-specific callers and backwards compatibility
_terminal_tavily_402 = _terminal_quota_402


def _charged_native(details: dict[str, Any]) -> Decimal | None:
    """Return a confirmed native charge reported by an adapter failure."""

    value = details.get("native_credits")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _vendor_retry_after_seconds(details: dict[str, Any]) -> int | None:
    """Return a real, finite, nonnegative integer Retry-After delay.

    Bools are rejected even though ``bool`` subclasses ``int``; any other
    shape yields ``None``."""

    value = details.get("retry_after_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


async def _record_vendor_cooldown(
    limits: "ProviderLimitsService | None",
    adapter: ProviderAdapter,
    error: Exception,
    *,
    credential_id: UUID | None = None,
    upstream_pool_id: UUID | None = None,
) -> None:
    """Record a vendor 429 as rate-state cooldown; additive and never raising.

    Only a vendor response carries the normalized 429 with its Retry-After
    seconds: the local denial raised before the vendor call exits in
    :func:`_admit_call` and never reaches the failure path of
    :func:`tracked_call`. The rate-service write stays defensive - a missing
    service or method, or a failed write, is skipped without touching the
    recorded failure.
    """

    if limits is None:
        return
    provider_error = getattr(error, "error", None)
    if not isinstance(provider_error, ProviderError) or provider_error.status_code != 429:
        return
    retry_after = _vendor_retry_after_seconds(provider_error.details)
    if retry_after is None:
        return
    record = getattr(getattr(limits, "rate_limits", None), "record_vendor_cooldown", None)
    if not callable(record):
        return
    with contextlib.suppress(Exception):
        await record(
            provider=adapter.name,
            auth_mode=_adapter_auth_mode(adapter),
            retry_after_seconds=retry_after,
            attempted_at=datetime.now(UTC),
            credential_id=credential_id,
            upstream_pool_id=upstream_pool_id,
        )


# Cache-only quota contract: a ``quota()`` read in this module must never
# issue vendor I/O in the request path. Tavily spends its documented usage
# endpoint budget only through the scheduler-driven ``usage_snapshot``
# (services/limits_sync.py); every read below is a cached snapshot or an
# unknown state, and the ``quota_after_success``/``quota_after_error``
# projections are local recomputes over cached state that never poll the
# vendor.
async def refresh_quotas(
    repository: SQLiteRepository | None,
    adapters: Sequence[ProviderAdapter],
    *,
    force: bool = False,
    now: datetime | None = None,
    secret_store: AsyncSecretStore | None = None,
    scopes: Mapping[int, ProviderObservationScope] | None = None,
    limits: "ProviderLimitsService | None" = None,
) -> list[QuotaSnapshot]:
    """Poll quota-capable adapters once per bounded TTL and persist snapshots."""

    if repository is None:
        return []
    observed_at = now or datetime.now(UTC)
    snapshots: list[QuotaSnapshot] = []
    for adapter in adapters:
        try:
            if not adapter.capabilities.quota:
                continue
            scope = scopes.get(id(adapter)) if scopes is not None else None
            if (
                scope is not None
                and limits is not None
                and (type(adapter).usage_snapshot is not ProviderAdapter.usage_snapshot)
            ):
                from freesearch.services.limits_sync import LimitSyncService

                def scoped_adapters(adapter: ProviderAdapter = adapter) -> list[ProviderAdapter]:
                    return [adapter]

                await LimitSyncService(
                    repository.limits,
                    limits,
                    scoped_adapters,
                    scope=scope,
                    quota_repository=repository,
                ).sync_provider(adapter.name, observed_at)
                snapshot = await repository.latest_quota(
                    adapter.name, credential_id=scope.credential_id, pool_id=scope.upstream_pool_id
                )
            else:
                snapshot = await _poll_one_quota(repository, adapter, force, observed_at, scope)

        except Exception:
            logger.warning("quota poll could not be completed")
            continue
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


async def _poll_one_quota(
    repository: SQLiteRepository,
    adapter: ProviderAdapter,
    force: bool,
    observed_at: datetime,
    scope: ProviderObservationScope | None = None,
) -> QuotaSnapshot | None:
    scope_key = scope.model_dump_json() if scope is not None else ""
    cache_key = (id(repository), id(adapter), scope_key)
    credential_id = scope.credential_id if scope is not None else None
    pool_id = scope.upstream_pool_id if scope is not None else None
    lock = _quota_poll_locks.setdefault(cache_key, asyncio.Lock())
    was_running = lock.locked()
    async with lock:
        failure_at = _quota_failure_cache.get(cache_key)
        if failure_at is not None:
            backoff = timedelta(seconds=_quota_failure_backoff_seconds())
            if observed_at - failure_at < backoff:
                try:
                    return (
                        await repository.latest_quota(adapter.name)
                        if scope is None
                        else await repository.latest_quota(
                            adapter.name, credential_id=credential_id, pool_id=pool_id
                        )
                    )
                except Exception:
                    return None
            _quota_failure_cache.pop(cache_key, None)
        cached_at = _quota_poll_cache.get(cache_key)
        ttl = _quota_ttl_seconds()
        within_ttl = cached_at is not None and observed_at - cached_at < timedelta(seconds=ttl)
        if within_ttl and (not force or was_running):
            try:
                return (
                    await repository.latest_quota(adapter.name)
                    if scope is None
                    else await repository.latest_quota(
                        adapter.name, credential_id=credential_id, pool_id=pool_id
                    )
                )
            except Exception:
                return None
        try:
            snapshot = await adapter.quota()
        except Exception:
            _quota_failure_cache[cache_key] = observed_at
            return None
        if snapshot is None:
            return None
        try:
            if scope is None:
                await repository.record_quota(snapshot)
            else:
                await repository.record_quota(
                    snapshot,
                    credential_id=credential_id,
                    pool_id=pool_id,
                    credential_generation=scope.credential_generation,
                )
        except Exception:
            _quota_failure_cache[cache_key] = observed_at
            return None
        _quota_failure_cache.pop(cache_key, None)
        _quota_poll_cache[cache_key] = observed_at
        return snapshot


def normalize_degenerate_quota(snapshot: QuotaSnapshot) -> QuotaSnapshot:
    """Return a copy that treats a zero quota limit as unknown."""

    if snapshot.limit == Decimal("0"):
        return snapshot.model_copy(update={"remaining": None, "limit": None, "reset_at": None})
    return snapshot.model_copy()


def _free_zero_due(provider: str, snapshot: QuotaSnapshot, now: datetime) -> bool:
    """Return True when Tavily's or Firecrawl's terminal free zero has passed its reset instant.

    The stored exhaustion mark (``vendor_402`` or the generic ``exhaustion``
    flag) identifies the terminal zero; the monthly reset instant is the only
    trigger, so no vendor read is needed to expire it.
    """

    if (
        provider not in ("tavily", "firecrawl", "exa")
        or snapshot.remaining != Decimal("0")
        or snapshot.reset_at is None
    ):
        return False
    metadata = snapshot.metadata
    exhausted = metadata.get("vendor_402") is True or metadata.get("exhaustion") is True
    return exhausted and now >= snapshot.reset_at


async def _expire_free_zero(
    repository: SQLiteRepository, snapshot: QuotaSnapshot, now: datetime
) -> QuotaSnapshot:
    """Persist and return the snapshot that expires Tavily's free zero.

    The cleared view keeps every metadata mark plus ``free_zero_expired`` and
    reports an unknown remaining balance; a failed write keeps the stored zero.
    """

    cleared = snapshot.model_copy(
        update={
            "remaining": None,
            "observed_at": now,
            "metadata": {**snapshot.metadata, "free_zero_expired": True},
        }
    )
    try:
        await repository.record_quota(cleared)
    except Exception:
        return snapshot
    return cleared


async def _expire_soft_zero(
    repository: SQLiteRepository, provider: str, snapshot: QuotaSnapshot
) -> QuotaSnapshot:
    """Persist and return the snapshot that clears a proven-soft zero.

    The shared clear path behind :func:`effective_quota` and
    :func:`effective_quotas_batch`: a later successful usage event proves the
    balance, so the zero is marked non-soft and the unknown state is stored.
    Persistence failures raise; callers keep their stored snapshot.
    """

    events = await repository.list_provider_usage(provider=provider)
    successful = [
        event
        for event in events
        if event.status is UsageStatus.SUCCESS and event.observed_at > snapshot.observed_at
    ]
    if not successful:
        return snapshot
    cleared = snapshot.model_copy(
        update={
            "remaining": None,
            "observed_at": max(event.observed_at for event in successful),
            "metadata": {**snapshot.metadata, "soft_zero": False},
        }
    )
    await repository.record_quota(cleared)
    return cleared


async def effective_quota(
    repository: SQLiteRepository | None,
    provider: str,
    *,
    now: datetime | None = None,
) -> QuotaSnapshot | None:
    """Return the routable quota view with stale zero states expired locally.

    No vendor read happens on this path: Parallel's soft zero clears once a
    later successful event proves balance, and Tavily's terminal free zero
    expires at its monthly reset instant.
    """

    if repository is None:
        return None
    observed_at = now or datetime.now(UTC)
    snapshot = await repository.latest_quota(provider)
    if snapshot is None:
        return None
    snapshot = normalize_degenerate_quota(snapshot)
    if snapshot.remaining != Decimal("0"):
        return snapshot
    if _free_zero_due(provider, snapshot, observed_at):
        return await _expire_free_zero(repository, snapshot, observed_at)
    if not is_soft_quota_zero(provider, snapshot):
        return snapshot
    try:
        return await _expire_soft_zero(repository, provider, snapshot)
    except Exception:
        return snapshot


async def effective_quotas_batch(
    repository: SQLiteRepository | None,
    providers: Sequence[str],
    *,
    now: datetime | None = None,
) -> dict[str, QuotaSnapshot]:
    """Return the routable quota view for each requested provider in one batch."""

    if repository is None or not providers:
        return {}
    observed_at = now or datetime.now(UTC)
    raw_snapshots = await repository.latest_quota_batch(providers)
    quotas: dict[str, QuotaSnapshot] = {}
    for provider, snapshot in raw_snapshots.items():
        snapshot = normalize_degenerate_quota(snapshot)
        if snapshot.remaining == Decimal("0"):
            if _free_zero_due(provider, snapshot, observed_at):
                snapshot = await _expire_free_zero(repository, snapshot, observed_at)
            elif is_soft_quota_zero(provider, snapshot):
                with contextlib.suppress(Exception):
                    snapshot = await _expire_soft_zero(repository, provider, snapshot)
        quotas[provider] = snapshot
    return quotas


async def _record_adapter_quota(
    repository: SQLiteRepository | None,
    adapter: ProviderAdapter,
    method_name: str,
    argument: object,
    *,
    operation: UsageOperation | None = None,
    credential_id: UUID | None = None,
    upstream_pool_id: UUID | None = None,
) -> None:
    """Persist local quota state exposed by an adapter without vendor polling.

    A quota snapshot written through a credential-scoped attempt is attributed
    to that credential, so one credential's balance never becomes another
    credential's routing state.
    """

    if repository is None:
        return
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return
    try:
        parameters = inspect.signature(method).parameters
        if operation is not None and "operation" in parameters:
            result = method(argument, operation=operation)
        else:
            result = method(argument)
        snapshot = await result if inspect.isawaitable(result) else result
        if isinstance(snapshot, QuotaSnapshot):
            await repository.record_quota(
                snapshot, credential_id=credential_id, pool_id=upstream_pool_id
            )
    except Exception:
        logger.warning("local quota state could not be persisted")


async def latency_p95_ms(
    repository: SQLiteRepository | None, provider: str, *, window: int = 100
) -> int | None:
    """Return the nearest-rank 95th percentile latency for ``provider``.

    Samples are the last ``window`` measured (non-null) latencies in the usage
    ledger. ``None`` is reported when no samples exist; read failures degrade
    to ``None`` without raising."""

    if repository is None:
        return None
    try:
        samples = await repository.recent_latencies(provider, limit=window)
    except Exception:
        logger.warning("latency sample read could not be collected")
        return None
    if not samples:
        return None
    ordered = sorted(samples)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


async def collect_stats(
    repository: SQLiteRepository | None,
    *,
    adapter_names: Sequence[str] = (),
    recent_limit: int = DEFAULT_RECENT_LIMIT,
    limits: "ProviderLimitsService | None" = None,
) -> StatsResponse:
    """Read the monitoring snapshot; every read path is failure-safe."""

    if repository is None:
        return _empty_stats()
    try:
        totals = await repository.installation_usage_totals()
        recent = await repository.recent_installation_usage(limit=recent_limit)
        providers = sorted(
            set(adapter_names)
            | {total.provider for total in totals}
            | {event.provider for event in recent}
        )
        latest_quota = await _latest_quotas(repository, providers, totals=totals)
        latest_health = await _latest_health(repository, providers)
    except Exception:
        logger.warning("monitoring reads could not be collected")
        return _empty_stats()
    crd_totals = await _crd_usage_totals(limits)
    return StatsResponse(
        notice=MONITORING_NOTICE,
        usage_totals=_contract_totals(totals),
        recent_usage=_contract_recent(recent),
        latest_quota=latest_quota,
        latest_health=_contract_health(latest_health),
        spend_totals=[USDUsageTotal.model_validate(row) for row in crd_totals],
    )


def _clamped_recent_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_RECENT_LIMIT)


async def _require_usage_read(
    repository: SQLiteRepository, actor: UserPrincipal, project_id: UUID
) -> None:
    """Require live project ``usage.read``; unknown projects are not found."""

    async def operation(session: AsyncSession) -> None:
        await require_project_permission(
            session,
            ScopedAuthorizationService(repository),
            actor,
            project_id,
            PermissionAction.USAGE_READ,
        )

    await run_control_read(repository, operation)


async def _project_usage_rows(
    repository: SQLiteRepository,
    *,
    project_id: UUID,
    recent_limit: int,
) -> tuple[list[UsageTotal | LegacyUsageTotal], list[UsageEvent]]:
    try:
        totals = await repository.project_usage_totals(project_id=project_id)
        recent = await repository.recent_project_usage(
            project_id=project_id, limit=_clamped_recent_limit(recent_limit)
        )
    except Exception as error:
        logger.warning("project usage reads could not be collected")
        raise ControlStorageUnavailable("project usage is unavailable") from error
    return totals, recent


async def collect_project_usage(
    repository: SQLiteRepository,
    actor: UserPrincipal,
    project_id: UUID,
    *,
    recent_limit: int = DEFAULT_RECENT_LIMIT,
) -> ProjectUsageResponse:
    """Return only the authorized project's usage totals and recent ledger."""

    await _require_usage_read(repository, actor, project_id)
    totals, recent = await _project_usage_rows(
        repository, project_id=project_id, recent_limit=recent_limit
    )
    return ProjectUsageResponse(
        project_id=project_id,
        totals=_contract_totals(totals),
        recent_usage=_contract_recent(recent),
        generated_at=datetime.now(UTC),
    )


async def _crd_usage_totals(
    limits: "ProviderLimitsService | None",
) -> list[CRDUsageTotal]:
    """Read the credit-unit totals best effort; a failure yields no totals."""

    if limits is None:
        return []
    try:
        return await limits.usage_totals()
    except Exception:
        logger.warning("credit-unit totals could not be collected")
        return []


def _brave_request_success_total(
    totals: Sequence[UsageTotal | LegacyUsageTotal],
) -> Decimal:
    """Sum Brave REQUEST success units without mixing other dimensions."""
    total = Decimal("0")
    for item in totals:
        if item.provider != "brave":
            continue
        if getattr(item, "unit_kind", None) is not UnitKind.REQUEST:
            continue
        total += item.total_units
    return total


def _enrich_brave_snapshot(snapshot: QuotaSnapshot, success_total: Decimal) -> QuotaSnapshot:
    """Attach derived USD spend metadata without touching throttle fields."""
    if snapshot.provider != "brave":
        return snapshot
    metadata: dict[str, Any] = dict(snapshot.metadata)
    metadata.setdefault("cost_per_req", COST_USD_PER_REQUEST)
    metadata.setdefault("allowance_usd", FREE_CREDITS_USD)
    try:
        metadata["spend_usd"] = brave_spend_usd(success_total)
    except (ArithmeticError, TypeError, ValueError):
        return snapshot.model_copy(update={"metadata": metadata})
    return snapshot.model_copy(update={"metadata": metadata})


async def _latest_quotas(
    repository: SQLiteRepository,
    providers: Sequence[str],
    *,
    totals: Sequence[UsageTotal | LegacyUsageTotal] | None = None,
) -> list[QuotaSnapshot]:
    """Return each provider's newest quota snapshot, keeping its provenance."""
    if totals is None:
        try:
            totals = await repository.installation_usage_totals()
        except Exception:
            totals = []
    brave_total = _brave_request_success_total(totals)
    snapshots: list[QuotaSnapshot] = []
    for provider in providers:
        snapshot = await repository.latest_quota(provider)
        if snapshot is not None:
            normalized = normalize_degenerate_quota(snapshot)
            if normalized.provider == "brave":
                normalized = _enrich_brave_snapshot(normalized, brave_total)
            snapshots.append(normalized)
    return snapshots


async def _latest_health(
    repository: SQLiteRepository, providers: Sequence[str]
) -> list[ProviderHealth]:
    """Return one intentional aggregate health entry per provider.

    The aggregate combines the newest observation of every credential scope
    with the newest provider-wide fact. The worst status wins (unavailable
    over degraded over unknown over healthy), so a degraded credential is
    never hidden while the aggregate still exposes no credential ids or
    diagnostic messages. A failed aggregate read degrades to no entry.
    """

    loader = getattr(repository, "latest_health_scopes", None)
    try:
        if callable(loader):
            observations = await loader(providers)
        else:
            observations = [
                observation
                for provider in providers
                if (observation := await repository.latest_health(provider)) is not None
            ]
    except Exception:
        return []
    severity = {
        HealthStatus.HEALTHY: 0,
        HealthStatus.UNKNOWN: 1,
        HealthStatus.DEGRADED: 2,
        HealthStatus.UNAVAILABLE: 3,
    }
    aggregated: dict[str, ProviderHealth] = {}
    for observation in observations:
        current = aggregated.get(observation.provider)
        if (
            current is None
            or severity[observation.status] > severity[current.status]
            or (
                severity[observation.status] == severity[current.status]
                and observation.checked_at > current.checked_at
            )
        ):
            aggregated[observation.provider] = observation
    return [aggregated[provider] for provider in providers if provider in aggregated]


def _contract_totals(
    totals: Sequence[UsageTotal | LegacyUsageTotal],
) -> list[ProviderUsageTotal]:
    """Convert storage usage totals into their contract model."""

    return [
        ProviderUsageTotal(
            provider=total.provider,
            operation=total.operation,
            total_units=total.total_units,
            event_count=total.event_count,
            unit_kind=getattr(total, "unit_kind", None),
        )
        for total in totals
    ]


def _contract_recent(events: Sequence[UsageEvent]) -> list[RecentUsageEntry]:
    """Convert usage events into their privacy-projected entry model."""

    return [
        RecentUsageEntry(
            provider=event.provider,
            operation=event.operation,
            units=event.units,
            observed_at=event.observed_at,
            latency_ms=event.latency_ms,
            status=event.status,
            unit_kind=event.unit_kind,
            display_unit=event.display_unit,
        )
        for event in events
    ]


def _contract_health(observations: Sequence[ProviderHealth]) -> list[LatestHealthEntry]:
    """Convert health observations into their privacy-projected entry model."""

    return [
        LatestHealthEntry(
            provider=observation.provider,
            status=observation.status,
            checked_at=observation.checked_at,
        )
        for observation in observations
    ]


def _empty_stats() -> StatsResponse:
    """Return the empty monitoring snapshot used before any read succeeds."""

    return StatsResponse(
        notice=MONITORING_NOTICE,
        usage_totals=[],
        recent_usage=[],
        latest_quota=[],
        latest_health=[],
    )
