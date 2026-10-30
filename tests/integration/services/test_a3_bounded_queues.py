"""A3 AC2: bounded queues per project and in total (TASK-000045).

Bounded by count, payload bytes, wait time, and concurrency. Queued work that
is canceled, expired, or lost to a live-authority change never reaches a
provider and never consumes a rate attempt. Queue wait is reported separately
from provider latency in the usage metadata (``queue_wait_ms``).

Every case drives the real execution over a temporary database with recording
fake adapters. Saturation happens at admission (nothing is dispatched, nothing
charged); parks hold in-flight dispatches so the queued side stays queued
deterministically, and the injected virtual clock moves wait bounds without
real sleeps.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from freesearch.models.contracts import RoutingPreference, SearchResponse
from freesearch.models.credentials import CredentialOperation
from freesearch.models.execution_failures import (
    ExecutionAuthorityUnavailable,
    ExecutionNotPermitted,
    ExecutionQueueExpired,
    ExecutionQueueSaturated,
)
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.models.schema_enums import UpstreamScope
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    UpstreamPoolRepository,
)
from freesearch.services.api_keys import ApiKeyService
from tests.fixtures.a2_execution import RecordingAdapter
from tests.fixtures.a3_authority import (
    PROVIDER,
    AllocationSpec,
    AuthorityPoolSpec,
    attempt_rows,
    build_authority_world,
    parked_search_handler,
    seed_credential,
    stored_dispatch_rows,
    usage_event_rows,
    usage_latency_ms,
    usage_queue_wait_ms,
)


def _spec_a(
    *,
    max_queued_bytes: int | None = None,
    max_queue_wait_ms: int | None = None,
    max_queued_requests: int | None = 1,
) -> AuthorityPoolSpec:
    """The suite pool: strict per-project bounds plus the documented 4:6 pair."""

    return AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                borrow_max=10,
                weight=4,
                max_concurrency=1,
                max_queued_requests=max_queued_requests,
                max_queued_bytes=max_queued_bytes,
                max_queue_wait_ms=max_queue_wait_ms,
            ),
            AllocationSpec(
                label="B",
                base_rate=6,
                borrow_max=10,
                weight=6,
                max_concurrency=1,
            ),
        ),
    )


async def _refusals(tasks: list[asyncio.Task[Any]], *, timeout: float = 5.0) -> list[BaseException]:
    """Wait for these tasks to settle and return their refusal exceptions."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    for task in tasks:
        while not task.done():
            if loop.time() > deadline:
                pytest.fail("a saturated admission never settled")
            await asyncio.sleep(0.001)
    outcomes: list[BaseException] = []
    for task in tasks:
        error = task.exception()
        assert error is not None, "a saturated admission must not resolve successfully"
        outcomes.append(error)
    return outcomes


