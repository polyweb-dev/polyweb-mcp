"""A3 authority fixtures: the API-hosted fenced execution authority (TASK-000045).

The durable substrate this suite drives is already settled and is never
monkeypatched away: the fenced authority persistence in
``polyweb.persistence.execution_authority`` (lease, fencing tokens, dispatch
rows, uncertain recovery), the queue/wait/concurrency bounds and loan fields on
``project_pool_allocations`` and ``upstream_quota_pools`` (D1 schema), and the
strict admission store in ``polyweb.persistence.limit_repository``.

SEAM CONTRACT (as landed; the tests assert this public shape)
========================================================================
1. Module ``polyweb.services.execution_authority`` exposes
   ``ExecutionAuthority`` -- the single API-hosted execution authority --
   composed into execution via ``ExecutionService(..., authority=...)`` (or
   hosted by default), so REST submits directly and MCP forwards to the same
   authoritative dispatch (one fence, one fair scheduler, one queue set per
   shared pool). Its constructor accepts ``authority_key``, ``monotonic_fn``,
   ``holder_id``, ``lease_seconds``, ``recovery_seconds``, and default queue
   bounds.

2. Module ``polyweb.models.execution_failures`` (re-exported through the
   authority module) carries the refusal taxonomy asserted here:

   * ``ExecutionAuthorityUnavailable`` -- typed, ``retriable=True`` refusal
     raised *before any provider dispatch* when the authority fence cannot be
     taken or kept (another live holder, recovery pause, capacity store
     outage). Its absence must never degrade into a direct provider bypass.
   * ``ExecutionQueueSaturated`` -- typed queue-bound refusal (count or
     payload bytes), ``retriable=False``, distinct from rate and funds
     denials.
   * ``ExecutionQueueExpired`` -- typed retriable refusal when the bounded
     queue wait (``max_queue_wait_ms``), the request deadline, or an
     authority shutdown passed before dispatch.

3. Queue telemetry: one successful queued dispatch records ``queue_wait_ms``
   into the usage event's ``metadata_json`` (via
   ``polyweb.services.monitoring.add_queue_wait``) -- the observed wait
   before dispatch, reported separately from the provider ``latency_ms``.

4. Scheduler contract (covered behaviorally below, never by internals):
   bounded weighted Deficit Round Robin over per-project queues with one cost
   unit per actual provider attempt, bounded idle deficits, stable tie-break,
   infeasible base guarantees refused, best-effort zero-share deferred while
   guaranteed work is outstanding, and provider ``Retry-After`` honored.

Local queue waits, deadlines, retry delays, and recovery pauses read the
injected virtual monotonic seconds (``MonotonicControl``); durable timestamps
use the repository's live clock. Fake providers and temporary databases only;
every "no provider call" assertion reads fake adapter counters and durable
rows, never a stubbed safety path.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from tests.fixtures.a2_execution import RecordingAdapter, SeededCredential, provider_error
from tests.fixtures.api_keys import ProjectKey, key_for_account
from tests.fixtures.execution import seed_execution_project

from polyweb.adapters.base import ProviderAdapter
from polyweb.configuration.provider_limits import provider_limit_defaults
from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models.contracts import (
    ProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ExecutionAttribution
from polyweb.models.projects import (
    API_KEY_SCOPES,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
)
from polyweb.models.provider_limits import (
    ProviderLimitRecord,
    RateScope,
    RateWindow,
    RateWindowName,
)
from polyweb.models.schema_enums import UpstreamScope
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.execution_authority import (
    ExecutionDispatchRow,
)
from polyweb.persistence.limit_rows import RateAttemptRow
from polyweb.persistence.pools import (
    PoolAllocationRepository,
    StoredAllocation,
    StoredPool,
    UpstreamPoolRepository,
)
from polyweb.persistence.storage import SQLiteRepository, UsageEventRow
from polyweb.services.credentials import credential_secret_slot
from polyweb.services.execution import ExecutionService
from polyweb.services.execution_authority import AUTHORITY_KEY as REAL_AUTHORITY_KEY
from polyweb.services.execution_scope import resolve_execution_boundary
from polyweb.services.monitoring import clear_quota_poll_cache
from polyweb.services.provider_limits import ProviderLimitsService
from polyweb.services.provider_runtime import clear_config_cache

#: The single provider this suite binds. One provider keeps every queue, pool,
#: and bucket assertion unambiguous.
PROVIDER = "exa"

#: The durable fence identity follows the implementation's authority key
#: constant so two compositions cannot drift into separate fence namespaces.
AUTHORITY_KEY: str = REAL_AUTHORITY_KEY


async def seed_credential(
    repository: SQLiteRepository,
    store: EncryptedDbSecretStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    label: str,
    secret: str,
    priority: int = 0,
) -> SeededCredential:
    """Seed one project-private credential, binding, and encryption slot."""

    async with repository.session() as session:
        credentials = CredentialRepository(session)
        credential = await credentials.insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type=PROVIDER,
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=project_id,
            label=label,
            auth_mode="api_key",
            created_by=actor_id,
        )
        bindings = ProjectBindingRepository(session)
        binding = await bindings.create(
            project_id=project_id,
            credential_id=credential.id,
            credential_scope=CredentialOwnerScope.PROJECT,
            route_label=label,
            created_by=actor_id,
            priority=priority,
        )
        enabled = await bindings.set_enabled_operations(
            project_id=project_id,
            binding_id=binding.id,
            operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
            expected_version=binding.version,
        )
        assert enabled is not None
        await store.create_slot_in_session(
            session,
            credential_secret_slot(credential.id, credential.generation),
            secret,
        )
        await session.commit()
    return SeededCredential(
        label=label,
        credential_id=credential.id,
        binding_id=binding.id,
        secret=secret,
        generation=credential.generation,
    )


class MonotonicControl:
    """Injectable queue clock: monotonic seconds fully controlled by the test.

    The authority must read every queue wait, queue deadline, retry delay, and
    local pause from this injected clock, so tests move a full minute of
    virtual time in one call instead of sleeping a real minute.
    """

    def __init__(self) -> None:
        self.seconds = 0.0

    def monotonic_fn(self) -> float:
        """Return the virtual monotonic seconds (the injectable queue clock)."""
        return self.seconds

    def advance(self, seconds: float) -> None:
        """Move virtual time forward; only forward movement is allowed."""
        self.seconds += max(0.0, seconds)

    def set(self, seconds: float) -> None:
        """Jump virtual time to an absolute value (forward or backward)."""
        self.seconds = seconds


@dataclass(frozen=True)
class AllocationSpec:
    """One project's allocation of the seeded pool.

    ``borrow_max=None`` keeps loans disabled with the same strict-cap meaning
    the A1 schema settles: ``max_rate`` is ``NULL`` and the base rate is also
    the effective ceiling. ``borrow_max=N`` turns borrowing on with
    ``max_rate=N``. A zero ``base_rate`` must be requested together with
    ``best_effort=True`` (the schema refuses anything else).
    """

    label: str
    base_rate: int
    weight: int = 1
    borrow_max: int | None = None
    best_effort: bool = False
    max_concurrency: int | None = None
    max_queued_requests: int | None = None
    max_queued_bytes: int | None = None
    max_queue_wait_ms: int | None = None

    @property
    def borrow_enabled(self) -> bool:
        """Whether this allocation lends idle capacity (opt-in loans)."""
        return self.borrow_max is not None


@dataclass(frozen=True)
class AuthorityPoolSpec:
    """Declaration of one shared upstream pool plus its project allocations."""

    limit: int = 1000
    window_seconds: int = 3600
    max_concurrency: int | None = None
    max_queued_requests: int | None = None
    allocations: tuple[AllocationSpec, ...] = ()

    @property
    def constraints(self) -> list[dict[str, Any]]:
        """The declared trailing-window rate envelope of this pool."""
        return [
            {
                "kind": "rate",
                "algorithm": "trailing_window",
                "window": self.window_seconds,
                "limit": self.limit,
            }
        ]

    @property
    def operation(self) -> CredentialOperation:
        """The single operation every allocation in this spec grants."""
        return CredentialOperation.SEARCH


@dataclass
class AuthorityProject:
    """One seeded project: human execution context plus its fake provider."""

    label: str
    attribution: ExecutionAttribution
    context: ProjectContext
    credential: SeededCredential
    adapter: RecordingAdapter

    @property
    def project_id(self) -> UUID:
        """The durable project id this stub's requests always carry."""
        return self.attribution.project_id


