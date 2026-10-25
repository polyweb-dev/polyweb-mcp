"""S1 Brave integration: sync, gate, manual fallback, grants. Mock HTTP only.

Brave slice only. Real SQLite repositories with the real Brave catalog
records and a mock-transport Brave adapter. No vendor I/O, no live keys.
Plan: monthly headers as budget, search 5 CRDs, manual fallback, funds 402.
"""

import gc
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest_asyncio
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter
from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.models.contracts import SearchRequest, SearchResponse, UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    CRDState,
    LimitCallContext,
    LimitDeniedError,
    LimitHistoryQuery,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    UsageSyncRequest,
)
from freesearch.models.provider_limits import (
    CRDGrantPayload as GrantPayload,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.limits_sync import LimitSyncService
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
    db_path = tmp_path / "brave-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _brave_records() -> list[ProviderLimitRecord]:
    return [r for r in provider_limit_defaults() if r.provider == "brave"]


def _payload() -> dict[str, object]:
    return {
        "web": {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com/article",
                    "description": "A result snippet.",
                    "page_age": "2024-01-02T03:04:05Z",
                    "language": "en",
                }
            ]
        }
    }


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    return BraveAdapter(client, api_key=SecretStr("brave-test-secret")), client


def _headers_adapter() -> tuple[BraveAdapter, httpx.AsyncClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"X-RateLimit-Remaining": "49, 900", "X-RateLimit-Limit": "50, 1000"},
        )

    return _adapter(handler)


def _service(repo: SQLiteRepository) -> ProviderLimitsService:
    return ProviderLimitsService(
        repo.limits,
        records=_brave_records(),
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )


async def test_b01_seeded_catalog_holds_two_brave_records(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    stored = [r for r in await repository.limits.list_records() if r.provider == "brave"]
    assert len(stored) == 2
    assert {r.operation for r in stored} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    assert all(r.auth_mode is AuthMode.KEYED for r in stored)


async def test_sync_monthly_headers_update_budget_only(repository: SQLiteRepository) -> None:
    adapter, client = _headers_adapter()
    try:
        service = _service(repository)
        await service.initialize()
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
        sync = LimitSyncService(
            repository.limits, service, lambda: [adapter], clock=lambda: FIXED_AT
        )
        result = await sync.sync_provider("brave", FIXED_AT)
    finally:
        await client.aclose()
    assert result.status == "synced"
    assert result.changed is True
    pool = await repository.limits.get_pool("brave:keyed:usd")
    assert pool is not None
    assert pool.allowance == Decimal("5.000")
    assert pool.remaining == Decimal("4.500")
    assert pool.source == "vendor_headers"
    bars = await service.rate_limits.progress("brave", FIXED_AT)
    assert bars == []


async def test_zero_funds_deny_with_non_retryable_402(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="brave:keyed:usd",
            provider="brave",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("0"),
            allowance=Decimal("5.000"),
            credential_generation=0,
        )
    )
    try:
        await service.admit(
            LimitCallContext(
                provider="brave",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="brave-402",
                requested_at=FIXED_AT,
            )
        )
        raise AssertionError("admission must deny")
    except LimitDeniedError as exc:
        assert exc.status_code == 402
        assert exc.error.code == "crd_exhausted"
        assert exc.error.retryable is False
        assert exc.error.details.get("origin") == "local"


async def test_manual_fallback_gives_estimated_5000(repository: SQLiteRepository) -> None:
    from freesearch.services import credit_units as cu

    service = _service(repository)
    await service.initialize()

    class _Anchor:
        remaining = Decimal("5")
        allowance = Decimal("5")
        billing_end = None
        updated_at = FIXED_AT

    await service.apply_manual_anchor("brave", _Anchor())
    pool = await repository.limits.get_pool("brave:keyed:usd")
    assert pool is not None and pool.remaining == Decimal("5")
    assert pool.confidence.value == "estimated"
    search = next(r for r in _brave_records() if r.operation is LimitOperation.SEARCH)
    assert cu.native_to_crd(pool, search.conversion_profile) == Decimal("5000")


async def test_grant_and_history_audit(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    saved = await service.save_grant(
        "brave",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("10"),
            fetch_crd=Decimal("0"),
        ),
        AuthMode.KEYED,
    )
    auth = saved.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.grants.search_granted_crd == Decimal("10")
    history = await service.history(
        LimitHistoryQuery(provider="brave", auth_mode=AuthMode.KEYED, limit=10)
    )
    assert any(e.reason == "grant" for e in history.events)


async def test_two_successes_debit_exact_ten(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="brave:keyed:usd",
            provider="brave",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("5.000"),
            allowance=Decimal("5.000"),
            credential_generation=0,
        )
    )
    for attempt in ("brave-s1", "brave-s2"):
        admission = await service.admit(
            LimitCallContext(
                provider="brave",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=attempt,
                requested_at=FIXED_AT,
            )
        )
        await service.record_success(
            admission, SearchResponse(query="q", results=[], provider="brave")
        )
    pool = await repository.limits.get_pool("brave:keyed:usd")
    assert pool is not None and pool.remaining == Decimal("4.990")
    totals = await repository.limits.crd_usage_totals("brave")
    assert len(totals) == 1
    assert totals[0].normalized_crd == Decimal("10")
    assert totals[0].attempt_count == 2


async def test_provider_view_search_finite_fetch_unavailable(
    repository: SQLiteRepository,
) -> None:
    adapter, client = _headers_adapter()
    try:
        service = _service(repository)
        await service.initialize()
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="brave", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
        assert snapshot is not None
        await repository.limits.apply_snapshot(snapshot)
        view = await service.provider_view("brave")
    finally:
        await client.aclose()
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    assert len(view.auths) == 1
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.state is CRDState.FINITE
    assert search_view.request_cost_crd == Decimal("5")
    assert search_view.remaining_crd == Decimal("4500")
    assert fetch_view.state is CRDState.UNAVAILABLE
