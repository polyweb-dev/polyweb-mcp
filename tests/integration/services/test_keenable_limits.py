"""Keenable integration: shared pool, sync, rate, rebuild. Mock HTTP only.

Keenable slice only. Real SQLite repositories with the real Keenable catalog
records and mock-transport adapters. No vendor I/O, no live keys. Plan:
100000 shared monthly requests, 10 per second keyed, 10 per second and 1000
per hour keyless, reported credits debit native units, 402 outranks paid.
"""

import asyncio
import gc
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest_asyncio
from pydantic import SecretStr

from polyweb.adapters.keenable import KeenableAdapter
from polyweb.configuration.provider_limits import provider_limit_defaults
from polyweb.models.contracts import (
    FetchRequest,
    SearchRequest,
    SearchResponse,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.provider_limits import (
    AuthMode,
    CRDState,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    UsageSyncRequest,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.limits_sync import LimitSyncService
from polyweb.services.provider_limits import ProviderLimitsService
from tests.fixtures.execution import FIXTURE_ACTOR, seed_execution_project
from tests.fixtures.execution import attributed_tracked_call as tracked_call

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_KEY = SecretStr("keenable-test-secret")


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
    db_path = tmp_path / "keenable-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _keenable_records() -> list[ProviderLimitRecord]:
    return [r for r in provider_limit_defaults() if r.provider == "keenable"]


def _pool_id() -> str:
    return "keenable:keyed:request"


def _service(repo: SQLiteRepository) -> ProviderLimitsService:
    return ProviderLimitsService(
        repo.limits,
        records=_keenable_records(),
        tier_defaults={},
        clock=lambda: FIXED_AT,
    )


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[KeenableAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    return KeenableAdapter(client, api_key=_KEY), client


def _search_fetch_handler(
    search_credits: object = 3, fetch_credits: object = 2
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "results": [{"title": "k", "url": "https://example.com/k"}],
                    "_meta": {
                        "keenable/usage": {
                            "credits": search_credits,
                            "paid": False,
                            "sku": "search.pro",
                        }
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "content": "hello world",
                "title": "Doc",
                "_meta": {
                    "keenable/usage": {
                        "credits": fetch_credits,
                        "paid": False,
                        "sku": "fetch",
                    }
                },
            },
        )

    return handler


async def _seed_full(service: ProviderLimitsService, repo: SQLiteRepository) -> None:
    await service.initialize()
    await repo.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=_pool_id(),
            provider="keenable",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.REQUEST,
            observed_at=FIXED_AT,
            remaining=Decimal("100000"),
            allowance=Decimal("100000"),
            credential_generation=0,
        )
    )


async def test_provider_view_uses_keenable_runtime_auth_mode(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()

    service.apply_keenable_auth_mode(AuthMode.KEYLESS)
    keyless_view = await service.provider_view("keenable")
    assert keyless_view.active_auth_mode is AuthMode.KEYLESS
    assert {auth.auth_mode for auth in keyless_view.auths} == {AuthMode.KEYED, AuthMode.KEYLESS}

    service.apply_keenable_auth_mode(AuthMode.KEYED)
    keyed_view = await service.provider_view("keenable")
    assert keyed_view.active_auth_mode is AuthMode.KEYED


async def test_provider_view_keeps_catalog_fallback_without_runtime_auth_mode(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()

    view = await service.provider_view("keenable")

    assert view.active_auth_mode is AuthMode.KEYED


async def test_search_and_fetch_reported_costs_debit_one_pool(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await _seed_full(service, repository)
    adapter, client = _adapter(_search_fetch_handler(3, 2))
    try:
        search = await tracked_call(
            repository,
            adapter,
            lambda running: running.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            ),
            operation=UsageOperation.SEARCH,
            limits=service,
            attribution=await seed_execution_project(repository),
        )
        fetch = await tracked_call(
            repository,
            adapter,
            lambda running: running.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/k"
                )
            ),
            operation=UsageOperation.FETCH,
            limits=service,
            attribution=await seed_execution_project(repository),
        )
    finally:
        await client.aclose()
    assert search.usage is not None and search.usage.units == Decimal("3")
    assert fetch.usage is not None and fetch.usage.units == Decimal("2")
    pool = await repository.limits.get_pool(_pool_id())
    assert pool is not None and pool.remaining == Decimal("99995")
    view = await service.provider_view("keenable")
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.state is CRDState.FINITE
    assert fetch_view.state is CRDState.FINITE
    assert search_view.remaining_crd == Decimal("399980")
    assert fetch_view.remaining_crd == Decimal("399980")
    assert search_view.shared_pool_id == fetch_view.shared_pool_id == _pool_id()
    totals = await repository.limits.crd_usage_totals("keenable")
    by_op = {t.operation: t for t in totals}
    assert by_op[LimitOperation.SEARCH].normalized_crd == Decimal("12")
    assert by_op[LimitOperation.FETCH].normalized_crd == Decimal("8")
    assert by_op[LimitOperation.SEARCH].attempt_count == 1
    assert by_op[LimitOperation.FETCH].attempt_count == 1


async def test_sync_does_not_repeat_debit(repository: SQLiteRepository) -> None:
    service = _service(repository)
    await _seed_full(service, repository)
    adapter, client = _adapter(_search_fetch_handler(3, 2))
    try:
        await tracked_call(
            repository,
            adapter,
            lambda running: running.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            ),
            operation=UsageOperation.SEARCH,
            limits=service,
            attribution=await seed_execution_project(repository),
        )
        await tracked_call(
            repository,
            adapter,
            lambda running: running.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/k"
                )
            ),
            operation=UsageOperation.FETCH,
            limits=service,
            attribution=await seed_execution_project(repository),
        )
        before = await repository.limits.get_pool(_pool_id())
        sync = LimitSyncService(
            repository.limits, service, lambda: [adapter], clock=lambda: FIXED_AT
        )
        result = await sync.sync_provider("keenable", FIXED_AT)
        after = await repository.limits.get_pool(_pool_id())
    finally:
        await client.aclose()
    assert result.status == "synced"
    assert before is not None and after is not None
    assert after.remaining == Decimal("99995")
    assert after.remaining == before.remaining
    totals = await repository.limits.crd_usage_totals("keenable")
    assert sum(t.attempt_count for t in totals) == 2