@dataclass(frozen=True)
class DispatchStart:
    """One recorded dispatch start, in its observed order."""

    label: str
    tag: str
    monotonic: float


@dataclass
class ParkedRequest:
    """One in-flight provider send parked until the test releases it."""

    label: str
    tag: str
    released: asyncio.Event = field(default_factory=asyncio.Event)


def provider_error_for(
    *,
    code: str = "rate_limited",
    status: int = 429,
    retryable: bool = True,
    details: dict[str, Any] | None = None,
) -> ProviderOperationError:
    """Build a provider error the exercised fake raises through execution."""

    return ProviderOperationError(
        ProviderError(
            provider=PROVIDER,
            code=code,
            message="vendor throttle",
            retryable=retryable,
            status_code=status,
            details=details or {},
        )
    )


def _search_success(adapter: RecordingAdapter, request: SearchRequest) -> SearchResponse:
    """Build the default success response a parked fake adapter returns."""
    del adapter
    return SearchResponse(
        query=request.query,
        provider=PROVIDER,
        results=[SearchResult(title="fake", url="https://example.com/fake")],
        total_results=1,
        usage=UsageEvent(
            provider=PROVIDER,
            operation=UsageOperation.SEARCH,
            units=Decimal("0"),
            observed_at=datetime.now(UTC),
        ),
    )


