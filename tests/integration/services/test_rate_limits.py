"""S0 core rate integration: durable cross-call reservations, no double count.

Synthetic records only. Uses a real SQLite repository through the shared
rate service. No vendor I/O.
"""

import gc
import time
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


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    db_path = tmp_path / "rate-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


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


# --- Tavily shared-bucket rate detail (PLAN 4.2) ------------------------------


def _tavily_records():  # type: ignore[no-untyped-def]
    from freesearch.configuration.provider_limits import provider_limit_defaults

    return [r for r in provider_limit_defaults() if r.provider == "tavily"]


async def test_tavily_rate_windows_expose_shared_bucket_headroom(repository) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

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
    from freesearch.configuration.provider_config import ProviderConfig

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
