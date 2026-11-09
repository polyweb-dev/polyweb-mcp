"""A3 AC3/AC4: fair capacity -- strict caps, loans, DRR, feasible promises.

Behavioral coverage over the real execution service, temporary databases,
and recording fake adapters:

* loans disabled behaves exactly like the settled strict caps (the base rate
  is also the ceiling, and idle capacity of other projects stays unused);
* loans enabled let a solo project borrow up to the pool limit, and the pool
  envelope is never exceeded;
* under continuous equal demand, the documented weighted DRR shares hold: a
  continuously eligible ten-dispatch cycle serves exactly four dispatches for
  the weight-4 project and six for the weight-6 project -- neither a 1:1 race
  nor a predetermined finite submission total; a returning project is served
  within one cycle without preempting anything;
* a zero-guaranteed-share project is served only under an explicit
  best-effort policy and never by a zero-weight division edge case;
* infeasible promised base allocations are rejected on every write path --
  allocation create and pool constraint changes alike.

Dispatch order is observed through the fake adapter's parking handler, and
every rate assertion reads the durable attempt rows (project and pool
buckets), never internal scheduler state. One case builds the scheduler queue
directly, so the weighted-DRR algorithm is proven in isolation; every other
case keeps the native rate rails fully enabled -- their nominal ceiling was
sized for the burst, never disabled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.models.provider_limits import LimitDeniedError
from polyweb.models.schema_enums import PoolStatus, UpstreamScope
from polyweb.persistence.pools import (
    AllocationInfeasibleError,
    PoolAllocationRepository,
    UpstreamPoolRepository,
)
from polyweb.services.execution_authority import ExecutionQueueExpired, QueuePolicy
from tests.fixtures.a3_authority import (
    AllocationSpec,
    AuthorityPoolSpec,
    build_authority_world,
    usage_event_rows,
)
from tests.fixtures.execution import seed_execution_project


def pair(
    *,
    base_a: int = 4,
    base_b: int = 6,
    weight_a: int = 4,
    weight_b: int = 6,
    borrow_max: int | None = None,
    concurrency: int | None = None,
) -> tuple[AllocationSpec, AllocationSpec]:
    """Build the two allocations with explicit rates and weights."""
    common: dict[str, Any] = {"max_concurrency": concurrency}
    if borrow_max is not None:
        common["borrow_max"] = borrow_max
    return (
        AllocationSpec(label="A", base_rate=base_a, weight=weight_a, **common),
        AllocationSpec(label="B", base_rate=base_b, weight=weight_b, **common),
    )


async def serve_until(
    world: Any, tasks: Sequence[asyncio.Task[Any]], *, timeout: float = 30.0, probe: Any = None
) -> tuple[list[Any], list[BaseException]]:
    """Release parked sends in waves until every task resolves, then join.

    ``probe`` runs after every wave so a test can assert queue-side invariants
    while the batches run (for example: the zero-share project is never
    dispatched while other projects still hold demand).
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not all(task.done() for task in tasks):
        if probe is not None:
            try:
                probe()
            except BaseException:
                # A probe failure must not orphan the in-flight work: drain
                # what was already dispatched, then re-raise to the test.
                world.release()
                with suppress(Exception):
                    await asyncio.sleep(0.02)
                with suppress(Exception):
                    await world.gather(list(tasks))
                raise
        world.release()
        if all(task.done() for task in tasks):
            break
        parked = any(not park.released.is_set() for park in world.parks)
        if not parked:
            await asyncio.sleep(0.001)
        if loop.time() > deadline:
            pytest.fail(
                f"serving never completed ({sum(1 for t in tasks if t.done())}/{len(tasks)} done; "
                f"starts={[(s.label, s.tag) for s in world.starts]})"
            )
        await asyncio.sleep(0.001)
        world.release()
    if probe is not None:
        probe()
    return await world.gather(list(tasks))