async def _drain(world: Any, tasks: list[asyncio.Task[Any]], *, timeout: float = 20.0) -> None:
    """Release parked sends in waves until every task resolves."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not all(task.done() for task in tasks):
        world.release()
        if loop.time() > deadline:
            pytest.fail(f"drain never completed ({sum(1 for t in tasks if t.done())}/{len(tasks)})")
        await asyncio.sleep(0.002)
    world.release()


# ---------------------------------------------------------------------------
# count bound, per project: the third request saturates, nothing is sent.
# ---------------------------------------------------------------------------


async def test_per_project_queue_count_bound_saturates_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a()
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        rest = world.submit("A", "a2", "a3")
        await world.wait_queued("A", 1)  # explicit enqueue anchor on the first pool
        saturated = await _refusals([rest[1]])
        attempts = await world.project_attempts("A")
        assert not rest[0].done(), "a2 must occupy the single queue slot"

        world.release()
        await world.wait_starts(2)
        world.release()
        await _drain(world, [*first, rest[0]])
        successes, failures = await world.gather(first + list(rest))
        usage = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        waits = [value for row in usage if (value := usage_queue_wait_ms(row)) is not None]
    finally:
        await world.aclose()

    assert len(saturated) == 1
    assert isinstance(saturated[0], ExecutionQueueSaturated), type(saturated[0]).__name__
    assert saturated[0].retriable is False, "saturation is not retriable"
    assert "queue" in str(saturated[0]).lower(), str(saturated[0])
    assert len(attempts) == 1, f"a refused queue admission charged a rate attempt: {attempts}"
    assert len(successes) == 2, "the parked a1 plus the queued a2 both complete"
    assert failures and len(failures) == 1
    assert world.projects["A"].adapter.search_calls == 2, "a saturated admission never dispatches"
    assert len(usage) == 2, "the refused admission must not see usage"
    assert waits, "usage rows must report queue_wait_ms for the queued dispatch"


# ---------------------------------------------------------------------------
# count bound, in total: the pool's total queue budget is shared.
# ---------------------------------------------------------------------------


async def test_pool_total_queue_bound_saturates_across_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        max_queued_requests=1,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "a1") + world.submit("B", "b1")
        await world.wait_starts(2)  # both sends hold their project slots, parked
        then = world.submit("A", "a2") + world.submit("B", "b2")

        # Exactly one of the two second waves saturates the shared total
        # bound; the other legitimately occupies the single queue slot. Which
        # label saturates depends on each admission's resolution timing, so
        # the test stays order-agnostic and anchors on the facts: check and
        # append are one synchronous step, so exactly one saturates.
        loop = asyncio.get_running_loop()
        settle_deadline = loop.time() + 5.0  # bounded: shorter than the park timeout
        while not any(task.done() for task in then):
            if loop.time() > settle_deadline:
                pytest.fail("the shared pool-total bound saturated neither second wave")
            await asyncio.sleep(0.002)
        refusers = [task for task in then if task.done() and task.exception() is not None]
        queued = [task for task in then if not task.done()]
        if len(refusers) != 1 or len(queued) != 1:
            pytest.fail(
                f"the pool-total bound must saturate exactly one queued request "
                f"(refused={[type(t.exception()).__name__ for t in refusers]})"
            )
        saturated = [task.exception() for task in refusers]
        assert all(isinstance(error, ExecutionQueueSaturated) for error in saturated), saturated
        assert saturated[0].retriable is False

        # Drain deterministically from explicit start evidence: the queued
        # wave cannot depart before its preceding parked wave is released.
        world.release()
        await world.wait_starts(3)
        world.release()
        await _drain(world, first + queued)
        drained, drained_failures = await world.gather(first + queued)
        dispatches = await stored_dispatch_rows(world)

        resolve_safe = first + list(then)
    finally:
        world.release()
        with suppress(Exception):
            await asyncio.gather(*resolve_safe, return_exceptions=True)
        await world.aclose()

    assert not drained_failures, [f"{type(f).__name__}: {f}" for f in drained_failures]
    assert len(drained) == 3, "a1, b1 plus the one queued second dispatch complete"
    assert sum(project.adapter.search_calls for project in world.projects.values()) == 3
    assert len(dispatches) == 3


# ---------------------------------------------------------------------------
# bytes bound: an oversized payload saturates at admission, nothing is sent.
# ---------------------------------------------------------------------------


async def test_queue_bytes_bound_saturates_before_any_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a(max_queued_bytes=512)
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        second = world.submit("A", "a2")
        oversize = world.submit("A", "oversize-" + ("x" * 1600))
        await world.wait_admitted("A")  # a2 queued and the oversized payload settled
        saturated = await _refusals(list(oversize))
        assert not second[0].done(), "a2 must still be queued when the payload saturates"
        world.release()
        await world.wait_starts(2)
        world.release()
        await _drain(world, first + list(second))
        successes, _failures = await world.gather(first + list(second))
        attempts = await world.project_attempts("A")
        calls = world.projects["A"].adapter.search_calls
    finally:
        await world.aclose()

    assert len(saturated) == 1, saturated
    oversize_error = saturated[0]
    assert isinstance(oversize_error, ExecutionQueueSaturated), (
        f"the bytes refusal must be the queue shape, got {type(oversize_error).__name__}"
    )
    assert "queue" in str(oversize_error).lower()
    assert oversize_error.retriable is False
    assert len(successes) == 2 and calls == 2
    assert len(attempts) == 2, "the oversized payload consumed no rate attempt"


# ---------------------------------------------------------------------------
# wait-time bound: expired queued work is removed without a debit or a send.
# ---------------------------------------------------------------------------


async def test_bounded_queue_wait_expiry_removes_work_without_any_debit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a(max_queue_wait_ms=100)
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("A", "a2")
        await world.wait_queued("A", 1)  # a2 occupies the queue state before the clock moves
        assert not queued[0].done(), "a2 must still be waiting while a1 holds the slot"

        world.monotonic.advance(0.25)
        expired = await _refusals(list(queued))
        world.release()
        successes, _failures = await world.gather(first)
        usage = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        attempts = await world.project_attempts("A")
        calls = world.projects["A"].adapter.search_calls
        settle_retired = first + list(queued)
    finally:
        world.release()
        with suppress(Exception):
            await asyncio.gather(*settle_retired, return_exceptions=True)
        await world.aclose()

    assert isinstance(expired[0], ExecutionQueueExpired), type(expired[0]).__name__
    assert expired[0].retriable is True
    assert "queue" in str(expired[0]).lower()
    assert successes, "the in-flight leg completes despite the queue expiry"
    assert calls == 1, "the expired dispatch never reached the provider"
    assert len(attempts) == 1, f"the expired dispatch consumed a rate attempt: {attempts}"
    assert len(usage) == 1, "the expired dispatch must not write usage"


# ---------------------------------------------------------------------------
# shutdown: queued work resolves retriable instead of claiming delivery.
# ---------------------------------------------------------------------------


async def test_shutdown_cancels_queued_work_with_retriable_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a(max_queue_wait_ms=20_000)
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("A", "a2")
        await world.wait_admitted("A")  # explicit enqueue synchronization
        assert not queued[0].done(), "a2 must be queued while a1 holds the slot"

        # Cancel queued work on shutdown; the in-flight send stays real work.
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(world.service.aclose(), timeout=5.0)
        outcome: Any
        try:
            outcome = await asyncio.wait_for(queued[0], timeout=5.0)
        except TimeoutError:
            pytest.fail("queued work produced no outcome across shutdown")
        except BaseException as error:
            outcome = error
        calls = world.projects["A"].adapter.search_calls
        attempts = await world.project_attempts("A")
    finally:
        world.release()
        await _drain(world, first)
        with suppress(Exception):
            await world.aclose()

    assert not isinstance(outcome, SearchResponse), "queued work must not claim delivery"
    assert isinstance(outcome, (ExecutionQueueExpired, ExecutionAuthorityUnavailable)), (
        f"shutdown outcome must be typed and retriable, got {type(outcome).__name__}"
    )
    assert getattr(outcome, "retriable", False) is True
    assert calls == 1, "the queued work reached the provider before being canceled"
    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# authority lost while queued: removed at dispatch without a debit or a send.
# ---------------------------------------------------------------------------


async def test_queued_work_lost_authority_is_removed_without_debit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a(max_queue_wait_ms=20_000)
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    project_id: UUID
    key: Any = None
    try:
        key, key_ctx = await world.key_context("A")
        project_id = world.projects["A"].project_id

        first = [
            asyncio.create_task(
                world.service.search(
                    world.request("A", tag="key-first"),
                    attribution=key.attribution,
                    context=key_ctx,
                )
            )
        ]
        await world.wait_starts(1)
        second = [
            asyncio.create_task(
                world.service.search(
                    world.request("A", tag="key-second"),
                    attribution=key.attribution,
                    context=key_ctx,
                )
            )
        ]
        await world.wait_admitted("A")  # the second leg is enqueued before revocation

        await ApiKeyService(world.repository).revoke(key.owner, key.project_id, key.api_key_id)
        world.release()
        successes, failures = await world.gather(first + second)
        attempts = await world.project_attempts("A")
        dispatches = await stored_dispatch_rows(world, project_id=project_id)
        usage = await usage_event_rows(world, project_id=project_id)
    finally:
        await world.aclose()

    assert len(successes) == 1, "only the already-dispatched leg completes"
    assert failures and isinstance(failures[0], ExecutionNotPermitted), [
        type(failure).__name__ for failure in failures
    ]
    assert world.projects["A"].adapter.search_calls == 1
    assert len(attempts) == 1, f"the revoked queued work left a rate debit: {attempts}"
    assert len(dispatches) == 1
    assert len(usage) == 1
    assert usage[0].actor_id == str(key.api_key_id)


# ---------------------------------------------------------------------------
# P3: the queued-count bound is authority-wide, not private to each
# (pool, operation) queue.
# ---------------------------------------------------------------------------


async def test_authority_queue_count_bound_is_authority_wide_across_pools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two (pool, operation) queues share one authority-wide queued total.

    The authority is composed with a default queued-request bound of one and
    a second independent pool is linked to B's credential, so execution
    produces a second fair queue. A queued request on that second pool must
    refuse against the authority-wide one-slot total even though this second
    queue itself is empty and the first pool's own queue carried the slot.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec, default_max_requests=1)
    all_tasks: list[asyncio.Task[Any]] = []
    pool_rows: list[Any] = []
    calls = 0
    saturated: list[BaseException] = []
    try:
        async with world.repository.session() as session:
            pools = UpstreamPoolRepository(session)
            second_pool = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=PROVIDER,
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key=f"a3-second-{uuid4().hex[:10]}",
                label="second bound pool",
                constraints=spec.constraints,
                max_concurrency=None,
                max_queued_requests=None,  # this queue's own count bound is unset
            )
            await pools.link_credential(
                credential_id=world.projects["B"].credential.credential_id,
                operation=CredentialOperation.SEARCH,
                pool_id=second_pool.id,
                provider_type=PROVIDER,
            )
            await PoolAllocationRepository(session).create(
                project_id=world.projects["B"].project_id,
                pool_id=second_pool.id,
                operation=CredentialOperation.SEARCH,
                base_rate=4,
                rate_window_seconds=spec.window_seconds,
                granted_by=world.projects["B"].attribution.actor_id,
            )
            await session.commit()

        first = world.submit("A", "a1") + world.submit("B", "b1")
        await world.wait_starts(2)
        queued_second_a = world.submit("A", "a2")
        second_b = world.submit("B", "b2")
        all_tasks = first + list(queued_second_a) + list(second_b)
        settle_retired = list(all_tasks)
        try:
            # Under the authority-wide contract exactly one of the two second
            # waves saturates; under the frozen per-pool accounting neither
            # does and the request parks on the provider instead, so the
            # bounded settle poll (shorter than the park timeout) reports the
            # defect. Which label saturates is a resolution-order fact: the
            # test stays order-agnostic.
            loop = asyncio.get_running_loop()
            settle_deadline = loop.time() + 5.0
            while not any(task.done() for task in (queued_second_a[0], second_b[0])):
                if loop.time() > settle_deadline:
                    pytest.fail("the authority-wide queued bound saturated neither second wave")
                await asyncio.sleep(0.002)
            refusers = [
                task
                for task in (queued_second_a[0], second_b[0])
                if task.done() and task.exception() is not None
            ]
            queued = [task for task in (queued_second_a[0], second_b[0]) if not task.done()]
            saturated = [task.exception() for task in refusers]
            assert len(refusers) == 1 and len(queued) == 1, (
                f"the authority-wide bound must saturate exactly one request "
                f"({[type(e).__name__ for e in saturated]})"
            )
            assert all(isinstance(error, ExecutionQueueSaturated) for error in saturated), saturated
            assert saturated[0].retriable is False

            # The one queued slot must still drain on its own pool (a2 or b2).
            world.release()
            await world.wait_starts(3)
            world.release()
            await _drain(world, first + queued)
            successes, failures = await world.gather(first + queued)
            assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
            assert len(successes) == 3, "a1, b1 plus the queued wave complete"
            pool_rows = await world.pool_attempts()
            second_rows = await attempt_rows(world, prefix=f"pool:{second_pool.id}:")
        finally:
            # Resolve every submitted request so no task is orphaned: the
            # release waves drive the parks, and the gather retrieves
            # exceptions even when an inner assertion already failed.
            world.release()
            if any(not task.done() for task in settle_retired):
                with suppress(Exception):
                    await _drain(world, settle_retired, timeout=10.0)
                with suppress(Exception):
                    await world.gather(settle_retired)
        calls = sum(project.adapter.search_calls for project in world.projects.values())
    finally:
        await world.aclose()

    assert saturated and isinstance(saturated[0], ExecutionQueueSaturated), [
        type(item).__name__ for item in saturated
    ]
    assert saturated[0].retriable is False
    # b1 drives the second pool exactly once; the queued wave pays its own
    # pool once; the refused wave never dispatched or charged anything.
    assert len(pool_rows) + len(second_rows) == 3, (
        f"refused wave charged nothing (pool {len(pool_rows)}, second {len(second_rows)})"
    )
    assert calls == 3, f"the refused queued request dispatched ({calls} provider calls)"


# ---------------------------------------------------------------------------
# P4 default wait: the authority-wide default bounds a backlog whose
# allocation never set its own wait.
# ---------------------------------------------------------------------------


async def _wait_expiry_settled(
    tasks: list[asyncio.Task[Any]], *, timeout: float = 5.0
) -> list[BaseException]:
    """Boundedly wait until every submitted task resolved into a refusal."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    for task in tasks:
        while not task.done():
            if loop.time() > deadline:
                pytest.fail(
                    "the default queue wait must bound a backlog whose allocation "
                    "set no explicit max_queue_wait_ms (P4)"
                )
            await asyncio.sleep(0.002)
    outcomes: list[BaseException] = []
    for task in tasks:
        error = task.exception()
        assert error is not None, "an expired queued admission must not resolve successfully"
        outcomes.append(error)
    return outcomes