@dataclass
class AuthorityWorld:
    """One seed database, its real execution service, and the test controls."""

    repository: SQLiteRepository
    store: EncryptedDbSecretStore
    monotonic: MonotonicControl
    pool: StoredPool
    spec: AuthorityPoolSpec
    authority: Any  # polyweb.services.execution_authority.ExecutionAuthority
    service: ExecutionService
    projects: dict[str, AuthorityProject] = field(default_factory=dict)
    allocations: dict[str, StoredAllocation] = field(default_factory=dict)
    starts: list[DispatchStart] = field(default_factory=list)
    parks: list[ParkedRequest] = field(default_factory=list)
    park_timeout: float = 10.0

    def project_of(self, project_id: UUID | None) -> AuthorityProject:
        """Return the seeded project a request belongs to."""
        for project in self.projects.values():
            if project.project_id == project_id:
                return project
        raise AssertionError(f"no seeded project owns {project_id!r}")

    def park(self, park: bool = True) -> None:
        """Switch every adapter between parking and instant handling.

        ``park(True)`` (the default) holds each provider send until the test
        releases it, so queue state and scheduler order stay deterministic.
        Tests that issue single sequential calls and need the response back
        switch to ``park(False)`` so no coordination is required.
        """

        handler: Any = parked_search_handler(self) if park else None
        for project in self.projects.values():
            project.adapter.search_handler = handler

    def request(self, label: str, *, tag: str | None = None, **overrides: Any) -> SearchRequest:
        """Build one search request for ``label``; the tag rides the query."""
        project = self.projects[label]
        payload: dict[str, Any] = {
            "query": f"{project.label}::{tag or uuid4().hex[:8]}",
            "project_id": project.project_id,
        }
        payload.update(overrides)
        return SearchRequest(**payload)

    def submit(self, label: str, *tags: str, **request_overrides: Any) -> list[asyncio.Task[Any]]:
        """Start one search per tag (one auto-generated tag, when not given)."""
        project = self.projects[label]
        tags = tags or (None,)  # type: ignore[assignment]
        tasks: list[asyncio.Task[Any]] = []
        for tag in tags:
            tasks.append(
                asyncio.create_task(
                    self.service.search(
                        self.request(label, tag=tag, **request_overrides),
                        attribution=project.attribution,
                        context=project.context,
                    )
                )
            )
        return tasks

    def release(self, *, count: int | None = None) -> None:
        """Release the oldest parked provider sends (all when count is None)."""
        parked = [parked for parked in self.parks if not parked.released.is_set()]
        chosen = parked if count is None else parked[:count]
        for parked in chosen:
            parked.released.set()

    def parked_for(self, label: str) -> list[ParkedRequest]:
        """Return the not-yet-released parks of one project."""
        return [
            parked
            for parked in self.parks
            if parked.label == label and not parked.released.is_set()
        ]

    def starts_of(self, label: str) -> list[DispatchStart]:
        """Return the recorded dispatch starts of one project in order."""
        return [start for start in self.starts if start.label == label]

    async def wait_starts(self, count: int, *, timeout: float = 10.0) -> None:
        """Wait until ``count`` dispatches started; never block without bound."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while len(self.starts) < count:
            if loop.time() > deadline:
                raise AssertionError(
                    f"expected {count} dispatch starts; observed {len(self.starts)} "
                    f"(starts={[(start.label, start.tag) for start in self.starts]})"
                )
            await asyncio.sleep(0.001)

    async def wait_admitted(self, label: str, *, timeout: float = 5.0) -> None:
        """Wait until every submitted request of ``label`` passed the admission gate.

        The execution service serializes one project's admissions behind a
        per-project gate lock and releases it the instant the request's queue
        entry is appended (or a bound refusal fired). Taking the lock — behind
        a bounded timeout, never a sleep — is the explicit enqueue
        synchronization queue tests need before they advance the virtual
        clock or mutate durable permissions.
        """

        project = self.projects[label]
        lock = self.service._admission_locks.get(project.project_id)  # sync-only access
        if lock is None:
            return
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except TimeoutError as error:
            raise AssertionError(f"admissions of {label!r} never settled") from error
        lock.release()

    def retry_not_before(self, label: str) -> float | None:
        """Return the pending retry's ``not_before`` (scheduler-state sync peek).

        Tests must synchronize on "the requeue was enqueued" before they
        advance the virtual clock to its due time. The scheduler reads that
        fact from one narrow, already-private queue cell (the project's first
        pending policy); this helper makes that synchronization use visible,
        bounded, and read-only. ``None`` means no pending retry is queued.
        """

        queue = self.authority._queues.get((self.pool.id, self.spec.operation))
        if queue is None:
            return None
        state = queue._projects.get(self.projects[label].project_id)
        if state is None or not state.pending:
            return None
        return state.pending[0].policy.not_before

    def queued_waiters(self, label: str, *, pool_id: UUID | None = None) -> int:
        """Count this project's pending waiters on one pool queue (sync peek).

        Same narrow, read-only scheduler-state access as
        :meth:`retry_not_before`, used only to synchronize admission order:
        a waiter exists here from ``_enqueue`` until it is dequeued for a
        grant, denies, expires, or is discarded, so "this project has ``n``
        queued waiters" is exactly the enqueue fact bounded tests must anchor
        on before advancing the virtual clock or mutating permissions.
        """

        pool = pool_id if pool_id is not None else self.pool.id
        queue = self.authority._queues.get((pool, self.spec.operation))
        if queue is None:
            return 0
        state = queue._projects.get(self.projects[label].project_id)
        return 0 if state is None else len(state.pending)

    async def wait_queued(
        self,
        label: str,
        count: int,
        *,
        timeout: float = 5.0,
        pool_id: UUID | None = None,
    ) -> None:
        """Wait until ``count`` waiters of ``label`` sit in the pool queue.

        The bounded-but-never-blind anchor for "this submit became queued"
        (or was already dispatched past the queue) before the test advances
        the virtual clock, drains parks, or mutates durable permissions.
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.queued_waiters(label, pool_id=pool_id) < count:
            if loop.time() > deadline:
                raise AssertionError(
                    f"expected {count} queued waiters for {label!r}, saw "
                    f"{self.queued_waiters(label, pool_id=pool_id)}"
                )
            await asyncio.sleep(0.001)

    async def key_context(self, label: str) -> tuple[ProjectKey, ProjectContext]:
        """Issue a real project API key and resolve its live execution context."""
        project = self.projects[label]
        key: ProjectKey = await key_for_account(
            self.repository, project.attribution.actor_id, project.project_id
        )
        principal = ProjectApiKeyPrincipal(
            api_key_id=key.api_key_id,
            project_id=key.project_id,
            scopes=frozenset(API_KEY_SCOPES),
        )
        context = (
            await resolve_execution_boundary(
                self.repository,
                principal,
                project_id=key.project_id,
                action=PermissionAction.SEARCH_EXECUTE,
            )
        ).context
        return key, context

    async def gather(self, tasks: list[asyncio.Task[Any]]) -> tuple[list[Any], list[BaseException]]:
        """Await every submitted task; split results from refusal exceptions."""
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        ok = [item for item in outcomes if not isinstance(item, BaseException)]
        failures = [item for item in outcomes if isinstance(item, BaseException)]
        return ok, failures

    async def pool_attempts(self) -> list[RateAttemptRow]:
        """Return the durable rate attempts charged against the pool buckets."""
        return await attempt_rows(self, prefix=f"pool:{self.pool.id}:")

    async def project_attempts(self, label: str) -> list[RateAttemptRow]:
        """Return the durable rate attempts charged against one project bucket."""
        project = self.projects[label]
        prefix = f"project:{project.project_id}:{self.pool.id}:"
        return await attempt_rows(self, prefix=prefix)

    async def dispatch_rows(self, *, project_id: UUID | None = None) -> list[ExecutionDispatchRow]:
        """Return the durable authority dispatch records of this database."""
        return await stored_dispatch_rows(self, project_id=project_id)

    async def usage_rows(self, *, project_id: UUID | None = None) -> list[UsageEventRow]:
        """Return the durable usage events (aggregated rows excluded)."""
        return await usage_event_rows(self, project_id=project_id)

    async def aclose(self) -> None:
        with suppress(Exception):
            await self.service.aclose()
        with suppress(Exception):
            await self.repository.close()
        clear_config_cache()
        clear_quota_poll_cache()

    @property
    def authority_key(self) -> str:
        """The durable fence identity of this world's pool (leasing convention)."""
        return f"{AUTHORITY_KEY}:{self.pool.id}"


