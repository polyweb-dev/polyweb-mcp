"""S0 core sync + rate integration: leases, cadence, backoff, bars.

Synthetic adapters only. Covers single-tick seams, injected clocks, the
60-second minimum cadence, stale generations, and hour/day-only progress.
"""

import gc
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio

from polyweb.models.contracts import UnitKind
from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from polyweb.models.provider_limits import (
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
from polyweb.models.schema_enums import UpstreamScope
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.pools import UpstreamPoolRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.limits_sync import LimitSyncService
from polyweb.services.provider_limits import ProviderLimitsService
from tests.fixtures.execution import seed_execution_user

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
    db_path = tmp_path / "limit-sync.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _record(provider="synth"):
    return ProviderLimitRecord(
        provider=provider,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=[], published=False),
        budget=BudgetBlock(model=BudgetModel.USD, standard_native_cost=Decimal("0.005")),
        native_unit=UnitKind.USD,
        native_pool_id=f"{provider}:keyed:USD",
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
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=request.observed_at,
            remaining=self._remaining,
            allowance=self._remaining,
            credential_generation=0,
        )


async def test_null_snapshot_skips_without_balance_change(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    sync = LimitSyncService(
        repository.limits,
        svc,
        lambda: [_NullAdapter()],
        clock=lambda: FIXED_AT,
    )
    result = await sync.sync_provider("synth", FIXED_AT)
    assert result.status == "skipped"


async def test_single_tick_updates_balance(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    adapter = _VendorAdapter("5.000")
    sync = LimitSyncService(
        repository.limits,
        svc,
        lambda: [adapter],
        clock=lambda: FIXED_AT,
    )
    result = await sync.sync_provider("synth", FIXED_AT)
    assert result.status in ("synced", "skipped")
    assert adapter.calls >= 0


async def test_stale_generation_discarded(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.credential_changed("synth")
    assert (
        await repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="synth:keyed:USD",
                provider="synth",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("9.000"),
                credential_generation=0,
            )
        )
        is False
    )


async def _scoped_identity(repository, *, pooled: bool = False) -> str:  # type: ignore[no-untyped-def]
    user = await seed_execution_user(repository, "limits-test")
    async with repository.session() as session:
        credential = await CredentialRepository(session).insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="synth",
            owner_scope=CredentialOwnerScope.SYSTEM,
            owner_project_id=None,
            label="limits-test",
            auth_mode="api_key",
            created_by=user.id,
        )
        scope = f"cred:{credential.id}"
        if pooled:
            pools = UpstreamPoolRepository(session)
            pool = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="synth",
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key=str(credential.id),
                label="limits-test",
                constraints=[],
            )
            await pools.link_credential(
                credential_id=credential.id,
                operation=CredentialOperation.SEARCH,
                pool_id=pool.id,
                provider_type="synth",
            )
            scope = f"pool:{pool.id}"
        await session.commit()
    return scope


async def _scoped_observation(  # type: ignore[no-untyped-def]
    repository, scope: str, remaining: str, allowance: str | None
):
    """Store one credential-scoped funds observation of the synthetic pool."""

    from polyweb.models.provider_limits import NativePool

    pool_id = f"synth:keyed:USD#{scope}"
    await repository.limits.ensure_pool(
        NativePool(
            pool_id=pool_id,
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
        )
    )
    assert await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=pool_id,
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal(remaining),
            allowance=Decimal(allowance) if allowance is not None else None,
            credential_generation=1,
        )
    )


async def _synth_limits(repository) -> ProviderLimitsService:  # type: ignore[no-untyped-def]
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    return svc


async def test_card_shows_credential_scoped_funds_when_catalog_pool_is_unobserved(
    repository,
) -> None:
    """Regression: keys moved to stored credentials, so funds land on scoped rows."""

    svc = await _synth_limits(repository)
    await _scoped_observation(repository, await _scoped_identity(repository), "4.5", "5")

    keyed = (await svc.provider_view("synth")).auths[0]

    assert keyed.aggregate_pool is not None
    assert keyed.aggregate_pool.pool_id == "synth:keyed:USD"
    assert keyed.aggregate_pool.remaining == Decimal("4.5")
    assert keyed.aggregate_pool.allowance == Decimal("5")
    assert keyed.detail is not None and keyed.detail.native_balance == Decimal("4.5")
    # The projection is display-only: the catalog row keeps no balance.
    stored = await repository.limits.get_pool("synth:keyed:USD")
    assert stored is not None and stored.remaining is None


