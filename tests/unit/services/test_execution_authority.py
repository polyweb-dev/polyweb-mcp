"""Queue accounting at simultaneous admission boundaries, without provider I/O."""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest

from polyweb.models.credentials import CredentialOperation
from polyweb.models.execution_failures import (
    ExecutionAuthorityUnavailable,
    ExecutionQueueExpired,
    ExecutionQueueSaturated,
)
from polyweb.services.execution_authority import (
    DispatchGrant,
    ExecutionAuthority,
    QueuePolicy,
    _PoolQueue,
    _QueueBudget,
)

# ---------------------------------------------------------------------------
# A3 planner boundary manifest (TASK-000045, extra correction loop).
#
# Every case below locks one ownership-boundary invariant of the frozen
# production implementation at head ef6b07b: a grant owns local concurrency,
# the waiting ledger owns admission and queued work, and the two never touch
# the same counter twice. Each handoff (grant, delivery, cancellation, failur
# e, shutdown) releases ownership exactly once. Cases synchronize on loop
# events, futures, and narrow private queue state; no test framework is
# added beyond plain asyncio helpers.
# ---------------------------------------------------------------------------


class _Clock:
    """Deterministic monotonic clock the tests advance explicitly."""

    __slots__ = ("seconds",)

    def __init__(self, seconds: float = 0.0) -> None:
        self.seconds = seconds

    def __call__(self) -> float:
        return self.seconds

    def advance(self, addition: float) -> None:
        self.seconds += max(0.0, addition)


class _SendHook:
    """Recording attempt seam for one queued request.

    It accepts the delivered grant (``started``), parks until released, and
    releases the concurrency slot at settlement exactly like the real
    reservation handoff. Tests cancel the owning task to reach the cleanup
    windows inside and outside the park.
    """

    __slots__ = ("calls", "released")

    def __init__(self) -> None:
        self.calls: list[DispatchGrant] = []
        self.released = asyncio.Event()

    async def __call__(self, grant: DispatchGrant) -> str:
        self.calls.append(grant)
        grant.started.set()
        await self.released.wait()
        grant.finish()
        return "ok"


async def _failing_send(grant: DispatchGrant) -> str:
    """Accepted attempt whose preparation fails before any send."""

    grant.started.set()
    raise ValueError("preparation failed before any send")


def _failing_admission() -> None:
    """Admission callback that raises before the request first awaits."""

    raise ValueError("admission callback failed")


def _policy(
    project_id: UUID | None = None,
    *,
    operation: CredentialOperation = CredentialOperation.SEARCH,
    payload_bytes: int = 0,
    weight: int = 1,
    base_rate: int = 100,
    max_rate: int | None = None,
    borrow_enabled: bool = False,
    best_effort: bool = False,
    max_concurrency: int | None = None,
    max_queued_requests: int | None = None,
    max_queued_bytes: int | None = None,
    max_queue_wait_ms: int | None = None,
    pool_max_concurrency: int | None = None,
    pool_max_queued_requests: int | None = None,
    project_max_concurrency: int | None = None,
    deadline: float | None = None,
    admitted_at: float | None = None,
    not_before: float | None = None,
    on_admitted: Callable[[], None] | None = None,
) -> QueuePolicy:
    """One strict (or explicitly opted-in) queue policy for this unit."""

    return QueuePolicy(
        provider="unit",
        project_id=project_id if project_id is not None else uuid4(),
        operation=operation,
        weight=weight,
        base_rate=base_rate,
        rate_window_seconds=60,
        max_rate=max_rate,
        borrow_enabled=borrow_enabled,
        best_effort=best_effort,
        max_concurrency=max_concurrency,
        max_queued_requests=max_queued_requests,
        max_queued_bytes=max_queued_bytes,
        max_queue_wait_ms=max_queue_wait_ms,
        pool_max_concurrency=pool_max_concurrency,
        pool_max_queued_requests=pool_max_queued_requests,
        project_max_concurrency=project_max_concurrency,
        payload_bytes=payload_bytes,
        deadline=deadline,
        admitted_at=admitted_at,
        not_before=not_before,
        on_admitted=on_admitted,
    )


def _queue(
    monotonic: Callable[[], float],
    budget: _QueueBudget,
) -> _PoolQueue:
    """Build one pool scheduler over the given (possibly shared) budget."""

    return _PoolQueue(
        pool_id=uuid4(),
        operation=CredentialOperation.SEARCH,
        monotonic=monotonic,
        default_max_wait_ms=5_000,
        default_max_requests=budget.default_max_requests,
        default_max_bytes=budget.default_max_bytes,
        budget=budget,
    )


async def _settle(
    condition: Callable[[], bool],
    subject: str,
    *,
    timeout: float = 2.0,
) -> None:
    """Bounded wait for a loop-native condition; never wait without bound."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError(
                f"{subject} did not settle within {timeout:.1f}s; "
                "the ownership boundary did not converge"
            )
        await asyncio.sleep(0.001)


def _pending(queue: _PoolQueue, project_id: UUID) -> int:
    """Return a project's queued-waiter count without raising early."""

    state = queue._projects.get(project_id)
    return 0 if state is None else len(state.pending)


