"""S0 core rate integration: durable cross-call reservations, no double count.

Synthetic records only. Uses a real SQLite repository through the shared
rate service. No vendor I/O.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio

from polyweb.models.provider_limits import (
    AuthMode,
    CRDPriceProfile,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.provider_limits import ProviderLimitsService
from tests.fixtures.database_lifecycle import unlink_with_retries
from tests.fixtures.execution import FIXTURE_ACTOR

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    db_path = tmp_path / "rate-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            unlink_with_retries(extra)


def _record() -> ProviderLimitRecord:
    window = RateWindow(
        bucket_id="s-hour",
        limit=Decimal("2"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    return ProviderLimitRecord(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=[window], published=True),
        budget=None,
        native_unit=None,
        native_pool_id=None,
        conversion_profile=CRDPriceProfile(),
    )


async def test_two_unit_hour_denies_third(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="h-1",
            requested_at=FIXED_AT,
        )
    )
    await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="h-2",
            requested_at=FIXED_AT,
        )
    )
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="h-3",
                requested_at=FIXED_AT,
            )
        )
    assert exc.value.status_code == 429


async def test_catalog_rate_bar_counts_scoped_attempts_once(repository: SQLiteRepository) -> None:
    record = _record()
    assert record.rate is not None
    record.rate.windows[0].limit = Decimal("10")
    svc = ProviderLimitsService(
        repository.limits, records=[record], tier_defaults={}, clock=lambda: FIXED_AT
    )
    await svc.initialize()
    credential = UUID("00000000-0000-0000-0000-000000000001")
    pool = UUID("00000000-0000-0000-0000-000000000002")
    project_credential = UUID("00000000-0000-0000-0000-000000000003")

    for attempt, at, credential_id, pool_id in (
        ("system", FIXED_AT, credential, None),
        ("project", FIXED_AT, project_credential, None),
        ("shared-pool", FIXED_AT, project_credential, pool),
        ("legacy", FIXED_AT, None, None),
        ("expired", FIXED_AT - timedelta(hours=2), credential, None),
    ):
        admission = await svc.rate_limits.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=attempt,
                requested_at=at,
                credential_id=credential_id,
                upstream_pool_id=pool_id,
            )
        )
        await svc.rate_limits.record_attempt(admission, at)

    # The same attempt can have both a legacy and a scoped row.
    await repository.limits.record_rate_attempt(
        **FIXTURE_ACTOR,
        attempt_id="system",
        bucket_id="s-hour",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        operation=LimitOperation.SEARCH,
        window=RateWindowName.HOUR,
        units=Decimal("1"),
        attempted_at=FIXED_AT,
    )
    view = await svc.provider_view("synth")
    bars = {bar.bucket_id: bar for bar in view.auths[0].rate_progress}
    assert bars["s-hour"].remaining == Decimal("6")
    assert await repository.limits.count_attempts(
        f"s-hour#cred:{credential}", window=RateWindowName.HOUR, now=FIXED_AT
    ) == Decimal("1")


async def test_catalog_observation_counts_only_later_scoped_attempts(
    repository: SQLiteRepository,
) -> None:
    svc = ProviderLimitsService(
        repository.limits, records=[_record()], tier_defaults={}, clock=lambda: FIXED_AT
    )
    await svc.initialize()
    observed_at = FIXED_AT - timedelta(minutes=5)
    await svc.rate_limits.observe(
        RateObservation(
            bucket_id="s-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("5"),
            remaining=Decimal("2"),
            observed_at=observed_at,
        )
    )
    credential = UUID("00000000-0000-0000-0000-000000000001")
    for attempt, at in (
        ("before", observed_at - timedelta(minutes=1)),
        ("after", observed_at + timedelta(minutes=1)),
    ):
        admission = await svc.rate_limits.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=attempt,
                requested_at=at,
                credential_id=credential,
            )
        )
        await svc.rate_limits.record_attempt(admission, at)
    bars = {bar.bucket_id: bar for bar in (await svc.provider_view("synth")).auths[0].rate_progress}
    assert bars["s-hour"].remaining == Decimal("1")


async def test_vendor_observation_not_double_counted(repository) -> None:
    """RT-09: a vendor observation already reflects earlier attempts.

    The vendor reports 2 of 5 hourly units left at ``T-300s``. One durable
    attempt predates that observation (already inside the vendor's number) and
    one follows it. Only the later attempt may reduce the vendor headroom, so
    exactly 1 unit remains at ``T``; counting the old attempt again would leave
    0 and wrongly deny the next call.

    A2: the post-lock service clock is the authoritative reservation instant
    (a caller's ``requested_at`` can only move a stamp forward), so each
    attempt's time is set through the injected clock, not the context.
    """

    now = [FIXED_AT]
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: now[0],
    )
    await svc.initialize()
    observed_at = FIXED_AT - timedelta(seconds=300)
    await svc.rate_limits.observe(
        RateObservation(
            bucket_id="s-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("5"),
            remaining=Decimal("2"),
            observed_at=observed_at,
        )
    )

    def _ctx(attempt: str, at: datetime) -> LimitCallContext:
        return LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id=attempt,
            requested_at=at,
        )

    async def _remaining() -> tuple[Decimal | None, Decimal | None]:
        bars = {bar.bucket_id: bar for bar in await svc.rate_limits.progress("synth", FIXED_AT)}
        details = {
            w.bucket_id: w
            for w in await svc.rate_limits.window_details("synth", AuthMode.KEYED, FIXED_AT)
        }
        return bars["s-hour"].remaining, details["s-hour"].remaining

    async def _persisted(since: datetime | None = None) -> Decimal:
        return await repository.limits.count_attempts(
            "s-hour", window=RateWindowName.HOUR, now=FIXED_AT, since=since
        )

    # Before any local attempt the vendor headroom is reported unchanged.
    assert await _remaining() == (Decimal("2"), Decimal("2"))

    now[0] = FIXED_AT - timedelta(seconds=400)
    await svc.admit(_ctx("v-old", now[0]))
    now[0] = FIXED_AT - timedelta(seconds=100)
    await svc.admit(_ctx("v-new", now[0]))
    now[0] = FIXED_AT
    assert await _persisted() == Decimal("2")
    assert await _persisted(since=observed_at) == Decimal("1")
    # Only the post-observation attempt is subtracted from the vendor's 2.
    assert await _remaining() == (Decimal("1"), Decimal("1"))

    third = await svc.admit(_ctx("v-third", FIXED_AT))
    assert third.attempt_id == "v-third"
    assert await _persisted() == Decimal("3")
    assert await _persisted(since=observed_at) == Decimal("2")
    assert await _remaining() == (Decimal("0"), Decimal("0"))

    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_ctx("v-fourth", FIXED_AT))
    assert exc.value.status_code == 429
    assert await _persisted() == Decimal("3")


async def test_window_reset_restores_capacity(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="w-1",
            requested_at=FIXED_AT,
        )
    )
    await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="w-2",
            requested_at=FIXED_AT,
        )
    )
    later = FIXED_AT + timedelta(hours=2)
    admission = await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="w-3",
            requested_at=later,
        )
    )
    assert admission.attempt_id == "w-3"


# --- Tavily shared-bucket rate detail (PLAN 4.2) ------------------------------


def _tavily_records():  # type: ignore[no-untyped-def]
    from polyweb.configuration.provider_limits import provider_limit_defaults

    return [r for r in provider_limit_defaults() if r.provider == "tavily"]


async def test_tavily_rate_windows_expose_shared_bucket_headroom(repository) -> None:
    from polyweb.configuration.provider_config import ProviderConfig

    svc = ProviderLimitsService(
        repository.limits,
        records=_tavily_records(),
        tier_defaults=None,
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await svc.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="tavily",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="t-detail-1",
            requested_at=FIXED_AT,
        )
    )
    windows = await svc.rate_limits.window_details("tavily", AuthMode.KEYED, FIXED_AT)
    assert len(windows) == 1
    assert windows[0].bucket_id == "tavily:keyed:search:requests"
    assert windows[0].remaining == Decimal("99")


async def test_tavily_vendor_cooldown_exposes_retry_after(repository) -> None:
    from polyweb.configuration.provider_config import ProviderConfig

    svc = ProviderLimitsService(
        repository.limits,
        records=_tavily_records(),
        tier_defaults=None,
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await svc.rate_limits.record_vendor_cooldown("tavily", AuthMode.KEYED, 45, FIXED_AT)
    windows = await svc.rate_limits.window_details("tavily", AuthMode.KEYED, FIXED_AT)
    assert windows[0].reset_at == FIXED_AT + timedelta(seconds=45)
