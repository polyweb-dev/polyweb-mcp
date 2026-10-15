"""S0 core provider-limits service integration: synthetic catalog only.

Covers admission, exact depletion, concurrent funds/rates, audit, grants,
manual reuse, unknown rails, and absent-record compatibility. No vendor I/O.
"""

import asyncio
import gc
import time
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
    db_path = tmp_path / "limit-service.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _record(
    provider="synth", operation=LimitOperation.SEARCH, cost="0.005", windows=None, priced=True
):
    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=windows or [], published=bool(windows)),
        budget=BudgetBlock(
            model=BudgetModel.USD,
            standard_native_cost=Decimal(cost),
            usd_per_call=Decimal(cost),
            priced=priced,
        ),
        native_unit=UnitKind.USD,
        native_pool_id=f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )


def _service(repo, records, at=FIXED_AT):
    return ProviderLimitsService(repo.limits, records=records, tier_defaults={}, clock=lambda: at)


def _ctx(provider="synth", attempt="a-1", at=FIXED_AT):
    return LimitCallContext(
        provider=provider,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


async def _seed(repo, record, remaining, allowance=None):
    svc = _service(repo, [record])
    await svc.initialize()
    await repo.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=record.native_pool_id or "",
            provider=record.provider,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal(remaining),
            allowance=Decimal(allowance or remaining),
            credential_generation=0,
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
    await svc.record_success(admission, SearchResponse(query="q", results=[], provider="synth"))
    pool = await repository.limits.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("4.995")


async def test_concurrent_rate_never_overspends(repository) -> None:
    window = RateWindow(
        bucket_id="s-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    svc = await _seed(repository, _record(cost="0.0006", windows=[window]), "0.01")

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
        model=BudgetModel.USD,
        standard_native_cost=Decimal("0.005"),
        usd_per_call=Decimal("0.005"),
        priced=False,
    )
    svc = _service(repository, [record])
    await svc.initialize()
    admission = await svc.admit(_ctx(attempt="u-1"))
    assert admission.attempt_id == "u-1"
    await svc.save_grant(
        "synth",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("0"),
            fetch_crd=Decimal("0"),
        ),
        AuthMode.KEYED,
    )


async def test_grant_and_history_audit(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")
    saved = await svc.save_grant(
        "synth",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("10"),
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


async def test_manual_anchor_delete_clears_to_unknown(repository) -> None:
    """D3 pin: service delete of an anchor restores unknown, not the old values."""
    svc = await _seed(repository, _record(), "5.000")

    class _Anchor:
        remaining = Decimal("10")
        allowance = Decimal("5")
        billing_end = None
        updated_at = FIXED_AT

    await svc.apply_manual_anchor("synth", _Anchor())
    anchored = await repository.limits.get_pool("synth:keyed:USD")
    assert anchored is not None and anchored.remaining == Decimal("10")
    await svc.apply_manual_anchor("synth", None)
    cleared = await repository.limits.get_pool("synth:keyed:USD")
    assert cleared is not None
    assert cleared.remaining is None
    assert cleared.allowance is None


# --- Tavily funds and rate admission (PLAN 4.2/4.3) ---------------------------


def _tavily_service(repo, at=FIXED_AT):  # type: ignore[no-untyped-def]
    from freesearch.configuration.provider_config import ProviderConfig
    from freesearch.configuration.provider_limits import provider_limit_defaults

    svc = ProviderLimitsService(
        repo.limits,
        records=[r for r in provider_limit_defaults() if r.provider == "tavily"],
        tier_defaults=None,
        clock=lambda: at,
    )
    return svc, ProviderConfig()


def _tavily_ctx(operation, attempt, at=FIXED_AT):  # type: ignore[no-untyped-def]
    return LimitCallContext(
        provider="tavily",
        operation=operation,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


async def test_tavily_dev_bucket_mixed_ops_deny_101(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    for index in range(50):
        await svc.admit(_tavily_ctx(LimitOperation.SEARCH, f"dev-s-{index}"))
        await svc.admit(_tavily_ctx(LimitOperation.FETCH, f"dev-f-{index}"))
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "dev-s-101"))
    assert exc.value.status_code == 429


async def test_tavily_prod_bucket_mixed_ops_deny_1001(repository) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

    svc, _ = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(
        ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
    )
    for index in range(500):
        await svc.admit(_tavily_ctx(LimitOperation.SEARCH, f"prod-s-{index}"))
        await svc.admit(_tavily_ctx(LimitOperation.FETCH, f"prod-f-{index}"))
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_tavily_ctx(LimitOperation.FETCH, "prod-f-1001"))
    assert exc.value.status_code == 429


async def test_tavily_concurrent_mixed_ops_share_bucket(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    for index in range(99):
        await svc.admit(_tavily_ctx(LimitOperation.SEARCH, f"pre-{index}"))

    async def admit(attempt: str, operation):  # type: ignore[no-untyped-def]
        try:
            return await svc.admit(_tavily_ctx(operation, attempt))
        except LimitDeniedError as exc:
            return exc

    results = await asyncio.gather(
        admit("race-s-1", LimitOperation.SEARCH),
        admit("race-f-1", LimitOperation.FETCH),
        admit("race-s-2", LimitOperation.SEARCH),
        admit("race-f-2", LimitOperation.FETCH),
        admit("race-s-3", LimitOperation.SEARCH),
    )
    admitted = [r for r in results if not isinstance(r, LimitDeniedError)]
    denied = [r for r in results if isinstance(r, LimitDeniedError)]
    assert len(admitted) == 1
    assert len(denied) == 4
    assert all(d.status_code == 429 for d in denied)


async def test_tavily_free_zero_denies_vendor_402_zero(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=FIXED_AT,
            remaining=Decimal("0"),
            allowance=Decimal("1000"),
            credential_generation=0,
            source="vendor_402",
        )
    )
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "t-zero"))
    assert exc.value.status_code == 402
    assert "credits_exhausted" in exc.value.reasons


async def test_tavily_unknown_balance_stays_eligible(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    admission = await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "t-unknown"))
    assert admission.attempt_id == "t-unknown"


async def test_tavily_shared_pool_both_views_after_debit(repository) -> None:
    from freesearch.models.contracts import SearchRequest, SearchResponse

    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
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
    admission = await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "t-shared"))
    await svc.record_success(
        admission,
        SearchResponse(query="q", results=[], provider="tavily"),
        request=SearchRequest(query="q", limit=2),
    )
    view = await svc.provider_view("tavily")
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.aggregate_pool is not None
    assert auth.aggregate_pool.remaining == Decimal("999")
    by_operation = {v.operation: v for v in auth.crd_views}
    assert by_operation[LimitOperation.SEARCH].shared_pool_id == "tavily:keyed:credit"
    assert by_operation[LimitOperation.FETCH].shared_pool_id == "tavily:keyed:credit"