# ---------------------------------------------------------------------------
# AC3 first clause: loans disabled behaves exactly like strict caps.
# ---------------------------------------------------------------------------


async def test_loans_disabled_keeps_the_strict_cap_under_sustained_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=10,
        allocations=pair(concurrency=4),  # loans disabled: no borrow_max
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        tasks = world.submit("A", *(f"a{index}" for index in range(10)))
        successes, failures = await serve_until(world, tasks)
        calls_a = world.projects["A"].adapter.search_calls
        calls_b = world.projects["B"].adapter.search_calls
        project_rows = await world.project_attempts("A")
        pool_rows = await world.pool_attempts()
        usage = await world.usage_rows(project_id=world.projects["A"].project_id)
        usage_b = await world.usage_rows(project_id=world.projects["B"].project_id)
    finally:
        await world.aclose()

    assert len(successes) == 4, (
        f"strict caps must never exceed the promised 4-base share: dispatched {len(successes)}"
    )
    assert calls_a == 4 and calls_b == 0, (
        f"A used {calls_a} and B used {calls_b} provider calls; B's idle share stayed unused"
    )
    assert len(failures) == 6
    assert all(
        isinstance(error, (LimitDeniedError, ExecutionQueueExpired)) for error in failures
    ), [type(error).__name__ for error in failures]
    assert len(project_rows) == 4, f"the project bucket charged {len(project_rows)}"
    assert len(pool_rows) == 4, f"the pool bucket charged {len(pool_rows)}"
    assert len(usage) == 4 and usage_b == []


# ---------------------------------------------------------------------------
# AC3 first clause: loans enabled let a solo project borrow the whole pool,
# but the pool envelope is never exceeded.
# ---------------------------------------------------------------------------


async def test_loans_enabled_solo_project_reaches_the_pool_limit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=10,
        allocations=pair(borrow_max=10, concurrency=None),
    )
    # The documented exa native rail admits ten sends per second; this burst
    # legitimately reaches exactly the pool limit, so the rail's nominal
    # ceiling is sized for it. The rail itself stays fully enforced.
    world = await build_authority_world(
        tmp_path, monkeypatch, spec=spec, native_search_second=1_000
    )
    try:
        tasks = world.submit("A", *(f"a{index}" for index in range(12)))
        successes, failures = await serve_until(world, tasks)
        calls = world.projects["A"].adapter.search_calls
        project_rows = await world.project_attempts("A")
        pool_rows = await world.pool_attempts()
    finally:
        await world.aclose()

    assert len(successes) == 10, f"A alone borrowed {len(successes)} of the 10 pool slots"
    assert calls == 10
    assert len(failures) == 2
    assert all(
        isinstance(error, (LimitDeniedError, ExecutionQueueExpired)) for error in failures
    ), [type(error).__name__ for error in failures]
    assert len(pool_rows) == 10, (
        f"the pool envelope charged {len(pool_rows)} rate attempts, never more than 10"
    )
    assert len(project_rows) == 10, (
        f"the borrowed ceiling wrote {len(project_rows)} project attempts"
    )


# ---------------------------------------------------------------------------
# AC3 second clause: the documented weighted-DRR shares under continuous
# equal demand. One case isolates the scheduler algorithm directly; the
# integration case drives it behind the real durable rails with both projects
# continuously backlogged.
# ---------------------------------------------------------------------------


def _drain_policy(*, project_id: UUID, weight: int) -> QueuePolicy:
    """One strict, unbounded-in-practice queue policy for a scheduler unit case."""

    return QueuePolicy(
        provider="unit",
        project_id=project_id,
        operation=CredentialOperation.SEARCH,
        weight=weight,
        base_rate=1_000_000,
        rate_window_seconds=3_600,
        max_rate=None,
        borrow_enabled=False,
        best_effort=False,
        max_concurrency=None,
        max_queued_requests=None,
        max_queued_bytes=None,
        max_queue_wait_ms=None,
        pool_max_concurrency=None,
        pool_max_queued_requests=None,
        payload_bytes=16,
    )


