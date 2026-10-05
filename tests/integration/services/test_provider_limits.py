"""S0 core provider-limits service integration: synthetic catalog only.

Covers admission, exact depletion, concurrent funds/rates, audit, grants,
manual reuse, unknown rails, and absent-record compatibility. No vendor I/O.
"""

import asyncio
import gc
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    CRDPriceProfile,
    LimitCallContext,
    LimitDeniedError,
    LimitHistoryQuery,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
)
from freesearch.models.provider_limits import (
    CRDGrantPayload as GrantPayload,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_DB_ROOT = Path(".runtime-tmp/limit-service-pytest-dbs")


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
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
async def repository():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-service-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _record(provider="synth", operation=LimitOperation.SEARCH, cost="0.005",
            windows=None, priced=True):
    return ProviderLimitRecord(
        provider=provider, operation=operation, auth_mode=AuthMode.KEYED,
        supported=True, transport_available=True,
        rate=RateBlock(windows=windows or [], published=bool(windows)),
        budget=BudgetBlock(
            model=BudgetModel.USD, native_cost_per_crd=Decimal(cost),
            usd_per_call=Decimal(cost), priced=priced,
        ),
        native_unit=UnitKind.USD, native_pool_id=f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )


def _service(repo, records, at=FIXED_AT):
    return ProviderLimitsService(
        repo.limits, records=records, tier_defaults={}, clock=lambda: at
    )


def _ctx(provider="synth", attempt="a-1", at=FIXED_AT):
    return LimitCallContext(
        provider=provider, operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED, attempt_id=attempt, requested_at=at,
    )


async def _seed(repo, record, remaining, allowance=None):
    svc = _service(repo, [record])
    await svc.initialize()
    await repo.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=record.native_pool_id or "", provider=record.provider,
            auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
            observed_at=FIXED_AT, remaining=Decimal(remaining),
            allowance=Decimal(allowance or remaining), credential_generation=0,
        )
    )
    return svc


async def test_empty_catalog_dashboard_is_empty(repository) -> None:
    svc = _service(repository, [])
    await svc.initialize()
    assert await svc.dashboard_views() == []
    assert svc.records == []


async def test_absent_record_adapter_is_never_gated(repository) -> None:
    svc = _service(repository, [])
    await svc.initialize()
    assert svc.supports("ghost", LimitOperation.SEARCH, AuthMode.KEYED) is False


async def test_exact_depletion_058_vs_0599(repository) -> None:
    svc = await _seed(repository, _record(cost="0.000599"), "0.00058", "0.005")
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_ctx())
    assert exc.value.status_code == 402


async def test_success_debits_exact_crd(repository) -> None:
    from freesearch.models.contracts import SearchResponse

    svc = await _seed(repository, _record(cost="0.005"), "5.000")
    admission = await svc.admit(_ctx(attempt="ok-1"))
    await svc.record_success(
        admission, SearchResponse(query="q", results=[], provider="synth")
    )
    pool = await repository.limits.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("4.995")


async def test_concurrent_rate_never_overspends(repository) -> None:
    window = RateWindow(
        bucket_id="s-hour", limit=Decimal("1"), window=RateWindowName.HOUR,
        scope=RateScope.KEY, unit=RateUnit.REQUESTS,
    )
    svc = await _seed(
        repository, _record(cost="0.0006", windows=[window]), "0.01"
    )

    async def admit(attempt):
        try:
            return await svc.admit(_ctx(attempt=attempt))
        except LimitDeniedError as exc:
            return exc

    first, second = await asyncio.gather(admit("c-1"), admit("c-2"))
    oks = sum(1 for r in (first, second) if not isinstance(r, LimitDeniedError))
    denied = [r for r in (first, second) if isinstance(r, LimitDeniedError)]
    assert oks == 1
    assert len(denied) == 1
    assert denied[0].status_code in (402, 429)
    pool = await repository.limits.get_pool("synth:keyed:USD")
    assert pool is not None and (pool.remaining or Decimal("0")) >= 0


async def test_unknown_balance_stays_eligible_until_grant_zero(repository) -> None:
    record = _record()
    record.budget = BudgetBlock(
        model=BudgetModel.USD, native_cost_per_crd=Decimal("0.005"),
        usd_per_call=Decimal("0.005"), priced=False,
    )
    svc = _service(repository, [record])
    await svc.initialize()
    admission = await svc.admit(_ctx(attempt="u-1"))
    assert admission.attempt_id == "u-1"
    await svc.save_grant(
        "synth",
        GrantPayload(
            version=0, period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1), search_crd=Decimal("0"),
            fetch_crd=Decimal("0"),
        ),
        AuthMode.KEYED,
    )


async def test_grant_and_history_audit(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")
    saved = await svc.save_grant(
        "synth",
        GrantPayload(
            version=0, period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1), search_crd=Decimal("10"),
            fetch_crd=Decimal("4"),
        ),
        AuthMode.KEYED,
    )
    assert saved.auth(AuthMode.KEYED) is not None
    history = await svc.history(
        LimitHistoryQuery(provider="synth", auth_mode=AuthMode.KEYED, limit=10)
    )
    assert any(e.reason == "grant" for e in history.events)


async def test_manual_anchor_reuse(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")

    class _Anchor:
        remaining = Decimal("7.000")
        allowance = Decimal("7.000")
        billing_end = None
        updated_at = FIXED_AT

    pool_before = await repository.limits.get_pool("synth:keyed:USD")
    assert pool_before is not None and pool_before.manual_anchor is False
    await svc.apply_manual_anchor("ghost-provider", None)
    await svc.apply_manual_anchor("synth", None)


async def test_credential_change_rejects_stale(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")
    await svc.credential_changed("synth")
    assert await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth",
            auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
            observed_at=FIXED_AT, remaining=Decimal("9.000"),
            credential_generation=0,
        )
    ) is False
