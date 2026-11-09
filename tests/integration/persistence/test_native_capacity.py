"""Native catalog admission is atomic across independent SQLite engines."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from polyweb.models.contracts import UnitKind
from polyweb.models.provider_limits import (
    AuthMode,
    LimitAdmission,
    LimitDeniedError,
    LimitOperation,
    NativePool,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateReservation,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
)
from polyweb.persistence.limit_rows import LimitAdmissionRow, RateAttemptRow
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import FIXTURE_ACTOR


@pytest.mark.parametrize("api", ["reserve", "reserve_attempt"])
@pytest.mark.parametrize("window", list(RateWindowName))
@pytest.mark.parametrize("scope", ["credential", "pool"])
async def test_all_native_windows_recheck_across_connections(tmp_path, api, window, scope):
    """Two valid preflights cannot spend the same native unit under either API."""
    first = await SQLiteRepository.open(tmp_path / "native.db")
    second = await SQLiteRepository.open(tmp_path / "native.db")
    now = datetime.now(UTC)
    bucket = f"native:shared#{'cred' if scope == 'credential' else 'pool'}:{uuid4()}"
    record = ProviderLimitRecord(
        provider="native",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[
                RateWindow(
                    bucket_id="native:shared",
                    window=window,
                    scope=RateScope.KEY,
                    limit=Decimal("1"),
                    unit=RateUnit.URLS,
                )
            ]
        ),
    )
    admissions = [
        LimitAdmission(
            provider="native",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id=uuid4().hex,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            rate_reservations=[
                RateReservation(bucket_id=bucket, window=window, units=Decimal("0.6"))
            ],
            **FIXTURE_ACTOR,
        )
        for _ in range(2)
    ]

    async def reserve(repo, admission):
        if api == "reserve":
            return await repo.limits.reserve(admission, record=record, clock=lambda: now)
        return await repo.limits.reserve_attempt(
            attempt_id=admission.attempt_id,
            provider=admission.provider,
            operation=admission.operation,
            auth_mode=admission.auth_mode,
            admission=admission,
            record=record,
            created_at=now,
        )

    try:
        results = await asyncio.gather(
            reserve(first, admissions[0]),
            reserve(second, admissions[1]),
            return_exceptions=True,
        )
        assert sum(isinstance(result, LimitDeniedError) for result in results) == 1
        winner = next(
            a for a, r in zip(admissions, results, strict=True) if not isinstance(r, Exception)
        )
        # Same-attempt retry is idempotent, so it cannot charge again.
        await reserve(second, winner)
        async with first.session() as session:
            rows = list((await session.scalars(select(RateAttemptRow))).all())
            holds = list((await session.scalars(select(LimitAdmissionRow))).all())
        assert len(rows) == len(holds) == 1
        assert Decimal(rows[0].units_text) == Decimal("0.6")
        assert rows[0].bucket_id == bucket
        assert rows[0].actor_id == str(FIXTURE_ACTOR["actor_id"])
    finally:
        await second.close()
        await first.close()


@pytest.mark.parametrize("api", ["reserve", "reserve_attempt"])
async def test_native_funds_and_scoped_observation_are_rechecked(tmp_path, api):
    first = await SQLiteRepository.open(tmp_path / "funds.db")
    second = await SQLiteRepository.open(tmp_path / "funds.db")
    now = datetime.now(UTC)
    record = ProviderLimitRecord(
        provider="native",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[
                RateWindow(
                    bucket_id="shared",
                    window=RateWindowName.HOUR,
                    scope=RateScope.KEY,
                    limit=Decimal("100"),
                )
            ]
        ),
    )

    async def reserve(repo, admission):
        if api == "reserve":
            return await repo.limits.reserve(admission, record=record, clock=lambda: now)
        return await repo.limits.reserve_attempt(
            attempt_id=admission.attempt_id,
            provider="native",
            operation=admission.operation,
            auth_mode=admission.auth_mode,
            admission=admission,
            record=record,
            created_at=now,
        )

    def admission(bucket, pool=None):
        return LimitAdmission(
            provider="native",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id=uuid4().hex,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            pool_id=pool,
            reserved_native=Decimal("0.6") if pool else None,
            rate_reservations=[RateReservation(bucket_id=bucket, window=RateWindowName.HOUR)],
            **FIXTURE_ACTOR,
        )

    try:
        await first.limits.ensure_pool(
            NativePool(
                pool_id="native:funds",
                provider="native",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
            )
        )
        await first.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="native:funds",
                provider="native",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=now,
                remaining=Decimal("1"),
            )
        )
        results = await asyncio.gather(
            reserve(first, admission("shared#cred:a", "native:funds")),
            reserve(second, admission("shared#cred:b", "native:funds")),
            return_exceptions=True,
        )
        assert sum(isinstance(r, LimitDeniedError) for r in results) == 1
        await first.limits.observe_rate(
            RateObservation(
                bucket_id="shared#cred:blocked",
                provider="native",
                auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR,
                unit=RateUnit.REQUESTS,
                remaining=Decimal("0"),
                limit=Decimal("100"),
                observed_at=now,
                reset_at=now + timedelta(hours=1),
            )
        )
        with pytest.raises(LimitDeniedError):
            await reserve(second, admission("shared#cred:blocked"))
        await reserve(second, admission("shared#cred:unrelated"))
    finally:
        await second.close()
        await first.close()


@pytest.mark.parametrize("provider", ["native", "tavily"])
@pytest.mark.parametrize("api", ["reserve", "reserve_attempt"])
async def test_native_windows_are_atomic_across_processes(tmp_path, provider, api):
    import multiprocessing

    from tests.integration.persistence._native_capacity_worker import run_worker

    database = tmp_path / "native-processes.db"
    repository = await SQLiteRepository.open(database)
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    workers = [
        ctx.Process(target=run_worker, args=(str(database), provider, api, barrier, results))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        outcomes = await asyncio.gather(
            *(asyncio.to_thread(results.get, True, 120) for _ in workers)
        )
        assert sorted(outcomes) == ["admitted", "denied"]
        for worker in workers:
            await asyncio.to_thread(worker.join, 30)
            assert worker.exitcode == 0
        async with repository.session() as session:
            attempts = list((await session.scalars(select(RateAttemptRow))).all())
            holds = list((await session.scalars(select(LimitAdmissionRow))).all())
        assert len(attempts) == len(holds) == 1
        assert attempts[0].actor_id == str(FIXTURE_ACTOR["actor_id"])
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            await asyncio.to_thread(worker.join, 10)
        results.close()
        results.join_thread()
        await repository.close()


@pytest.mark.parametrize("api", ["reserve", "reserve_attempt"])
async def test_native_window_units_expire_by_attempt_age(tmp_path, api):
    repository = await SQLiteRepository.open(tmp_path / "native-expiry.db")
    now = datetime.now(UTC)
    record = ProviderLimitRecord(
        provider="native",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[
                RateWindow(
                    bucket_id="hour",
                    limit=Decimal("1"),
                    scope=RateScope.KEY,
                    window=RateWindowName.HOUR,
                )
            ]
        ),
    )

    async def reserve(at):
        admission = LimitAdmission(
            provider="native",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id=uuid4().hex,
            created_at=at,
            expires_at=at + timedelta(minutes=5),
            rate_reservations=[
                RateReservation(bucket_id="hour#cred:one", window=RateWindowName.HOUR)
            ],
            **FIXTURE_ACTOR,
        )
        if api == "reserve":
            return await repository.limits.reserve(admission, record=record, clock=lambda: at)
        return await repository.limits.reserve_attempt(
            attempt_id=admission.attempt_id,
            provider="native",
            operation=admission.operation,
            auth_mode=admission.auth_mode,
            admission=admission,
            record=record,
            created_at=at,
        )

    try:
        await reserve(now)
        with pytest.raises(LimitDeniedError):
            await reserve(now + timedelta(minutes=59))
        await reserve(now + timedelta(hours=1, seconds=1))
    finally:
        await repository.close()