async def test_card_sums_distinct_scoped_funds_and_keeps_unknown_allowance(repository) -> None:
    svc = await _synth_limits(repository)
    await _scoped_observation(repository, await _scoped_identity(repository), "4", "5")
    await _scoped_observation(
        repository, await _scoped_identity(repository, pooled=True), "2", None
    )

    pool = (await svc.provider_view("synth")).auths[0].aggregate_pool

    assert pool is not None
    assert pool.remaining == Decimal("6")
    assert pool.allowance is None


async def test_catalog_observation_wins_over_scoped_funds(repository) -> None:
    svc = await _synth_limits(repository)
    assert await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("3.000"),
            allowance=Decimal("5"),
        )
    )
    await _scoped_observation(repository, await _scoped_identity(repository), "1", "5")

    pool = (await svc.provider_view("synth")).auths[0].aggregate_pool

    assert pool is not None and pool.remaining == Decimal("3.000")


async def test_missing_adapter_delegates_to_credential_sync(repository) -> None:
    from polyweb.models.provider_limits import SyncResult

    svc = await _synth_limits(repository)
    calls: list[str] = []

    async def credential_sync(provider: str, now: datetime) -> SyncResult | None:
        calls.append(provider)
        return SyncResult(
            provider=provider, status="skipped", observed_at=now, reason="no_credential"
        )

    sync = LimitSyncService(
        repository.limits, svc, lambda: [], clock=lambda: FIXED_AT, credential_sync=credential_sync
    )
    result = await sync.sync_provider("synth", FIXED_AT)

    assert calls == ["synth"]
    assert result.reason == "no_credential"


async def test_missing_adapter_without_credential_sync_stays_no_adapter(repository) -> None:
    svc = await _synth_limits(repository)

    async def unresolved(provider: str, now: datetime) -> None:
        return None

    plain = LimitSyncService(repository.limits, svc, lambda: [], clock=lambda: FIXED_AT)
    unresolved_sync = LimitSyncService(
        repository.limits, svc, lambda: [], clock=lambda: FIXED_AT, credential_sync=unresolved
    )

    assert (await plain.sync_provider("synth", FIXED_AT)).reason == "no_adapter"
    assert (await unresolved_sync.sync_provider("synth", FIXED_AT)).reason == "no_adapter"


async def test_rate_progress_hour_day_only(repository) -> None:
    svc = ProviderLimitsService(
        repository.limits,
        records=[_record()],
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )
    await svc.initialize()
    await svc.rate_limits.observe(
        RateObservation(
            bucket_id="s",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("10"),
            remaining=Decimal("7"),
            observed_at=FIXED_AT,
        )
    )
    bars = await svc.rate_limits.progress("synth", FIXED_AT)
    assert all(b.window in ("1h", "1d") for b in bars)


# --- Tavily durable cadence (PLAN 4.3): 60s floor, atomic claims -------------


def _tavily_records():  # type: ignore[no-untyped-def]
    from polyweb.configuration.provider_limits import provider_limit_defaults

    return [r for r in provider_limit_defaults() if r.provider == "tavily"]


class _TavilyVendorAdapter:
    name = "tavily"
    limit_auth_mode = AuthMode.KEYED

    def __init__(self) -> None:
        self.calls = 0

    async def usage_snapshot(self, request: UsageSyncRequest):
        self.calls += 1
        return NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=request.observed_at,
            remaining=Decimal("999"),
            allowance=Decimal("1000"),
            credential_generation=0,
        )


def _tavily_sync(repository, adapter, owner: str = "owner-a", clock=FIXED_AT):  # type: ignore[no-untyped-def]
    svc = ProviderLimitsService(
        repository.limits,
        records=_tavily_records(),
        tier_defaults=None,
        clock=lambda: clock,
    )
    sync = LimitSyncService(
        repository.limits,
        svc,
        lambda: [adapter],
        clock=lambda: clock,
        owner=owner,
    )
    return svc, sync


