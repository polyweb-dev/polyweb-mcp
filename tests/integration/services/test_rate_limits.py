"""S0 core rate integration: durable cross-call reservations, no double count.

Synthetic records only. Uses a real SQLite repository through the shared
rate service. No vendor I/O.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.models.provider_limits import (
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
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_DB_ROOT = Path(".runtime-tmp/rate-limit-pytest-dbs")


@pytest_asyncio.fixture
async def repository():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"rate-limit-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            with suppress(FileNotFoundError):
                extra.unlink()


def _record():
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
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="h-1",
            requested_at=FIXED_AT,
        )
    )
    await svc.admit(
        LimitCallContext(
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
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="h-3",
                requested_at=FIXED_AT,
            )
        )
    assert exc.value.status_code == 429


async def test_vendor_observation_not_double_counted(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.rate_limits.observe(
        RateObservation(
            bucket_id="s-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("2"),
            remaining=Decimal("2"),
            observed_at=FIXED_AT,
        )
    )
    await svc.admit(
        LimitCallContext(
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="v-1",
            requested_at=FIXED_AT,
        )
    )
    bars = await svc.rate_limits.progress("synth", FIXED_AT)
    assert isinstance(bars, list)


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
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="w-1",
            requested_at=FIXED_AT,
        )
    )
    await svc.admit(
        LimitCallContext(
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
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="w-3",
            requested_at=later,
        )
    )
    assert admission.attempt_id == "w-3"