def parked_search_handler(
    world: AuthorityWorld,
) -> Callable[[RecordingAdapter, SearchRequest], Awaitable[SearchResponse]]:
    """Dispatch-start recorder that parks every provider send until released.

    The handler appends one :class:`DispatchStart` the moment execution calls
    the provider (the dispatch decision was made) and parks the send until the
    test releases it. This keeps scheduler order observable without real
    sleeps and holds concurrency slots open deterministically. A handler that
    fails instead of parking is built through :func:`install_first_failures` on
    top of this default.
    """

    async def handler(adapter: RecordingAdapter, request: SearchRequest) -> SearchResponse:
        project = world.project_of(request.project_id)
        tag = request.query.split("::", 1)[-1]
        world.starts.append(
            DispatchStart(
                label=project.label,
                tag=tag,
                monotonic=world.monotonic.monotonic_fn(),
            )
        )
        parked = ParkedRequest(label=project.label, tag=tag)
        world.parks.append(parked)
        await asyncio.wait_for(parked.released.wait(), timeout=world.park_timeout)
        return _search_success(adapter, request)

    return handler


def install_first_failures(
    world: AuthorityWorld,
    label: str,
    *,
    error: ProviderOperationError,
    fail_times: int = 1,
    park_on_success: bool = True,
) -> Callable[[], None]:
    """Make one project's fake adapter fail its first ``fail_times`` starts.

    The real :class:`RecordingAdapter` counts every ``search`` call before the
    handler runs, so failing starts stay visible in ``adapter.search_calls``
    and (via the requeue contract) must each carry their own durable attempt.
    Returns a reset callable restoring the recorded parked behavior.
    """

    project = world.projects[label]
    original = project.adapter.search_handler

    async def failing_handler(adapter: RecordingAdapter, request: SearchRequest) -> SearchResponse:
        project = world.project_of(request.project_id)
        tag = request.query.split("::", 1)[-1]
        world.starts.append(
            DispatchStart(
                label=project.label,
                tag=tag,
                monotonic=world.monotonic.monotonic_fn(),
            )
        )
        if adapter.search_calls <= fail_times:
            raise error
        if park_on_success:
            parked = ParkedRequest(label=project.label, tag=tag)
            world.parks.append(parked)
            await asyncio.wait_for(parked.released.wait(), timeout=world.park_timeout)
        return _search_success(adapter, request)

    project.adapter.search_handler = failing_handler

    def reset() -> None:
        project.adapter.search_handler = original

    return reset


