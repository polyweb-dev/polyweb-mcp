"""One fenced execution authority with bounded queues and weighted fair dispatch.

REST dispatches through this authority in-process. A standalone MCP server
forwards to the API that hosts it, so exactly one process owns fair queue order
for a borrowed pool. Strict (non-borrowing) pools stay correct through the
durable strict-cap transaction alone; only a borrowed pool needs the durable
fencing lease in ``execution_authority_leases``.

Scheduling is unit-cost weighted Deficit Round Robin with one unit per actual
provider attempt. Each round grants every participant its weight as a deficit;
each visit serves one unit in stable ring order, so a continuously eligible
4:6 pair produces four grants for the 4-weight project and six for the
6-weight project in every ten-dispatch cycle. A project joining mid-round gets
one bounded quantum; a round is exhausted only after every backlogged
participant spends its deficit, so momentary queue gaps cannot hand a project
a fresh quantum ahead of a sibling. Deficit is capped at one quantum.

Queues are bounded per project and per pool by pending count, pending bytes,
wait time, and in-flight concurrency. The same bounds are also enforced across
every pool and operation hosted by this authority, and a finite concurrency
default bounds compositions that declare none. A canceled or expired waiter
leaves the queue without a durable reservation, so it never reaches a provider
and never consumes a rate attempt. Wait time is measured on the monotonic clock
and reported to the caller separately from provider latency.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID, uuid4

from polyweb.models.credentials import CredentialOperation
from polyweb.models.execution_failures import (
    ExecutionAuthorityUnavailable,
    ExecutionQueueExpired,
    ExecutionQueueSaturated,
)
from polyweb.models.observability import ActorType
from polyweb.models.provider_limits import LimitDebit
from polyweb.models.schema_enums import AuthorityState, DispatchState
from polyweb.persistence.execution_authority import ExecutionAuthorityRepository
from polyweb.persistence.storage import SQLiteRepository

logger = logging.getLogger(__name__)

#: The one authority key every host of this deployment must share.
AUTHORITY_KEY = "execution-authority"

#: One scheduler unit is one actual provider attempt.
UNIT_COST = 1

#: Defaults used when an allocation or pool declares no bound.
DEFAULT_MAX_QUEUE_WAIT_MS = 5_000
DEFAULT_MAX_QUEUED_REQUESTS = 100
DEFAULT_MAX_QUEUED_BYTES = 1_000_000
DEFAULT_MAX_CONCURRENCY = 100
DEFAULT_PROJECT_MAX_CONCURRENCY = 100
DEFAULT_LEASE_SECONDS = 30.0
DEFAULT_RECOVERY_SECONDS = 5.0

ResponseT = TypeVar("ResponseT")


@dataclass
class DispatchGrant:
    """One scheduler decision attached to one provider attempt.

    ``started`` is set by the execution seam once the attempt has passed its
    final reservation and is about to call the provider. The scheduler waits
    for it before granting the next turn, so the observed dispatch start order
    is the fair order instead of the order in which asyncio happened to resume
    reserving tasks. ``finish`` releases the in-flight concurrency slot after
    the actual send settles, so a parked provider call still occupies it.
    """

    base: bool
    queue_wait_ms: int
    started: asyncio.Event = field(default_factory=asyncio.Event, compare=False, repr=False)
    on_finished: Callable[[], None] | None = field(default=None, compare=False, repr=False)
    #: Set once the waiting request has resumed and taken ownership of this
    #: grant. Shutdown must not finish an accepted grant; its attempt owns the
    #: normal settlement path. A delivered but unaccepted grant is still the
    #: queue's responsibility.
    _accepted: bool = field(default=False, compare=False, repr=False)
    _finished: bool = field(default=False, compare=False, repr=False)

    def finish(self) -> None:
        """Release the queue's in-flight slot exactly once.

        Releasing also opens the pool's start barrier: an abandoned grant
        (cancellation, expiry, shutdown) must never wedge the next turn behind
        a start that cannot happen.
        """

        if self._finished:
            return
        self._finished = True
        self.started.set()
        if self.on_finished is not None:
            self.on_finished()


@dataclass(frozen=True)
class QueuePolicy:
    """Every bound and fairness fact of one queued attempt."""

    provider: str
    project_id: UUID
    operation: CredentialOperation
    weight: int
    base_rate: int
    rate_window_seconds: int
    max_rate: int | None
    borrow_enabled: bool
    best_effort: bool
    max_concurrency: int | None
    max_queued_requests: int | None
    max_queued_bytes: int | None
    max_queue_wait_ms: int | None
    pool_max_concurrency: int | None
    pool_max_queued_requests: int | None
    #: Strictest declared project concurrency across every pool/operation.
    project_max_concurrency: int | None = None
    payload_bytes: int = 0
    #: Monotonic instant after which this request must not wait or dispatch.
    deadline: float | None = None
    #: Monotonic instant this logical request entered admission.
    admitted_at: float | None = None
    #: Monotonic instant before which a requeued retry must not dispatch.
    not_before: float | None = None
    #: Released once the queue appends this waiter (admission order gate).
    on_admitted: Callable[[], None] | None = None
    #: The admission reservation this same request is transferring, if any.
    admission_key: tuple[str, UUID, UUID] | None = None


@dataclass
class _Waiter:
    policy: QueuePolicy
    future: asyncio.Future[DispatchGrant]
    enqueued: float
    expires_at: float | None


@dataclass(frozen=True)
class _Grant:
    waiter: _Waiter
    base: bool
    dispatch: DispatchGrant


def _bounded(value: int | None, default: int) -> int:
    return max(0, default if value is None else value)


@dataclass
class _ProjectState:
    """One project's in-memory scheduling state inside one pool queue."""

    pending: deque[_Waiter] = field(default_factory=deque[_Waiter])
    #: Unit-cost weighted DRR deficit (bounded by this project's quantum).
    deficit: int = 0


class AdmissionReservation:
    """One counted admission waiter, transferring ownership to its queue."""

    __slots__ = ("_budget", "_key", "_released", "project_id")

    @property
    def key(self) -> tuple[str, UUID, UUID]:
        """Return the budget entry key this reservation owns."""

        return self._key

    def __init__(self, budget: _QueueBudget, key: tuple[str, UUID, UUID], project_id: UUID) -> None:
        self._budget = budget
        self._key = key
        self.project_id = project_id
        self._released = False

    def release(self) -> None:
        """Release this waiter exactly once (transfer or cancellation)."""

        if self._released:
            return
        self._released = True
        self._budget.remove_entry(self._key, self.project_id)