async def test_pool_queue_weighted_drr_unit_shares_under_continuous_backlog() -> None:
    """Unit scheduler isolation: a continuously eligible 4:6 pair serves 4:6.

    Weighted DEFICIT Round Robin is a bounded service contract, and the A3
    design record writes it as: one cost unit per actual provider attempt, so
    a continuously eligible weight-4 and weight-6 pair settle into a period of
    ten dispatches carrying exactly four and six starts. This is the bound a
    correct weighted scheduler must produce -- never a 1:1 race.
    """

    from polyweb.services.execution_authority import DispatchGrant, _PoolQueue

    queue = _PoolQueue(
        pool_id=uuid4(),
        operation=CredentialOperation.SEARCH,
        monotonic=lambda: 0.0,
        default_max_wait_ms=5_000,
        default_max_requests=10_000,
        default_max_bytes=10_000_000,
    )
    a_id, b_id = uuid4(), uuid4()
    order: list[str] = []

    async def submit_one(label: str) -> None:
        weight = 4 if label == "A" else 6
        project_id = a_id if label == "A" else b_id
        policy = _drain_policy(project_id=project_id, weight=weight)

        async def attempt(grant: DispatchGrant) -> str:
            grant.started.set()
            order.append(label)
            grant.finish()
            return label

        await queue.submit(policy, attempt)

    tasks = [asyncio.create_task(submit_one(label)) for index in range(40) for label in ("A", "B")]
    tasks.extend(asyncio.create_task(submit_one("B")) for _ in range(8))
    try:
        deadline = asyncio.get_running_loop().time() + 15.0
        while any(not task.done() for task in tasks):
            await asyncio.sleep(0.002)
            if asyncio.get_running_loop().time() > deadline:
                pytest.fail(f"the isolated scheduler served {len(order)}/{len(tasks)} grants")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        queue.close()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert len(order) == 88, f"every grant was served (observed {len(order)})"
    for index in range(0, 80, 10):
        cycle = order[index : index + 10]
        share = (cycle.count("A"), cycle.count("B"))
        assert share == (4, 6), (
            f"ten-start cycle {index // 10} served {share}; the documented weighted "
            "DRR bound for 4:6 is exactly 4:6 per cycle, never a 1:1 split"
        )


async def test_continuous_equal_demand_serves_documented_four_six_shares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both projects remain continuously backlogged; the documented holds.

    Neither project's demand is a counted-ahead fixed total: the feeder keeps
    at least one parked in-flight send plus one queued request per project,
    and the run stops at the first four documented ten-dispatch cycles. The
    exact 4:6 bound must hold in every cycle window, and the pool attempts
    must charge exactly one cost unit per actual provider attempt.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=pair(borrow_max=100, concurrency=1),
    )
    world = await build_authority_world(
        tmp_path, monkeypatch, spec=spec, native_search_second=10_000
    )
    try:
        goal = 40  # four documented ten-dispatch cycles, fed continuously
        submitted: dict[str, int] = {"A": 0, "B": 0}
        tasks: list[asyncio.Task[Any]] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 60.0

        def submit_one(label: str) -> None:
            tasks.append(world.submit(label, f"{label.lower()}{submitted[label]}")[0])
            submitted[label] += 1

        for _round in range(2):
            for label in ("A", "B"):
                submit_one(label)

        while len(world.starts) < goal:
            world.release()
            if loop.time() > deadline:
                pytest.fail(f"continuous demand stalled at {len(world.starts)} starts")
            for label in ("A", "B"):
                queued = submitted[label] - len(world.starts_of(label))
                if queued < 2 and len(world.starts) < goal:
                    submit_one(label)
            await asyncio.sleep(0.002)
        world.release()
        drain_deadline = loop.time() + 30.0
        while any(not task.done() for task in tasks):
            world.release()
            if loop.time() > drain_deadline:
                pytest.fail(
                    f"the drain never completed ({sum(1 for t in tasks if t.done())}/{len(tasks)})"
                )
            await asyncio.sleep(0.002)
        successes, failures = await world.gather(list(tasks))
        starts = list(world.starts)
        pool_rows = await world.pool_attempts()
        calls = sum(project.adapter.search_calls for project in world.projects.values())
    finally:
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert len(successes) == len(tasks), "every admitted request completes"
    assert len(pool_rows) == len(starts) and calls == len(starts), (
        f"one cost unit per actual provider attempt ({len(pool_rows)} rows, {calls} calls, "
        f"{len(starts)} starts)"
    )
    assert len(starts) >= goal, starts
    observed = starts[:goal]
    assert {start.label for start in observed} <= {"A", "B"}
    for index in range(0, goal, 10):
        cycle = observed[index : index + 10]
        share = (
            sum(1 for start in cycle if start.label == "A"),
            sum(1 for start in cycle if start.label == "B"),
        )
        assert share == (4, 6), (
            f"ten-start cycle {index // 10} served {share}; the documented weighted DRR "
            "bound under continuous equal demand is exactly 4:6 per cycle"
        )