async def attempt_rows(world: AuthorityWorld, *, prefix: str) -> list[RateAttemptRow]:
    """Return durable rate attempts whose bucket id starts with ``prefix``."""

    async with world.repository.session() as session:
        rows = await session.execute(
            select(RateAttemptRow).where(RateAttemptRow.bucket_id.startswith(prefix))
        )
        return [row for row in rows.scalars().all()]


async def stored_dispatch_rows(
    world: AuthorityWorld,
    *,
    project_id: UUID | None = None,
) -> list[ExecutionDispatchRow]:
    """Return durable authority dispatch rows, optionally of one project."""

    statement = select(ExecutionDispatchRow)
    if project_id is not None:
        statement = statement.where(ExecutionDispatchRow.project_id == str(project_id))
    async with world.repository.session() as session:
        rows = await session.execute(statement)
        return [row for row in rows.scalars().all()]


async def usage_event_rows(
    world: AuthorityWorld,
    *,
    project_id: UUID | None = None,
) -> list[UsageEventRow]:
    """Return durable usage events (aggregated rows excluded), project-filtered."""

    statement = select(UsageEventRow).where(UsageEventRow.provider != "aggregated")
    if project_id is not None:
        statement = statement.where(UsageEventRow.project_id == str(project_id))
    async with world.repository.session() as session:
        rows = await session.execute(statement)
        return [row for row in rows.scalars().all()]