class _QueueBudget:
    """Authority-wide queue and admission accounting shared by every pool.

    Every genuinely waiting entry counts: a scheduler entry counts until it
    receives an actual grant, and an admission reservation counts until it
    transfers to that entry. A grant owns concurrency, not a queue slot, so it
    is never waiting work. Admission waiters use the same totals, so the
    global count/byte bounds cannot be bypassed by a second project or by the
    pre-queue gate. The accounting is keyed per project and per pool queue, and
    every queue republishes when waiting ownership changes elsewhere.
    """

    def __init__(
        self,
        *,
        default_max_requests: int,
        default_max_bytes: int,
        max_concurrency: int,
        project_max_concurrency: int,
    ) -> None:
        self.default_max_requests = max(0, default_max_requests)
        self.default_max_bytes = max(0, default_max_bytes)
        self.max_concurrency = max(1, max_concurrency)
        self.project_max_concurrency = max(1, project_max_concurrency)
        self.total_waiting_count = 0
        self.total_waiting_bytes = 0
        self.project_waiting_count: dict[UUID, int] = {}
        self.project_waiting_bytes: dict[UUID, int] = {}
        self._entries: dict[tuple[str, UUID, UUID], tuple[UUID, int, int]] = {}
        self._queues: list[_PoolQueue] = []
        self._refreshing = False
        self.inflight = 0
        self.project_inflight: dict[UUID, int] = {}
        self.project_caps: dict[UUID, int] = {}

    def register_queue(self, queue: _PoolQueue) -> None:
        """Include one pool scheduler in cross-queue republishing."""

        if queue not in self._queues:
            self._queues.append(queue)

    def refresh(self) -> None:
        """Republish every queue's waiting view after capacity changes."""

        if self._refreshing:
            return
        self._refreshing = True
        try:
            for queue in self._queues:
                queue._sync_all_budgets()
        finally:
            self._refreshing = False

    def set_project_cap(self, project_id: UUID, cap: int | None) -> None:
        """Remember the latest derived project concurrency cap."""

        if cap is None:
            self.project_caps.pop(project_id, None)
            return
        self.project_caps[project_id] = max(1, cap)

    def set_waiting(
        self,
        key: tuple[str, UUID, UUID],
        project_id: UUID,
        count: int,
        byte_count: int,
    ) -> None:
        """Publish one scope/project's waiting count and payload bytes."""

        value = (project_id, max(0, count), max(0, byte_count))
        previous = self._entries.get(key)
        if previous == value:
            return
        self._entries[key] = value
        old_count, old_bytes = (0, 0) if previous is None else (previous[1], previous[2])
        self._adjust_totals(
            project_id,
            count - old_count,
            byte_count - old_bytes,
        )

    def remove_entry(self, key: tuple[str, UUID, UUID], project_id: UUID) -> None:
        """Remove one published entry (admission or queue teardown)."""

        previous = self._entries.pop(key, None)
        if previous is None:
            return
        self._adjust_totals(project_id, -previous[1], -previous[2])

    def _adjust_totals(self, project_id: UUID, delta_count: int, delta_bytes: int) -> None:
        self.total_waiting_count = max(0, self.total_waiting_count + delta_count)
        self.total_waiting_bytes = max(0, self.total_waiting_bytes + delta_bytes)
        count = max(0, self.project_waiting_count.get(project_id, 0) + delta_count)
        if count:
            self.project_waiting_count[project_id] = count
        else:
            self.project_waiting_count.pop(project_id, None)
        byte_count = max(0, self.project_waiting_bytes.get(project_id, 0) + delta_bytes)
        if byte_count:
            self.project_waiting_bytes[project_id] = byte_count
        else:
            self.project_waiting_bytes.pop(project_id, None)

    def saturation(
        self,
        policy: QueuePolicy,
        *,
        pool_id: UUID,
        exclude_key: tuple[str, UUID, UUID] | None = None,
    ) -> tuple[str, str] | None:
        """Return the bound this genuinely waiting candidate would exceed.

        The caller makes this check only after the candidate failed to obtain
        an actual grant. A grant owns concurrency and is never waiting work, so
        only a real queue entry reaches this method. ``exclude_key`` is this
        same request's admission reservation: its count/bytes transfer to the
        queue entry, they are never owned twice.

        Authority, project, and pool bounds are checked independently. A pool
        override can tighten its local allowance, but it can never widen the
        authority-wide count or bytes budget.
        """

        project_id = policy.project_id
        excluded = (0, 0)
        if exclude_key is not None:
            entry = self._entries.get(exclude_key)
            if entry is not None and entry[0] == project_id:
                excluded = (entry[1], entry[2])
        # Admission waiters are counted in the authority total but never in an
        # allocation's per-project queue bound: they have not resolved a pool
        # or allocation yet. The queue itself re-checks the project bound when
        # each waiter transfers, so the later waiter is the one refused.
        admission_count, admission_bytes = self._project_admission_totals(project_id)
        project_count = max(
            0,
            self.project_waiting_count.get(project_id, 0) - admission_count,
        )
        authority_count = max(0, self.total_waiting_count - excluded[0])
        project_bytes = max(
            0,
            self.project_waiting_bytes.get(project_id, 0) - admission_bytes,
        )
        authority_bytes = max(0, self.total_waiting_bytes - excluded[1])
        pool_count, _pool_bytes = self._pool_waiting_totals(pool_id)
        max_project = _bounded(policy.max_queued_requests, self.default_max_requests)
        max_pool = _bounded(policy.pool_max_queued_requests, self.default_max_requests)
        if project_count + 1 > max_project:
            return ("count", "the execution queue count bound is full")
        if authority_count + 1 > self.default_max_requests:
            return ("count", "the execution queue count bound is full")
        if pool_count + 1 > max_pool:
            return ("count", "the execution queue count bound is full")
        payload = max(0, policy.payload_bytes)
        max_project_bytes = _bounded(policy.max_queued_bytes, self.default_max_bytes)
        if project_bytes + payload > max_project_bytes:
            return ("byte", "the execution queue byte bound is full")
        if authority_bytes + payload > self.default_max_bytes:
            return ("byte", "the execution queue byte bound is full")
        return None

    def transfer(
        self,
        *,
        admission_key: tuple[str, UUID, UUID] | None,
        queue_key: tuple[str, UUID, UUID],
        project_id: UUID,
        count: int,
        byte_count: int,
    ) -> None:
        """Move one request from admission ownership to its queue entry once.

        The admission reservation and the queue entry publish one net delta,
        so the transfer never briefly owns the request twice in the authority
        totals.
        """

        absorption_count = 0
        absorption_bytes = 0
        if admission_key is not None:
            previous = self._entries.pop(admission_key, None)
            if previous is not None:
                absorption_count = previous[1]
                absorption_bytes = previous[2]
        previous = self._entries.get(queue_key)
        old_count, old_bytes = (0, 0) if previous is None else (previous[1], previous[2])
        value = (project_id, max(0, count), max(0, byte_count))
        self._entries[queue_key] = value
        self._adjust_totals(
            project_id,
            value[1] - old_count - absorption_count,
            value[2] - old_bytes - absorption_bytes,
        )

    def _pool_waiting_totals(self, pool_id: UUID) -> tuple[int, int]:
        """Return this pool's queued count and bytes across all its projects."""

        count = 0
        byte_count = 0
        for (scope, entry_pool, _project), (_, entry_count, entry_bytes) in self._entries.items():
            if scope != "queue" or entry_pool != pool_id:
                continue
            count += entry_count
            byte_count += entry_bytes
        return count, byte_count

    def _project_admission_totals(self, project_id: UUID) -> tuple[int, int]:
        """Return this project's admission waiter count and payload bytes."""

        count = 0
        byte_count = 0
        for (scope, entry_project, _token), (_, entry_count, entry_bytes) in self._entries.items():
            if scope == "admission" and entry_project == project_id:
                count += entry_count
                byte_count += entry_bytes
        return count, byte_count

    def admission_saturation(self, *, project_id: UUID, payload_bytes: int) -> str | None:
        """Return the count/byte refusal for one extra admission waiter."""

        if self.project_waiting_count.get(project_id, 0) + 1 > self.default_max_requests:
            return "the execution admission count bound is full"
        if self.total_waiting_count + 1 > self.default_max_requests:
            return "the execution admission count bound is full"
        bytes_wanted = max(0, payload_bytes)
        if self.project_waiting_bytes.get(project_id, 0) + bytes_wanted > self.default_max_bytes:
            return "the execution queue byte bound is full"
        if self.total_waiting_bytes + bytes_wanted > self.default_max_bytes:
            return "the execution queue byte bound is full"
        return None

    def grant(self, project_id: UUID) -> None:
        self.inflight += 1
        self.project_inflight[project_id] = self.project_inflight.get(project_id, 0) + 1

    def complete(self, project_id: UUID) -> None:
        self.inflight = max(0, self.inflight - 1)
        remaining = max(0, self.project_inflight.get(project_id, 0) - 1)
        if remaining:
            self.project_inflight[project_id] = remaining
        else:
            self.project_inflight.pop(project_id, None)

    def concurrency_available(self, project_id: UUID) -> bool:
        if self.inflight >= self.max_concurrency:
            return False
        cap = self.project_caps.get(project_id, self.project_max_concurrency)
        return self.project_inflight.get(project_id, 0) < cap