async def _reclaim(
    tasks: list[asyncio.Task[Any]],
    hooks: list[_SendHook | None],
    queues: list[_PoolQueue],
) -> None:
    """Cancel, settle, and close every test artifact; never raises.

    Entries of ``hooks`` may be ``None`` for submissions that refused or
    failed before their recorded seam could ever park.
    """

    for hook in hooks:
        if isinstance(hook, _SendHook):
            hook.released.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for queue in queues:
        queue.close()
    runners = [queue._runner for queue in queues if queue._runner is not None]
    await asyncio.gather(*runners, return_exceptions=True)


def _assert_no_ownership_leak(
    budget: _QueueBudget,
    queues: list[_PoolQueue],
    scene: str,
) -> None:
    """Require every counter back at exact zero after full cleanup."""

    assert budget.inflight == 0, f"{scene}: concurrency slot leaked ({budget.inflight})"
    assert budget.project_inflight == {}, f"{scene}: project slot leaked"
    assert budget.total_waiting_count == 0, f"{scene}: waiting count leaked"
    assert budget.total_waiting_bytes == 0, f"{scene}: waiting bytes leaked"
    for queue in queues:
        assert queue._staged is None, f"{scene}: staged grant leaked in {queue.pool_id}"
        leak = [state for state in queue._projects.values() if state.pending]
        assert not leak, f"{scene}: pending waiters leaked in {queue.pool_id}"


async def test_simultaneous_idle_pools_cannot_share_one_free_dispatch_slot() -> None:
    """Only one head can own the free slot; all other heads need queue budget."""

    budget = _QueueBudget(
        default_max_requests=1,
        default_max_bytes=1000,
        max_concurrency=1,
        project_max_concurrency=1,
    )
    queues = [
        _PoolQueue(
            pool_id=uuid4(),
            operation=CredentialOperation.SEARCH,
            monotonic=lambda: 0.0,
            default_max_wait_ms=5000,
            default_max_requests=1,
            default_max_bytes=1000,
            budget=budget,
        )
        for _ in range(5)
    ]
    started = asyncio.Event()
    release = asyncio.Event()

    async def send(grant: DispatchGrant) -> None:
        grant.started.set()
        started.set()
        try:
            await release.wait()
        finally:
            grant.finish()

    tasks = []
    try:
        for queue in queues:
            policy = QueuePolicy(
                provider="unit",
                project_id=uuid4(),
                operation=CredentialOperation.SEARCH,
                weight=1,
                base_rate=100,
                rate_window_seconds=60,
                max_rate=None,
                borrow_enabled=False,
                best_effort=False,
                max_concurrency=None,
                max_queued_requests=None,
                max_queued_bytes=None,
                max_queue_wait_ms=None,
                pool_max_concurrency=None,
                pool_max_queued_requests=None,
                payload_bytes=600,
            )
            tasks.append(asyncio.create_task(queue.submit(policy, send)))
        await asyncio.wait_for(started.wait(), timeout=2)
        pending = sum(len(state.pending) for queue in queues for state in queue._projects.values())
        assert budget.inflight == 1
        assert pending <= 1, (
            f"one active slot and one queue slot admitted {pending} waiting calls; "
            f"published bytes={budget.total_waiting_bytes}"
        )
        assert budget.total_waiting_count == pending
        assert budget.total_waiting_bytes <= 1000
        refusals = [task for task in tasks if task.done() and task.exception() is not None]
        assert len(refusals) == 3
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for queue in queues:
            queue.close()


async def test_started_predecessor_allows_same_pool_free_slot_before_runner_resumes() -> None:
    """A completed start barrier is independent of the active grant's lifetime."""

    budget = _QueueBudget(
        default_max_requests=0,
        default_max_bytes=0,
        max_concurrency=2,
        project_max_concurrency=2,
    )
    queue = _queue(_Clock(), budget)
    policy = _policy(max_queued_requests=0, pool_max_queued_requests=0)
    tasks: list[asyncio.Task[Any]] = []
    grants: list[DispatchGrant] = []

    async def second(grant: DispatchGrant) -> str:
        grants.append(grant)
        grant.started.set()
        try:
            assert budget.inflight == 2
            assert budget.project_inflight[policy.project_id] == 2
            assert budget.total_waiting_count == 0
            assert not grants[0]._finished, "clearing the barrier must not settle its owner"
            return "second"
        finally:
            grant.finish()

    async def first(grant: DispatchGrant) -> str:
        grants.append(grant)
        assert queue._staged is not None and queue._staged.dispatch is grant
        assert grant._accepted
        grant.started.set()
        try:
            # No yield before the nested admission: the runner still holds
            # the predecessor's staged barrier despite its completed start.
            result = await queue.submit(policy, second)
            assert budget.inflight == 1
            assert not grant._finished
            return result
        finally:
            grant.finish()

    try:
        task = asyncio.create_task(queue.submit(policy, first))
        tasks.append(task)
        assert await asyncio.wait_for(task, timeout=2) == "second"
        assert len(grants) == 2
    finally:
        await _reclaim(tasks, [], [queue])
    _assert_no_ownership_leak(budget, [queue], "completed start barrier")


# ---------------------------------------------------------------------------
# Ownership boundary: occupied capacity, scoped bounds, zero-bound bytes.
# ---------------------------------------------------------------------------