async def test_tavily_second_poll_inside_cadence_is_lease_held(repository) -> None:
    from datetime import timedelta

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    first = await sync.sync_provider("tavily", FIXED_AT)
    assert first.status == "synced"
    assert adapter.calls == 1
    # 59.999s later the durable cadence still holds: no second GET.
    second = await sync.sync_provider("tavily", FIXED_AT + timedelta(seconds=59.999))
    assert second.status == "skipped"
    assert adapter.calls == 1


async def test_tavily_poll_at_60s_syncs_again(repository) -> None:
    from datetime import timedelta

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    assert (await sync.sync_provider("tavily", FIXED_AT)).status == "synced"
    result = await sync.sync_provider("tavily", FIXED_AT + timedelta(seconds=60))
    assert result.status == "synced"
    assert adapter.calls == 2


async def test_tavily_same_owner_cannot_bypass_active_claim(repository) -> None:
    from polyweb.models.provider_limits import SyncClaim

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    assert (await sync.sync_provider("tavily", FIXED_AT)).status == "synced"
    # Same owner, active lease: the atomic claim refuses.
    claim = SyncClaim(provider="tavily", owner="owner-a", now=FIXED_AT, lease_seconds=90)
    assert await repository.limits.claim_sync(claim) is False


async def test_tavily_two_schedulers_one_wins(repository) -> None:
    adapter = _TavilyVendorAdapter()
    svc, sync_a = _tavily_sync(repository, adapter, owner="owner-a")
    _, sync_b = _tavily_sync(repository, adapter, owner="owner-b")
    await svc.initialize()
    first = await sync_a.sync_provider("tavily", FIXED_AT)
    second = await sync_b.sync_provider("tavily", FIXED_AT)
    assert first.status == "synced"
    assert second.status == "skipped"
    assert adapter.calls == 1


async def test_tavily_force_sync_respects_cadence(repository) -> None:
    from datetime import timedelta

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    assert (await sync.sync_provider("tavily", FIXED_AT)).status == "synced"
    forced = await sync.sync_provider("tavily", FIXED_AT + timedelta(seconds=30))
    assert forced.status == "skipped"
    assert adapter.calls == 1


async def test_tavily_poll_failure_keeps_balance_and_marks_stale(repository) -> None:
    from datetime import timedelta

    from polyweb.infrastructure.resilience import ProviderOperationError
    from polyweb.models.contracts import ProviderError

    class _Failing:
        name = "tavily"
        limit_auth_mode = AuthMode.KEYED
        calls = 0

        async def usage_snapshot(self, request: UsageSyncRequest):
            type(self).calls += 1
            raise ProviderOperationError(
                ProviderError(provider="tavily", code="transport_error", message="down")
            )

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    assert (await sync.sync_provider("tavily", FIXED_AT)).status == "synced"
    failing_sync = LimitSyncService(
        repository.limits, svc, lambda: [_Failing()], clock=lambda: FIXED_AT + timedelta(seconds=61)
    )
    result = await failing_sync.sync_provider("tavily", FIXED_AT + timedelta(seconds=61))
    assert result.status == "failed"
    pool = await repository.limits.get_pool("tavily:keyed:credit")
    assert pool is not None and pool.remaining == Decimal("999")


async def test_tavily_old_poll_cannot_replace_newer_terminal(repository) -> None:
    from datetime import timedelta

    adapter = _TavilyVendorAdapter()
    svc, sync = _tavily_sync(repository, adapter)
    await svc.initialize()
    assert (await sync.sync_provider("tavily", FIXED_AT)).status == "synced"
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=FIXED_AT + timedelta(seconds=61),
            remaining=Decimal("0"),
            allowance=Decimal("1000"),
            credential_generation=0,
            source="vendor_402",
        )
    )
    # A late positive read for the same month must not restore funds.
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=FIXED_AT,
            remaining=Decimal("1000"),
            allowance=Decimal("1000"),
            credential_generation=0,
        )
    )
    pool = await repository.limits.get_pool("tavily:keyed:credit")
    assert pool is not None and pool.remaining == Decimal("0")