def usage_queue_wait_ms(row: Any) -> int | None:
    """Read the reported queue wait (ms) from one usage row's metadata."""
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except (TypeError, ValueError):
        return None
    value = metadata.get("queue_wait_ms")
    return value if isinstance(value, int) and value >= 0 else None


def usage_latency_ms(row: Any) -> int | None:
    """Read the reported provider latency (ms) column of one usage row."""
    value = row.latency_ms
    return value if isinstance(value, int) and value >= 0 else None


def provider_records_with_search_rate(
    rate: int,
    *,
    provider: str = PROVIDER,
) -> list[ProviderLimitRecord]:
    """Return the default catalog with one provider's keyed search rate raised.

    The documented exa team rail is 10 requests/second, so any A3 scenario
    that legitimately backlogs more than ten provider sends could be denied
    by the native rail inside one real second, before the scheduler could
    even serve the demand. The rail stays fully enforced and durable (every
    attempt still consumes a native reservation); the test only sizes the
    nominal ceiling to what this suite must exercise. Use it for fairness and
    contention scenarios; keep the catalog default when the native rails are
    the subject under test.
    """

    raised: list[ProviderLimitRecord] = []
    for record in provider_limit_defaults():
        if record.provider == provider and record.rate is not None:
            window = RateWindow(
                bucket_id=f"{provider}:keyed:{record.operation.value}:1s",
                limit=Decimal(max(1, rate)),
                window=RateWindowName.SECOND,
                scope=RateScope.TEAM,
            )
            raised.append(
                record.model_copy(
                    update={"rate": record.rate.model_copy(update={"windows": [window]})}
                )
            )
        else:
            raised.append(record)
    return raised


