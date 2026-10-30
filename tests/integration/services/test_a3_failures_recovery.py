"""A3 AC5/AC6: distinct failures, Retry-After, restart, funds, takeover.

Cases over the real execution service with fake providers and temporary
databases:

* rate exhaustion, spend exhaustion, queue saturation, queue expiry, and
  lost credentials stay mutually distinguishable refusals (typed refusals,
  provider codes, and retriable properties); native spend settles exactly
  once per attempt;
* a provider ``Retry-After`` defers the requeued retry by that amount on the
  injected virtual clock; every retry re enters the queue as a fresh attempt
  (new attempt id) with a bounded backoff when the header is absent, and a
  valid header above sixty seconds is never shortened;
* an authority restart fences past dispatches as uncertain (conservative
  recovery pause), never restores a wasted rate bucket, never settles the
  same attempt's capacity twice, and -- over a reopened runtime -- refuses
  dispatch until recovery finishes.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.execution_failures import ExecutionNotPermitted
from freesearch.models.provider_limits import (
    LOCAL_RATE_DENIAL_CODE,
    AuthMode,
    LimitDeniedError,
    NativeUsageSnapshot,
    UnitKind,
)
from freesearch.persistence.limit_rows import LimitAdmissionRow
from freesearch.services.execution import ExecutionService
from freesearch.services.execution_authority import (
    AUTHORITY_KEY,
    ExecutionAuthority,
    ExecutionAuthorityUnavailable,
    ExecutionQueueExpired,
)
from freesearch.services.provider_limits import ProviderLimitsService
from tests.fixtures.a3_authority import (
    AllocationSpec,
    AuthorityPoolSpec,
    build_authority_world,
    install_first_failures,
    provider_error_for,
)


async def _exa_pool_remaining(
    world: Any, *, repository: Any = None, pool_id: str = "exa:keyed:usd"
) -> Decimal | None:
    """Read one exa native USD bucket's remaining balance."""

    store = repository if repository is not None else world.repository
    pool_ro = await store.limits.get_pool(pool_id)
    if pool_ro is None:
        return None
    return getattr(pool_ro, "remaining", None)


def small_pool() -> AuthorityPoolSpec:
    """One exhausted-window pool for refusal cases (feasible 4:6 promises)."""
    return AuthorityPoolSpec(
        limit=10,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=4, weight=4),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6),
        ),
    )


# ---------------------------------------------------------------------------
# AC5: rate exhaustion stays a distinct local refusal (funds, queue and
# credentials are separate shapes; queue shapes live in dedicated tests).
# ---------------------------------------------------------------------------


async def test_rate_exhaustion_is_a_distinct_local_rate_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = small_pool()
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        used, refusals = await _run(world, "A", 6)
        attempts = await world.pool_attempts()
    finally:
        await world.aclose()

    assert used == 4
    assert len(attempts) == 4
    rate_refusals = [error for error in refusals if isinstance(error, LimitDeniedError)]
    assert rate_refusals, f"expected rate refusals, got {[type(e).__name__ for e in refusals]}"
    for error in rate_refusals:
        assert error.refusal == "rate"
        assert error.status_code == 429
        assert error.error.code == LOCAL_RATE_DENIAL_CODE
        assert error.retry_after_seconds is None or error.retry_after_seconds >= 0


async def build_limits(repository: Any) -> ProviderLimitsService:
    """Start the provider rails over one repository (same as compositions do)."""

    limits_service = ProviderLimitsService(repository.limits)
    await limits_service.initialize()
    return limits_service


async def _run(world: Any, label: str, count: int) -> tuple[int, list[BaseException]]:
    """Submit ``count`` searches for one project and join everything."""
    tasks = world.submit(label, *(f"{label}{index}" for index in range(count)))
    if tasks:
        await world.wait_starts(1)
    while not all(task.done() for task in tasks):
        world.release()
        await asyncio.sleep(0.001)
        if not any(not park.released.is_set() for park in world.parks):
            await asyncio.sleep(0.001)
    world.release()
    _, failures = await world.gather(list(tasks))
    used = world.projects[label].adapter.search_calls
    return used, failures


# ---------------------------------------------------------------------------
# AC5: invalid credentials are a distinct refusal from rate and queue shapes.
# ---------------------------------------------------------------------------