async def test_actual_sku_cost_does_not_consume_extra_rate(
    repository: SQLiteRepository,
) -> None:
    from datetime import datetime as _dt

    from polyweb.models.provider_limits import RateWindowName

    service = _service(repository)
    await _seed_full(service, repository)
    adapter, client = _adapter(_search_fetch_handler(3, 2))
    try:
        await tracked_call(
            repository,
            adapter,
            lambda running: running.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            ),
            operation=UsageOperation.SEARCH,
            limits=service,
            attribution=await seed_execution_project(repository),
        )
    finally:
        await client.aclose()
    used = await repository.limits.count_attempts(
        "keenable:keyed:requests",
        window=RateWindowName.SECOND,
        now=_dt.now(UTC),
    )
    assert used == Decimal("1")


async def test_failures_release_funds_reservations(
    repository: SQLiteRepository,
) -> None:
    from polyweb.models.contracts import ProviderError

    service = _service(repository)
    await _seed_full(service, repository)
    admission = await service.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="keenable",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="keenable-fail-1",
            requested_at=FIXED_AT,
        )
    )
    await service.record_failure(
        admission,
        ProviderError(provider="keenable", code="http_error", message="boom", retryable=True),
    )
    pool = await repository.limits.get_pool(_pool_id())
    assert pool is not None and pool.remaining == Decimal("100000")
    totals = await repository.limits.crd_usage_totals("keenable")
    assert totals == []
    admission2 = await service.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="keenable",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="keenable-fail-2",
            requested_at=FIXED_AT,
        )
    )
    await service.record_success(
        admission2, SearchResponse(query="q", results=[], provider="keenable")
    )
    pool2 = await repository.limits.get_pool(_pool_id())
    assert pool2 is not None and pool2.remaining == Decimal("99999")