async def test_occupied_capacity_keeps_its_owner_while_a_waiter_queues_and_rest_refuse() -> None:
    """One extra waiting request succeeds; the next refuses; ownership stays."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=1,
        default_max_bytes=2_000,
        max_concurrency=1,
        project_max_concurrency=1,
    )
    queue = _queue(clock, budget)
    owner, waiter, refused = _policy(), _policy(payload_bytes=600), _policy()
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        tasks.append(asyncio.create_task(queue.submit(owner, owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the first grant was never delivered")
        owner_hook.calls[0].started.set()

        waiter_hook = _SendHook()
        hooks.append(waiter_hook)
        tasks.append(asyncio.create_task(queue.submit(waiter, waiter_hook)))
        await _settle(
            lambda: _pending(queue, waiter.project_id) == 1 and budget.total_waiting_count == 1,
            "the second request did not queue behind the occupied capacity",
        )
        assert budget.total_waiting_bytes == 600
        assert budget.inflight == 1

        refused_task = asyncio.create_task(queue.submit(refused, _SendHook()))
        hooks.append(None)  # imports of _reclaim tolerate None for refused seams
        tasks.append(refused_task)
        await _settle(refused_task.done, "the bound refusal never settled")
        error = refused_task.exception()
        assert isinstance(error, ExecutionQueueSaturated), type(error).__name__

        # The active owner is untouched by both the queue entry and refusal.
        assert budget.inflight == 1
        assert budget.project_inflight[owner.project_id] == 1
        assert len(owner_hook.calls) == 1
        assert queue._staged is None, "a bound-refused waiter must never be staged"
        assert not queue._projects[refused.project_id].pending, "the refused waiter leaked"
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "occupied-capacity point")


async def test_same_project_shares_project_bounds_across_two_pools() -> None:
    """One project's concurrency and queued bounds hold across pool queues."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=2,
        default_max_bytes=2_000,
        max_concurrency=2,
        project_max_concurrency=1,
    )
    first = _queue(clock, budget)
    second = _queue(clock, budget)
    project = uuid4()
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    queues = [first, second]
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        tasks.append(
            asyncio.create_task(first.submit(_policy(project, max_queued_requests=1), owner_hook))
        )
        await _settle(lambda: len(owner_hook.calls) == 1, "the pool-one grant was never delivered")

        sibling_priority = _SendHook()
        hooks.append(sibling_priority)
        tasks.append(
            asyncio.create_task(
                second.submit(
                    _policy(project, payload_bytes=600, max_queued_requests=1), sibling_priority
                )
            )
        )
        await _settle(
            lambda: _pending(second, project) == 1,
            "the same project queued through the second pool",
        )
        assert budget.project_waiting_count[project] == 1
        assert budget.project_waiting_bytes[project] == 600
        assert budget.project_inflight[project] == 1
        assert budget.inflight == 1, "the shared project cap was bypassed through the second pool"
        assert second._staged is None

        overflow = asyncio.create_task(
            first.submit(_policy(project, max_queued_requests=1), _SendHook())
        )
        hooks.append(None)
        tasks.append(overflow)
        await _settle(overflow.done, "the project-bound refusal never settled")
        error = overflow.exception()
        assert isinstance(error, ExecutionQueueSaturated), type(error).__name__
        assert budget.project_waiting_count[project] == 1, "the refused waiter was accounted"
    finally:
        await _reclaim(tasks, hooks, queues)
    _assert_no_ownership_leak(budget, queues, "same-project-across-pools point")