# ---------------------------------------------------------------------------
# AC3 last clause: a returning project is served without preemption or
# starvation; idle deficits never grow beyond quantum (bounded service).
# ---------------------------------------------------------------------------


async def test_returning_project_is_served_without_preemption_or_starvation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=pair(borrow_max=100, concurrency=1),
    )
    world = await build_authority_world(
        tmp_path, monkeypatch, spec=spec, native_search_second=1_000
    )
    try:
        opening = world.submit("A", "a0", "a1", "a2", "a3") + world.submit(
            "B", *(f"b{index}" for index in range(24))
        )
        a_tasks = opening[:4]
        b_tasks = opening[4:]

        # Serve A's opening quantum while B runs continuously; B's queue stays
        # long so B's demand is still continuous when A returns.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0
        while not all(task.done() for task in a_tasks):
            if loop.time() > deadline:
                pytest.fail("A's opening quantum never drained")
            world.release()
            await asyncio.sleep(0.002)
        assert not all(task.done() for task in b_tasks), (
            "the bounded-deficit test needs B's continuous demand at A's return"
        )

        # A returns with a burst larger than its quantum.
        returned = world.submit("A", *(f"a{index}" for index in range(4, 14)))
        all_tasks = list(opening) + list(returned)
        successes, failures = await serve_until(world, all_tasks)
        starts = list(world.starts)
        a_starts = len(world.starts_of("A"))
        return_index = min(
            index for index, start in enumerate(starts) if start.label == "A" and start.tag == "a4"
        )
        first_ten_after_return = starts[return_index : return_index + 10]
        served_in_first_ten = sum(1 for start in first_ten_after_return if start.label == "A")
        released_units = [start for start in first_ten_after_return if start.label == "B"]
    finally:
        world.release()
        with suppress(Exception):
            await world.gather(list(opening) + [task for task in returned])
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert a_starts == 14 and len(successes) == 38, (
        "every opening and returned dispatch completes; the native rail and the pool "
        f"envelope stayed intact ({a_starts} A starts, "
        f"{sum(project.adapter.search_calls for project in world.projects.values())} calls)"
    )
    assert served_in_first_ten >= 4, (
        f"the first ten starts after A's return served {served_in_first_ten} A dispatches; "
        "A must not be starved by its bounded idle deficit"
    )
    assert served_in_first_ten <= 5, (
        f"the first ten starts after A's return served {served_in_first_ten} A dispatches; "
        "the bounded idle deficit caps A's burst at quantum plus a bounded error; "
        f"starts={[(start.label, start.tag) for start in starts]}"
    )
    assert len(released_units) >= 5, (
        "B keeps its share when a returning project bursts against accumulated idleness"
    )


# ---------------------------------------------------------------------------
# AC4 second clause: a zero guaranteed share is served only through the
# explicit best-effort policy, never while guaranteed work stays queued.
# ---------------------------------------------------------------------------