def _specs_by_label(spec: AuthorityPoolSpec) -> dict[str, AllocationSpec]:
    """Map the pool spec's allocation declarations by project label."""
    mapping: dict[str, AllocationSpec] = {}
    for allocation in spec.allocations:
        if allocation.label in mapping:
            raise AssertionError(f"duplicate allocation for {allocation.label!r}")
        mapping[allocation.label] = allocation
    return mapping


async def _seed_pool_and_allocations(
    repository: SQLiteRepository,
    projects: dict[str, AuthorityProject],
    *,
    spec: AuthorityPoolSpec,
) -> tuple[StoredPool, dict[str, StoredAllocation]]:
    """Seed the upstream pool, its credential links, and every allocation."""

    mapping = _specs_by_label(spec)
    unknown = sorted(label for label in mapping if label not in projects)
    if unknown:
        raise AssertionError(f"allocations name unknown projects {unknown}")

    async with repository.session() as session:
        pools = UpstreamPoolRepository(session)
        pool_row = await pools.create_pool(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type=PROVIDER,
            upstream_scope=UpstreamScope.ACCOUNT,
            pool_key=f"a3-{uuid4().hex[:10]}",
            label="a3 pool",
            constraints=spec.constraints,
            max_concurrency=spec.max_concurrency,
            max_queued_requests=spec.max_queued_requests,
        )
        allocation_repository = PoolAllocationRepository(session)
        allocations: dict[str, StoredAllocation] = {}
        for label, allocation in mapping.items():
            allocated = await allocation_repository.create(
                project_id=projects[label].project_id,
                pool_id=pool_row.id,
                operation=spec.operation,
                base_rate=allocation.base_rate,
                rate_window_seconds=spec.window_seconds,
                granted_by=projects[label].attribution.actor_id,
                borrow_enabled=allocation.borrow_enabled,
                max_rate=allocation.borrow_max,
                weight=allocation.weight,
                best_effort=allocation.best_effort,
                max_concurrency=allocation.max_concurrency,
                max_queued_requests=allocation.max_queued_requests,
                max_queued_bytes=allocation.max_queued_bytes,
                max_queue_wait_ms=allocation.max_queue_wait_ms,
            )
            allocations[label] = allocated
            for operation in (spec.operation,):
                await pools.link_credential(
                    credential_id=projects[label].credential.credential_id,
                    operation=operation,
                    pool_id=pool_row.id,
                    provider_type=PROVIDER,
                )
        await session.commit()
    return pool_row, allocations


def DefaultPoolSpec(
    *,
    limit: int = 1000,
    allocations: tuple[AllocationSpec, ...] = (),
    **pool_field_overrides: Any,
) -> AuthorityPoolSpec:
    """Build the standard trailing-window pool spec with explicit allocations."""
    del pool_field_overrides
    return AuthorityPoolSpec(limit=limit, allocations=allocations)


def build_default_allocations(
    base_a: int = 4, base_b: int = 6, *, borrow_max: int | None = None
) -> tuple[AllocationSpec, ...]:
    """The 4:6 weighted example pair (loans on with ``borrow_max``)."""
    return (
        AllocationSpec(label="A", base_rate=base_a, weight=base_a, borrow_max=borrow_max),
        AllocationSpec(label="B", base_rate=base_b, weight=base_b, borrow_max=borrow_max),
    )