async def test_authority_totals_apply_across_project_identities() -> None:
    """Distinct projects cannot sidestep the authority-wide waiting count."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=1,
        default_max_bytes=2_000,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        tasks.append(asyncio.create_task(queue.submit(_policy(), owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the first grant was never delivered")

        sibling_hook = _SendHook()
        hooks.append(sibling_hook)
        sibling = _policy()
        tasks.append(asyncio.create_task(queue.submit(sibling, sibling_hook)))
        await _settle(
            lambda: _pending(queue, sibling.project_id) == 1,
            "the second project did not queue on the shared authority total",
        )
        assert budget.total_waiting_count == 1

        refused_task = asyncio.create_task(queue.submit(_policy(), _SendHook()))
        hooks.append(None)
        tasks.append(refused_task)
        await _settle(refused_task.done, "the authority-bound refusal never settled")
        error = refused_task.exception()
        assert isinstance(error, ExecutionQueueSaturated), type(error).__name__
        assert budget.total_waiting_count == 1
        assert budget.inflight == 1
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "authority-total point")


async def test_full_waiting_budget_leaves_free_capacity_for_another_pool() -> None:
    """A grant consumes no waiting allowance even when the waiting budget is full."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=1,
        default_max_bytes=2_000,
        max_concurrency=2,
        project_max_concurrency=1,
    )
    first = _queue(clock, budget)
    second = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    queues = [first, second]
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        owner = _policy()
        tasks.append(asyncio.create_task(first.submit(owner, owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the pool-one grant was never delivered")

        backlog_hook = _SendHook()
        hooks.append(backlog_hook)
        backlog = _policy(project_id=owner.project_id, payload_bytes=600)
        tasks.append(asyncio.create_task(first.submit(backlog, backlog_hook)))
        await _settle(
            lambda: budget.total_waiting_count == 1 and budget.total_waiting_bytes == 600,
            "the project-capped overflow did not fill the waiting budget",
        )

        # A different project on another pool acquires the genuinely free slot
        # synchronously: grants never need, nor consume, waiting allowance.
        independent_hook = _SendHook()
        hooks.append(independent_hook)
        independent = _policy()
        tasks.append(asyncio.create_task(second.submit(independent, independent_hook)))
        await _settle(
            lambda: len(independent_hook.calls) == 1,
            "the free slot was not granted to the independent pool",
        )
        assert budget.inflight == 2
        assert budget.total_waiting_count == 1, "the grant consumed waiting allowance"
        assert budget.total_waiting_bytes == 600
        assert budget.project_inflight == {owner.project_id: 1, independent.project_id: 1}

        tail = asyncio.create_task(second.submit(_policy(), _SendHook()))
        hooks.append(None)
        tasks.append(tail)
        await _settle(tail.done, "the full-budget refusal never settled")
        assert isinstance(tail.exception(), ExecutionQueueSaturated), type(
            tail.exception()
        ).__name__
        assert budget.total_waiting_count == 1 and budget.total_waiting_bytes == 600
        assert budget.inflight == 2
    finally:
        await _reclaim(tasks, hooks, queues)
    _assert_no_ownership_leak(budget, queues, "independent-capacity point")


async def test_large_pool_override_cannot_widen_the_authority_bound() -> None:
    """A permissive pool bound stays inside the authority-wide waiting count."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=1,
        default_max_bytes=2_000,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        tasks.append(asyncio.create_task(queue.submit(_policy(), owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the first grant was never delivered")

        backlog_hook = _SendHook()
        hooks.append(backlog_hook)
        backlog = _policy(max_queued_requests=50, pool_max_queued_requests=50)
        tasks.append(asyncio.create_task(queue.submit(backlog, backlog_hook)))
        await _settle(
            lambda: budget.total_waiting_count == 1,
            "the permissive pool bound did not queue behind occupied capacity",
        )

        refused_task = asyncio.create_task(
            queue.submit(_policy(max_queued_requests=50, pool_max_queued_requests=50), _SendHook())
        )
        hooks.append(None)
        tasks.append(refused_task)
        await _settle(refused_task.done, "the override-widening refusal never settled")
        assert isinstance(refused_task.exception(), ExecutionQueueSaturated), type(
            refused_task.exception()
        ).__name__
        assert budget.total_waiting_count == 1, "the refused waiter joined the ledger"
        assert budget.inflight == 1
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "pool-override point")


async def test_unrelated_pool_backlog_never_consumes_a_pools_local_allowance() -> None:
    """Pool totals use that pool's own entries and stay within its own bound."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=5,
        default_max_bytes=10_000,
        max_concurrency=2,
        project_max_concurrency=1,
    )
    first = _queue(clock, budget)
    second = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    queues = [first, second]
    try:
        # Two grants occupy both concurrency slots.
        for slot in (0, 1):
            queue_for = queues[slot]
            hook = _SendHook()
            hooks.append(hook)
            tasks.append(asyncio.create_task(queue_for.submit(_policy(), hook)))
            await _settle(
                lambda position=slot: len(hooks[position].calls) == 1,
                f"grant number {slot + 1} was never delivered",
            )

        # Two backlogs: one local to pool one, two unrelated in pool two.
        for pool_queue, entries, pool_bound in ((first, 1, 2), (second, 2, 10)):
            for _ in range(entries):
                hook = _SendHook()
                hooks.append(hook)
                tasks.append(
                    asyncio.create_task(
                        pool_queue.submit(_policy(pool_max_queued_requests=pool_bound), hook)
                    )
                )
        await _settle(
            lambda: budget.total_waiting_count == 3,
            "the two pools did not accumulate three queued entries",
        )
        assert budget.total_waiting_count == 3

        # Pool one is at its own complete allowance; one more entry fits ONLY
        # because pool two's backlog is nobody else's ledger. Under the
        # consumed-allowance defect this entry was refused.
        local_hook = _SendHook()
        hooks.append(local_hook)
        local = _policy(pool_max_queued_requests=2)
        tasks.append(asyncio.create_task(first.submit(local, local_hook)))
        await _settle(
            lambda: budget.total_waiting_count == 4,
            "the unrelated pool backlog consumed pool one's local allowance",
        )
        assert len(first._projects[local.project_id].pending) == 1

        # Pool one is genuinely full for its own bound now.
        refused_task = asyncio.create_task(
            first.submit(_policy(pool_max_queued_requests=2), _SendHook())
        )
        hooks.append(None)
        tasks.append(refused_task)
        await _settle(refused_task.done, "the pool-local bound refusal never settled")
        assert isinstance(refused_task.exception(), ExecutionQueueSaturated), type(
            refused_task.exception()
        ).__name__
        assert budget.total_waiting_count == 4, "the refused waiter joined the ledger"
    finally:
        await _reclaim(tasks, hooks, queues)
    _assert_no_ownership_leak(budget, queues, "pool-local-allowance point")


@pytest.mark.parametrize("bound", ["project", "pool", "authority"])
async def test_zero_waiting_count_bounds_admit_only_actual_grants(bound: str) -> None:
    """A zero bound allows immediate grants and refuses every real wait."""

    clock = _Clock()
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    queues: list[_PoolQueue] = []
    try:
        if bound == "authority":
            budget = _QueueBudget(
                default_max_requests=0,
                default_max_bytes=5_000,
                max_concurrency=2,
                project_max_concurrency=1,
            )
            first = _queue(clock, budget)
            second = _queue(clock, budget)
            queues = [first, second]
            for hook_slot in (0, 1):
                hook = _SendHook()
                hooks.append(hook)
                tasks.append(asyncio.create_task(queues[hook_slot].submit(_policy(), hook)))
                await _settle(
                    lambda slot=hook_slot: len(hooks[slot].calls) == 1,
                    f"the grant number {hook_slot + 1} never delivered despite the zero bound",
                )
            assert budget.total_waiting_count == 0
            blocked = asyncio.create_task(first.submit(_policy(), _SendHook()))
            hooks.append(None)
            subject = f"authority-zero({bound})"
        elif bound == "pool":
            budget = _QueueBudget(
                default_max_requests=4,
                default_max_bytes=5_000,
                max_concurrency=1,
                project_max_concurrency=4,
            )
            first = _queue(clock, budget)
            queues = [first]
            owner_hook = _SendHook()
            hooks.append(owner_hook)
            tasks.append(
                asyncio.create_task(first.submit(_policy(pool_max_queued_requests=0), owner_hook))
            )
            await _settle(
                lambda: len(owner_hook.calls) == 1,
                "the grant never delivered despite the zero pool bound",
            )
            blocked = asyncio.create_task(
                first.submit(_policy(pool_max_queued_requests=0), _SendHook())
            )
            hooks.append(None)
            subject = "pool-zero"
        else:
            budget = _QueueBudget(
                default_max_requests=4,
                default_max_bytes=5_000,
                max_concurrency=1,
                project_max_concurrency=1,
            )
            first = _queue(clock, budget)
            queues = [first]
            owner = _policy(max_queued_requests=0)
            owner_hook = _SendHook()
            hooks.append(owner_hook)
            tasks.append(asyncio.create_task(first.submit(owner, owner_hook)))
            await _settle(
                lambda: len(owner_hook.calls) == 1,
                "the grant never delivered despite the zero project bound",
            )
            blocked = asyncio.create_task(
                first.submit(
                    _policy(project_id=owner.project_id, max_queued_requests=0), _SendHook()
                )
            )
            hooks.append(None)
            subject = "project-zero"
        tasks.append(blocked)
        await _settle(blocked.done, f"the {subject} refusal never settled")
        assert isinstance(blocked.exception(), ExecutionQueueSaturated), type(
            blocked.exception()
        ).__name__
        assert budget.total_waiting_count == 0, "a real wait was admitted past a zero bound"
        assert budget.total_waiting_bytes == 0
        assert budget.inflight > 0, "the zero bound refused a legitimate actual grant"
    finally:
        await _reclaim(tasks, hooks, queues)
    _assert_no_ownership_leak(budget, queues, f"zero-bound-{bound} point")


async def test_queue_byte_boundary_fits_600_plus_400_and_refuses_one_more() -> None:
    """Waiting payloads accumulate to the byte bound; active payloads are exempt."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=5,
        default_max_bytes=1_000,
        max_concurrency=1,
        project_max_concurrency=1,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        owner = _policy(payload_bytes=600)
        tasks.append(asyncio.create_task(queue.submit(owner, owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the first grant was never delivered")
        assert budget.total_waiting_bytes == 0, "the active payload double-counted"

        for payload in (600, 400):
            hook = _SendHook()
            hooks.append(hook)
            tasks.append(
                asyncio.create_task(
                    queue.submit(_policy(project_id=owner.project_id, payload_bytes=payload), hook)
                )
            )
        await _settle(
            lambda: budget.total_waiting_bytes == 1_000,
            "the 600 and 400 payload waiters did not fill the byte bound",
        )
        assert budget.total_waiting_count == 2
        assert budget.inflight == 1

        refused_task = asyncio.create_task(
            queue.submit(_policy(project_id=owner.project_id, payload_bytes=1), _SendHook())
        )
        hooks.append(None)
        tasks.append(refused_task)
        await _settle(refused_task.done, "the one-over-byte refusal never settled")
        assert isinstance(refused_task.exception(), ExecutionQueueSaturated), type(
            refused_task.exception()
        ).__name__
        assert budget.total_waiting_bytes == 1_000
        assert budget.total_waiting_count == 2
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "byte-boundary point")


async def test_zero_byte_allowance_queues_only_zero_payload_waiters() -> None:
    """With count room, a zero-byte bound queues empty payloads and refuses more."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=5,
        default_max_bytes=0,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        tasks.append(asyncio.create_task(queue.submit(_policy(payload_bytes=600), owner_hook)))
        await _settle(lambda: len(owner_hook.calls) == 1, "the first grant was never delivered")

        empty_hook = _SendHook()
        hooks.append(empty_hook)
        empty = _policy()
        tasks.append(asyncio.create_task(queue.submit(empty, empty_hook)))
        await _settle(
            lambda: _pending(queue, empty.project_id) == 1,
            "the zero-payload waiter was refused by a zero-byte bound that fits it",
        )
        assert budget.total_waiting_count == 1
        assert budget.total_waiting_bytes == 0

        refused_task = asyncio.create_task(queue.submit(_policy(payload_bytes=1), _SendHook()))
        hooks.append(None)
        tasks.append(refused_task)
        await _settle(refused_task.done, "the one-byte refusal never settled")
        assert isinstance(refused_task.exception(), ExecutionQueueSaturated), type(
            refused_task.exception()
        ).__name__
        assert budget.total_waiting_count == 1
        assert budget.total_waiting_bytes == 0
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "zero-byte point")


# ---------------------------------------------------------------------------
# Ownership handoffs: cancellation windows, failures, retry eligibility,
# operation aliases, best-effort ownership, and shutdown.
# ---------------------------------------------------------------------------


async def test_canceling_a_grant_before_delivery_returns_ownership_once() -> None:
    """A staged candidate canceled before delivery releases its slot once."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=4,
        default_max_bytes=2_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hook = _SendHook()
    tasks: list[asyncio.Task[Any]] = []
    hooks: list[_SendHook] = []
    try:
        task = asyncio.create_task(queue.submit(_policy(), hook))
        hooks.append(hook)
        tasks.append(task)
        await asyncio.sleep(0)  # one loop step: admission staged the actual grant
        assert queue._staged is not None, "admission never staged the candidate grant"
        assert budget.inflight == 1, "the staged grant did not own its slot synchronously"
        grant = queue._staged.dispatch
        assert not grant._accepted
        assert hook.calls == []

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled(), "the canceled admission did not surface CancelledError"
        assert hook.calls == [], "the attempt callback ran for a canceled admission"
        assert grant._finished, "the staged grant was never finished"
        assert budget.inflight == 0, "the canceled grant kept its slot"
        assert queue._staged is None
        assert queue._inflight_pool == 0

        # The queue stays healthy: the next request is granted normally.
        follow_hook = _SendHook()
        hooks.append(follow_hook)
        follow = asyncio.create_task(queue.submit(_policy(), follow_hook))
        tasks.append(follow)
        await _settle(lambda: len(follow_hook.calls) == 1, "the follow-up grant never delivered")
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "cancel-before-delivery point")


async def test_canceling_a_delivered_grant_before_acceptance_finishes_it_once() -> None:
    """A delivered but unaccepted grant canceled by its owner releases once."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=4,
        default_max_bytes=2_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hook = _SendHook()
    tasks: list[asyncio.Task[Any]] = []
    hooks: list[_SendHook] = []
    try:
        task = asyncio.create_task(queue.submit(_policy(), hook))
        hooks.append(hook)
        tasks.append(task)
        await asyncio.sleep(0)  # admission stage
        await asyncio.sleep(0)  # scheduler delivery
        assert queue._staged is not None, "the scheduler never delivered the staged grant"
        assert queue._staged.waiter.future.done(), "the grant result was never published"
        grant = queue._staged.dispatch
        assert not grant._accepted, "the grant was accepted before resumption"
        assert hook.calls == []

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert hook.calls == [], "the attempt callback ran for a canceled delivered grant"
        assert grant._finished, "the delivered grant was never finished"
        assert budget.inflight == 0, "the delivered grant kept its slot"
        assert queue._staged is None
        assert budget.project_inflight == {}

        follow_hook = _SendHook()
        hooks.append(follow_hook)
        follow = asyncio.create_task(queue.submit(_policy(), follow_hook))
        tasks.append(follow)
        await _settle(lambda: len(follow_hook.calls) == 1, "the follow-up grant never delivered")
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "cancel-after-delivery point")