async def test_local_funds_denial_is_402_with_zero_vendor_calls(
    repository: SQLiteRepository,
) -> None:
    calls: list[object] = []
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=_pool_id(),
            provider="keenable",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.REQUEST,
            observed_at=FIXED_AT,
            remaining=Decimal("0"),
            allowance=Decimal("100000"),
            credential_generation=0,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": []})

    adapter, client = _adapter(handler)
    try:
        with pytest_assert_402() as caught:
            await tracked_call(
                repository,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                limits=service,
                attribution=await seed_execution_project(repository),
            )
    finally:
        await client.aclose()
    assert caught.value.status_code == 402
    assert caught.value.error.retryable is False
    assert calls == []


class _Caught:
    value: LimitDeniedError | None = None


class pytest_assert_402:
    def __init__(self) -> None:
        self.value: LimitDeniedError  # type: ignore[misc]

    def __enter__(self) -> "pytest_assert_402":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        assert isinstance(exc, LimitDeniedError)
        self.value = exc
        return True


async def test_keyless_operations_share_rate_capacity(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    for index in range(10):
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="keenable",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYLESS,
                attempt_id=f"keenable-kl-s-{index}",
                requested_at=FIXED_AT,
            )
        )
    try:
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="keenable",
                operation=LimitOperation.FETCH,
                auth_mode=AuthMode.KEYLESS,
                attempt_id="keenable-kl-f-denied",
                requested_at=FIXED_AT,
            )
        )
        raise AssertionError("keyless fetch must share the exhausted bucket")
    except LimitDeniedError as exc:
        assert exc.status_code == 429
    keyed = await service.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="keenable",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="keenable-keyed-still-ok",
            requested_at=FIXED_AT,
        )
    )
    assert keyed.attempt_id == "keenable-keyed-still-ok"


async def test_paid_402_survives_rebuild(repository: SQLiteRepository) -> None:
    def paid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"title": "k", "url": "https://example.com/k"}],
                "_meta": {"keenable/usage": {"credits": 2, "paid": True, "sku": "search.pro"}},
            },
        )

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "HTTP 402"})

    first_client = httpx.AsyncClient(transport=httpx.MockTransport(paid), timeout=30.0)
    try:
        first = KeenableAdapter(first_client, api_key=_KEY)
        await tracked_call(
            repository,
            first,
            lambda running: running.search(
                SearchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", query="paid", limit=2
                )
            ),
            operation=UsageOperation.SEARCH,
            attribution=await seed_execution_project(repository),
        )
        assert first._paid_spend == Decimal("2")
        fail_client = httpx.AsyncClient(transport=httpx.MockTransport(denied), timeout=30.0)
        try:
            failing = KeenableAdapter(fail_client, api_key=_KEY)
            failing._allowance_spend = first._allowance_spend
            failing._paid_spend = first._paid_spend
            failing._paid_usage_seen = True
            try:
                await tracked_call(
                    repository,
                    failing,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repository),
                )
                raise AssertionError("402 must raise")
            except Exception:
                pass
            assert (await failing.quota()).remaining == Decimal("0")  # type: ignore[union-attr]
        finally:
            await fail_client.aclose()
        rebuilt_client = httpx.AsyncClient(timeout=30.0)
        try:
            rebuilt = KeenableAdapter(rebuilt_client, api_key=_KEY)
            await rebuilt.hydrate_quota(repository)
        finally:
            await rebuilt_client.aclose()
    finally:
        await first_client.aclose()
    assert (await rebuilt.quota()).remaining == Decimal("0")  # type: ignore[union-attr]
    assert rebuilt._paid_usage_seen is True


async def test_concurrent_search_fetch_share_pool_and_rate(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=_pool_id(),
            provider="keenable",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.REQUEST,
            observed_at=FIXED_AT,
            remaining=Decimal("100000"),
            allowance=Decimal("100000"),
            credential_generation=0,
        )
    )

    async def admit(op: LimitOperation, attempt: str):  # type: ignore[no-untyped-def]
        try:
            return await service.admit(
                LimitCallContext(
                    **FIXTURE_ACTOR,
                    provider="keenable",
                    operation=op,
                    auth_mode=AuthMode.KEYED,
                    attempt_id=attempt,
                    requested_at=FIXED_AT,
                )
            )
        except LimitDeniedError as exc:
            return exc

    results = await asyncio.gather(
        *[admit(LimitOperation.SEARCH, f"keenable-cc-{i}") for i in range(9)],
        admit(LimitOperation.FETCH, "keenable-cc-fetch"),
    )
    assert all(not isinstance(r, LimitDeniedError) for r in results)
    try:
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="keenable",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="keenable-cc-last",
                requested_at=FIXED_AT,
            )
        )
        raise AssertionError("shared rate bucket must deny the eleventh call")
    except LimitDeniedError as exc:
        assert exc.status_code == 429