async def test_default_queue_wait_bounds_a_backlog_when_the_allocation_sets_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The authority-wide default queue wait governs when an allocation awaits.

    The allocation carries no ``max_queue_wait_ms`` and the forwarded request
    carries no deadline, so the queue's default wait bound must expire the
    backlog before any send -- never leaving it queued unbounded.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec, default_max_wait_ms=250)
    settle_retired: list[asyncio.Task[Any]] = []
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("A", "a2", "a3")
        await world.wait_queued("A", 2)
        settle_retired = first + queued
        assert not all(task.done() for task in queued), (
            "the backlog must still be waiting before the default wait elapses"
        )

        world.monotonic.advance(0.35)
        expired = await _wait_expiry_settled(queued)
        world.release()
        successes, _failures = await world.gather(first)
        usage = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        attempts = await world.project_attempts("A")
        calls = world.projects["A"].adapter.search_calls
    finally:
        world.release()
        if any(not task.done() for task in settle_retired):
            with suppress(Exception):
                await _drain(world, settle_retired, timeout=10.0)
            with suppress(Exception):
                await world.gather(settle_retired)
        await world.aclose()

    assert len(expired) == 2, [type(item).__name__ for item in expired]
    assert all(isinstance(error, ExecutionQueueExpired) for error in expired), [
        f"{type(error).__name__}: {error}" for error in expired
    ]
    assert all(error.retriable is True for error in expired), [str(error) for error in expired]
    assert "queue" in str(expired[0]).lower()
    assert successes, "the in-flight leg completes despite the default wait expiry"
    assert calls == 1, f"the expired backlog reached the provider ({calls} calls)"
    assert len(attempts) == 1, f"the expired backlog charged rate attempts: {attempts}"
    assert len(usage) == 1, f"the expired backlog wrote usage: {[row.status for row in usage]}"