async def test_zero_share_project_is_explicit_best_effort_and_only_served_on_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                weight=4,
                borrow_max=100,
                max_concurrency=1,
            ),
            AllocationSpec(
                label="B",
                base_rate=6,
                weight=6,
                borrow_max=100,
                max_concurrency=1,
            ),
            AllocationSpec(
                label="C",
                base_rate=0,
                weight=1,
                borrow_max=10,
                best_effort=True,
                max_concurrency=1,
            ),
        ),
    )
    world = await build_authority_world(
        tmp_path, monkeypatch, spec=spec, labels=("A", "B", "C"), native_search_second=1_000
    )
    try:
        guaranteed_a = world.submit("A", *(f"a{i}" for i in range(4)))
        guaranteed_b = world.submit("B", *(f"b{i}" for i in range(4)))
        guaranteed = list(guaranteed_a) + list(guaranteed_b)
        submitted_guaranteed = len(guaranteed)
        await world.wait_starts(2)
        await world.wait_queued("A", 3)
        await world.wait_queued("B", 3)
        best_effort = world.submit("C", *(f"c{i}" for i in range(4)))

        def never_while_guaranteed_demand() -> None:
            # The zero-share policy defers while guaranteed work is still
            # queued (never-started): already-dispatched (parked) work cannot
            # be preempted and must not be confused with queued demand.
            never_started = (
                len(guaranteed_a) - len(world.starts_of("A")),
                len(guaranteed_b) - len(world.starts_of("B")),
            )
            if any(queued > 0 for queued in never_started):
                assert world.starts_of("C") == [], (
                    "the zero-share project dispatched while guaranteed work was queued "
                    f"(C starts={len(world.starts_of('C'))}, "
                    f"guaranteed outstanding={never_started})"
                )

        successes, failures = await serve_until(
            world, guaranteed + list(best_effort), probe=never_while_guaranteed_demand
        )
        c_starts = world.starts_of("C")
        usage_c = await world.usage_rows(project_id=world.projects["C"].project_id)
        attempts_c = await world.project_attempts("C")
        del submitted_guaranteed
    finally:
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert len(successes) == 12
    assert len(c_starts) == 4, f"best effort served {len(c_starts)} starts once the pool went idle"
    assert usage_c and len(usage_c) == 4
    assert len(attempts_c) == 4, "the best-effort dispatch paid the same attempt cost"


# ---------------------------------------------------------------------------
# AC4 first clause: infeasible promised base allocations are rejected on
# every write path.
# ---------------------------------------------------------------------------


async def test_infeasible_base_allocations_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=10,
        allocations=pair(borrow_max=10, concurrency=None),  # A4 + B6 sums to 10: feasible
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        # First the feasible baseline stands (A promises 4 of a 10 pool).
        async with world.repository.session() as session:
            stored = await PoolAllocationRepository(session).get(
                project_id=world.projects["A"].project_id,
                pool_id=world.pool.id,
                operation=world.spec.operation,
            )
            assert stored is not None and stored.base_rate == 4

        # Raising B's promised share beyond the pool envelope is refused.
        async with world.repository.session() as session:
            repository = PoolAllocationRepository(session)
            refused: BaseException | None = None
            try:
                await repository.update(
                    project_id=world.projects["B"].project_id,
                    pool_id=world.pool.id,
                    operation=world.spec.operation,
                    expected_version=1,
                    base_rate=7,
                    rate_window_seconds=world.spec.window_seconds,
                    borrow_enabled=True,
                    max_rate=10,
                    weight=6,
                    best_effort=False,
                    max_concurrency=None,
                    max_queued_requests=None,
                    max_queued_bytes=None,
                    max_queue_wait_ms=None,
                )
            except BaseException as error:
                refused = error
            await session.commit() if refused is None else await session.rollback()
    finally:
        await world.aclose()

    assert refused is not None, "an infeasible base guarantee was accepted"
    assert isinstance(refused, AllocationInfeasibleError), type(refused).__name__


