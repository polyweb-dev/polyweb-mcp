"""Exa limits integration: catalog, rate limits, funds reservation, and 402 terminal denial.

Real SQLite repositories with the real Exa catalog records. No vendor I/O, no live keys.
"""

import gc
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import AnyHttpUrl

from freesearch.configuration.provider_limits import (
    provider_limit_defaults,
    provider_tier_defaults,
)
from freesearch.models.contracts import FetchRequest, SearchRequest, SearchResponse, UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    FundingMode,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateScope,
    RateWindowName,
    ResetRule,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
EXA_POOL = "exa:keyed:usd"


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
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    db_path = tmp_path / "exa-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (
            db_path,
            Path(f"{db_path}.migration.lock"),
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
        ):
            _unlink_with_retries(extra)


def _exa_records() -> list[ProviderLimitRecord]:
    return [r for r in provider_limit_defaults() if r.provider == "exa"]


def _service(repo: SQLiteRepository) -> ProviderLimitsService:
    return ProviderLimitsService(
        repo.limits,
        records=_exa_records(),
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )


def _snapshot(
    remaining: Decimal | None = Decimal("10.00"),
    allowance: Decimal | None = Decimal("10.00"),
    *,
    source: str = "vendor_api",
    observed_at: datetime = FIXED_AT,
) -> NativeUsageSnapshot:
    return NativeUsageSnapshot(
        pool_id=EXA_POOL,
        provider="exa",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        observed_at=observed_at,
        remaining=remaining,
        allowance=allowance,
        credential_generation=0,
        source=source,
    )


async def test_seeded_catalog_records(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    stored = [r for r in await repository.limits.list_records() if r.provider == "exa"]
    assert len(stored) == 2
    assert all(r.auth_mode is AuthMode.KEYED for r in stored)
    assert {r.operation for r in stored} == {LimitOperation.SEARCH, LimitOperation.FETCH}

    search = next(r for r in stored if r.operation is LimitOperation.SEARCH)
    assert search.native_pool_id == EXA_POOL
    assert search.native_unit is UnitKind.USD
    assert search.rate is not None
    assert len(search.rate.windows) == 1
    s_window = search.rate.windows[0]
    assert s_window.limit == Decimal("10")
    assert s_window.window is RateWindowName.SECOND
    assert s_window.scope is RateScope.TEAM
    assert s_window.bucket_id == "exa:keyed:search:requests"

    fetch = next(r for r in stored if r.operation is LimitOperation.FETCH)
    assert fetch.native_pool_id == EXA_POOL
    assert fetch.native_unit is UnitKind.USD
    assert fetch.rate is not None
    assert len(fetch.rate.windows) == 1
    f_window = fetch.rate.windows[0]
    assert f_window.limit == Decimal("100")
    assert f_window.window is RateWindowName.SECOND
    assert f_window.scope is RateScope.TEAM
    assert f_window.bucket_id == "exa:keyed:fetch:requests"


async def test_rate_admission_search_and_fetch(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("100.00")))

    # 10 search admissions within 1s succeed
    for i in range(10):
        admission = await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=f"rate-search-{i}",
                requested_at=FIXED_AT,
                request=SearchRequest(query="test", limit=10),
            )
        )
        assert admission.attempt_id == f"rate-search-{i}"

    # 11th search admission is denied with 429 (rate_limited)
    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="rate-search-11",
                requested_at=FIXED_AT,
                request=SearchRequest(query="test", limit=10),
            )
        )
    assert excinfo.value.status_code == 429
    assert excinfo.value.error.code == "rate_limited"
    assert excinfo.value.retry_after_seconds == 1

    # 100 fetch admissions within 1s succeed
    for i in range(100):
        admission = await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.FETCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=f"rate-fetch-{i}",
                requested_at=FIXED_AT,
                request=FetchRequest(url=AnyHttpUrl("https://example.com/doc")),
            )
        )
        assert admission.attempt_id == f"rate-fetch-{i}"

    # 101st fetch admission is denied with 429 (rate_limited)
    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.FETCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="rate-fetch-101",
                requested_at=FIXED_AT,
                request=FetchRequest(url=AnyHttpUrl("https://example.com/doc")),
            )
        )
    assert excinfo.value.status_code == 429
    assert excinfo.value.error.code == "rate_limited"
    assert excinfo.value.retry_after_seconds == 1