# ---------------------------------------------------------------------------
# P7 request deadline: an end-to-end deadline expires queued work before any
# send, even with a wide queue-wait allocation -- the deadline is never
# extended behind the sender's back.
# ---------------------------------------------------------------------------


async def test_request_deadline_expires_queued_work_before_any_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _spec_a(max_queue_wait_ms=20_000)
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    settle_retired: list[asyncio.Task[Any]] = []
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)

        project = world.projects["A"]
        deadline = world.monotonic.seconds + 0.05

        async def _search_deadlined() -> Any:
            return await world.service.search(
                world.request("A", tag="a2"),
                attribution=project.attribution,
                context=project.context,
                deadline=deadline,
            )

        queued = [asyncio.create_task(_search_deadlined())]
        await world.wait_queued("A", 1)
        settle_retired = first + queued
        assert not queued[0].done(), "the deadlined request must still be waiting"

        world.monotonic.advance(0.1)
        expired = await _wait_expiry_settled(queued)
        world.release()
        successes, _failures = await world.gather(first)
        usage = await usage_event_rows(world, project_id=project.project_id)
        attempts = await world.project_attempts("A")
        calls = world.projects["A"].adapter.search_calls
        starts = [start.tag for start in world.starts_of("A")]
    finally:
        world.release()
        if any(not task.done() for task in settle_retired):
            with suppress(Exception):
                await _drain(world, settle_retired, timeout=10.0)
            with suppress(Exception):
                await world.gather(settle_retired)
        await world.aclose()

    assert len(expired) == 1
    assert isinstance(expired[0], ExecutionQueueExpired), type(expired[0]).__name__
    assert expired[0].retriable is True
    assert "queue" in str(expired[0]).lower()
    assert successes, "the in-flight leg completes despite the request deadline expiry"
    assert calls == 1, f"the deadlined request reached the provider ({calls} calls)"
    assert len(attempts) == 1, f"the deadlined request consumed a rate attempt: {attempts}"
    assert len(usage) == 1, f"the deadlined request wrote usage: {[row.status for row in usage]}"
    assert starts == ["a1"], f"the expired request must never be granted or sent: starts={starts}"


