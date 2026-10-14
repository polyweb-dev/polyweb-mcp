"""Firecrawl limits integration: catalog, rate limits, funds reservation, and 402 terminal denial.

Real SQLite repositories with the real Firecrawl catalog records. No vendor I/O, no live keys.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.models.contracts import FetchRequest, SearchRequest, UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateScope,
    RateWindowName,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_DB_ROOT = Path(".runtime-tmp/firecrawl-limit-pytest-dbs")
FIRECRAWL_POOL = "firecrawl:keyed:credit"


@pytest_asyncio.fixture
async def repository():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"firecrawl-limit-{uuid.uuid4().hex}.db"
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
            with suppress(OSError):
                extra.unlink()


def _firecrawl_records() -> list[ProviderLimitRecord]:
    return [r for r in provider_limit_defaults() if r.provider == "firecrawl"]


def _service(repo: SQLiteRepository) -> ProviderLimitsService:
    return ProviderLimitsService(
        repo.limits,
        records=_firecrawl_records(),
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )


def _snapshot(
    remaining: Decimal | None = Decimal("1000"),
    allowance: Decimal | None = Decimal("1000"),
    *,
    source: str = "vendor_api",
    observed_at: datetime = FIXED_AT,
) -> NativeUsageSnapshot:
    return NativeUsageSnapshot(
        pool_id=FIRECRAWL_POOL,
        provider="firecrawl",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        observed_at=observed_at,
        remaining=remaining,
        allowance=allowance,
        credential_generation=0,
        source=source,
    )


async def test_seeded_catalog_records(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    stored = [r for r in await repository.limits.list_records() if r.provider == "firecrawl"]
    assert len(stored) == 4

    keyed = [r for r in stored if r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    assert {r.operation for r in keyed} == {LimitOperation.SEARCH, LimitOperation.FETCH}

    for record in keyed:
        assert record.plan_name == "Free plan (1,000 monthly credits)"
        assert record.usage_url == "https://firecrawl.dev/app/settings"
        assert record.native_pool_id == FIRECRAWL_POOL
        assert record.rate is not None
        assert len(record.rate.windows) == 1
        window = record.rate.windows[0]
        assert window.bucket_id == "firecrawl:keyed:requests"
        assert window.window is RateWindowName.MINUTE
        assert window.limit == Decimal("10")
        assert window.scope is RateScope.TEAM

    keyless = [r for r in stored if r.auth_mode is AuthMode.KEYLESS]
    assert len(keyless) == 2
    assert {r.operation for r in keyless} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    for record in keyless:
        assert record.transport_available is False
        assert record.plan_name == "Keyless public pool (rate limit not published)"
        assert record.budget is None


async def test_rate_admission_enforces_10_rpm_team_scoped(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000")))

    # 10 admissions within the minute succeed
    for i in range(10):
        admission = await service.admit(
            LimitCallContext(
                provider="firecrawl",
                operation=LimitOperation.SEARCH if i % 2 == 0 else LimitOperation.FETCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=f"rate-{i}",
                requested_at=FIXED_AT,
            )
        )
        assert admission.attempt_id == f"rate-{i}"

    # 11th admission is denied by team-scoped 10 RPM rate limit
    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="firecrawl",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="rate-11-denied",
                requested_at=FIXED_AT,
            )
        )
    assert excinfo.value.status_code == 429


async def test_funds_admission_reserves_search_and_fetch_costs(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000")))

    # Search with limit=10: 2 credits (7.6 CRD)
    adm_s10 = await service.admit(
        LimitCallContext(
            provider="firecrawl",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="s-10",
            requested_at=FIXED_AT,
            request=SearchRequest(query="test", limit=10),
        )
    )
    assert adm_s10.reserved_native == Decimal("2")
    assert adm_s10.reserved_crd == Decimal("7.6")

    # Search with limit=15: 4 credits (15.2 CRD)
    adm_s15 = await service.admit(
        LimitCallContext(
            provider="firecrawl",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="s-15",
            requested_at=FIXED_AT,
            request=SearchRequest(query="test", limit=15),
        )
    )
    assert adm_s15.reserved_native == Decimal("4")
    assert adm_s15.reserved_crd == Decimal("15.2")

    # Fetch with default options: 1 credit (3.8 CRD)
    adm_f_def = await service.admit(
        LimitCallContext(
            provider="firecrawl",
            operation=LimitOperation.FETCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="f-def",
            requested_at=FIXED_AT,
            request=FetchRequest(url="https://example.com/doc"),
        )
    )
    assert adm_f_def.reserved_native == Decimal("1")
    assert adm_f_def.reserved_crd == Decimal("3.8")

    # Fetch with pdf_pages=2, json_extract=True: 7 credits (26.6 CRD)
    adm_f_mod = await service.admit(
        LimitCallContext(
            provider="firecrawl",
            operation=LimitOperation.FETCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="f-mod",
            requested_at=FIXED_AT,
            request=FetchRequest(url="https://example.com/doc", pdf_pages=2, json_extract=True),
        )
    )
    assert adm_f_mod.reserved_native == Decimal("7")
    assert adm_f_mod.reserved_crd == Decimal("26.6")


async def test_terminal_402_recording_clamps_balance_and_denies(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000")))

    # Initial balance is 1000
    pool = await repository.limits.get_pool(FIRECRAWL_POOL)
    assert pool is not None
    assert pool.remaining == Decimal("1000")

    # Record terminal 402
    await service.record_terminal_402("firecrawl", AuthMode.KEYED)

    # Balance is clamped to 0 with vendor_402 source
    updated_pool = await repository.limits.get_pool(FIRECRAWL_POOL)
    assert updated_pool is not None
    assert updated_pool.remaining == Decimal("0")
    assert updated_pool.source == "vendor_402"

    # Subsequent admission immediately denied locally with status 402
    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                provider="firecrawl",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="denied-after-402",
                requested_at=FIXED_AT,
                request=SearchRequest(query="denied", limit=10),
            )
        )
    assert excinfo.value.status_code == 402
    assert "funds_exhausted" in excinfo.value.reasons