async def test_admission_callback_failure_returns_every_counter() -> None:
    """A failing admission callback cleans up even before the first await."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=4,
        default_max_bytes=2_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        failed = asyncio.create_task(
            queue.submit(_policy(on_admitted=_failing_admission), _SendHook())
        )
        hooks.append(None)
        tasks.append(failed)
        await _settle(failed.done, "the admission failure never settled")
        assert isinstance(failed.exception(), ValueError), type(failed.exception()).__name__
        assert budget.inflight == 0, "the failed admission kept its grant slot"
        assert budget.total_waiting_count == 0, "the failed admission kept waiting ownership"
        assert budget.total_waiting_bytes == 0
        assert queue._staged is None
        assert queue._runner is None or queue._runner.done(), "a runner leaked after failure"

        retry_hook = _SendHook()
        hooks.append(retry_hook)
        retry = asyncio.create_task(queue.submit(_policy(), retry_hook))
        tasks.append(retry)
        await _settle(
            lambda: len(retry_hook.calls) == 1, "the queue wedged after its callback failure"
        )
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "admission-callback point")


async def test_preparation_failure_releases_the_grant_slot_exactly_once() -> None:
    """A failing attempt after acceptance reopens the slot for the next request."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=4,
        default_max_bytes=2_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        failed = asyncio.create_task(queue.submit(_policy(), _failing_send))
        hooks.append(None)
        tasks.append(failed)
        await _settle(failed.done, "the preparation failure never settled")
        assert isinstance(failed.exception(), ValueError), type(failed.exception()).__name__
        assert budget.inflight == 0, "the failed attempt kept its slot"
        assert budget.project_inflight == {}

        retry_hook = _SendHook()
        hooks.append(retry_hook)
        retry = asyncio.create_task(queue.submit(_policy(), retry_hook))
        tasks.append(retry)
        await _settle(
            lambda: len(retry_hook.calls) == 1, "the slot was not reusable after the failure"
        )
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "preparation-failure point")