# ---------------------------------------------------------------------------
# P13 telemetry separation: the queue wait rides its own metadata field while
# the provider latency stays only the provider's own measured time.
# ---------------------------------------------------------------------------


async def test_queue_wait_is_reported_separately_from_provider_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued send reports two separated numbers, wait and provider latency.

    Project B waits ~2 virtual seconds for its grant, then sends instantly.
    The usage row must report that wait in ``metadata_json.queue_wait_ms``
    while ``latency_ms`` keeps measuring the provider call only -- the queue
    hold must never inflate the provider latency number.

    Under actual-grant ownership a genuinely free slot is granted
    synchronously, so the real wait is created the scheduler's way: the pool
    declares exactly one concurrency unit and the parked send of A holds it
    while B queues.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        max_concurrency=1,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(
                label="B",
                base_rate=6,
                borrow_max=10,
                weight=6,
                max_concurrency=1,
                max_queue_wait_ms=20_000,
            ),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    settle_retired: list[asyncio.Task[Any]] = []
    try:
        first = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("B", "b1")
        await world.wait_queued("B", 1)
        settle_retired = first + queued
        assert not queued[0].done(), "b1 must still be queued before the virtual grace elapses"

        world.monotonic.advance(2.0)
        world.release()
        await _drain(world, settle_retired, timeout=30.0)
        successes, _failures = await world.gather(settle_retired)
        a_rows = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        b_rows = await usage_event_rows(world, project_id=world.projects["B"].project_id)
    finally:
        world.release()
        if any(not task.done() for task in settle_retired):
            with suppress(Exception):
                await _drain(world, settle_retired, timeout=10.0)
            with suppress(Exception):
                await world.gather(settle_retired)
        await world.aclose()

    assert len(successes) == 2, f"both sends must complete: {successes!r}"
    assert len(a_rows) == 1 and len(b_rows) == 1
    idle_wait = usage_queue_wait_ms(a_rows[0])
    assert idle_wait in (None, 0), (
        f"the immediately granted send must report no queue wait: {idle_wait}"
    )
    reported_wait = usage_queue_wait_ms(b_rows[0])
    assert reported_wait == 2000, (
        f"the queued send must report its exact virtual wait: {reported_wait}"
    )
    reported_latency = usage_latency_ms(b_rows[0])
    assert reported_latency is not None, "the provider surface must measure its latency"
    assert reported_latency < 1500, (
        f"the queue wait must not be folded into the provider latency: "
        f"wait={reported_wait} latency={reported_latency}"
    )