async def test_lost_credentials_stay_distinct_from_capacity_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from freesearch.services.api_keys import ApiKeyService

    spec = small_pool()
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    key: Any = None
    try:
        key, key_ctx = await world.key_context("A")
        try:
            await world.service.search(
                world.request("A", tag="valid"),
                attribution=key.attribution,
                context=key_ctx,
            )
        except BaseException as error:
            raise AssertionError(f"the staged key execution must work, got {error}") from error
        await ApiKeyService(world.repository).revoke(key.owner, key.project_id, key.api_key_id)
        refusal: BaseException | None = None
        try:
            await world.service.search(
                world.request("A", tag="revoked"),
                attribution=key.attribution,
                context=key_ctx,
            )
        except BaseException as error:
            refusal = error
        calls = world.projects["A"].adapter.search_calls
    finally:
        await world.aclose()

    assert refusal is not None
    assert isinstance(refusal, ExecutionNotPermitted), (
        f"revoked key must fail as the typed permission refusal: {type(refusal).__name__}"
    )
    assert calls == 1


# ---------------------------------------------------------------------------
# AC五章: queue shapes are distinct from the capacity shapes.
# ---------------------------------------------------------------------------


async def test_queue_shapes_are_distinct_from_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                borrow_max=10,
                weight=4,
                max_concurrency=1,
                max_queued_requests=1,
                max_queue_wait_ms=50,
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
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        tasks = world.submit("A", "a1", "a2", "a3")
        await world.wait_starts(1)
        saturated = await _settle(tasks[2])
        del saturated
        # Advance past the queued a2's wait bound: expiry instead of saturation.
        world.monotonic.advance(0.2)
        expired = await _settle(tasks[1])
    finally:
        await world.aclose()

    assert isinstance(expired, ExecutionQueueExpired), type(expired).__name__
    assert expired.retriable is True
    assert expired.__class__ is not LimitDeniedError


async def _settle(task: asyncio.Task[Any], *, timeout: float = 5.0) -> BaseException:
    """Settle one task and return its refusal (or fail when it succeeds)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not task.done():
        if loop.time() > deadline:
            raise AssertionError("task never settled")
        await asyncio.sleep(0.001)
    error = task.exception()
    assert error is not None, "expected a refusal"
    return error


# ---------------------------------------------------------------------------
# AC5: provider Retry-After delays the requeued retry; every retry requeues.
# ---------------------------------------------------------------------------


async def test_provider_retry_after_defers_the_requeued_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                borrow_max=10,
                weight=4,
                max_concurrency=1,
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
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    not_before: float | None = 99_999.0
    try:
        error = provider_error_for(
            code="rate_limited",
            status=429,
            retryable=True,
            details={"retry_after_seconds": 30},
        )
        install_first_failures(world, "A", error=error)
        tasks = world.submit("A", "retry-after")
        await world.wait_starts(1)
        world.monotonic.set(0.0)
        # Synchronize on the requeue actually being enqueued (the failed
        # attempt is requeued as this project's only pending waiter), then
        # advance the virtual clock to its due time. No sleeps guess at the
        # requeue: without this anchor the retry's own not_before is read
        # after the clock already moved.
        await world.wait_queued("A", 1)
        not_before = world.retry_not_before("A")
        # The requeued retry must not start while the virtual Retry-After
        # window still runs; after it lapses the retry goes out as its own
        # attempt and the released send completes the request.
        world.monotonic.advance(31.0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        while len(world.starts) < 2:
            if loop.time() > deadline:
                pytest.fail(f"the retry never requeued (starts={world.starts})")
            await asyncio.sleep(0.002)
        starts = list(world.starts)
        second_start = starts[-1]
        world.release()
        successes, failures = await world.gather(list(tasks))
        attempts = await world.project_attempts("A")
        attempt_ids = [row.attempt_id for row in attempts]
    finally:
        with suppress(Exception):
            await world.gather(list(tasks))
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert len(successes) == 1
    assert world.projects["A"].adapter.search_calls == 2, "the retry re-dispatches"
    assert len(attempt_ids) == len(set(attempt_ids)) == 2, (
        "every retry is a fresh attempt id, not a reused attempt"
    )
    assert not_before is not None, "the requeued retry carried no Retry-After deferral"
    assert abs(not_before - 30.0) <= 0.5, (
        f"the requeue read not_before={not_before}; provider Retry-After (30s) must "
        "defer the requeue by exactly that virtual delay"
    )
    assert len(starts) == 2 and starts[0].monotonic <= 0.0
    assert second_start.monotonic >= 30.0, (
        f"the requeued retry started at {second_start.monotonic}; "
        "provider Retry-After (30s) must defer the requeue"
    )


async def test_retry_without_retry_after_uses_a_bounded_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry without a Retry-After requeues on its own bounded backoff.

    The previous assertion (``second_start.monotonic <= 60``) read the virtual
    clock against a REAL sleep, which cannot advance an injected read-only
    clock. The corrected observable facts are: the failed attempt requeues as
    a fresh attempt within a bounds-checked real window, the virtual queue
    clock itself never moves because of it, and the retried attempt pays the
    same attempt cost.
    """

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                borrow_max=10,
                weight=4,
                max_concurrency=1,
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
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        error = provider_error_for(code="overloaded", status=503, retryable=True)
        install_first_failures(world, "A", error=error)
        tasks = world.submit("A", "bounded-backoff")
        await world.wait_starts(1)
        world.monotonic.set(0.0)
        loop = asyncio.get_running_loop()
        real_deadline = loop.time() + 10.0  # bounded join, not a blind wave
        while len(world.starts) < 2:
            if loop.time() > real_deadline:
                pytest.fail(f"the backoff retry never dispatched (starts={world.starts})")
            await asyncio.sleep(0.002)
        starts = list(world.starts)
        second_start = starts[-1]
        world.release()
        successes, failures = await world.gather(list(tasks))
        attempts = await world.project_attempts("A")
    finally:
        with suppress(Exception):
            await world.gather(list(tasks))
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert len(successes) == 1
    assert world.projects["A"].adapter.search_calls == 2
    assert len(attempts) == 2, "the retried attempt carried no charge"
    assert second_start.monotonic <= 60.0, (
        f"the bounded backoff must stay short on the virtual clock (got {second_start.monotonic}s)"
    )
    assert not (second_start.monotonic > 1.0), (
        "the absent-header backoff must not depend on advancing the virtual clock"
    )