async def test_dynamic_crd_request_cost(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("10.00")))

    # Limit 10 -> 7 CRD ($0.007)
    adm_s10 = await service.admit(
        LimitCallContext(
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="cost-s10",
            requested_at=FIXED_AT,
            request=SearchRequest(query="test", limit=10),
        )
    )
    assert adm_s10.reserved_native == Decimal("0.007")
    assert adm_s10.reserved_crd == Decimal("7")

    # Limit 20 -> 17 CRD ($0.017)
    adm_s20 = await service.admit(
        LimitCallContext(
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="cost-s20",
            requested_at=FIXED_AT,
            request=SearchRequest(query="test", limit=20),
        )
    )
    assert adm_s20.reserved_native == Decimal("0.017")
    assert adm_s20.reserved_crd == Decimal("17")

    # Fetch 1 URL -> 1 CRD ($0.001)
    adm_f1 = await service.admit(
        LimitCallContext(
            provider="exa",
            operation=LimitOperation.FETCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="cost-f1",
            requested_at=FIXED_AT,
            request=FetchRequest(url=AnyHttpUrl("https://example.com/1"), url_count=1),
        )
    )
    assert adm_f1.reserved_native == Decimal("0.001")
    assert adm_f1.reserved_crd == Decimal("1")

    # Fetch 5 URLs -> 5 CRD ($0.005)
    adm_f5 = await service.admit(
        LimitCallContext(
            provider="exa",
            operation=LimitOperation.FETCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="cost-f5",
            requested_at=FIXED_AT,
            request=FetchRequest(url=AnyHttpUrl("https://example.com/1"), url_count=5),
        )
    )
    assert adm_f5.reserved_native == Decimal("0.005")
    assert adm_f5.reserved_crd == Decimal("5")


async def test_funds_denial_on_zero_balance(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("0.00")))

    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="denied-zero-balance",
                requested_at=FIXED_AT,
                request=SearchRequest(query="test", limit=10),
            )
        )
    assert excinfo.value.status_code == 402
    assert excinfo.value.error.code == "crd_exhausted"
    assert excinfo.value.error.retryable is False
    assert "funds_exhausted" in excinfo.value.reasons


async def test_terminal_402_records_zero_and_blocks_locally(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("10.00")))

    pool = await repository.limits.get_pool(EXA_POOL)
    assert pool is not None
    assert pool.remaining == Decimal("10.00")

    await service.record_terminal_402("exa", AuthMode.KEYED)

    updated_pool = await repository.limits.get_pool(EXA_POOL)
    assert updated_pool is not None
    assert updated_pool.remaining == Decimal("0")
    assert updated_pool.source == "vendor_402"
    assert updated_pool.native_unit is UnitKind.USD

    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="exa",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="denied-after-terminal-402",
                requested_at=FIXED_AT,
                request=SearchRequest(query="test", limit=10),
            )
        )
    assert excinfo.value.status_code == 402
    assert excinfo.value.error.code == "crd_exhausted"
    assert excinfo.value.error.retryable is False


async def test_debit_success_decrements_exact_usd_and_crd(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("10.00")))

    admission = await service.admit(
        LimitCallContext(
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="exa-debit-1",
            requested_at=FIXED_AT,
            request=SearchRequest(query="test", limit=10),
        )
    )
    assert admission.reserved_native == Decimal("0.007")
    assert admission.reserved_crd == Decimal("7")

    await service.record_success(
        admission,
        SearchResponse(query="test", results=[], provider="exa"),
        request=SearchRequest(query="test", limit=10),
    )

    pool = await repository.limits.get_pool(EXA_POOL)
    assert pool is not None
    assert pool.remaining == Decimal("9.993")

    totals = await repository.limits.crd_usage_totals("exa")
    assert len(totals) == 1
    assert totals[0].normalized_crd == Decimal("7")
    assert totals[0].attempt_count == 1


async def test_provider_view_crd_projections(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("10.00")))

    view = await service.provider_view("exa")
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)

    assert search_view.remaining_crd == Decimal("10000")
    assert search_view.possible_standard_calls == Decimal("1428")

    assert fetch_view.remaining_crd == Decimal("10000")
    assert fetch_view.possible_standard_calls == Decimal("10000")


def test_declared_tier_defaults() -> None:
    tiers = provider_tier_defaults().get("exa:keyed", [])
    assert len(tiers) == 3
    free_tier = next(t for t in tiers if t.pool_id == "exa:keyed:free")
    bonus_tier = next(t for t in tiers if t.pool_id == "exa:keyed:bonus")
    paid_tier = next(t for t in tiers if t.pool_id == "exa:keyed:paid")

    assert free_tier.native_allowance == Decimal("10")
    assert free_tier.native_unit is UnitKind.USD
    assert free_tier.reset_rule is ResetRule.MONTHLY_FIRST
    assert free_tier.funding_mode is FundingMode.RECURRING

    assert bonus_tier.native_allowance == Decimal("10")
    assert bonus_tier.native_unit is UnitKind.USD
    assert bonus_tier.reset_rule is ResetRule.NEVER
    assert bonus_tier.funding_mode is FundingMode.PREPAID

    assert paid_tier.native_unit is UnitKind.USD
    assert paid_tier.reset_rule is ResetRule.NEVER
    assert paid_tier.funding_mode is FundingMode.PREPAID