# ---------------------------------------------------------------------------
# P3 global bounds: the authority-wide queued-bytes budget holds across pools.
# ---------------------------------------------------------------------------


async def _wait_p3_refusals(
    tasks: list[asyncio.Task[Any]], *, timeout: float = 5.0, subject: str
) -> list[BaseException]:
    """Boundedly wait until the bytes-bound expectations settled."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    for task in tasks:
        while not task.done():
            if loop.time() > deadline:
                pytest.fail(
                    f"the authority-wide queued-bytes budget must refuse {subject} whose "
                    "payload pushes the cross-pool queue total over the bound (P3)"
                )
            await asyncio.sleep(0.002)
    outcomes: list[BaseException] = []
    for task in tasks:
        error = task.exception()
        assert error is not None, f"{subject} must not resolve successfully"
        outcomes.append(error)
    return outcomes


async def test_authority_bytes_bound_is_authority_wide_across_pools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The queued-bytes budget must hold across queues, not only inside one.

    Project A borrows the same queue budget through two independent
    credentials (two pools). While the first pool's queue holds a large
    payload, a pool-two submission whose payload would push the cross-pool
    queue total over ``default_max_bytes`` must refuse, while a small payload
    keeps queueing. A strictly per-queue view would let the pair exceed the
    authority budget it was composed with.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        max_concurrency=1,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=2),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec, default_max_bytes=700)
    extra_secret = f"fake-{PROVIDER}-x-{uuid4().hex[:8]}"
    extra_adapter = RecordingAdapter(PROVIDER)
    settle_retired: list[asyncio.Task[Any]] = []
    saturated: list[BaseException] = []
    drainer_retired: list[asyncio.Task[Any]] = []
    try:
        extra_credential = await seed_credential(
            world.repository,
            world.store,
            project_id=world.projects["A"].project_id,
            actor_id=world.projects["A"].attribution.actor_id,
            label="a-extra",
            secret=extra_secret,
        )
        async with world.repository.session() as session:
            pools = UpstreamPoolRepository(session)
            second_pool = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=PROVIDER,
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key=f"a3-bytes-{uuid4().hex[:10]}",
                label="second bytes pool",
                constraints=spec.constraints,
                max_concurrency=1,
                max_queued_requests=None,
            )
            await pools.link_credential(
                credential_id=extra_credential.credential_id,
                operation=CredentialOperation.SEARCH,
                pool_id=second_pool.id,
                provider_type=PROVIDER,
            )
            await PoolAllocationRepository(session).create(
                project_id=world.projects["A"].project_id,
                pool_id=second_pool.id,
                operation=CredentialOperation.SEARCH,
                base_rate=4,
                rate_window_seconds=spec.window_seconds,
                granted_by=world.projects["A"].attribution.actor_id,
                borrow_enabled=True,
                max_rate=10,
                weight=4,
                max_concurrency=2,
            )
            await session.commit()

        import freesearch.services.execution as execution_module

        forwarded_factory = execution_module.adapter_factory

        def extended_adapter_factory(name: str) -> Any:
            """Extend the adapter registry checker with the extra credential."""

            result = forwarded_factory(name)
            if name != PROVIDER or result is None:
                return result
            base_build = result

            def extended_build(client: Any, api_key: Any = None) -> Any:
                key = api_key.get_secret_value() if api_key is not None else ""
                if key == extra_secret:
                    return extra_adapter
                return base_build(client, api_key)

            return extended_build

        monkeypatch.setattr(execution_module, "adapter_factory", extended_adapter_factory)
        extra_adapter.search_handler = parked_search_handler(world)

        # Hold the first pool's head so its payload stays queued there. Every
        # submission pins its binding, so the pools stay deterministic.
        first_pool_routing = RoutingPreference(binding_id=world.projects["A"].credential.binding_id)
        first = world.submit("A", "a0", routing=first_pool_routing)
        settle_retired += first
        await world.wait_starts(1)
        heavy = "y" * 60
        queued_big = world.submit("A", "a1", query=heavy, routing=first_pool_routing)
        settle_retired += queued_big
        await world.wait_queued("A", 1)
        big_request = world.request("A", tag="a1", query=heavy, routing=first_pool_routing)
        big_bytes = len(big_request.model_dump_json().encode("utf-8"))
        assert 0 < big_bytes <= 700, "the heavy request must fit the per-queue bound alone"

        # The second pool carries its own in-flight head through the pinned
        # extra binding, so heavy A submissions land there deterministically.
        routing_second = RoutingPreference(binding_id=extra_credential.binding_id)
        second_head = world.submit("A", "b0", routing=routing_second)
        settle_retired += second_head
        await world.wait_queued("A", 0, pool_id=second_pool.id)
        await world.wait_starts(2)

        heavy_second = "z" * 60
        heavy_request = world.request("A", tag="b1", query=heavy_second, routing=routing_second)
        heavy_bytes = len(heavy_request.model_dump_json().encode("utf-8"))
        assert 0 < heavy_bytes <= 700, "the second pool's payload must fit its queue alone"
        assert big_bytes + heavy_bytes > 700, (
            "the two pools' queued payloads must exceed the authority-wide budget"
        )
        overflow = world.submit("A", "b1", query=heavy_second, routing=routing_second)
        settle_retired += overflow
        saturated = await _wait_p3_refusals(overflow, subject="the cross-pool overflow")
        small = world.submit("A", "b2", routing=routing_second)
        settle_retired += small
        await world.wait_queued("A", 1, pool_id=second_pool.id)
        small_bytes = len(
            world.request("A", tag="b2", routing=routing_second).model_dump_json().encode("utf-8")
        )
        assert big_bytes + small_bytes <= 700 < big_bytes + heavy_bytes
        assert not small[0].done(), "the small submission must remain queued"
        drainer_retired = list(settle_retired)
    finally:
        drainer_retired = list(settle_retired)
        world.release()
        if any(not task.done() for task in drainer_retired):
            with suppress(Exception):
                await _drain(world, drainer_retired, timeout=10.0)
            with suppress(Exception):
                await world.gather(drainer_retired)
        await world.aclose()

    assert saturated and isinstance(saturated[0], ExecutionQueueSaturated), [
        f"{type(item).__name__}: {item}" for item in saturated
    ]
    assert saturated[0].retriable is False
    assert "byte" in str(saturated[0]).lower(), str(saturated[0])