async def test_allocation_create_refuses_infeasible_base_promises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feasibility is a create-path invariant, not only an update-path check."""

    spec = AuthorityPoolSpec(
        limit=10,
        allocations=pair(borrow_max=10, concurrency=None),  # A4 + B6 sums to 10: feasible
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec, labels=("A", "B", "C"))
    extra = await seed_execution_project(world.repository, name="D3")
    try:
        async with world.repository.session() as session:
            repository = PoolAllocationRepository(session)
            refused: BaseException | None = None
            try:
                await repository.create(
                    project_id=extra.project_id,
                    pool_id=world.pool.id,
                    operation=world.spec.operation,
                    base_rate=5,
                    rate_window_seconds=world.spec.window_seconds,
                    granted_by=extra.actor_id,
                )
            except BaseException as error:
                refused = error
            finally:
                await session.rollback()
    finally:
        await world.aclose()

    assert refused is not None, "an allocation create overcommitting the pool was accepted"
    assert isinstance(refused, AllocationInfeasibleError), type(refused).__name__


async def test_pool_capacity_tightening_refuses_infeasible_promises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A constraint write that promises less than the standing base sum is refused."""

    spec = AuthorityPoolSpec(
        limit=10,
        allocations=pair(borrow_max=10, concurrency=None),  # A4 + B6 sums to 10
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        async with world.repository.session() as session:
            pools = UpstreamPoolRepository(session)
            refused: BaseException | None = None
            try:
                await pools.update_pool(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    pool_id=world.pool.id,
                    upstream_scope=UpstreamScope.ACCOUNT,
                    pool_key=world.pool.pool_key,
                    label=world.pool.label,
                    constraints=[
                        {
                            "kind": "rate",
                            "algorithm": "trailing_window",
                            "window": world.spec.window_seconds,
                            "limit": 9,
                        }
                    ],
                    max_concurrency=world.pool.max_concurrency,
                    max_queued_requests=world.pool.max_queued_requests,
                    status=PoolStatus.ACTIVE,
                )
            except BaseException as error:
                refused = error
            finally:
                await session.rollback()
    finally:
        await world.aclose()

    assert refused is not None, "pool capacity tightening accepted an overcommitted promise"
    assert isinstance(refused, AllocationInfeasibleError), type(refused).__name__


async def test_zero_share_requires_the_explicit_best_effort_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alpha schema refuses a zero guaranteed share without best effort."""
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=pair(borrow_max=10, concurrency=1),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        refused: IntegrityError | None = None
        async with world.repository.session() as session:
            repository = PoolAllocationRepository(session)
            try:
                await repository.create(
                    project_id=world.projects["A"].project_id,
                    pool_id=world.pool.id,
                    operation=world.spec.operation,
                    base_rate=0,
                    rate_window_seconds=world.spec.window_seconds,
                    granted_by=world.projects["A"].attribution.actor_id,
                    best_effort=False,
                )
            except BaseException as error:
                refused = error if isinstance(error, IntegrityError) else None
                if refused is None:
                    raise
            finally:
                await session.rollback()
    finally:
        await world.aclose()

    assert refused is not None, "a zero base_rate without best_effort must be refused by the schema"


# ---------------------------------------------------------------------------
# P5 cancellations, adjudicated. Canceling an ALREADY-DISPATCHED send is an
# uncertain upstream send, not a provable non-dispatch: the canceled task
# must NOT automatically free durable concurrency merely because it was
# canceled (only a settlement, an explicit release, or recovery adjudication
# ends the hold). What the cancel itself MUST do is free the scheduler's own
# in-memory slot so the queue never wedges behind the parked send. A call
# canceled while still QUEUED never holds a grant or a charge at all.
# ---------------------------------------------------------------------------


async def _bounded_condition(
    predicate: Callable[[], bool], *, timeout: float, message: Callable[[], str]
) -> None:
    """Bounded busy-wait on an in-process condition; never an unbounded block."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            pytest.fail(message())
        await asyncio.sleep(0.001)


async def test_canceling_a_dispatched_send_conserves_durable_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    settle_retired: list[asyncio.Task[Any]] = []
    try:
        granted = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("A", "a2")
        await world.wait_queued("A", 1)
        settle_retired = granted + queued

        # Cancel the granted call while its provider send is parked. The
        # attempt was already dispatched (its recovery record was written
        # before the send), so the canceled task must not make the system
        # pretend the vendor call never happened: the unknown-send outcome
        # is uncertain and the send's debit stays charged.
        granted[0].cancel()
        canceled = await asyncio.gather(*granted, return_exceptions=True)
        assert canceled and isinstance(canceled[0], BaseException), (
            f"the canceled call must not complete: {canceled!r}"
        )

        # The cancel itself must still free the queue's own in-memory slot,
        # so the scheduler hands the follow-up waiter its turn (and the
        # conservative hold below, not a hang, settles it). The narrow sync
        # peek follows the same bounded precedent as queued_waiters.
        queue: Any = world.authority._queues.get((world.pool.id, CredentialOperation.SEARCH))
        assert queue is not None, "the pool queue is missing after the cancel"
        project_id = world.projects["A"].project_id
        await _bounded_condition(
            lambda: queue._inflight.get(project_id, 0) == 0 and queue._inflight_pool == 0,
            timeout=10.0,
            message=lambda: (
                "the cancel itself must not leak the scheduler's in-memory slot "
                f"(inflight={queue._inflight.get(world.projects['A'].project_id, 0)}, "
                f"pool={queue._inflight_pool})"
            ),
        )
        follow_up: BaseException | None = None
        try:
            await asyncio.wait_for(queued[0], timeout=15.0)
        except BaseException as error:
            follow_up = error
        moves = list(world.starts)
        calls = world.projects["A"].adapter.search_calls
        attempts = await world.project_attempts("A")
        usage = await usage_event_rows(world, project_id=project_id)
        # The uncertain resolution is written off the critical path as well:
        # poll the durable rows, bounded, until the canceled attempt's record
        # reaches its recovery state before asserting on it.
        seen_rows = await world.dispatch_rows(project_id=project_id)
        loop = asyncio.get_running_loop()
        settle_deadline = loop.time() + 10.0
        while len(seen_rows) != 1 or (
            (
                seen_rows[0].state.value
                if hasattr(seen_rows[0].state, "value")
                else seen_rows[0].state
            )
            != "uncertain"
        ):
            if loop.time() > settle_deadline:
                break
            await asyncio.sleep(0.01)
            seen_rows = await world.dispatch_rows(project_id=project_id)
        rows = seen_rows
    finally:
        world.release()
        for task in settle_retired:
            if not task.done():
                task.cancel()
        with suppress(Exception):
            await asyncio.gather(*settle_retired, return_exceptions=True)
        await world.aclose()

    assert [start.tag for start in moves] == ["a1"], (
        f"the uncertain cancel must not open a second overlapping send: {moves}"
    )
    assert calls == 1, f"the canceled send's own debit stays charged (calls={calls})"
    assert follow_up is not None and isinstance(follow_up, LimitDeniedError), (
        f"the conservative hold must refuse the follow-up with the typed durable "
        f"capacity denial: {follow_up}"
    )
    assert follow_up.refusal == "rate", follow_up.refusal
    assert follow_up.status_code == 429
    assert "concurrency cap is full" in str(follow_up), str(follow_up)
    assert any("concurrent_cap" in reason for reason in follow_up.reasons), follow_up.reasons
    assert len(attempts) == 1, (
        f"the canceled uncertain send keeps its own attempt charged, and the "
        f"refused follow-up consumes none: {[row.attempt_id for row in attempts]}"
    )
    assert usage == [], (
        f"the canceled uncertain send must not settle usage of its own, and a "
        f"refused pre-send follow-up writes none: {[row.status for row in usage]}"
    )
    assert len(rows) == 1, f"only the canceled attempt carries a dispatch row: {rows}"
    assert (
        rows[0].state.value if hasattr(rows[0].state, "value") else rows[0].state
    ) == "uncertain", (
        "the canceled already-dispatched send must be resolved uncertain -- the "
        f"conservative recovery record: {rows[0].state}"
    )


async def test_canceling_a_queued_call_never_grants_or_charges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call canceled while it is still queued leaves with no grant at all.

    The canceled waiter is discarded with no dispatch, no attempt charge, no
    usage row, and no dispatch record, and the scheduler's bookkeeping
    returns to its before-submission shape so the next call is served.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4, max_concurrency=1),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6, max_concurrency=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    settle_retired: list[asyncio.Task[Any]] = []
    try:
        granted = world.submit("A", "a1")
        await world.wait_starts(1)
        queued = world.submit("A", "a2")
        await world.wait_queued("A", 1)
        settle_retired = granted + queued

        # Cancel the queued call while the only concurrency slot is still
        # held by the parked a1 send: the waiter cannot be granted before the
        # cancel, so the pre-grant cancel is deterministic.
        queued[0].cancel()
        with suppress(asyncio.CancelledError, Exception):
            await queued[0]
        assert world.queued_waiters("A") == 0, (
            "the canceled queued call must leave the queue immediately"
        )
        successes, failures = await serve_until(world, granted, timeout=15.0)
        follow = world.submit("A", "a3")
        follow_ok, follow_failures = await serve_until(world, follow, timeout=15.0)

        attempts = await world.project_attempts("A")
        usage = await usage_event_rows(world, project_id=world.projects["A"].project_id)
        # The dispatch rows resolve off the request's critical path: poll the
        # durable rows bounded until the served sends' records settle, so the
        # assertion reads the settled state rather than racing the writer.
        seen_rows = await world.dispatch_rows(project_id=world.projects["A"].project_id)
        loop = asyncio.get_running_loop()
        settle_deadline = loop.time() + 10.0
        while len(seen_rows) != 2 or not all(
            (row.state.value if hasattr(row.state, "value") else row.state) == "completed"
            for row in seen_rows
        ):
            if loop.time() > settle_deadline:
                break
            await asyncio.sleep(0.01)
            seen_rows = await world.dispatch_rows(project_id=world.projects["A"].project_id)
        rows = seen_rows
        moves = list(world.starts)
        calls = world.projects["A"].adapter.search_calls
    finally:
        world.release()
        for task in settle_retired:
            if not task.done():
                task.cancel()
        with suppress(Exception):
            await asyncio.gather(*settle_retired, return_exceptions=True)
        await world.aclose()

    assert not failures and [response.provider for response in successes] == ["exa"], (
        f"the parked send must still complete around the canceled waiter "
        f"(successes={successes}, failures={failures})"
    )
    assert not follow_failures and len(follow_ok) == 1, (
        f"a canceled queued call must not wedge the queue behind the next waiter "
        f"(follow_ok={follow_ok}, follow_failures={follow_failures})"
    )
    assert [start.tag for start in moves] == ["a1", "a3"], (
        f"the canceled queued call was never granted: {moves}"
    )
    assert calls == 2, f"the canceled call never reached the provider (calls={calls})"
    assert len(attempts) == 2, (
        f"the canceled queued call consumed no rate attempt: {[row.attempt_id for row in attempts]}"
    )
    assert len(usage) == 2, f"the canceled queued call wrote no usage (rows={len(usage)})"
    assert len(rows) == 2, f"only the two served sends carry dispatch rows: {rows}"
    assert all(
        (row.state.value if hasattr(row.state, "value") else row.state) == "completed"
        for row in rows
    ), f"both served sends completed cleanly: {[row.state for row in rows]}"