async def test_retry_after_over_sixty_seconds_is_never_shortened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P12: a provider Retry-After above sixty seconds is honored verbatim."""

    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(
                label="A",
                base_rate=4,
                borrow_max=10,
                weight=4,
                max_concurrency=1,
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
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    try:
        error = provider_error_for(
            code="rate_limited",
            status=429,
            retryable=True,
            details={"retry_after_seconds": 90},
        )
        install_first_failures(world, "A", error=error)
        tasks = world.submit("A", "long-retry-after")
        await world.wait_starts(1)
        world.monotonic.set(0.0)
        await world.wait_queued("A", 1)  # the requeue is enqueued
        not_before = world.retry_not_before("A")
        # Advance to the requeue's declared due time (synchronized above), so
        # the bounded dispatch wait observes the real scheduler decision.
        due = max(91.0, (not_before or 0.0) + 2.0)
        world.monotonic.advance(due)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10.0
        while len(world.starts) < 2:
            if loop.time() > deadline:
                pytest.fail(f"the retry never requeue-dispatched (starts={world.starts})")
            await asyncio.sleep(0.002)
        starts = list(world.starts)
        second_start = starts[-1]
        world.release()
        successes, failures = await world.gather(list(tasks))
        attempts = await world.project_attempts("A")
    finally:
        with suppress(Exception):
            await world.gather(list(tasks))
        await world.aclose()

    assert not failures, [f"{type(f).__name__}: {f}" for f in failures]
    assert len(successes) == 1
    assert world.projects["A"].adapter.search_calls == 2
    assert len({row.attempt_id for row in attempts}) == 2
    assert not_before is not None and not_before >= 89.5, (
        f"the requeue read not_before={not_before}; a valid Retry-After of 90 seconds "
        "must never be shortened to a sixty-second ceiling"
    )
    assert second_start.monotonic >= 89.5, (
        f"the requeued retry dispatched at {second_start.monotonic}s; the unshortened "
        "Retry-After window must hold across the requeue"
    )


# ---------------------------------------------------------------------------
# AC6: authority restart conservatively fences; the rate bucket is never
# restored, and no attempt's admission is recorded twice.
# ---------------------------------------------------------------------------


async def test_restart_never_refills_the_bucket_or_settles_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=10,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    middle: Any = None
    try:
        # The native funds door starts observed, so each of the send's final
        # settlements debits its exact native price against that balance.
        await world.repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=f"exa:keyed:usd#pool:{world.pool.id}",
                provider="exa",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=datetime.now(UTC),
                remaining=Decimal("10.00"),
                allowance=Decimal("10.00"),
                source="vendor_api",
            )
        )
        # Nine settled dispatches fill the window, the tenth stays mid-flight
        # (dispatched, never resolved) so the crash leaves recovery work.
        drained, refused = await _drain(
            world, world.submit("A", *(f"a{index}" for index in range(9)))
        )
        assert len(drained) == 9 and not refused, (
            f"the borrowed solo run exhausted exactly the pool: {list(map(type, refused))}"
        )
        in_flight = world.submit("A", "a9")
        await world.wait_starts(10)
        assert not in_flight[0].done(), "the tenth dispatch must stay mid-flight"
        attempts_before = await world.pool_attempts()
        assert len(attempts_before) == 10
        # Native funds settle per pooled dispatch on the pool-scoped bucket.
        funds_scope = f"exa:keyed:usd#pool:{world.pool.id}"
        native_before = await _exa_pool_remaining(world, pool_id=funds_scope)

        # A crash: the fence expires without any dispatch row being resolved.
        from freesearch.persistence.execution_authority import (
            ExecutionAuthorityRepository,
        )

        async with world.repository.session() as session:
            lease = await ExecutionAuthorityRepository(session).current(
                authority_key=world.authority_key
            )
            if lease is not None:
                await ExecutionAuthorityRepository(session).release(
                    authority_key=world.authority_key,
                    holder_id=lease.holder_id,
                    fencing_token=lease.fencing_token,
                    now=datetime.now(UTC),
                )
            await session.commit()
        baseline_usage = await world.usage_rows(project_id=world.projects["A"].project_id)
        assert len(baseline_usage) == 9

        # The restarted authority over the same durable store.
        limits_service = await build_limits(world.repository)
        from freesearch.services.execution_authority import ExecutionAuthority

        restarted = ExecutionAuthority(
            repository=world.repository,
            secret_store=world.store,
            authority_key=AUTHORITY_KEY,
            monotonic_fn=world.monotonic.monotonic_fn,
            limits=limits_service,
            lease_seconds=3.0,
            recovery_seconds=1.0,
        )
        middle = ExecutionService(
            repository=world.repository,
            secret_store=world.store,
            client=object(),
            limits=limits_service,
            authority=restarted,
        )
        try:
            try:
                during: Any = await middle.search(
                    world.request("A", tag="during-recovery"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                )
                during = None
            except BaseException as error:
                during = error
            calls_during_pause = world.projects["A"].adapter.search_calls
            await asyncio.sleep(1.5)
            try:
                aftermath: Any = await middle.search(
                    world.request("A", tag="after-recovery"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                )
                aftermath = None
            except BaseException as error:
                aftermath = error
            attempts_after = await world.pool_attempts()
            admissions = await _admission_rows(world)
            uncertain = await _uncertain_rows(world.repository, world.projects["A"].project_id)
        finally:
            with suppress(Exception):
                await middle.aclose()
    finally:
        world.release()
        with suppress(Exception):
            await world.service.aclose()
        with suppress(Exception):
            await world.repository.close()

    assert during is not None, "the restarted authority executed during recovery"
    assert isinstance(
        during, (ExecutionAuthorityUnavailable, ExecutionQueueExpired, LimitDeniedError)
    ), f"the restart refusal must stay typed: {type(during).__name__}: {during}"
    assert calls_during_pause == 10, "the restarted authority dispatched during recovery"
    assert aftermath is not None and isinstance(
        aftermath, (LimitDeniedError, ExecutionQueueExpired, ExecutionAuthorityUnavailable)
    ), f"the wasted bucket must stay enforced after restart, got {type(aftermath)}"
    assert len(attempts_after) == 10, (
        f"restart restored the rate bucket ({len(attempts_after)} pool attempts)"
    )
    assert uncertain, "past dispatches were not fenced into uncertain recovery rows"
    attempt_ids = [row.attempt_id for row in admissions]
    assert len(attempt_ids) == len(set(attempt_ids)), (
        "the same attempt's admission was settled twice"
    )
    # Funds and attempts settle once per attempt: the nine completed sends
    # already debited their native charge, the unresolved (crashed) tenth did
    # not, and the restart resolves it by RETAINING exactly one more debit
    # (7.2: the rate debit of uncertain receipt stays), never settling any
    # settled attempt twice.
    assert native_before == Decimal("9.937"), (
        f"nine settled dispatches debited ${10.00 - float(native_before):.3f} once"
    )
    native_after = await _exa_pool_remaining(world, pool_id=funds_scope)
    assert native_after == Decimal("9.930"), (
        f"the restart finalized the uncertain attempt once more, and only once "
        f"(unexpected native remaining {native_after} against {native_before})"
    )


async def _drain(
    world: Any, tasks: list[asyncio.Task[Any]]
) -> tuple[list[Any], list[BaseException]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 30.0
    while not all(task.done() for task in tasks):
        world.release()
        if loop.time() > deadline:
            pytest.fail(f"drain never completed ({sum(1 for t in tasks if t.done())}/{len(tasks)})")
        await asyncio.sleep(0.001)
        world.release()
    return await world.gather(list(tasks))


async def _admission_rows(world: Any) -> list[LimitAdmissionRow]:
    async with world.repository.session() as session:
        rows = await session.execute(select(LimitAdmissionRow))
        return [row for row in rows.scalars().all()]


async def _uncertain_rows(repository: Any, project_id: Any) -> list[Any]:
    from freesearch.persistence.execution_authority import ExecutionAuthorityRepository

    async with repository.session() as session:
        return await ExecutionAuthorityRepository(session).list_uncertain(project_id=project_id)


# ---------------------------------------------------------------------------
# P8: a takeover with unresolved work and available rate capacity must enter
# recovery. The crash is a real close/reopen of the runtime and database, and
# funds settle exactly once across the takeover.
# ---------------------------------------------------------------------------


async def test_takeover_with_unresolved_work_stays_in_recovery_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=10,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6),
        ),
    )
    codec = SecretCodec(MasterKey(os.urandom(32)))
    world = await build_authority_world(
        tmp_path, monkeypatch, spec=spec, codec=codec, recovery_seconds=0.2
    )
    database_path = world.repository.database_path
    reopened_service: Any = None
    reopened_repository: Any = None
    in_flight: list[asyncio.Task[Any]] = []
    try:
        # Native funds start observed, so the crash cannot hide a settlement.
        await world.repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=f"exa:keyed:usd#pool:{world.pool.id}",
                provider="exa",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=datetime.now(UTC),
                remaining=Decimal("10.00"),
                allowance=Decimal("10.00"),
                source="vendor_api",
            )
        )
        # One dispatch leaves unresolved work behind (a dispatched row with an
        # older fencing token), and the window still has four units left, so
        # only recovery can stop the next dispatch.
        in_flight = world.submit("A", "crash")
        await world.wait_starts(1)
        open_rows = await world.dispatch_rows(project_id=world.projects["A"].project_id)
        assert len(open_rows) == 1, "the first dispatch wrote its recovery record"
        funds_scope = f"exa:keyed:usd#pool:{world.pool.id}"
        native_before = await _exa_pool_remaining(world, pool_id=funds_scope)
        assert native_before == Decimal("10.00"), "the parked send is not yet settled"

        # The crash: vacate the lease row and drop this database connection,
        # exactly as the stopped-process simulation of the restart case does.
        # The parked send is left UNRESOLVED: no cancellation (a cancel is an
        # in-process outcome and would resolve the attempt itself), no
        # settlement, no service close -- its dispatch record stays
        # unresolved under the old fencing token for the takeover to fence.
        # Waiting out the lease TTL is not reproducible in-process (the live
        # authority keeps renewing until expiry), so the takeover acquires a
        # vacated fence -- the predecessor's token is still the last token
        # any dispatch was recorded under.
        from freesearch.persistence.execution_authority import ExecutionAuthorityRepository

        async with world.repository.session() as session:
            lease = await ExecutionAuthorityRepository(session).current(
                authority_key=world.authority_key
            )
            if lease is not None:
                await ExecutionAuthorityRepository(session).release(
                    authority_key=world.authority_key,
                    holder_id=lease.holder_id,
                    fencing_token=lease.fencing_token,
                    now=datetime.now(UTC),
                )
            await session.commit()
        with suppress(Exception):
            await world.repository.close()

        # The reopened runtime takes over the same durable state.
        reopened_repository = await SQLiteRepository_open(database_path)
        store = EncryptedDbSecretStore(reopened_repository, codec)
        limits_service = ProviderLimitsService(reopened_repository.limits)
        await limits_service.initialize()
        new_authority = ExecutionAuthority(
            repository=reopened_repository,
            secret_store=store,
            authority_key=AUTHORITY_KEY,
            monotonic_fn=world.monotonic.monotonic_fn,
            lease_seconds=30.0,
            recovery_seconds=0.2,
        )
        reopened_service = ExecutionService(
            repository=reopened_repository,
            secret_store=store,
            client=object(),
            limits=limits_service,
            authority=new_authority,
        )
        # The takeover must refuse during recovery, though the rate window has
        # capacity: the unresolved send of the older incarnation is unknown.
        # The parked provider stub is switched to instant mode so a defect
        # that dispatches surfaces as a completed send instead of a hang.
        world.park(False)
        refusal: BaseException | None = None
        try:
            await asyncio.wait_for(
                reopened_service.search(
                    world.request("A", tag="during-takeover"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                ),
                timeout=10.0,
            )
        except BaseException as error:
            refusal = error
        # A second immediate acquisition must retain the same recovery pause.
        with pytest.raises(ExecutionAuthorityUnavailable):
            await asyncio.wait_for(
                reopened_service.search(
                    world.request("A", tag="still-recovering"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                ),
                timeout=10.0,
            )
        calls_during_recovery = world.projects["A"].adapter.search_calls
        uncertain = await _uncertain_rows(reopened_repository, world.projects["A"].project_id)
        native_during = await _exa_pool_remaining(
            world, repository=reopened_repository, pool_id=funds_scope
        )

        assert refusal is not None, "the takeover dispatched during recovery"
        assert isinstance(
            refusal, (ExecutionAuthorityUnavailable, ExecutionQueueExpired, LimitDeniedError)
        ), f"recovery must refuse dispatch with a typed refusal: {type(refusal).__name__}"
        assert calls_during_recovery == 1, (
            "recovery must stop new dispatch: one send belongs to the closed incarnation"
        )
        assert uncertain, "the takeover did not fence the unresolved dispatch as uncertain"
        # Uncertainty retains exactly one debit (the closed incarnation's send);
        # refusing during recovery must not add a second one.
        assert native_during == Decimal("9.993"), (
            f"the takeover kept exactly one retained debit "
            f"(unexpected native remaining {native_during})"
        )

        # After the bounded recovery pause the dispatcher serves again and its
        # one send finalizes once more.
        world.park(False)
        await asyncio.sleep(0.5)  # bounded recovery pause (0.2s + slack)
        after: Any = None
        after_failure: BaseException | None = None
        assert reopened_service is not None
        try:
            after = await asyncio.wait_for(
                reopened_service.search(
                    world.request("A", tag="after-recovery"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                ),
                timeout=10.0,
            )
        except BaseException as error:
            after_failure = error
        assert after_failure is None, f"dispatch after recovery must serve: {after_failure}"
        assert after is not None and getattr(after, "provider", None) == "exa"
        calls_after = world.projects["A"].adapter.search_calls
        assert calls_after == 2, "the post-recovery dispatch served once more"
        native_later = await _exa_pool_remaining(
            world, repository=reopened_repository, pool_id=funds_scope
        )
        assert native_later == Decimal("9.986"), (
            f"the post-recovery send settled exactly once (remaining {native_later})"
        )
    finally:
        for task in in_flight:
            with suppress(asyncio.CancelledError, Exception):
                task.cancel()
                await task
        world.release()
        with suppress(Exception):
            await world.service.aclose()
        with suppress(Exception):
            await world.repository.close()
        if reopened_service is not None:
            with suppress(Exception):
                await reopened_service.aclose()
        if reopened_repository is not None:
            with suppress(Exception):
                await reopened_repository.close()


async def SQLiteRepository_open(path: Path) -> Any:
    """Open a SQLite repository (kept local to keep the crash semantics obvious)."""

    from freesearch.persistence.storage import SQLiteRepository

    return await SQLiteRepository.open(path)


# ---------------------------------------------------------------------------
# AC5: local spend exhaustion is its own funds refusal, and every successful
# send finalizes its native debit exactly once.
# ---------------------------------------------------------------------------


async def test_local_spend_exhaustion_is_a_distinct_funds_refusal_and_settles_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = AuthorityPoolSpec(
        limit=1000,
        allocations=(
            AllocationSpec(label="A", base_rate=4, borrow_max=10, weight=4),
            AllocationSpec(label="B", base_rate=6, borrow_max=10, weight=6),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    # Pooled execution scopes the vendor's shared balance to its own
    # upstream pool (`exa:keyed:usd#pool:<id>`), so the local funds door is
    # seeded with exactly one send's worth: the $0.007 search debit fits,
    # the next one does not.
    funds_scope = f"exa:keyed:usd#pool:{world.pool.id}"
    try:
        await world.repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=funds_scope,
                provider="exa",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=datetime.now(UTC),
                remaining=Decimal("0.01"),
                allowance=Decimal("0.01"),
                source="vendor_api",
            )
        )
        first = await asyncio.wait_for(
            world.service.search(
                world.request("A", tag="spend-ok"),
                attribution=world.projects["A"].attribution,
                context=world.projects["A"].context,
            ),
            timeout=15.0,
        )
        settled = await _exa_pool_remaining(world, pool_id=funds_scope)
        refusal: BaseException | None = None
        try:
            await asyncio.wait_for(
                world.service.search(
                    world.request("A", tag="spend-short"),
                    attribution=world.projects["A"].attribution,
                    context=world.projects["A"].context,
                ),
                timeout=15.0,
            )
        except BaseException as error:
            refusal = error
        after_denial = await _exa_pool_remaining(world, pool_id=funds_scope)
        calls = world.projects["A"].adapter.search_calls
        usage = await world.usage_rows(project_id=world.projects["A"].project_id)
        project_attempts = await world.project_attempts("A")
        pool_rows = await world.pool_attempts()
        # "Settles once" must survive repetition: two further denial sweeps
        # must each repeat the same typed refusal, and every settled-once
        # observable (native balance, provider sends, usage rows, charged
        # attempts) must stay frozen at the successful send's facts.
        repeated: list[tuple[BaseException | None, Decimal | None, int, int, int, int]] = []
        for tag in ("spend-short-again", "spend-short-last"):
            denial: BaseException | None = None
            try:
                await asyncio.wait_for(
                    world.service.search(
                        world.request("A", tag=tag),
                        attribution=world.projects["A"].attribution,
                        context=world.projects["A"].context,
                    ),
                    timeout=15.0,
                )
            except BaseException as error:
                denial = error
            repeated.append(
                (
                    denial,
                    await _exa_pool_remaining(world, pool_id=funds_scope),
                    world.projects["A"].adapter.search_calls,
                    len(await world.usage_rows(project_id=world.projects["A"].project_id)),
                    len(await world.project_attempts("A")),
                    len(await world.pool_attempts()),
                )
            )
    finally:
        await world.aclose()

    assert first.provider == "exa", "the send within the spend window executes"
    assert settled == Decimal("0.003"), (
        f"one send finalizes its exact native debit once (settled={settled})"
    )
    assert refusal is not None, "a send beyond the spend window must refuse locally"
    assert isinstance(refusal, LimitDeniedError), (
        f"spend exhaustion must be the typed local denial: {type(refusal).__name__}"
    )
    assert getattr(refusal, "refusal", None) == "funds", getattr(refusal, "refusal", None)
    assert refusal.status_code == 402
    assert refusal.error.retryable is False
    assert refusal.error.code == "crd_exhausted", refusal.error.code
    assert calls == 1, "spend exhaustion sent nothing further to the provider"
    assert len(usage) == 1, (
        f"the funds denial wrote no usage of its own (rows={[row.status for row in usage]})"
    )
    assert len(project_attempts) == 1 and len(pool_rows) == 1, (
        f"the refused funds denial consumed no rate attempt "
        f"(project {len(project_attempts)}, pool {len(pool_rows)})"
    )
    # Funds did not drift after the refusal: the settled send was finalized
    # exactly once and the denial released nothing extra.
    assert after_denial == settled == Decimal("0.003"), (
        f"the funds refusal re-finalized or released the settled send ({after_denial})"
    )
    for index, (denial, remaining, seen_calls, seen_usage, seen_project, seen_pool) in enumerate(
        repeated, start=1
    ):
        assert denial is not None, f"the repeated denial {index} unexpectedly executed"
        assert isinstance(denial, LimitDeniedError), (
            f"the repeated denial {index} must stay the typed local funds refusal "
            f"(got {type(denial).__name__})"
        )
        assert denial.refusal == "funds", f"denial {index}: {denial.refusal}"
        assert denial.status_code == 402
        assert remaining == Decimal("0.003"), (
            f"denial {index} re-finalized or released the settled send ({remaining})"
        )
        assert seen_calls == 1, f"denial {index} reached the provider (calls={seen_calls})"
        assert seen_usage == 1, f"denial {index} wrote a usage row of its own (rows={seen_usage})"
        assert seen_project == 1 and seen_pool == 1, (
            f"denial {index} consumed a rate attempt (project {seen_project}, pool {seen_pool})"
        )


# ---------------------------------------------------------------------------
# P2: a project's absolute loan ceiling is durable state, not scheduler
# memory. An authority replacement over the same durable store must not
# re-grant past the ceiling the first incarnation already served.
# ---------------------------------------------------------------------------


async def test_project_loan_ceiling_survives_authority_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two served sends exhaust the loan ceiling; a fresh authority must refuse.

    The first authority serves two sends (base grant, then loan grant) so the
    served count reaches ``max_rate``. Its incarnation is then closed and a
    fresh ``ExecutionAuthority`` is composed over the SAME repository and the
    same seam the attempts read. A durable ceiling must refuse send three with
    the typed local denial naming ``project:<id>:ceiling`` and must charge no
    third send: no attempt row, no usage, no provider call. Today the
    replacement's fresh in-memory scheduler re-grants a loan -- that is the
    P2 production defect this test pins.
    """

    spec = AuthorityPoolSpec(
        limit=2000,
        allocations=(
            AllocationSpec(label="A", base_rate=1, borrow_max=2, weight=1),
            AllocationSpec(label="B", base_rate=1, borrow_max=2, weight=1),
        ),
    )
    world = await build_authority_world(tmp_path, monkeypatch, spec=spec)
    world.park(False)
    try:
        project = world.projects["A"]
        first = await asyncio.wait_for(
            world.service.search(
                world.request("A", tag="ceiling-ok-1"),
                attribution=project.attribution,
                context=project.context,
            ),
            timeout=15.0,
        )
        second = await asyncio.wait_for(
            world.service.search(
                world.request("A", tag="ceiling-ok-2"),
                attribution=project.attribution,
                context=project.context,
            ),
            timeout=15.0,
        )
        served_after_two = (
            await world.project_attempts("A"),
            await world.usage_rows(project_id=project.project_id),
            project.adapter.search_calls,
        )

        # Replace the authority over the same durable store, exactly as an
        # API host re-acquires the dispatch fence after a workload restart.
        # The old incarnation resolves its open dispatch records before
        # aclose returns (it gathers its pending resolutions), so the takeover
        # has nothing uncertain to mark and takes an ACTIVE lease.
        await world.authority.aclose()
        replacement_limits = await build_limits(world.repository)
        replacement = ExecutionAuthority(
            repository=world.repository,
            secret_store=world.store,
            authority_key=AUTHORITY_KEY,
            monotonic_fn=world.monotonic.monotonic_fn,
            limits=replacement_limits,
        )
        world.service._authority = replacement  # the seam every new attempt reads
        refusal: BaseException | None = None
        try:
            await asyncio.wait_for(
                world.service.search(
                    world.request("A", tag="ceiling-over"),
                    attribution=project.attribution,
                    context=project.context,
                ),
                timeout=15.0,
            )
        except BaseException as error:
            refusal = error
        attempts = await world.project_attempts("A")
        usage = await world.usage_rows(project_id=project.project_id)
        calls = world.projects["A"].adapter.search_calls
    finally:
        await world.aclose()

    assert first.provider == "exa" and second.provider == "exa", (
        "both sends within the absolute ceiling must execute through the host"
    )
    served_attempts, served_usage, served_calls = served_after_two
    assert len(served_attempts) == 2 and len(served_usage) == 2 and served_calls == 2, (
        f"the two served sends must be charged exactly once each "
        f"(attempts {len(served_attempts)}, usage {len(served_usage)}, calls {served_calls})"
    )
    assert refusal is not None, "the replacement authority re-granted past the ceiling"
    assert isinstance(refusal, LimitDeniedError), (
        f"the over-ceiling refusal must be the typed local denial: {type(refusal).__name__}"
    )
    assert refusal.refusal == "rate", refusal.refusal
    assert refusal.status_code == 429
    assert refusal.error.retryable is False
    assert refusal.error.code == LOCAL_RATE_DENIAL_CODE
    # The refusal must be recognizable as the project's absolute loan ceiling,
    # not an incidental shape: the project prefix plus the ``ceiling`` suffix
    # is the shared shape of both the scheduler's own ceiling denial
    # (``project:<id>:ceiling``) and the durable loan-ceiling window bucket
    # (``project:<id>:<pool>:<op>:ceiling``). Today the replacement denies
    # from the re-classified BASE window instead (reasons carry the plain
    # ``...:search`` bucket) -- the P2 nondurable-ceiling evidence to fix.
    ceiling_reason = any(
        reason.startswith(f"project:{world.projects['A'].project_id}:")
        and reason.endswith("ceiling")
        for reason in refusal.reasons
    )
    assert ceiling_reason, (
        f"the over-ceiling refusal after the authority replacement must name the "
        f"project's absolute ceiling, got reasons={refusal.reasons}"
    )
    assert calls == 2, f"the replacement dispatched a third send ({calls} calls)"
    assert len(attempts) == 2, (
        f"the over-ceiling send must charge no attempt "
        f"(project bucket rows={[row.attempt_id for row in attempts]})"
    )
    assert len(usage) == 2, f"the over-ceiling send must write no usage (rows={len(usage)})"