async def test_delayed_retry_waits_counted_then_reenters_drr_deadline_wins() -> None:
    """A Retry-After waiter owns no capacity, then is served on DRR when due."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        retry_hook = _SendHook()
        hooks.append(retry_hook)
        retry_policy = _policy(not_before=clock() + 2.0)
        retry_task = asyncio.create_task(queue.submit(retry_policy, retry_hook))
        tasks.append(retry_task)
        await _settle(
            lambda: budget.total_waiting_count == 1,
            "the sleeping retry was not counted as waiting work",
        )
        assert budget.inflight == 0, "the sleeping retry owned capacity"
        assert queue._staged is None

        unrelated_hook = _SendHook()
        hooks.append(unrelated_hook)
        unrelated_task = asyncio.create_task(queue.submit(_policy(), unrelated_hook))
        tasks.append(unrelated_task)
        await _settle(
            lambda: len(unrelated_hook.calls) == 1,
            "the sleeping retry blocked unrelated progress",
        )
        assert budget.inflight == 1
        assert len(queue._projects[retry_policy.project_id].pending) == 1

        clock.advance(2.5)
        unrelated_hook.released.set()
        await _settle(lambda: len(retry_hook.calls) == 1, "the retry never reentered DRR")
        assert len(unrelated_hook.calls) == 1
        assert retry_hook.calls[0]._finished is False

        # An absolute logical deadline beats a retry delay: the work expires.
        late_hook = _SendHook()
        hooks.append(late_hook)
        late_policy = _policy(not_before=clock() + 100.0, deadline=clock() + 0.5)
        late_task = asyncio.create_task(queue.submit(late_policy, late_hook))
        tasks.append(late_task)
        await _settle(
            lambda: budget.total_waiting_count == 1,
            "the deadline-blocked retry was not counted while waiting",
        )
        clock.advance(0.6)
        await _settle(late_task.done, "the deadline-blocked retry never expired while sleeping")
        assert isinstance(late_task.exception(), ExecutionQueueExpired), type(
            late_task.exception()
        ).__name__
        assert late_hook.calls == [], "the deadline-blocked retry was granted or sent"
        assert budget.total_waiting_count == 0, "the expired retry kept waiting ownership"
        assert budget.inflight == 1, "the accepted retry lost its slot"
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "retry point")


async def test_search_and_fetch_alias_one_queue_per_pool() -> None:
    """Both operations share one scheduler, pool counters, and fair order."""

    authority = ExecutionAuthority(None, default_max_concurrency=1, default_max_requests=8)
    budget = authority._budget
    pool_id = uuid4()
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        search_hook = _SendHook()
        hooks.append(search_hook)
        search_task = asyncio.create_task(
            authority.submit(
                pool_id=pool_id,
                operation=CredentialOperation.SEARCH,
                policy=_policy(),
                attempt=search_hook,
            )
        )
        tasks.append(search_task)
        await _settle(lambda: len(search_hook.calls) == 1, "the search alias grant never delivered")
        search_queue = authority._queues[(pool_id, CredentialOperation.SEARCH)]
        fetch_queue = authority._queues[(pool_id, CredentialOperation.FETCH)]
        assert search_queue is fetch_queue, "the operations raced in independent queues"
        assert len(authority._pool_queues) == 1
        assert search_queue._inflight_pool == 1, "the aliases kept split pool counters"

        fetch_hook = _SendHook()
        hooks.append(fetch_hook)
        fetch_task = asyncio.create_task(
            authority.submit(
                pool_id=pool_id,
                operation=CredentialOperation.FETCH,
                policy=_policy(),
                attempt=fetch_hook,
            )
        )
        tasks.append(fetch_task)
        await _settle(
            lambda: budget.total_waiting_count == 1,
            "the fetch alias did not queue on the shared scheduler",
        )
        assert search_queue._inflight_pool == 1

        search_hook.released.set()
        await _settle(lambda: len(fetch_hook.calls) == 1, "the fetch alias never got its turn")
        assert len(search_hook.calls) == 1

        # A closed authority rejects new submissions immediately (same guard
        # ``aclose`` would apply; set narrowly instead of leasing a database).
        authority._closed = True
        with pytest.raises(ExecutionAuthorityUnavailable):
            authority.submit(
                pool_id=pool_id,
                operation=CredentialOperation.SEARCH,
                policy=_policy(),
                attempt=_SendHook(),
            )
    finally:
        search_queue_close = authority._pool_queues.get(pool_id)
        if search_queue_close is not None:
            search_queue_close.close()
        await _reclaim(tasks, hooks, [])
    _assert_no_ownership_leak(budget, [], "alias point")


async def test_guaranteed_demand_after_a_best_effort_grant_cannot_revoke_it() -> None:
    """A later guaranteed project queues instead of revoking best-effort ownership."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        best_effort_hook = _SendHook()
        hooks.append(best_effort_hook)
        best_effort = _policy(base_rate=0, borrow_enabled=True, best_effort=True, max_rate=10)
        best_effort_task = asyncio.create_task(queue.submit(best_effort, best_effort_hook))
        tasks.append(best_effort_task)
        await _settle(
            lambda: len(best_effort_hook.calls) == 1,
            "the best-effort grant never delivered",
        )
        assert budget.inflight == 1

        guaranteed_hook = _SendHook()
        hooks.append(guaranteed_hook)
        guaranteed = _policy(base_rate=5, borrow_enabled=True, max_rate=10)
        guaranteed_task = asyncio.create_task(queue.submit(guaranteed, guaranteed_hook))
        tasks.append(guaranteed_task)
        await _settle(
            lambda: _pending(queue, guaranteed.project_id) == 1,
            "the guaranteed demand was not counted as waiting work",
        )
        assert budget.total_waiting_count == 1
        assert budget.inflight == 1, "the staged best-effort grant was revoked"
        assert best_effort_hook.calls[0]._finished is False

        best_effort_hook.released.set()
        await _settle(
            lambda: len(guaranteed_hook.calls) == 1, "the guaranteed demand never got a turn"
        )
        assert len(best_effort_hook.calls) == 1
        assert guaranteed_hook.calls[0].base is True
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "best-effort point")