async def build_authority_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    spec: AuthorityPoolSpec,
    labels: tuple[str, ...] = ("A", "B"),
    authority_key: str = AUTHORITY_KEY,
    monotonic: MonotonicControl | None = None,
    codec: SecretCodec | None = None,
    native_search_second: int | None = None,
    default_max_wait_ms: int | None = None,
    default_max_requests: int | None = None,
    default_max_bytes: int | None = None,
    lease_seconds: float | None = None,
    recovery_seconds: float | None = None,
) -> AuthorityWorld:
    """Seed projects, pool, allocations, and compose the real execution service.

    ``codec`` lets a reopen-based recovery test rebuild the encrypted store of
    the same database (a caller needs the original master key to read old
    credential slots). ``native_search_second`` sizes the keyed native rate
    rail for burst workloads without ever disabling it. The three default
    queue bounds feed the authority so its per-queue fallback limits (wait,
    request count, payload bytes) match the scenario's declared
    authority-wide contract.
    """

    repository = await SQLiteRepository.open(tmp_path / f"a3-{uuid4().hex[:8]}.db")
    attributions: dict[str, ExecutionAttribution] = {}
    projects: dict[str, AuthorityProject] = {}
    adapters_by_secret: dict[str, RecordingAdapter] = {}

    store_codec = codec or SecretCodec(MasterKey(os.urandom(32)))
    store = EncryptedDbSecretStore(repository, store_codec)
    for label in labels:
        attributions[label] = await seed_execution_project(repository, name=label)
        secret = f"fake-{PROVIDER}-{label}-{uuid4().hex[:10]}"
        adapters_by_secret[secret] = RecordingAdapter(PROVIDER)
        credential = await seed_credential(
            repository,
            store,
            project_id=attributions[label].project_id,
            actor_id=attributions[label].actor_id,
            label=label,
            secret=secret,
        )
        projects[label] = AuthorityProject(
            label=label,
            attribution=attributions[label],
            context=ProjectContext(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                project_id=attributions[label].project_id,
                principal=HumanPrincipal(user_id=attributions[label].actor_id, session_id=uuid4()),
                effective_permissions=frozenset(
                    {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
                ),
                policy_revision=1,
            ),
            credential=credential,
            adapter=adapters_by_secret[secret],
        )

    pool, allocations = await _seed_pool_and_allocations(repository, projects, spec=spec)

    import polyweb.services.execution as execution_module

    def factory(client: Any, api_key: Any = None) -> ProviderAdapter:
        del client
        key = api_key.get_secret_value() if api_key is not None else ""
        adapter = adapters_by_secret.get(key)
        assert adapter is not None, "execution supplied an unknown fixture credential"
        return adapter

    def adapter_factory(name: str) -> Callable[..., ProviderAdapter] | None:
        return factory if name == PROVIDER else None

    monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)

    limits_service = (
        ProviderLimitsService(
            repository.limits, records=provider_records_with_search_rate(native_search_second)
        )
        if native_search_second is not None
        else ProviderLimitsService(repository.limits)
    )
    await limits_service.initialize()

    from polyweb.services.execution_authority import ExecutionAuthority

    stepped = monotonic or MonotonicControl()
    authority_arguments: dict[str, Any] = {}
    if default_max_wait_ms is not None:
        authority_arguments["default_max_wait_ms"] = default_max_wait_ms
    if default_max_requests is not None:
        authority_arguments["default_max_requests"] = default_max_requests
    if default_max_bytes is not None:
        authority_arguments["default_max_bytes"] = default_max_bytes
    if lease_seconds is not None:
        authority_arguments["lease_seconds"] = lease_seconds
    if recovery_seconds is not None:
        authority_arguments["recovery_seconds"] = recovery_seconds
    authority = ExecutionAuthority(
        repository=repository,
        authority_key=authority_key,
        monotonic_fn=stepped.monotonic_fn,
        limits=limits_service,
        **authority_arguments,
    )
    service = ExecutionService(
        repository=repository,
        secret_store=store,
        client=object(),
        limits=limits_service,
        authority=authority,
    )
    world = AuthorityWorld(
        repository=repository,
        store=store,
        monotonic=stepped,
        pool=pool,
        spec=spec,
        authority=authority,
        service=service,
        projects=projects,
        allocations=allocations,
    )
    for project in projects.values():
        project.adapter.search_handler = parked_search_handler(world)
    return world


__all__ = [
    "AUTHORITY_KEY",
    "PROVIDER",
    "AllocationSpec",
    "AuthorityPoolSpec",
    "AuthorityProject",
    "AuthorityWorld",
    "DispatchStart",
    "MonotonicControl",
    "ParkedRequest",
    "build_authority_world",
    "install_first_failures",
    "parked_search_handler",
    "provider_error",
    "provider_error_for",
    "provider_records_with_search_rate",
    "stored_dispatch_rows",
    "usage_event_rows",
    "usage_latency_ms",
    "usage_queue_wait_ms",
]
