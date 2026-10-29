"""Tavily limits integration: pools, config, admission, ledger, refill, detail.

Parallel to tests/integration/services/test_brave_limits.py. Real SQLite
repositories with the real Tavily catalog records. No vendor I/O, no live
keys; usage payloads are built locally through the adapter mapping seam.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio

from freesearch.configuration.provider_config import ProviderConfig
from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.models.contracts import SearchRequest, SearchResponse, UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    LimitCallContext,
    LimitDeniedError,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService
from tests.fixtures.database_lifecycle import unlink_with_retries
from tests.fixtures.execution import FIXTURE_ACTOR, seed_execution_project

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

TAVILY_POOL = "tavily:keyed:credit"


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    db_path = tmp_path / "tavily-limit.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            unlink_with_retries(extra)


def _tavily_records() -> list[ProviderLimitRecord]:
    return [r for r in provider_limit_defaults() if r.provider == "tavily"]


def _service(repo: SQLiteRepository) -> ProviderLimitsService:
    return ProviderLimitsService(
        repo.limits,
        records=_tavily_records(),
        tier_defaults=None,
        clock=lambda: FIXED_AT,
    )


def _snapshot(
    remaining: Decimal | None,
    allowance: Decimal | None = Decimal("1000"),
    *,
    source: str = "vendor_api",
    observed_at: datetime = FIXED_AT,
) -> NativeUsageSnapshot:
    return NativeUsageSnapshot(
        pool_id=TAVILY_POOL,
        provider="tavily",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        observed_at=observed_at,
        remaining=remaining,
        allowance=allowance,
        credential_generation=0,
        source=source,
    )


async def test_t01_seeded_catalog_holds_shared_bucket_records(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    stored = [r for r in await repository.limits.list_records() if r.provider == "tavily"]
    assert len(stored) == 4
    keyed = [r for r in stored if r.auth_mode is AuthMode.KEYED]
    assert {r.operation for r in keyed} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    buckets = {w.bucket_id for r in keyed if r.rate for w in r.rate.windows}
    assert buckets == {"tavily:keyed:search:requests"}


async def test_config_apply_selects_dev_then_prod_rate(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    dev = {
        r.operation: r
        for r in service.records
        if r.provider == "tavily" and r.auth_mode is AuthMode.KEYED
    }
    dev_search = dev[LimitOperation.SEARCH]
    assert dev_search.rate is not None
    assert dev_search.rate.windows[0].limit == Decimal("100")
    await service.apply_tavily_config(
        ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
    )
    prod = {
        r.operation: r
        for r in service.records
        if r.provider == "tavily" and r.auth_mode is AuthMode.KEYED
    }
    assert prod[LimitOperation.SEARCH].rate is not None
    assert prod[LimitOperation.SEARCH].rate.windows[0].limit == Decimal("1000")  # type: ignore[union-attr]
    # Both operations share the same bucket after the config apply.
    fetch_windows = prod[LimitOperation.FETCH].rate.windows  # type: ignore[union-attr]
    assert fetch_windows[0].bucket_id == "tavily:keyed:search:requests"


async def test_admission_and_ledger_debit_basic_then_advanced(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000")))
    for attempt, mode, expected in (
        ("tavily-s1", None, Decimal("999")),
        ("tavily-s2", "advanced", Decimal("997")),
    ):
        admission = await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="tavily",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=attempt,
                requested_at=FIXED_AT,
            )
        )
        await service.record_success(
            admission,
            SearchResponse(query="q", results=[], provider="tavily"),
            request=SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2, mode=mode
            ),  # type: ignore[arg-type]
        )
        pool = await repository.limits.get_pool(TAVILY_POOL)
        assert pool is not None and pool.remaining == expected


async def test_funds_gate_terminal_vendor_402_denies(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(_snapshot(Decimal("0"), source="vendor_402"))
    try:
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="tavily",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="tavily-402",
                requested_at=FIXED_AT,
            )
        )
        raise AssertionError("admission must deny")
    except LimitDeniedError as exc:
        assert exc.status_code == 402
        assert "credits_exhausted" in exc.reasons
        assert exc.error.retryable is False


async def test_paygo_flag_admits_after_free_zero(
    repository: SQLiteRepository,
) -> None:
    from freesearch.models.contracts import UnitKind as UK
    from freesearch.models.provider_limits import Confidence, FundingMode, TierBalance

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(
        ProviderConfig(tavily_paygo_enabled=True), auth_mode=AuthMode.KEYED
    )
    # PAYGO is access, not a stored Credits balance: the pool holds an unknown
    # balance with an OBSERVED PAYGO tier, so the durable funds recheck stays
    # unenforced while the operator flag confirms overage.
    snapshot = _snapshot(None, allowance=None, source="vendor_api").model_copy(
        update={
            "tiers": [
                TierBalance(
                    pool_id="tavily:keyed:paygo",
                    tier="paid",
                    native_unit=UK.CREDIT,
                    funding_mode=FundingMode.POSTPAID,
                    confidence=Confidence.OBSERVED,
                    label="PAYGO access",
                )
            ],
            "tier_split_known": True,
        }
    )
    await repository.limits.apply_snapshot(snapshot)
    admission = await service.admit(
        LimitCallContext(
            **FIXTURE_ACTOR,
            provider="tavily",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="tavily-paygo",
            requested_at=FIXED_AT,
        )
    )
    assert admission.attempt_id == "tavily-paygo"


async def test_refill_day1_dec_to_jan_restores_free_pool(
    repository: SQLiteRepository,
) -> None:
    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    dec = datetime(2025, 12, 31, 23, 0, 0, tzinfo=UTC)
    await repository.limits.apply_snapshot(
        _snapshot(Decimal("0"), source="vendor_402", observed_at=dec)
    )
    jan = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000"), observed_at=jan))
    pool = await repository.limits.get_pool(TAVILY_POOL)
    assert pool is not None and pool.remaining == Decimal("1000")


async def test_observed_tiers_and_live_detail_windows(
    repository: SQLiteRepository,
) -> None:
    from freesearch.models.contracts import UnitKind as UK
    from freesearch.models.provider_limits import Confidence, TierBalance

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    snapshot = _snapshot(Decimal("999"))
    snapshot = snapshot.model_copy(
        update={
            "tiers": [
                TierBalance(
                    pool_id="tavily:keyed:free",
                    tier="free",
                    native_unit=UK.CREDIT,
                    native_remaining=Decimal("999"),
                    native_allowance=Decimal("1000"),
                    confidence=Confidence.OBSERVED,
                )
            ],
            "tier_split_known": True,
        }
    )
    await repository.limits.apply_snapshot(snapshot)
    view = await service.provider_view("tavily")
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.aggregate_pool is not None
    assert auth.aggregate_pool.remaining == Decimal("999")
    # Live minute detail: window headroom plus cooldown seconds.
    windows = await service.rate_limits.window_details("tavily", AuthMode.KEYED, FIXED_AT)
    assert len(windows) >= 1
    assert windows[0].bucket_id == "tavily:keyed:search:requests"
    await service.rate_limits.record_vendor_cooldown("tavily", AuthMode.KEYED, 30, FIXED_AT)
    detail = await service.provider_view("tavily")
    keyed = detail.auth(AuthMode.KEYED)
    assert keyed is not None


async def test_held_usage_poll_adds_no_search_extract_delay(
    repository: SQLiteRepository,
) -> None:
    """AC5: search and extract finish while the usage poll is held (Event)."""
    import asyncio

    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.models.contracts import FetchRequest
    from freesearch.models.provider_limits import UsageSyncRequest

    gate = asyncio.Event()
    real_refresh = TavilyAdapter._refresh_usage

    async def _held_refresh(self: TavilyAdapter, request: UsageSyncRequest):  # type: ignore[no-untyped-def]
        await gate.wait()
        return await real_refresh(self, request)

    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.path == "/usage":
            return httpx.Response(200, json={"account": {"plan_usage": 1, "plan_limit": 1000}})
        if request.url.path == "/extract":
            return httpx.Response(
                200,
                json={
                    "results": [{"url": "https://example.com/a", "raw_content": "body"}],
                    "usage": {"credits": 0.2},
                },
            )
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    # Real SDK construction so the owned client carries the usage rail.
    adapter = TavilyAdapter(client, api_key=SecretStr("tvly-held"))
    adapter._refresh_usage = _held_refresh.__get__(adapter, TavilyAdapter)  # type: ignore[method-assign]
    try:
        poll = asyncio.ensure_future(
            adapter.usage_snapshot(
                UsageSyncRequest(provider="tavily", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
            )
        )
        await asyncio.sleep(0)
        search_result, fetch_result = await asyncio.wait_for(
            asyncio.gather(
                adapter.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="fast", limit=2
                    )
                ),
                adapter.fetch(
                    FetchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa",
                        url="https://example.com/a",
                    )
                ),
            ),
            timeout=5,
        )
        assert not poll.done()
        assert search_result.provider == "tavily"
        assert fetch_result.provider == "tavily"
        gate.set()
        snapshot = await asyncio.wait_for(poll, timeout=5)
        assert snapshot is not None and snapshot.remaining == Decimal("999")
    finally:
        await adapter.aclose()
        await client.aclose()


async def test_zero_usage_gets_from_cost_quota_and_view(
    repository: SQLiteRepository,
) -> None:
    """Route/budget reads stay cache-only: zero usage GETs."""
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.models.contracts import FetchRequest

    class _ImmediateSDK:
        async def search(self, **kwargs: object) -> object:
            return {"results": [], "usage": {"credits": 1}}

        async def extract(self, **kwargs: object) -> object:
            return {"results": []}

    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"account": {"plan_usage": 1, "plan_limit": 1000}})

    service = _service(repository)
    await service.initialize()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    adapter = TavilyAdapter(client, api_key=SecretStr("tvly-cache"), sdk_client=_ImmediateSDK())  # type: ignore[arg-type]
    try:
        await adapter.estimate_cost(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
        await adapter.estimate_cost(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/a"
            )
        )
        assert await adapter.quota() is None
        await service.provider_view("tavily")
    finally:
        await adapter.aclose()
        await client.aclose()
    assert recorded == []


async def test_pinned_second_call_after_402_denies_locally(
    repository: SQLiteRepository,
) -> None:
    """Pinned 402 writes the vendor_402 pool zero; the next pinned admit denies locally (F5)."""
    import httpx
    import pytest
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.infrastructure.resilience import ProviderOperationError
    from freesearch.models.contracts import UsageOperation
    from tests.fixtures.execution import attributed_tracked_call as tracked_call

    class _FailingSDK:
        calls = 0

        async def search(self, **kwargs: object) -> object:
            type(self).calls += 1
            raise httpx.HTTPStatusError(
                "vendor 402",
                request=httpx.Request("POST", "https://api.tavily.com/search"),
                response=httpx.Response(402),
            )

        async def extract(self, **kwargs: object) -> object:
            raise NotImplementedError

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(_snapshot(Decimal("1000")))
    client = httpx.AsyncClient(timeout=30.0)
    adapter = TavilyAdapter(client, sdk_client=_FailingSDK(), api_key=SecretStr("tvly-402-pin"))  # type: ignore[arg-type]
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await tracked_call(
                repository,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                request=SearchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=1
                ),
                limits=service,
                attribution=await seed_execution_project(repository),
            )
    finally:
        await adapter.aclose()
        await client.aclose()

    assert excinfo.value.error.code == "quota_exhausted"
    assert _FailingSDK.calls == 1
    pool = await repository.limits.get_pool(TAVILY_POOL)
    assert pool is not None and pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"
    totals = await repository.limits.crd_usage_totals("tavily")
    assert all(t.normalized_crd == Decimal("0") for t in totals)
    try:
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="tavily",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="tavily-402-second",
                requested_at=FIXED_AT,
            )
        )
        raise AssertionError("second pinned admission must deny")
    except LimitDeniedError as exc:
        assert "credits_exhausted" in exc.reasons
    assert _FailingSDK.calls == 1


async def test_env_switch_dev_to_prod_preserves_pool_caps_terminal_and_bucket(
    repository: SQLiteRepository,
) -> None:
    """Dev-to-prod keeps the native pool, local grant cap, terminal state, bucket."""
    from datetime import date

    from freesearch.models.provider_limits import CRDGrantPayload as GrantPayload

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(_snapshot(Decimal("0"), source="vendor_402"))
    await service.save_grant(
        "tavily",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("10"),
            fetch_crd=Decimal("4"),
        ),
        AuthMode.KEYED,
    )
    before_pool = await repository.limits.get_pool(TAVILY_POOL)
    assert before_pool is not None
    before_grants = await repository.limits.grants("tavily", AuthMode.KEYED, now=FIXED_AT)
    assert before_grants is not None

    await service.apply_tavily_config(
        ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
    )

    pool = await repository.limits.get_pool(TAVILY_POOL)
    assert pool is not None
    assert pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"
    assert pool.allowance == before_pool.allowance
    after_grants = await repository.limits.grants("tavily", AuthMode.KEYED, now=FIXED_AT)
    assert after_grants is not None
    assert after_grants.remaining(LimitOperation.SEARCH) == before_grants.remaining(
        LimitOperation.SEARCH
    )
    assert after_grants.remaining(LimitOperation.FETCH) == before_grants.remaining(
        LimitOperation.FETCH
    )
    keyed = [r for r in service.records if r.provider == "tavily" and r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    buckets = set()
    for record in keyed:
        assert record.rate is not None
        assert record.rate.windows[0].limit == Decimal("1000")
        buckets.add(record.rate.windows[0].bucket_id)
    assert buckets == {"tavily:keyed:search:requests"}


async def test_env_switch_prod_to_dev_preserves_pool_caps_terminal_and_bucket(
    repository: SQLiteRepository,
) -> None:
    """Prod-to-dev keeps the native pool, local grant cap, terminal state, bucket."""
    from datetime import date

    from freesearch.models.provider_limits import CRDGrantPayload as GrantPayload

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(
        ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
    )
    await repository.limits.apply_snapshot(_snapshot(Decimal("0"), source="vendor_402"))
    await service.save_grant(
        "tavily",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("10"),
            fetch_crd=Decimal("4"),
        ),
        AuthMode.KEYED,
    )
    before_grants = await repository.limits.grants("tavily", AuthMode.KEYED, now=FIXED_AT)
    assert before_grants is not None

    await service.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)

    pool = await repository.limits.get_pool(TAVILY_POOL)
    assert pool is not None
    assert pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"
    after_grants = await repository.limits.grants("tavily", AuthMode.KEYED, now=FIXED_AT)
    assert after_grants is not None
    assert after_grants.remaining(LimitOperation.SEARCH) == before_grants.remaining(
        LimitOperation.SEARCH
    )
    keyed = [r for r in service.records if r.provider == "tavily" and r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    buckets = set()
    for record in keyed:
        assert record.rate is not None
        assert record.rate.windows[0].limit == Decimal("100")
        buckets.add(record.rate.windows[0].bucket_id)
    assert buckets == {"tavily:keyed:search:requests"}


async def test_spent_key_with_funded_plan_denies_key_cap(
    repository: SQLiteRepository,
) -> None:
    """A spent key ceiling with a funded plan denies key_cap_exhausted despite PAYGO (F7)."""
    import pytest

    from freesearch.models.contracts import UnitKind as UK
    from freesearch.models.provider_limits import Confidence, TierBalance

    service = _service(repository)
    await service.initialize()
    await service.apply_tavily_config(
        ProviderConfig(tavily_paygo_enabled=True), auth_mode=AuthMode.KEYED
    )
    snapshot = _snapshot(Decimal("0"), allowance=Decimal("10000"), source="vendor_api").model_copy(
        update={
            "tiers": [
                TierBalance(
                    pool_id="tavily:keyed:plan",
                    tier="paid",
                    native_unit=UK.CREDIT,
                    native_remaining=Decimal("10000"),
                    native_allowance=Decimal("10000"),
                    confidence=Confidence.OBSERVED,
                )
            ],
            "tier_split_known": True,
        }
    )
    await repository.limits.apply_snapshot(snapshot)
    with pytest.raises(LimitDeniedError) as excinfo:
        await service.admit(
            LimitCallContext(
                **FIXTURE_ACTOR,
                provider="tavily",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="tavily-key-spent",
                requested_at=FIXED_AT,
            )
        )
    assert "key_cap_exhausted" in excinfo.value.reasons