async def test_close_fails_pending_work_and_releases_its_waiting_ownership() -> None:
    """Closing the queue fails queued work and empties the waiting ledger."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=1,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hooks: list[_SendHook] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        owner_hook = _SendHook()
        hooks.append(owner_hook)
        owner_task = asyncio.create_task(queue.submit(_policy(), owner_hook))
        tasks.append(owner_task)
        await _settle(lambda: len(owner_hook.calls) == 1, "the owner grant never delivered")

        queued_hook = _SendHook()
        hooks.append(queued_hook)
        queued = _policy()
        queued_task = asyncio.create_task(queue.submit(queued, queued_hook))
        tasks.append(queued_task)
        await _settle(
            lambda: _pending(queue, queued.project_id) == 1,
            "the second request never queued behind the owner",
        )
        assert budget.total_waiting_count == 1

        queue.close()
        await _settle(queued_task.done, "the queued request never learned about the close")
        assert isinstance(queued_task.exception(), ExecutionAuthorityUnavailable), type(
            queued_task.exception()
        ).__name__
        assert budget.total_waiting_count == 0, "the closed pending entry kept its count"
        assert budget.total_waiting_bytes == 0
        assert not queue._projects[queued.project_id].pending
        assert budget.inflight == 1, "the accepted owner had no reason to lose its slot"

        owner_hook.released.set()
        await _settle(owner_task.done, "the accepted attempt did not settle through the close")
        assert owner_task.result() == "ok"
        assert budget.inflight == 0
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "close-pending point")


async def test_close_finishes_a_staged_unpublished_grant_exactly_once() -> None:
    """Shutdown revokes a staged grant no request ever saw."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hook = _SendHook()
    tasks: list[asyncio.Task[Any]] = []
    hooks: list[_SendHook] = []
    try:
        task = asyncio.create_task(queue.submit(_policy(), hook))
        hooks.append(hook)
        tasks.append(task)
        await asyncio.sleep(0)  # one loop step: admission staged the actual grant
        assert queue._staged is not None
        staged = queue._staged
        assert not staged.dispatch._accepted
        assert hook.calls == []

        queue.close()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() or isinstance(task.exception(), ExecutionAuthorityUnavailable), (
            "the staged request did not fail closed"
        )
        assert not hook.calls, "the shutdown granted a staged request anyway"
        assert queue._staged is None
        assert staged.dispatch._finished, "the staged grant was never finished"
        assert budget.inflight == 0, "the staged grant kept its slot through shutdown"
        assert budget.total_waiting_count == 0
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "close-staged point")