async def test_stale_generation_cannot_replace_newer_snapshot(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await service.credential_changed("keenable")
    assert (
        await repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_pool_id(),
                provider="keenable",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.REQUEST,
                observed_at=FIXED_AT,
                remaining=Decimal("99990"),
                allowance=Decimal("100000"),
                credential_generation=0,
            )
        )
        is False
    )


async def test_rebuild_restores_counters_and_paid_before_402(
    repository: SQLiteRepository,
) -> None:
    from polyweb.models.contracts import UsageStatus

    now = datetime.now(UTC)
    await repository.record_usage(
        UsageEvent(
            provider="keenable",
            operation=UsageOperation.SEARCH,
            units=Decimal("3"),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=now,
            status=UsageStatus.SUCCESS,
            metadata={"paid": False},
        ),
        attribution=await seed_execution_project(repository),
    )
    await repository.record_usage(
        UsageEvent(
            provider="keenable",
            operation=UsageOperation.FETCH,
            units=Decimal("2"),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=now,
            status=UsageStatus.SUCCESS,
            metadata={"paid": True},
        ),
        attribution=await seed_execution_project(repository),
    )
    from polyweb.models.contracts import QuotaSnapshot, QuotaSource

    await repository.record_quota(
        QuotaSnapshot(
            provider="keenable",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=Decimal("100000"),
            observed_at=now,
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
        )
    )
    client = httpx.AsyncClient(timeout=30.0)
    try:
        rebuilt = KeenableAdapter(client, api_key=_KEY)
        await rebuilt.hydrate_quota(repository)
        snapshot = await rebuilt.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=now)
        )
    finally:
        await client.aclose()
    assert rebuilt._allowance_spend == Decimal("3")
    assert rebuilt._paid_spend == Decimal("2")
    assert rebuilt._hard_exhausted is True
    assert snapshot is not None and snapshot.remaining == Decimal("0")


async def test_keyless_snapshot_is_none_and_keyed_views_share_pool(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await _seed_full(service, repository)
    view = await service.provider_view("keenable")
    assert len(view.auths) == 2
    keyed = view.auth(AuthMode.KEYED)
    keyless = view.auth(AuthMode.KEYLESS)
    assert keyed is not None and keyless is not None
    assert all(v.state is CRDState.FINITE for v in keyed.crd_views)
    assert all(v.state is CRDState.UNMETERED for v in keyless.crd_views)
    assert keyed.crd_views[0].shared_pool_id == keyed.crd_views[1].shared_pool_id
    client = httpx.AsyncClient(timeout=30.0)
    try:
        keyless_adapter = KeenableAdapter(client)
        assert (
            await keyless_adapter.usage_snapshot(
                UsageSyncRequest(
                    provider="keenable", auth_mode=AuthMode.KEYLESS, observed_at=FIXED_AT
                )
            )
            is None
        )
    finally:
        await client.aclose()


async def test_vendor_429_preserves_budget_without_zero(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await _seed_full(service, repository)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "HTTP 429"})

    adapter, client = _adapter(handler)
    try:
        with pytest_assert_429() as caught:
            await tracked_call(
                repository,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repository),
            )
    finally:
        await client.aclose()
    assert caught.value.error.retryable is True
    pool = await repository.limits.get_pool(_pool_id())
    assert pool is not None and pool.remaining == Decimal("100000")


class pytest_assert_429:
    def __init__(self) -> None:
        self.value: Exception  # type: ignore[misc]

    def __enter__(self) -> "pytest_assert_429":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        assert exc is not None
        self.value = exc  # type: ignore[assignment]
        return True