class _PoolQueue:
    """Bounded per-pool queue with weighted Deficit Round Robin service."""

    def __init__(
        self,
        *,
        pool_id: UUID,
        operation: CredentialOperation,
        monotonic: Callable[[], float],
        default_max_wait_ms: int,
        default_max_requests: int,
        default_max_bytes: int,
        budget: _QueueBudget | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        project_max_concurrency: int = DEFAULT_PROJECT_MAX_CONCURRENCY,
    ) -> None:
        self.pool_id = pool_id
        self.operation = operation
        self._monotonic = monotonic
        self._default_max_wait_ms = max(0, default_max_wait_ms)
        self._budget = budget or _QueueBudget(
            default_max_requests=default_max_requests,
            default_max_bytes=default_max_bytes,
            max_concurrency=max_concurrency,
            project_max_concurrency=project_max_concurrency,
        )
        self._budget.register_queue(self)
        self._projects: dict[UUID, _ProjectState] = {}
        self._ring: list[UUID] = []
        self._round_participants: set[UUID] = set()
        self._last_served: UUID | None = None
        self._no_progress_since: float | None = None
        self._inflight: dict[UUID, int] = {}
        self._inflight_pool = 0
        self._event = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._staged: _Grant | None = None
        self._closed = False

    # -------------------------------------------------------------- admission

    async def submit(
        self,
        policy: QueuePolicy,
        attempt: Callable[[DispatchGrant], Awaitable[ResponseT]],
    ) -> ResponseT:
        """Admit, wait for one grant, run the attempt, and free its slot."""

        grant = await self._enqueue(policy)
        completed = False
        try:
            result = await attempt(grant)
            completed = True
            return result
        finally:
            # The normal path hands the grant to the returned reservation, which
            # releases the slot after the actual send settles. A cancellation
            # or failure before that handoff releases the in-memory slot here
            # exactly once; ``finish`` is idempotent.
            grant.started.set()
            if not completed:
                grant.finish()

    async def _enqueue(self, policy: QueuePolicy) -> DispatchGrant:
        now = self._monotonic()
        if self._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        if policy.deadline is not None and now >= policy.deadline:
            raise ExecutionQueueExpired("the execution request deadline expired before dispatch")
        self._expire_waiters(now)
        # Earlier eligible work keeps its scheduler turn even if this newcomer
        # arrives at the same instant. Staging is synchronous and owns real
        # concurrency, so it cannot overbook a free slot.
        self._stage_next(now)
        if self._staged is not None:
            self._ensure_runner()
            self._event.set()
        state = self._project(policy.project_id)
        if not state.pending and policy.project_id not in self._ring:
            self._ring.append(policy.project_id)
            self._ring.sort()
        future: asyncio.Future[DispatchGrant] = asyncio.get_running_loop().create_future()
        started = policy.admitted_at if policy.admitted_at is not None else now
        wait_from = started
        if policy.not_before is not None:
            # A provider-mandated Retry-After is not queue contention: the
            # wait bound starts when the retry becomes dispatchable, so a
            # 90-second Retry-After is never expired by a 5-second default.
            wait_from = max(started, policy.not_before)
        timeout = self._wait_seconds(policy, wait_from)
        expires_at = wait_from + timeout
        if policy.deadline is not None:
            # The wait may start at a retry's eligibility, but the logical
            # request deadline is absolute: it always wins.
            expires_at = min(expires_at, policy.deadline)
        waiter = _Waiter(
            policy=policy,
            future=future,
            enqueued=started,
            expires_at=expires_at,
        )
        state.pending.append(waiter)
        try:
            self._register_waiter(policy, state, waiter, now)
        except BaseException:
            self._discard(policy.project_id, waiter)
            raise
        try:
            delivered = await future
        except asyncio.CancelledError:
            self._release_delivered(policy.project_id, waiter, future)
            raise
        except BaseException:
            self._discard(policy.project_id, waiter)
            raise
        if self._closed:
            delivered.finish()
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        if policy.deadline is not None and self._monotonic() >= policy.deadline:
            delivered.finish()
            raise ExecutionQueueExpired("the execution request deadline expired before dispatch")
        delivered._accepted = True
        return delivered

    def _register_waiter(
        self,
        policy: QueuePolicy,
        state: _ProjectState,
        waiter: _Waiter,
        now: float,
    ) -> None:
        """Publish one candidate's ownership before the caller awaits.

        The candidate either receives the actual grant in the same synchronous
        step that reserves concurrency, or transfers its admission reservation
        to a counted queue entry. A refusal leaves no ownership behind.
        """

        staged = self._stage_next(now, deferred=waiter)
        if staged is not None and staged.waiter is waiter:
            # The grant owns concurrency; its admission reservation leaves the
            # waiting ledger in the same step.
            if policy.admission_key is not None:
                self._budget.remove_entry(policy.admission_key, policy.project_id)
        else:
            refusal = self._budget.saturation(
                policy, pool_id=self.pool_id, exclude_key=policy.admission_key
            )
            if refusal is not None:
                raise ExecutionQueueSaturated(refusal[1])
            self._budget.transfer(
                admission_key=policy.admission_key,
                queue_key=("queue", self.pool_id, policy.project_id),
                project_id=policy.project_id,
                count=len(state.pending),
                byte_count=sum(max(0, item.policy.payload_bytes) for item in state.pending),
            )
        if policy.on_admitted is not None:
            policy.on_admitted()
        self._ensure_runner()
        self._event.set()

    def _wait_seconds(self, policy: QueuePolicy, now: float) -> float:
        wait_ms = (
            self._default_max_wait_ms
            if policy.max_queue_wait_ms is None
            else policy.max_queue_wait_ms
        )
        limits: list[float] = [max(0.0, wait_ms / 1000.0)]
        if policy.deadline is not None:
            limits.append(max(0.0, policy.deadline - now))
        return min(limits)

    def _project(self, project_id: UUID) -> _ProjectState:
        state = self._projects.get(project_id)
        if state is None:
            state = _ProjectState()
            self._projects[project_id] = state
        return state

    def _sync_all_budgets(self) -> None:
        """Republish every project's waiting view of this queue."""

        for project_id in list(self._projects):
            self._sync_budget(project_id)

    def _sync_budget(self, project_id: UUID, *, exclude: _Waiter | None = None) -> None:
        """Publish this project's genuinely waiting work.

        A pending entry counts until it receives an actual grant. A staged
        grant already owns concurrency and is never waiting work, so it has
        left the pending deque. ``exclude`` covers the one provisional
        admission candidate whose queue entry has not been published yet:
        its projected post-state is checked separately before transfer.
        """

        state = self._projects.get(project_id)
        waiting = [] if state is None else [item for item in state.pending if item is not exclude]
        count = len(waiting)
        byte_count = sum(max(0, item.policy.payload_bytes) for item in waiting)
        self._budget.set_waiting(
            ("queue", self.pool_id, project_id),
            project_id,
            count,
            byte_count,
        )

    def _best_effort_blocked(self, project_id: UUID, policy: QueuePolicy) -> bool:
        """Return whether a zero-share policy must defer to guaranteed demand.

        A guaranteed project with queued work is demand even while its own
        concurrency slot is occupied. Best-effort projects never block each
        other: only a project with a positive base entitlement counts.
        """

        if not policy.best_effort or policy.base_rate > 0:
            return False
        for other_id, other_state in self._projects.items():
            if other_id == project_id or not other_state.pending:
                continue
            other_policy = other_state.pending[0].policy
            if other_policy.base_rate > 0 and not other_policy.best_effort:
                return True
        return False

    # -------------------------------------------------------------- selection

    def _ensure_runner(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while not self._closed:
            self._event.clear()
            staged = self._staged
            if staged is None:
                if not self._has_pending():
                    return
                now = self._monotonic()
                self._expire_waiters(now)
                if not self._has_pending():
                    return
                staged = self._stage_next(now)
                if staged is None:
                    # A concurrency-blocked sibling must not starve an eligible
                    # project forever. After a bounded no-progress interval,
                    # let the eligible project use a partial quantum; the
                    # blocked project keeps its own bounded deficit for when it
                    # returns.
                    loop_now = asyncio.get_running_loop().time()
                    if self._no_progress_since is None:
                        self._no_progress_since = loop_now
                    elif loop_now - self._no_progress_since >= 0.05:
                        staged = self._stage_next(now, force_progress=True)
                        self._no_progress_since = None
                else:
                    self._no_progress_since = None
                if staged is None:
                    await self._wait_for_change(now)
                    continue
            if self._closed:
                return
            if staged.waiter.future.done():
                # The waiter was canceled between staging and delivery: the
                # reserved capacity must return exactly once.
                if self._staged is staged:
                    self._staged = None
                staged.dispatch.started.set()
                staged.dispatch.finish()
                continue
            # Deliver asynchronously on the scheduler's turn. Admission has
            # already reserved the actual grant; this step only hands it to
            # the waiting request and then preserves start order.
            staged.waiter.future.set_result(staged.dispatch)
            while not self._closed and not staged.dispatch.started.is_set():
                try:
                    await asyncio.wait_for(staged.dispatch.started.wait(), timeout=0.1)
                except TimeoutError:
                    # Housekeeping may run, but the staged owner remains the
                    # pool's start barrier until it starts or is released. A
                    # timeout never lets a successor bypass it.
                    self._expire_waiters(self._monotonic())
                    self._budget.refresh()
            if self._staged is staged:
                self._staged = None

    def _expire_waiters(self, now: float) -> None:
        """Expire queued work on the injected monotonic clock, before any send."""

        for project_id, state in self._projects.items():
            for waiter in list(state.pending):
                if waiter.expires_at is None or now < waiter.expires_at:
                    continue
                self._forget(state, waiter)
                if not waiter.future.done():
                    waiter.future.set_exception(
                        ExecutionQueueExpired(
                            "the execution queue wait bound expired before dispatch"
                        )
                    )
            if not state.pending:
                self._idle(project_id)

    def _forget(self, state: _ProjectState, waiter: _Waiter) -> bool:
        """Remove one still-pending waiter and its shared budget accounting."""

        try:
            state.pending.remove(waiter)
        except ValueError:
            return False
        self._sync_budget(waiter.policy.project_id)
        self._budget.refresh()
        return True

    async def _wait_for_change(self, now: float) -> None:
        timeout = self._next_window_timeout(now)
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except TimeoutError:
            return

    def _next_window_timeout(self, now: float) -> float:
        remaining: list[float] = []
        for state in self._projects.values():
            if not state.pending:
                continue
            for pending in state.pending:
                if pending.expires_at is not None:
                    remaining.append(max(0.01, min(0.05, pending.expires_at - now)))
                    break
            not_before = state.pending[0].policy.not_before
            if not_before is not None and not_before > now:
                remaining.append(max(0.02, min(0.05, not_before - now)))
        return min(remaining) if remaining else 0.25

    def _next_grant(
        self,
        now: float,
        *,
        force_progress: bool = False,
        publish_exclude: _Waiter | None = None,
    ) -> _Grant | None:
        """Pick one eligible project by unit-cost weighted deficit.

        Every eligible backlogged project receives its weight as a quantum
        when the previous round is exhausted. Each grant costs one unit, so a
        continuously eligible weight-4/weight-6 pair serves four A and six B
        grants per ten-dispatch round. Ineligible projects are skipped, not
        allowed to block a sibling: a concurrency-blocked project keeps a
        bounded (one-quantum) deficit and a returning project cannot bank idle
        service. Zero-share best-effort projects defer only to guaranteed
        demand, never to one another. Stable ring order is the tie-break.

        This method is the single synchronous ownership point: it removes the
        selected waiter, reserves every applicable concurrency counter, and
        builds the actual grant. Publication happens once the caller stages or
        delivers the grant, never between selection steps.
        """

        if not self._ring:
            return None
        backlogged, eligible = self._collect_eligible(now)
        if not eligible:
            return None
        self._seed_round(backlogged)
        project_id = self._next_rotation(eligible)
        if project_id is None and force_progress:
            for candidate in eligible:
                state = self._projects[candidate]
                if state.deficit < UNIT_COST:
                    # This is a liveness escape while a sibling still owns
                    # unspent credit, not a new weighted round. Permit one
                    # attempt without banking another full quantum.
                    state.deficit = UNIT_COST
            project_id = self._next_rotation(eligible)
        if project_id is None:
            return None
        state = self._projects[project_id]
        state.deficit -= UNIT_COST
        self._last_served = project_id
        waiter = state.pending.popleft()
        self._budget.grant(project_id)
        self._inflight[project_id] = self._inflight.get(project_id, 0) + 1
        self._inflight_pool += 1
        serving = project_id

        def finished(project_id: UUID = serving) -> None:
            self.complete(project_id)

        dispatch = DispatchGrant(
            base=eligible[project_id],
            queue_wait_ms=max(0, int((now - waiter.enqueued) * 1000)),
            on_finished=finished,
        )
        self._sync_budget(project_id, exclude=publish_exclude)
        if not state.pending:
            self._idle(project_id)
        return _Grant(waiter=waiter, base=eligible[project_id], dispatch=dispatch)

    def _stage_next(
        self,
        now: float,
        *,
        force_progress: bool = False,
        deferred: _Waiter | None = None,
    ) -> _Grant | None:
        """Reserve at most one unstarted grant for asynchronous delivery.

        A staged grant already owns the pool's next start turn. Nothing else
        in this pool may stage until that turn starts or its grant is
        released, which keeps the observed start order equal to the fair
        selection order. ``deferred`` is the provisional admission candidate:
        it is excluded from the published waiting view until its projected
        queue entry is accepted.
        """

        # Starting opens the ordering barrier, but the predecessor still owns
        # its concurrency until settlement. Admission can observe this before
        # the delivery runner resumes to retire that completed barrier.
        if self._staged is not None and self._staged.dispatch.started.is_set():
            self._staged = None
        if self._closed or self._staged is not None:
            return None
        grant = self._next_grant(
            now,
            force_progress=force_progress,
            publish_exclude=deferred,
        )
        if grant is None:
            return None
        self._staged = grant
        return grant

    def _collect_eligible(self, now: float) -> tuple[list[UUID], dict[UUID, bool]]:
        """Return backlogged and currently dispatchable projects in ring order."""

        backlogged: list[UUID] = []
        eligible: dict[UUID, bool] = {}
        for project_id in self._ring:
            state = self._projects.get(project_id)
            if state is None or not state.pending:
                continue
            policy = state.pending[0].policy
            if policy.not_before is not None and now < policy.not_before:
                continue
            base = self._base_grant(project_id, state, policy)
            if base is None or self._best_effort_blocked(project_id, policy):
                continue
            backlogged.append(project_id)
            if self._concurrency_available(project_id, policy, state=state):
                eligible[project_id] = base
        return backlogged, eligible

    def _seed_round(self, backlogged: list[UUID]) -> None:
        """Give new participants one quantum and open a round when spent."""

        # A project joining mid-round receives only its own quantum; existing
        # participants are never topped up until the round is exhausted.
        for project_id in backlogged:
            if project_id in self._round_participants:
                continue
            state = self._projects[project_id]
            weight = max(1, state.pending[0].policy.weight)
            # A returning project keeps its bounded remainder; it is topped up
            # only when that remainder is exhausted.
            if state.deficit < UNIT_COST:
                state.deficit = weight
            self._round_participants.add(project_id)
        if any(self._projects[project_id].deficit > 0 for project_id in backlogged):
            return
        for project_id in backlogged:
            state = self._projects[project_id]
            state.deficit = max(1, state.pending[0].policy.weight)
        self._round_participants = set(backlogged)
        self._last_served = None

    def _next_rotation(self, eligible: dict[UUID, bool]) -> UUID | None:
        """Return the next eligible project in stable ring rotation."""

        order = [project_id for project_id in self._ring if project_id in eligible]
        if not order:
            return None
        start_index = 0
        if self._last_served in order:
            start_index = order.index(self._last_served) + 1
        for offset in range(len(order)):
            project_id = order[(start_index + offset) % len(order)]
            if self._projects[project_id].deficit >= UNIT_COST:
                return project_id
        return None

    def _base_grant(
        self,
        project_id: UUID,
        state: _ProjectState | None,
        policy: QueuePolicy,
    ) -> bool | None:
        """Return whether this head is allowed by the policy, or ``None``.

        The durable strict reservation is the authoritative absolute ceiling
        for both strict and borrowing policies, on one stable bucket identity.
        The scheduler therefore keeps no second in-memory counter that could
        drift on an idle window or a restart; it only rejects a zero-share
        project that has no best-effort entitlement and defers explicit
        best-effort demand behind guaranteed work.
        """

        del project_id, state
        if not policy.borrow_enabled:
            return True
        if policy.max_rate is None and not policy.best_effort:
            return None
        if policy.base_rate <= 0 and not policy.best_effort:
            return None
        return not policy.best_effort

    def _concurrency_available(
        self,
        project_id: UUID,
        policy: QueuePolicy,
        *,
        state: _ProjectState | None,
    ) -> bool:
        del state
        if not self._budget.concurrency_available(project_id):
            return False
        cap = self._budget.project_caps.get(project_id)
        if cap is None:
            cap = (
                policy.project_max_concurrency
                if policy.project_max_concurrency is not None
                else policy.max_concurrency
            )
        if cap is not None and self._budget.project_inflight.get(project_id, 0) >= cap:
            return False
        if policy.pool_max_concurrency is not None and (
            self._inflight_pool >= policy.pool_max_concurrency
        ):
            return False
        return policy.max_concurrency is None or (
            self._inflight.get(project_id, 0) < policy.max_concurrency
        )

    def _idle(self, project_id: UUID) -> None:
        # Keep the bounded remainder of the current quantum: a project that
        # empties mid-round but returns shortly must not be granted a fresh
        # full quantum on top of the unfinished one. The value is already
        # capped at this project's weight, so idle credit never accumulates.
        # The project stays a member of the current round until that round is
        # exhausted. A momentary queue gap therefore cannot hand it a fresh
        # quantum while a sibling is still waiting for its own.
        if self._last_served == project_id and not self._has_pending():
            self._last_served = None
        self._drop_from_ring(project_id)

    def _drop_from_ring(self, project_id: UUID) -> None:
        try:
            index = self._ring.index(project_id)
        except ValueError:
            return
        self._ring.pop(index)

    # ------------------------------------------------------------- completion

    def complete(self, project_id: UUID) -> None:
        self._inflight[project_id] = max(0, self._inflight.get(project_id, 0) - 1)
        self._inflight_pool = max(0, self._inflight_pool - 1)
        self._budget.complete(project_id)
        self._sync_budget(project_id)
        self._budget.refresh()
        self._event.set()

    def _release_delivered(
        self,
        project_id: UUID,
        waiter: _Waiter,
        future: asyncio.Future[DispatchGrant],
    ) -> None:
        """Finish a grant delivered to a request canceled before acceptance."""

        if future.done() and not future.cancelled():
            grant: DispatchGrant | None
            try:
                grant = future.result()
            except BaseException:
                grant = None
            if grant is not None:
                staged = self._staged
                if staged is not None and staged.dispatch is grant:
                    self._staged = None
                grant.finish()
        self._discard(project_id, waiter)

    def _discard(self, project_id: UUID, waiter: _Waiter) -> None:
        staged = self._staged
        if staged is not None and staged.waiter is waiter:
            # The request was staged synchronously and never delivered, or it
            # was delivered and this is its cancellation cleanup. Its actual
            # grant returns exactly once.
            self._staged = None
            staged.dispatch.finish()
        state = self._projects.get(project_id)
        if state is not None and self._forget(state, waiter) and not state.pending:
            self._idle(project_id)
        if not waiter.future.done():
            waiter.future.cancel()
        self._budget.refresh()
        self._event.set()

    def _has_pending(self) -> bool:
        return any(state.pending for state in self._projects.values())

    def close(self) -> None:
        """Revoke queued and staged work; accepted attempts keep settling."""

        if self._closed:
            return
        self._closed = True
        self._event.set()
        for project_id, state in self._projects.items():
            while state.pending:
                waiter = state.pending.popleft()
                if not waiter.future.done():
                    waiter.future.set_exception(
                        ExecutionAuthorityUnavailable(
                            "the execution authority stopped before dispatch"
                        )
                    )
            self._sync_budget(project_id)
        staged = self._staged
        self._staged = None
        if staged is not None and not staged.dispatch._accepted:
            if not staged.waiter.future.done():
                staged.waiter.future.set_exception(
                    ExecutionAuthorityUnavailable("the execution authority stopped before dispatch")
                )
            staged.dispatch.started.set()
            staged.dispatch.finish()
        self._ring.clear()
        self._round_participants.clear()
        self._last_served = None
        self._budget.refresh()
        if self._runner is not None:
            self._runner.cancel()


class ExecutionAuthority:
    """The single fenced host of fair queues for one durable database."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        secret_store: object | None = None,
        authority_key: str = AUTHORITY_KEY,
        monotonic_fn: Callable[[], float] | None = None,
        limits: object | None = None,
        holder_id: str | None = None,
        default_max_wait_ms: int = DEFAULT_MAX_QUEUE_WAIT_MS,
        default_max_requests: int = DEFAULT_MAX_QUEUED_REQUESTS,
        default_max_bytes: int = DEFAULT_MAX_QUEUED_BYTES,
        default_max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        default_project_max_concurrency: int = DEFAULT_PROJECT_MAX_CONCURRENCY,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # The authority owns scheduling and the fence; credential resolution
        # and provider I/O stay with the execution service that composes it.
        # The limits service is retained only to retain an uncertain native
        # debit once during takeover recovery.
        del secret_store
        self._limits = limits
        self._repository = repository
        self._authority_key = authority_key
        self._holder_id = holder_id or f"authority-{uuid4().hex}"
        self._default_max_wait_ms = max(0, default_max_wait_ms)
        self._default_max_requests = max(0, default_max_requests)
        self._default_max_bytes = max(0, default_max_bytes)
        self._budget = _QueueBudget(
            default_max_requests=self._default_max_requests,
            default_max_bytes=self._default_max_bytes,
            max_concurrency=default_max_concurrency,
            project_max_concurrency=default_project_max_concurrency,
        )
        self._lease_seconds = max(1.0, lease_seconds)
        self._recovery_seconds = max(0.0, recovery_seconds)
        self._monotonic = monotonic_fn or monotonic
        self._clock = clock or (lambda: datetime.now(UTC))
        self._queues: dict[tuple[UUID, CredentialOperation], _PoolQueue] = {}
        self._pool_queues: dict[UUID, _PoolQueue] = {}
        self._fences: dict[UUID, tuple[int, float]] = {}
        self._recovering_until: dict[UUID, datetime] = {}
        self._lease_lock = asyncio.Lock()
        self._renewal: asyncio.Task[None] | None = None
        self._resolutions: set[asyncio.Task[None]] = set()
        self._closed = False

    # ------------------------------------------------------------------ lease

    @property
    def max_queued_requests(self) -> int:
        """The authority-wide queued-request bound used for admission waiters."""

        return self._budget.default_max_requests

    @property
    def default_max_wait_seconds(self) -> float:
        """The authority-wide admission wait bound in seconds."""

        return self._default_max_wait_ms / 1000.0

    def reserve_admission(self, *, project_id: UUID, payload_bytes: int) -> AdmissionReservation:
        """Count one admission waiter in the common queue budget.

        The reservation is released exactly once: on cancellation, on a failed
        resolution, or when the request's first queue entry is appended (the
        transfer keeps one ownership, never a second accounting owner).
        """

        if self._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        self._budget.refresh()
        refusal = self._budget.admission_saturation(
            project_id=project_id, payload_bytes=payload_bytes
        )
        if refusal is not None:
            raise ExecutionQueueSaturated(refusal)
        key = ("admission", project_id, uuid4())
        self._budget.set_waiting(key, project_id, 1, max(0, payload_bytes))
        return AdmissionReservation(self._budget, key, project_id)

    def update_project_cap(self, project_id: UUID, cap: int | None) -> None:
        """Apply a freshly derived project concurrency cap to the live queue."""

        self._budget.set_project_cap(project_id, cap)
        self._budget.refresh()

    def authority_key_for(self, pool_id: UUID) -> str:
        """Return the durable pool fence identity of one shared pool.

        A caller may pass the already-pool-scoped key the fixture convention
        uses; it is then used as-is. A bare base key is scoped per pool.
        """

        suffix = f":{pool_id}"
        if self._authority_key.endswith(suffix):
            return self._authority_key
        return f"{self._authority_key}{suffix}"

    @property
    def holder_id(self) -> str:
        return self._holder_id

    def lease_token(self, pool_id: UUID) -> int | None:
        held = self._fences.get(pool_id)
        return None if held is None else held[0]

    def now(self) -> float:
        """Return the authority's local monotonic clock."""

        return self._monotonic()

    async def ensure_borrowed(self, pool_id: UUID) -> None:
        """Take or confirm this pool's durable fence.

        A recovering incarnation keeps its acquired token and persisted
        recovery deadline. Repeated requests never reset the lease to ACTIVE
        early: they fail closed until the bounded pause has elapsed, then the
        same incarnation renews into ACTIVE and may dispatch.
        """

        if self._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        async with self._lease_lock:
            held = self._fences.get(pool_id)
            if held is not None and self._monotonic() < held[1]:
                recovery_until = self._recovering_until.get(pool_id)
                if recovery_until is not None:
                    if self._clock() < recovery_until:
                        raise ExecutionAuthorityUnavailable(
                            "the execution authority is recovering an earlier incarnation"
                        )
                    renewed = await self._renew_one(pool_id, held)
                    if renewed is None:
                        self._fences.pop(pool_id, None)
                        raise ExecutionAuthorityUnavailable(
                            "another execution authority holds the dispatch lease"
                        )
                    self._fences[pool_id] = (
                        renewed.fencing_token,
                        self._monotonic() + self._lease_seconds,
                    )
                    if renewed.state is AuthorityState.RECOVERING:
                        self._recovering_until[pool_id] = renewed.recovery_until or self._clock()
                        raise ExecutionAuthorityUnavailable(
                            "the execution authority is recovering an earlier incarnation"
                        )
                    self._recovering_until.pop(pool_id, None)
                return
            lease = await self._acquire(pool_id)
            self._fences[pool_id] = (
                lease.fencing_token,
                self._monotonic() + self._lease_seconds,
            )
            if lease.state is not AuthorityState.ACTIVE:
                assert lease.recovery_until is not None
                self._recovering_until[pool_id] = lease.recovery_until
                self._start_renewal()
                raise ExecutionAuthorityUnavailable(
                    "the execution authority is recovering an earlier incarnation"
                )
            self._recovering_until.pop(pool_id, None)
            self._start_renewal()

    async def _acquire(self, pool_id: UUID) -> Any:
        now = self._clock()
        key = self.authority_key_for(pool_id)
        try:
            async with self._repository.session() as session:
                repository = ExecutionAuthorityRepository(session)
                await repository._ensure_row(authority_key=self._authority_key)
                lease = await repository.acquire(
                    authority_key=key,
                    holder_id=self._holder_id,
                    now=now,
                    ttl=timedelta(seconds=self._lease_seconds),
                    recovery=timedelta(seconds=self._recovery_seconds),
                    pool_id=pool_id,
                )
                if lease is None:
                    raise ExecutionAuthorityUnavailable(
                        "another execution authority holds the dispatch lease"
                    )
                await session.commit()
        except ExecutionAuthorityUnavailable:
            raise
        except Exception as error:
            raise ExecutionAuthorityUnavailable(
                "the execution authority lease store is unavailable"
            ) from error
        await self._retain_uncertain_debits(lease.uncertain_attempt_ids)
        return lease

    async def _retain_uncertain_debits(self, attempt_ids: tuple[str, ...]) -> None:
        """Retain one native debit for each dispatch fenced into uncertainty.

        The closed incarnation may have reached the vendor, so its reserved
        funds are never refunded. The admission's own state makes this
        idempotent: an already finalized or released attempt is skipped.
        """

        for attempt_id in attempt_ids:
            try:
                admission = await self._repository.limits.get_admission(attempt_id)
            except Exception:
                logger.warning("execution recovery could not read an uncertain admission")
                continue
            if admission is None or admission.state != "reserved":
                continue
            try:
                await self._repository.limits.finalize(
                    LimitDebit(
                        attempt_id=admission.attempt_id,
                        provider=admission.provider,
                        operation=admission.operation,
                        auth_mode=admission.auth_mode,
                        pool_id=admission.pool_id,
                        outcome="failure",
                        native_units=admission.reserved_native,
                        successful_urls=0,
                        crd_debit=admission.reserved_crd,
                        reason="local_uncertain",
                        audit_source="local",
                    )
                )
            except Exception:
                logger.warning("execution recovery could not retain an uncertain debit")

    def _start_renewal(self) -> None:
        if self._renewal is not None and not self._renewal.done():
            return
        self._renewal = asyncio.get_running_loop().create_task(self._renew())

    async def _renew(self) -> None:
        interval = max(0.5, self._lease_seconds / 3)
        try:
            while not self._closed:
                await asyncio.sleep(interval)
                async with self._lease_lock:
                    for pool_id, held in list(self._fences.items()):
                        renewed = await self._renew_one(pool_id, held)
                        if renewed is None:
                            self._fences.pop(pool_id, None)
                            self._recovering_until.pop(pool_id, None)
                            continue
                        self._fences[pool_id] = (
                            renewed.fencing_token,
                            self._monotonic() + self._lease_seconds,
                        )
                        if renewed.state is AuthorityState.RECOVERING:
                            self._recovering_until[pool_id] = (
                                renewed.recovery_until or self._clock()
                            )
                        else:
                            self._recovering_until.pop(pool_id, None)
        except asyncio.CancelledError:
            raise

    async def _renew_one(self, pool_id: UUID, held: tuple[int, float]) -> Any | None:
        now = self._clock()
        try:
            async with self._repository.session() as session:
                lease = await ExecutionAuthorityRepository(session).renew(
                    authority_key=self.authority_key_for(pool_id),
                    holder_id=self._holder_id,
                    fencing_token=held[0],
                    now=now,
                    ttl=timedelta(seconds=self._lease_seconds),
                )
                await session.commit()
        except Exception:
            return None
        return lease

    async def record_dispatch(
        self,
        *,
        attempt_id: str,
        request_id: str,
        project_id: UUID,
        pool_id: UUID,
        operation: CredentialOperation,
        actor_type: ActorType,
        actor_id: UUID,
        credential_id: UUID | None = None,
        binding_id: UUID | None = None,
    ) -> None:
        """Write the recovery record of one attempt under the pool's live fence."""

        await self.ensure_borrowed(pool_id)
        held = self._fences.get(pool_id)
        if held is None:
            raise ExecutionAuthorityUnavailable("the execution authority holds no live lease")
        try:
            async with self._repository.session() as session:
                recorded = await ExecutionAuthorityRepository(session).record_dispatch(
                    authority_key=self.authority_key_for(pool_id),
                    ledger_key=self._authority_key,
                    fencing_token=held[0],
                    attempt_id=attempt_id,
                    request_id=request_id,
                    project_id=project_id,
                    pool_id=pool_id,
                    operation=operation,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    credential_id=credential_id,
                    binding_id=binding_id,
                    now=self._clock(),
                )
                await session.commit()
        except ExecutionAuthorityUnavailable:
            raise
        except Exception as error:
            raise ExecutionAuthorityUnavailable(
                "the execution authority dispatch record could not be written"
            ) from error
        if not recorded:
            self._fences.pop(pool_id, None)
            raise ExecutionAuthorityUnavailable("the execution authority lease was fenced")

    async def resolve_dispatch(self, *, project_id: UUID, attempt_id: str, outcome: str) -> None:
        """Resolve one dispatch record off the request's critical path."""

        try:
            task = asyncio.get_running_loop().create_task(
                self._resolve_dispatch_now(
                    project_id=project_id, attempt_id=attempt_id, outcome=outcome
                )
            )
        except RuntimeError:
            return
        self._resolutions.add(task)
        task.add_done_callback(self._resolutions.discard)

    async def _resolve_dispatch_now(
        self, *, project_id: UUID, attempt_id: str, outcome: str
    ) -> None:
        state = (
            DispatchState.COMPLETED
            if outcome == "completed"
            else DispatchState.FAILED
            if outcome == "failed"
            else DispatchState.UNCERTAIN
        )
        try:
            async with self._repository.session() as session:
                await ExecutionAuthorityRepository(session).resolve_dispatch(
                    project_id=project_id,
                    attempt_id=attempt_id,
                    state=state,
                    now=self._clock(),
                )
                await session.commit()
        except Exception:
            logger.warning("execution dispatch resolution could not be persisted")

    # -------------------------------------------------------------- scheduling

    def submit(
        self,
        *,
        pool_id: UUID,
        operation: CredentialOperation,
        policy: QueuePolicy,
        attempt: Callable[[DispatchGrant], Awaitable[ResponseT]],
    ) -> Awaitable[ResponseT]:
        """Queue one attempt on the pool's fair scheduler."""

        if self._closed:
            raise ExecutionAuthorityUnavailable("the execution authority is stopped")
        queue = self._pool_queues.get(pool_id)
        if queue is None:
            queue = _PoolQueue(
                pool_id=pool_id,
                operation=operation,
                monotonic=self._monotonic,
                default_max_wait_ms=self._default_max_wait_ms,
                default_max_requests=self._default_max_requests,
                default_max_bytes=self._default_max_bytes,
                budget=self._budget,
            )
            self._pool_queues[pool_id] = queue
        # One scheduler per shared pool. Both operation keys are aliases of
        # that queue so search and fetch share one fairness order and one
        # concurrency view instead of racing in independent queues.
        for candidate in CredentialOperation:
            self._queues[(pool_id, candidate)] = queue
        return queue.submit(policy, attempt)

    async def dispatch(
        self,
        *,
        pool_id: UUID,
        operation: CredentialOperation,
        policy: QueuePolicy,
        attempt: Callable[[DispatchGrant], Awaitable[ResponseT]],
    ) -> ResponseT:
        """Run one attempt after a fair grant under the pool's live fence."""

        await self.ensure_borrowed(pool_id)
        return await self.submit(
            pool_id=pool_id,
            operation=operation,
            policy=policy,
            attempt=attempt,
        )

    async def aclose(self) -> None:
        """Stop queues and vacate every leased pool fence."""

        if self._closed:
            return
        self._closed = True
        runners: list[asyncio.Task[None]] = []
        for queue in self._pool_queues.values():
            queue.close()
            if queue._runner is not None:
                runners.append(queue._runner)
        if runners:
            await asyncio.gather(*runners, return_exceptions=True)
        self._queues.clear()
        self._pool_queues.clear()
        resolutions = list(self._resolutions)
        self._resolutions.clear()
        if resolutions:
            await asyncio.gather(*resolutions, return_exceptions=True)
        renewal, self._renewal = self._renewal, None
        if renewal is not None:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
        for pool_id, (token, _expires) in list(self._fences.items()):
            with suppress(Exception):
                async with self._repository.session() as session:
                    await ExecutionAuthorityRepository(session).release(
                        authority_key=self.authority_key_for(pool_id),
                        holder_id=self._holder_id,
                        fencing_token=token,
                        now=self._clock(),
                    )
                    await session.commit()
        self._fences.clear()
        self._recovering_until.clear()


__all__ = [
    "AUTHORITY_KEY",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_QUEUED_BYTES",
    "DEFAULT_MAX_QUEUED_REQUESTS",
    "DEFAULT_MAX_QUEUE_WAIT_MS",
    "DEFAULT_RECOVERY_SECONDS",
    "UNIT_COST",
    "AuthorityUnavailable",
    "DispatchGrant",
    "ExecutionAuthority",
    "QueueExpired",
    "QueuePolicy",
    "QueueSaturated",
]

#: Tester- and transport-facing names of the A3 refusals.
AuthorityUnavailable = ExecutionAuthorityUnavailable
QueueSaturated = ExecutionQueueSaturated
QueueExpired = ExecutionQueueExpired