async def test_close_revokes_a_delivered_grant_and_blocks_late_acceptance() -> None:
    """A delivered grant is revoked once, and its late acceptance must fail."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hook = _SendHook()
    tasks: list[asyncio.Task[Any]] = []
    hooks: list[_SendHook] = []
    try:
        task = asyncio.create_task(queue.submit(_policy(), hook))
        hooks.append(hook)
        tasks.append(task)
        await asyncio.sleep(0)  # admission stage
        await asyncio.sleep(0)  # scheduler delivery
        assert queue._staged is not None and queue._staged.waiter.future.done()
        grant = queue._staged.dispatch
        assert not grant._accepted

        queue.close()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() or isinstance(task.exception(), ExecutionAuthorityUnavailable), (
            "the delivered request accepted a grant from a closed queue"
        )
        assert not hook.calls, "the closed queue let the attempt run"
        assert grant._finished, "the delivered grant was never revoked"
        assert budget.inflight == 0, "the delivered grant kept its slot through shutdown"
        assert queue._staged is None
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "close-delivered point")


async def test_close_keeps_an_accepted_grant_settling_and_refuses_new_work() -> None:
    """Accepted attempts keep their settlement path; closed submission fails."""

    clock = _Clock()
    budget = _QueueBudget(
        default_max_requests=8,
        default_max_bytes=5_000,
        max_concurrency=4,
        project_max_concurrency=4,
    )
    queue = _queue(clock, budget)
    hook = _SendHook()
    tasks: list[asyncio.Task[Any]] = []
    hooks: list[_SendHook] = []
    try:
        task = asyncio.create_task(queue.submit(_policy(), hook))
        hooks.append(hook)
        tasks.append(task)
        await _settle(lambda: len(hook.calls) == 1, "the grant was never accepted")
        assert hook.calls[0]._accepted is True
        grant = hook.calls[0]

        queue.close()
        assert hook.calls == [grant], "shutdown re-granted the accepted request"
        assert not grant._finished, "shutdown finished an accepted attempt"
        assert budget.inflight == 1

        hook.released.set()
        await _settle(task.done, "the accepted attempt did not settle through the close")
        assert task.result() == "ok"
        assert grant._finished
        assert budget.inflight == 0

        with pytest.raises(ExecutionAuthorityUnavailable):
            await queue.submit(_policy(), _SendHook())
    finally:
        await _reclaim(tasks, hooks, [queue])
    _assert_no_ownership_leak(budget, [queue], "close-accepted point")
