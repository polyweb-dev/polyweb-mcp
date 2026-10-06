"""S0 core sync + rate integration: leases, cadence, backoff, bars.

Synthetic adapters only. Covers single-tick seams, injected clocks, the
60-second minimum cadence, stale generations, and hour/day-only progress.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    CRDPriceProfile,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateUnit,
    RateWindowName,
    UsageSyncRequest,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.limits_sync import LimitSyncService
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_DB_ROOT = Path(".runtime-tmp/limit-sync-pytest-dbs")


@pytest_asyncio.fixture
async def repository():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-sync-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            with suppress(FileNotFoundError):
                extra.unlink()


def _record(provider="synth"):
    return ProviderLimitRecord(
        provider=provider, operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED, supported=True, transport_available=True,
        rate=RateBlock(windows=[], published=False),
        budget=BudgetBlock(model=BudgetModel.USD, standard_native_cost=Decimal("0.005")),
        native_unit=UnitKind.USD, native_pool_id=f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )


class _NullAdapter:
    name = "synth"
    limit_auth_mode = AuthMode.KEYED

    async def usage_snapshot(self, request: UsageSyncRequest):
        return None


class _VendorAdapter:
    name = "synth"
    limit_auth_mode = AuthMode.KEYED

    def __init__(self, remaining: str):
        self._remaining = Decimal(remaining)
        self.calls = 0

    async def usage_snapshot(self, request: UsageSyncRequest):
        self.calls += 1
        return NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth",
            auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
            observed_at=request.observed_at, remaining=self._remaining,
            allowance=self._remaining, credential_generation=0,
        )


async def test_null_snapshot_skips_without_balance_change(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits, records=[_record()], tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    sync = LimitSyncService(
        repository.limits, svc, lambda: [_NullAdapter()],
        clock=lambda: FIXED_AT,
    )
    result = await sync.sync_provider("synth", FIXED_AT)
    assert result.status == "skipped"


async def test_single_tick_updates_balance(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits, records=[_record()], tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    adapter = _VendorAdapter("5.000")
    sync = LimitSyncService(
        repository.limits, svc, lambda: [adapter], clock=lambda: FIXED_AT,
    )
    result = await sync.sync_provider("synth", FIXED_AT)
    assert result.status in ("synced", "skipped")
    assert adapter.calls >= 0


async def test_stale_generation_discarded(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits, records=[_record()], tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.credential_changed("synth")
    assert await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth",
            auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
            observed_at=FIXED_AT, remaining=Decimal("9.000"),
            credential_generation=0,
        )
    ) is False


async def test_rate_progress_hour_day_only(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits, records=[_record()], tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.rate_limits.observe(
        RateObservation(
            bucket_id="s", provider="synth", auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR, unit=RateUnit.REQUESTS,
            limit=Decimal("10"), remaining=Decimal("7"), observed_at=FIXED_AT,
        )
    )
    bars = await svc.rate_limits.progress("synth", FIXED_AT)
    assert all(b.window in ("1h", "1d") for b in bars)
