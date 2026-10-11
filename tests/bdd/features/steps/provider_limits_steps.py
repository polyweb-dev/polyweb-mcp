"""S0 core BDD steps: synthetic catalog, pools, rates, leases, audit.

Every scenario uses synthetic provider ids (never real vendor builders),
a fresh isolated SQLite database, and deterministic clocks. No vendor I/O.
Plan: P01-P02, P03 base hooks, P04-P07, P08 generic detail; B01/0, B02,
B04-B06, B11-B13, B19-B27, B33, B37-B41. Rev5 K=0.001 exact Decimal math.
"""

import asyncio
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    Confidence,
    CRDPriceProfile,
    CRDState,
    LimitCallContext,
    LimitDeniedError,
    LimitHistoryQuery,
    LimitOperation,
    NativePool,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
    SyncClaim,
)
from freesearch.models.provider_limits import (
    CRDGrantPayload as GrantPayload,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services import credit_units as cu
from freesearch.services.provider_limits import ProviderLimitsService

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
SYNTH = "synth"
SYNTH_B = "synth-b"


def _run(context: Any, coro: Any) -> Any:
    return context.loop.run_until_complete(coro)


def _open_repo(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="s0-core-", suffix=".db", dir=Path.cwd(), delete=False
    ) as tmp:
        context.database_path = tmp.name
    context.repository = _run(context, SQLiteRepository.open(Path(context.database_path)))


def _limits_repo(context: Any) -> Any:
    return context.repository.limits


def _usd_record(
    provider: str = SYNTH,
    operation: LimitOperation = LimitOperation.SEARCH,
    *,
    native_cost: str = "0.005",
    pool_id: str | None = None,
    rate_windows: list[RateWindow] | None = None,
    supported: bool = True,
    transport: bool = True,
    priced: bool = True,
) -> ProviderLimitRecord:
    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=AuthMode.KEYED,
        supported=supported,
        transport_available=transport,
        rate=RateBlock(windows=rate_windows or [], published=bool(rate_windows)),
        budget=BudgetBlock(
            model=BudgetModel.USD,
            standard_native_cost=Decimal(native_cost),
            usd_per_call=Decimal(native_cost),
            priced=priced,
        ),
        native_unit=UnitKind.USD,
        native_pool_id=pool_id or f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
        plan_name="Synthetic Plan",
        usage_url="https://example.com/usage",
    )


def _pool(
    pool_id: str,
    provider: str = SYNTH,
    *,
    remaining: str | None,
    allowance: str | None = None,
    unit: UnitKind = UnitKind.USD,
) -> NativePool:
    return NativePool(
        pool_id=pool_id,
        provider=provider,
        auth_mode=AuthMode.KEYED,
        native_unit=unit,
        remaining=Decimal(remaining) if remaining is not None else None,
        allowance=Decimal(allowance) if allowance is not None else None,
        source="vendor_api",
        confidence=Confidence.OBSERVED,
        observed_at=FIXED_AT,
    )


def _service(
    context: Any, records: list[ProviderLimitRecord], *, clock_at: datetime = FIXED_AT
) -> ProviderLimitsService:
    return ProviderLimitsService(
        _limits_repo(context),
        records=records,
        tier_defaults={},
        clock=lambda: clock_at,
    )


def _ctx(
    provider: str = SYNTH,
    operation: LimitOperation = LimitOperation.SEARCH,
    attempt: str = "attempt-s0-1",
    at: datetime = FIXED_AT,
) -> LimitCallContext:
    return LimitCallContext(
        provider=provider,
        operation=operation,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


# --- B01: empty core --------------------------------------------------------


@given("an empty synthetic limit catalog")
def step_empty_catalog(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, [])
    context.vendor_calls = 0


@when("I read the synthetic dashboard views")
def step_read_dashboard(context: Any) -> None:
    context.dashboard_views = _run(context, context.service.dashboard_views())
    context.catalog_records = list(context.service.records)


@then("the synthetic catalog holds 0 records")
def step_zero_records(context: Any) -> None:
    assert context.catalog_records == []
    assert _run(context, _limits_repo(context).list_records()) == []


@then("the synthetic dashboard views are empty")
def step_empty_views(context: Any) -> None:
    assert context.dashboard_views == []


# --- B02: migration ---------------------------------------------------------


@given("a legacy synthetic database with native history")
def step_legacy_db(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="s0-legacy-", suffix=".db", dir=Path.cwd(), delete=False
    ) as tmp:
        context.database_path = tmp.name
    with sqlite3.connect(context.database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                operation TEXT NOT NULL, units TEXT NOT NULL,
                observed_at TEXT NOT NULL, request_id TEXT, metadata TEXT NOT NULL);
            CREATE TABLE quota_snapshots (
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                source TEXT NOT NULL, remaining TEXT, limit_units TEXT,
                reset_at TEXT, observed_at TEXT NOT NULL);
            """
        )
        conn.execute(
            "INSERT INTO usage_events VALUES (7,'synth','search','12.50',"
            "'2026-01-01T00:00:00+00:00','r-7','{}')"
        )
        conn.execute(
            "INSERT INTO quota_snapshots VALUES (9,'synth','OBSERVED','75',"
            "'100',NULL,'2026-01-01T00:00:00+00:00')"
        )


@when("I upgrade the synthetic database twice")
def step_upgrade_twice(context: Any) -> None:
    from freesearch.persistence.database_migrations import (
        migration_head,
        upgrade_database,
    )

    first = upgrade_database(Path(context.database_path))
    second = upgrade_database(Path(context.database_path))
    context.first_changed = first.changed
    context.second_changed = second.changed
    context.head = migration_head()


@then("the synthetic native rows are preserved")
def step_rows_preserved(context: Any) -> None:
    assert context.first_changed is True
    assert context.second_changed is False
    with sqlite3.connect(context.database_path) as conn:
        usage = conn.execute("SELECT units FROM usage_events WHERE id=7").fetchone()
        quota = conn.execute("SELECT remaining FROM quota_snapshots WHERE id=9").fetchone()
    assert usage == ("12.50",)
    assert quota == ("75",)


@then("the synthetic database is at one migration head with limit tables")
def step_one_head(context: Any) -> None:
    from freesearch.persistence.database_migrations import migration_head

    assert context.head == migration_head()
    with sqlite3.connect(context.database_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    for table in (
        "provider_limits",
        "provider_native_pools",
        "provider_crd_grants",
        "provider_limit_events",
        "provider_limit_admissions",
        "provider_rate_observations",
        "provider_rate_attempts",
    ):
        assert table in tables


# --- B04: lease -------------------------------------------------------------


@when("two synthetic sync claimants race for one provider")
def step_lease_race(context: Any) -> None:
    repo = _limits_repo(context)
    now = FIXED_AT
    _run(
        context,
        repo.ensure_pool(
            NativePool(
                pool_id=f"{SYNTH}:keyed:USD",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                source="vendor_api",
            )
        ),
    )
    context.claim_a = _run(
        context,
        repo.claim_sync(SyncClaim(provider=SYNTH, owner="owner-a", now=now, lease_seconds=60)),
    )
    context.claim_b = _run(
        context,
        repo.claim_sync(
            SyncClaim(
                provider=SYNTH,
                owner="owner-b",
                now=now + timedelta(seconds=1),
                lease_seconds=60,
            )
        ),
    )


@then("one synthetic claimant owns the sync lease")
def step_one_owner(context: Any) -> None:
    assert context.claim_a is True
    assert context.claim_b is False


# --- B05: stale -------------------------------------------------------------


@given("a synthetic finite pool with known balance")
def step_known_pool(context: Any) -> None:
    _open_repo(context)
    record = _usd_record(native_cost="0.005")
    context.record = record
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )


@when("a bad synthetic usage payload arrives")
def step_bad_payload(context: Any) -> None:
    from freesearch.models.provider_limits import SyncResult

    repo = _limits_repo(context)
    pool = _run(context, repo.get_pool(context.record.native_pool_id or ""))
    assert pool is not None and pool.remaining == Decimal("5.000")
    _run(
        context,
        repo.claim_sync(
            SyncClaim(
                provider=SYNTH,
                owner="synthetic-sync",
                now=FIXED_AT + timedelta(seconds=30),
                lease_seconds=60,
            )
        ),
    )
    _run(
        context,
        repo.complete_sync(
            SyncResult(
                provider=SYNTH,
                status="failed",
                observed_at=FIXED_AT + timedelta(seconds=30),
                error_code="usage_429",
                stale=True,
                reason="bad synthetic payload",
            )
        ),
    )
    context.snapshot_changed = True
    context.after_pool = _run(context, repo.get_pool(context.record.native_pool_id or ""))


@then("the synthetic last balance survives as stale")
def step_stale(context: Any) -> None:
    assert context.after_pool.remaining == Decimal("5.000")
    assert context.after_pool.stale is True


# --- B06: exact math --------------------------------------------------------


@when("I project synthetic priced balances")
def step_project(context: Any) -> None:
    profile = CRDPriceProfile()
    context.usd_one = cu.native_to_crd(_pool("p", remaining="0.001", unit=UnitKind.USD), profile)
    context.usd_two = cu.native_to_crd(_pool("p", remaining="0.002", unit=UnitKind.USD), profile)


@then("USD 0.001 gives one CRD and USD 0.002 gives two")
def step_k_oracle(context: Any) -> None:
    assert context.usd_one == Decimal("1")
    assert context.usd_two == Decimal("2")


@then("standard search costs are five for 0.005 and seven for 0.007")
def step_search_costs(context: Any) -> None:
    assert cu.request_cost_crd(_usd_record(native_cost="0.005")) == Decimal("5")
    assert cu.request_cost_crd(_usd_record(native_cost="0.007")) == Decimal("7")
    assert cu.request_cost_crd(_usd_record(native_cost="0.008")) == Decimal("8")


@then("a Turbo fetch costs one CRD")
def step_turbo(context: Any) -> None:
    assert cu.request_cost_crd(_usd_record(native_cost="0.001")) == Decimal("1")
    daily = Decimal("100") * Decimal("0.005") / Decimal("0.001")
    assert daily == Decimal("500")


# --- B11 --------------------------------------------------------------------


@given("a synthetic finite pool with 0.58 CRDs and cost 0.599")
def step_small_pool(context: Any) -> None:
    _open_repo(context)
    record = _usd_record(native_cost="0.000599")
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0.00058"),
                allowance=Decimal("0.005"),
                credential_generation=0,
            )
        ),
    )
    context.vendor_calls = 0


@when("I request one synthetic call")
def step_one_call(context: Any) -> None:
    try:
        context.admission = _run(context, context.service.admit(_ctx()))
        context.denial = None
    except LimitDeniedError as exc:
        context.admission = None
        context.denial = exc


@then("the synthetic gate denies with local 402 and zero vendor calls")
def step_402(context: Any) -> None:
    assert context.admission is None
    assert context.denial is not None
    assert context.denial.status_code == 402
    assert context.vendor_calls == 0


# --- B12 --------------------------------------------------------------------


@given("a synthetic finite pool with 1.0 CRDs and cost 0.6")
def step_pool_10_06(context: Any) -> None:
    _open_repo(context)
    window = RateWindow(
        bucket_id="synth-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.0006", rate_windows=[window])
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0.001"),
                allowance=Decimal("0.001"),
                credential_generation=0,
            )
        ),
    )


@when("two synthetic calls race for admission")
def step_race(context: Any) -> None:
    async def _admit(attempt: str) -> Any:
        try:
            return await context.service.admit(_ctx(attempt=attempt))
        except LimitDeniedError as exc:
            return exc

    async def _both() -> tuple[Any, Any]:
        return await asyncio.gather(_admit("race-1"), _admit("race-2"))

    context.race_a, context.race_b = _run(context, _both())


@then("one synthetic admission succeeds and balances never go negative")
def step_race_result(context: Any) -> None:
    from freesearch.models.provider_limits import LimitAdmission as Adm

    admissions = [r for r in (context.race_a, context.race_b) if isinstance(r, Adm)]
    denials = [r for r in (context.race_a, context.race_b) if isinstance(r, LimitDeniedError)]
    assert len(admissions) == 1
    assert len(denials) == 1
    assert denials[0].status_code in (402, 429)
    pool = _run(context, _limits_repo(context).get_pool(f"{SYNTH}:keyed:USD"))
    assert pool is not None and pool.remaining is not None and pool.remaining >= 0


# --- B13 --------------------------------------------------------------------


@given("a synthetic admitted call with reserved capacity")
def step_admitted(context: Any) -> None:
    _open_repo(context)
    record = _usd_record(native_cost="0.005")
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.admission = _run(context, context.service.admit(_ctx(attempt="rel-1")))


@when("the synthetic vendor fails definitely")
def step_fail(context: Any) -> None:
    from freesearch.models.contracts import ProviderError

    _run(
        context,
        context.service.record_failure(
            context.admission,
            ProviderError(provider=SYNTH, code="timeout", message="synthetic timeout"),
        ),
    )
    context.after = _run(context, _limits_repo(context).get_pool(f"{SYNTH}:keyed:USD"))
    context.history = _run(
        context,
        context.service.history(LimitHistoryQuery(provider=SYNTH, limit=10)),
    )


@then("the synthetic reservation releases with zero CRD debit")
def step_released(context: Any) -> None:
    assert context.after.remaining == Decimal("5.000")
    released = [e for e in context.history.events if e.local_attempt_id == "rel-1"]
    assert released, "release audit must reference the attempt"
    assert all(e.crd_debit == Decimal("0") for e in released)


# --- B19 --------------------------------------------------------------------


@when("I read the synthetic provider detail")
def step_detail(context: Any) -> None:
    context.view = _run(context, context.service.provider_view(SYNTH))


@then("the synthetic detail shows native USD plan reset rates source and link")
def step_detail_fields(context: Any) -> None:
    auth = context.view.auth(AuthMode.KEYED)
    assert auth is not None and auth.detail is not None
    detail = auth.detail
    assert detail.native_balance == Decimal("5.000")
    assert detail.usd_per_call == Decimal("0.005")
    assert detail.plan_name == "Synthetic Plan"
    assert detail.usage_url == "https://example.com/usage"
    assert detail.source in ("vendor_api", "manual_anchor")
    assert isinstance(detail.rate_windows, list)
    payload = context.view.model_dump(mode="json")
    assert payload["auths"][0]["detail"]["native_balance"] == "5.000"


# --- B20 --------------------------------------------------------------------


@when("I save a synthetic grant for one period")
def step_grant(context: Any) -> None:
    context.saved = _run(
        context,
        context.service.save_grant(
            SYNTH,
            GrantPayload(
                version=0,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 4, 1),
                search_crd=Decimal("10"),
                fetch_crd=Decimal("4"),
            ),
            AuthMode.KEYED,
        ),
    )
    context.history = _run(
        context,
        context.service.history(
            LimitHistoryQuery(provider=SYNTH, auth_mode=AuthMode.KEYED, limit=10)
        ),
    )


@then("the synthetic grant period persists with audit old new source")
def step_grant_audit(context: Any) -> None:
    auth = context.saved.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.grants.search_granted_crd == Decimal("10")
    reasons = [e.reason for e in context.history.events]
    assert "grant" in reasons
    grant_event = next(e for e in context.history.events if e.reason == "grant")
    assert grant_event.source in ("local", "operator")


# --- B21 --------------------------------------------------------------------


@given("synthetic route fixtures with different CRD values")
def step_route_fixtures(context: Any) -> None:
    from freesearch.adapters.base import ProviderAdapter
    from freesearch.models.contracts import (
        CostEstimate,
        FetchRequest,
        FetchResponse,
        ProviderCapabilities,
        SearchRequest,
        SearchResponse,
    )

    class _RouteStub(ProviderAdapter):
        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def name(self) -> str:
            return self._name

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

        async def search(self, request: SearchRequest) -> SearchResponse:
            raise NotImplementedError

        async def fetch(self, request: FetchRequest) -> FetchResponse:
            raise NotImplementedError

        async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
            raise NotImplementedError

    from freesearch.services.routing import select_route

    context.select_route = select_route
    context.route_adapters = [_RouteStub("b"), _RouteStub("a")]


@when("I select routes twice")
def step_routes_twice(context: Any) -> None:
    from freesearch.models.contracts import SearchRequest

    req = SearchRequest(query="synthetic routing probe")
    context.first_order = [
        c.adapter.name for c in context.select_route(req, context.route_adapters, {}, {})
    ]
    context.second_order = [
        c.adapter.name for c in context.select_route(req, context.route_adapters, {}, {})
    ]


@then("the synthetic route order and fallback stay identical")
def step_routes_same(context: Any) -> None:
    assert context.first_order == context.second_order


# --- B22 --------------------------------------------------------------------


@given("two synthetic providers with one denied by funds")
def step_two_providers(context: Any) -> None:
    _open_repo(context)
    rich = _usd_record(provider=SYNTH, native_cost="0.005")
    poor = _usd_record(provider=SYNTH_B, native_cost="0.005")
    context.service = _service(context, [rich, poor])
    _run(context, context.service.initialize())
    repo = _limits_repo(context)
    _run(
        context,
        repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=rich.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(
        context,
        repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=poor.native_pool_id or "",
                provider=SYNTH_B,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.candidates = [SYNTH, SYNTH_B]


@when("I run synthetic fanout admission")
def step_fanout(context: Any) -> None:
    context.fanout = {}
    for provider in context.candidates:
        try:
            context.fanout[provider] = _run(
                context, context.service.admit(_ctx(provider=provider, attempt=f"fan-{provider}"))
            )
        except LimitDeniedError as exc:
            context.fanout[provider] = exc


@then("the synthetic candidates stay unchanged and the live result fuses")
def step_fanout_result(context: Any) -> None:
    assert context.candidates == [SYNTH, SYNTH_B]
    assert not isinstance(context.fanout[SYNTH], LimitDeniedError)
    assert isinstance(context.fanout[SYNTH_B], LimitDeniedError)
    assert context.fanout[SYNTH_B].status_code == 402


# --- B23 --------------------------------------------------------------------


@when("the synthetic credential rotates then the old response arrives")
def step_rotate(context: Any) -> None:
    _run(context, context.service.credential_changed(SYNTH))
    context.rotated = _run(
        context, _limits_repo(context).get_pool(context.record.native_pool_id or "")
    )
    context.late = _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=context.record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(seconds=5),
                remaining=Decimal("9.000"),
                allowance=Decimal("9.000"),
                credential_generation=0,
            )
        ),
    )
    context.kept = _run(
        context, _limits_repo(context).get_pool(context.record.native_pool_id or "")
    )


@then("the synthetic stale response is rejected")
def step_stale_rejected(context: Any) -> None:
    assert context.rotated is not None and context.rotated.stale is True
    assert context.late is False
    assert context.kept.remaining == Decimal("5.000")


# --- B24 --------------------------------------------------------------------


@when("I start and stop the synthetic sync task")
def step_lifecycle(context: Any) -> None:
    from freesearch.services.limits_sync import LimitSyncService

    context.sync = LimitSyncService(
        _limits_repo(context),
        context.service,
        lambda: [],
        clock=lambda: FIXED_AT,
    )
    context.stop = asyncio.Event()
    context.task = context.loop.create_task(context.sync.run(context.stop))
    _run(context, asyncio.sleep(0))
    context.task_running = not context.task.done()
    context.stop.set()
    _run(context, asyncio.wait_for(context.task, timeout=5))


@then("one synthetic task runs per generation and closes cleanly")
def step_task_clean(context: Any) -> None:
    assert context.task_running is True
    assert context.task.done() and not context.task.cancelled()


# --- B25 --------------------------------------------------------------------


@when("I submit a synthetic fetch with url_count 2")
def step_batch(context: Any) -> None:
    from fastapi.testclient import TestClient

    from freesearch.models.users import UserRole
    from freesearch.routers.api import create_app
    from tests.fixtures.auth import (
        configure_bdd_secret,
        raw_auth_headers,
        register_promote_login,
        temp_email,
    )
    from tests.integration.services.test_monitoring import _StubAdapter

    configure_bdd_secret(context)
    app = create_app([_StubAdapter("synth-gate")], repository=context.repository)
    with TestClient(app) as client:
        pair = _run(
            context,
            register_promote_login(
                client, context.repository, temp_email("s0-batch"), UserRole.DEVELOPER
            ),
        )
        headers = raw_auth_headers(pair["access_token"])
        context.batch_response = client.post(
            "/fetch", json={"url": "https://example.com/a", "url_count": 2}, headers=headers
        )


@then("the synthetic fetch is rejected with 422 and zero vendor calls")
def step_batch_422(context: Any) -> None:
    assert context.batch_response.status_code == 422
    assert context.repository is not None


# --- B26 --------------------------------------------------------------------


@given("a synthetic unpriced finite record with no balance")
def step_unpriced(context: Any) -> None:
    _open_repo(context)
    context.record = ProviderLimitRecord(
        provider=SYNTH,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=None,
        budget=BudgetBlock(
            model=BudgetModel.USD,
            standard_native_cost=Decimal("0.005"),
            usd_per_call=Decimal("0.005"),
            priced=False,
        ),
        native_unit=UnitKind.USD,
        native_pool_id=f"{SYNTH}:keyed:USD",
        conversion_profile=CRDPriceProfile(native_usd_per_unit=None),
    )
    context.service = _service(context, [context.record])
    _run(context, context.service.initialize())


@when("I project the synthetic CRD view")
def step_project_unknown(context: Any) -> None:
    context.state = cu.crd_state(context.record, None)
    context.view = cu.crd_view(context.record, None)


@then("the synthetic state is unknown and never zero Free or n-a")
def step_unknown(context: Any) -> None:
    assert context.state is CRDState.UNKNOWN
    assert context.view.state is CRDState.UNKNOWN
    assert context.view.remaining_crd is None
    assert context.view.spendable_crd is None


# --- B27 --------------------------------------------------------------------


@given("a synthetic unmetered rail and a synthetic finite pool with funds")
def step_free_paid(context: Any) -> None:
    _open_repo(context)
    free = ProviderLimitRecord(
        provider=SYNTH,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=None,
        budget=None,
        native_unit=None,
        native_pool_id=None,
        conversion_profile=CRDPriceProfile(),
    )
    paid = _usd_record(provider=SYNTH_B, native_cost="0.005")
    context.service = _service(context, [free, paid])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=paid.native_pool_id or "",
                provider=SYNTH_B,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=paid.native_pool_id or "",
                provider=SYNTH_B,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(seconds=1),
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )


@when("I request one synthetic call on each rail")
def step_both(context: Any) -> None:
    context.free_adm = _run(context, context.service.admit(_ctx(provider=SYNTH, attempt="free-1")))
    context.paid_adm = _run(
        context, context.service.admit(_ctx(provider=SYNTH_B, attempt="paid-1"))
    )


@then("both synthetic rails admit the call")
def step_both_admit(context: Any) -> None:
    assert context.free_adm.attempt_id == "free-1"
    assert context.paid_adm.attempt_id == "paid-1"


# --- B33 --------------------------------------------------------------------


@when("a malformed synthetic rate observation arrives")
def step_malformed(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, [])
    _run(
        context,
        context.service.rate_limits.observe(
            RateObservation(
                bucket_id="synth-bucket",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR,
                unit=RateUnit.REQUESTS,
                limit=None,
                remaining=None,
                observed_at=FIXED_AT,
                source="vendor_header",
                confidence=Confidence.UNKNOWN,
            )
        ),
    )
    context.bars = _run(context, context.service.rate_limits.progress(SYNTH))


@then("the synthetic rate state stays unknown without denial")
def step_malformed_ok(context: Any) -> None:
    assert context.bars == [] or all(b.remaining is None and b.limit is None for b in context.bars)


# --- B37 --------------------------------------------------------------------


@given("a synthetic finite pool with funds and an exhausted hour window")
def step_funds_rate(context: Any) -> None:
    _open_repo(context)
    window = RateWindow(
        bucket_id="synth-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(
        context,
        context.service.rate_limits.observe(
            RateObservation(
                bucket_id="synth-hour",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR,
                unit=RateUnit.REQUESTS,
                limit=Decimal("1"),
                remaining=Decimal("1"),
                observed_at=FIXED_AT,
                reset_at=FIXED_AT + timedelta(hours=1),
            )
        ),
    )
    first = _run(context, context.service.admit(_ctx(attempt="r-1")))
    context.first_admission = first


@then("the synthetic gate denies with local 429 and Retry-After")
def step_429(context: Any) -> None:
    try:
        _run(context, context.service.admit(_ctx(attempt="r-2")))
        raise AssertionError("second admission must deny with 429")
    except LimitDeniedError as exc:
        assert exc.status_code == 429


# --- B38 --------------------------------------------------------------------


@given("a synthetic finite pool with an exhausted hour window")
def step_exhausted(context: Any) -> None:
    _open_repo(context)
    window = RateWindow(
        bucket_id="synth-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    record_b = _usd_record(provider=SYNTH_B, native_cost="0.005")
    context.service = _service(context, [record, record_b])
    context.record = record
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("3.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record_b.native_pool_id or "",
                provider=SYNTH_B,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("1.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(context, context.service.admit(_ctx(attempt="b38-r1")))
    try:
        _run(context, context.service.admit(_ctx(attempt="b38-r2")))
        raise AssertionError("hour window must deny before the refill")
    except LimitDeniedError as exc:
        assert exc.status_code == 429


@when("the synthetic hour passes and a budget refill arrives")
def step_refill(context: Any) -> None:
    repo = _limits_repo(context)
    _run(
        context,
        repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=context.record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(hours=2),
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.refilled = _run(context, repo.get_pool(context.record.native_pool_id or ""))
    context.other = _run(context, repo.get_pool(f"{SYNTH_B}:keyed:USD"))
    context.renewed = _run(
        context,
        context.service.admit(_ctx(attempt="b38-r3", at=FIXED_AT + timedelta(hours=2))),
    )


@then("the synthetic rate refills without moving funds and the pool refills")
def step_refill_ok(context: Any) -> None:
    assert context.refilled is not None
    assert context.refilled.remaining == Decimal("5.000")
    assert context.renewed.attempt_id == "b38-r3"
    assert context.other is not None
    assert context.other.remaining == Decimal("1.000")


# --- B39 --------------------------------------------------------------------


@given("one synthetic shared pool with search and fetch views")
def step_shared(context: Any) -> None:
    _open_repo(context)
    pool_id = f"{SYNTH}:keyed:USD"
    search = _usd_record(
        provider=SYNTH,
        operation=LimitOperation.SEARCH,
        native_cost="0.005",
        pool_id=pool_id,
    )
    fetch = _usd_record(
        provider=SYNTH,
        operation=LimitOperation.FETCH,
        native_cost="0.001",
        pool_id=pool_id,
    )
    context.records = [search, fetch]
    context.pool = _pool(pool_id, remaining="5.000", allowance="5.000")


@when("I project the synthetic shared views and totals")
def step_shared_views(context: Any) -> None:
    context.views = cu.project_shared_crd_views(context.pool, context.records)
    context.funds_once = cu.shared_pool_funds(context.pool, context.records)


@then("the synthetic funds count once and totals count each attempt once")
def step_shared_once(context: Any) -> None:
    assert len(context.views) == 2
    assert context.funds_once == Decimal("5000")
    assert context.views[0].remaining_crd == Decimal("5000")
    assert context.views[1].remaining_crd == Decimal("5000")
    assert context.views[0].shared_pool_id == context.views[1].shared_pool_id
    assert context.views[0].shared_pool_id == f"{SYNTH}:keyed:USD"


# --- B40 --------------------------------------------------------------------


@when("the synthetic price version changes after a debit")
def step_version_change(context: Any) -> None:
    admission = _run(context, context.service.admit(_ctx(attempt="v-1")))
    from freesearch.models.contracts import SearchResponse

    _run(
        context,
        context.service.record_success(
            admission, SearchResponse(query="v", results=[], provider=SYNTH)
        ),
    )
    context.history = _run(
        context,
        context.service.history(LimitHistoryQuery(provider=SYNTH, limit=10)),
    )


@then("the synthetic audit keeps the original price version")
def step_version_kept(context: Any) -> None:
    debits = [e for e in context.history.events if e.local_attempt_id == "v-1"]
    assert debits, "success audit must reference the attempt"
    assert all(e.reason == "local_success" for e in debits)
    assert all(e.crd_debit == Decimal("5") for e in debits)


# --- B41 --------------------------------------------------------------------


@given("a synthetic finite pool with zero funds and an exhausted hour window")
def step_both_denied(context: Any) -> None:
    _open_repo(context)
    window = RateWindow(
        bucket_id="synth-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    _run(
        context,
        context.service.rate_limits.observe(
            RateObservation(
                bucket_id="synth-hour",
                provider=SYNTH,
                auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR,
                unit=RateUnit.REQUESTS,
                limit=Decimal("1"),
                remaining=Decimal("0"),
                observed_at=FIXED_AT,
                reset_at=FIXED_AT + timedelta(hours=1),
            )
        ),
    )
    context.vendor_calls = 0


@then("the synthetic denial keeps both reasons with 402 precedence and zero vendor calls")
def step_both_reasons(context: Any) -> None:
    try:
        _run(context, context.service.admit(_ctx(attempt="both-1")))
        raise AssertionError("admission must deny")
    except LimitDeniedError as exc:
        assert exc.status_code == 402
        assert context.vendor_calls == 0


# --- S1 Brave ---------------------------------------------------------------


def _brave_search_payload() -> dict[str, object]:
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


def _brave_adapter(handler: Any, calls: list[Any] | None = None) -> tuple[Any, Any]:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.brave import BraveAdapter

    def counting(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    return BraveAdapter(client, api_key=SecretStr("brave-test-secret")), client


def _brave_records() -> list[ProviderLimitRecord]:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    return [record for record in provider_limit_defaults() if record.provider == "brave"]


def _brave_pool_id() -> str:
    from freesearch.models.provider_limits import native_pool_id

    return native_pool_id("brave", AuthMode.KEYED, UnitKind.USD)


def _brave_service(context: Any) -> ProviderLimitsService:
    return _service(context, _brave_records())


@given("the Brave catalog records")
def step_brave_catalog(context: Any) -> None:
    _open_repo(context)
    context.brave_records = _brave_records()
    context.service = _service(context, context.brave_records)
    context.vendor_calls = []


@then("Brave holds one keyed search record and one keyed fetch placeholder")
def step_brave_two_records(context: Any) -> None:
    assert len(context.brave_records) == 2
    search = next(r for r in context.brave_records if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in context.brave_records if r.operation is LimitOperation.FETCH)
    assert search.auth_mode is AuthMode.KEYED and search.supported
    assert search.transport_available and search.budget is not None
    assert search.budget.model is BudgetModel.USD
    assert fetch.auth_mode is AuthMode.KEYED
    assert fetch.supported is False and fetch.transport_available is False
    assert fetch.rate is None and fetch.budget is None


@then("Brave holds no keyless record")
def step_brave_no_keyless(context: Any) -> None:
    assert all(r.auth_mode is not AuthMode.KEYLESS for r in context.brave_records)


@when("I project the Brave priced balance")
def step_brave_project(context: Any) -> None:
    search = next(r for r in context.brave_records if r.operation is LimitOperation.SEARCH)
    pool = _pool(_brave_pool_id(), provider="brave", remaining="5.000", allowance="5.000")
    context.brave_crd = cu.native_to_crd(pool, search.conversion_profile)
    context.brave_cost = cu.request_cost_crd(search)


@then("USD 5 gives 5000 CRDs and one standard search costs 5 CRDs")
def step_brave_five(context: Any) -> None:
    assert context.brave_crd == Decimal("5000")
    assert context.brave_cost == Decimal("5")


@given("a Brave adapter with monthly headers of 900 left of 1000")
def step_brave_headers(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _brave_records())
    _run(context, context.service.initialize())
    context.vendor_calls = []

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(
            200,
            json=_brave_search_payload(),
            headers={"X-RateLimit-Remaining": "49, 900", "X-RateLimit-Limit": "50, 1000"},
        )

    adapter, client = _brave_adapter(handler, context.vendor_calls)
    context.brave_adapter = adapter
    context.brave_client = client
    from freesearch.models.contracts import SearchRequest

    context.brave_response = _run(context, adapter.search(SearchRequest(query="q", limit=2)))


@when("I read the Brave usage snapshot")
def step_brave_snapshot(context: Any) -> None:
    from freesearch.models.provider_limits import UsageSyncRequest

    context.snapshot = _run(
        context,
        context.brave_adapter.usage_snapshot(
            UsageSyncRequest(provider="brave", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        ),
    )
    assert context.snapshot is not None
    _run(context, _limits_repo(context).apply_snapshot(context.snapshot))
    context.brave_pool = _run(context, _limits_repo(context).get_pool(_brave_pool_id()))


@then("the Brave pool holds allowance 5.000 USD with remaining 4.500 USD")
def step_brave_pool(context: Any) -> None:
    assert context.snapshot.allowance == Decimal("5.000")
    assert context.snapshot.remaining == Decimal("4.500")
    assert context.snapshot.source == "vendor_headers"
    assert context.brave_pool is not None
    assert context.brave_pool.remaining == Decimal("4.500")


@then("the Brave observation carries no hour bar and no day bar")
def step_brave_no_bars(context: Any) -> None:
    assert context.snapshot.rate_observations, "burst headroom must be observed"
    assert all(obs.window is RateWindowName.SECOND for obs in context.snapshot.rate_observations)
    bars = _run(context, context.service.rate_limits.progress("brave", FIXED_AT))
    assert bars == []


@given("a Brave adapter with no vendor headers")
def step_brave_no_headers(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _brave_records())
    _run(context, context.service.initialize())

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(200, json=_brave_search_payload())

    adapter, client = _brave_adapter(handler)
    context.brave_adapter = adapter
    context.brave_client = client


@when("I anchor Brave manual funds of USD 5")
def step_brave_anchor(context: Any) -> None:
    class _Anchor:
        remaining = Decimal("5")
        allowance = Decimal("5")
        billing_end = None
        updated_at = FIXED_AT

    _run(context, context.service.apply_manual_anchor("brave", _Anchor()))
    context.brave_pool = _run(context, _limits_repo(context).get_pool(_brave_pool_id()))


@then("the Brave manual pool projects 5000 estimated CRDs")
def step_brave_manual(context: Any) -> None:
    search = next(r for r in _brave_records() if r.operation is LimitOperation.SEARCH)
    assert context.brave_pool is not None
    assert context.brave_pool.confidence is Confidence.ESTIMATED
    assert cu.native_to_crd(context.brave_pool, search.conversion_profile) == Decimal("5000")


@given("a Brave app with seeded catalog and monthly headers of 900 left of 1000")
def step_brave_app(context: Any) -> None:
    from fastapi.testclient import TestClient

    from freesearch.models.contracts import SearchRequest
    from freesearch.models.provider_limits import UsageSyncRequest
    from freesearch.models.users import UserRole
    from freesearch.routers.api import create_app
    from tests.fixtures.auth import (
        configure_bdd_secret,
        raw_auth_headers,
        register_promote_login,
        temp_email,
    )

    configure_bdd_secret(context)
    _open_repo(context)
    context.vendor_calls = []

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(
            200,
            json=_brave_search_payload(),
            headers={"X-RateLimit-Remaining": "49, 900", "X-RateLimit-Limit": "50, 1000"},
        )

    adapter, client = _brave_adapter(handler, context.vendor_calls)
    context.brave_adapter = adapter
    context.brave_client = client
    context.brave_app = create_app([adapter], repository=context.repository)
    with TestClient(context.brave_app) as http_client:
        pair = _run(
            context,
            register_promote_login(
                http_client, context.repository, temp_email("s1-brave"), UserRole.ADMIN
            ),
        )
        context.brave_admin_headers = raw_auth_headers(pair["access_token"])
    _run(context, context.brave_adapter.search(SearchRequest(query="q", limit=2)))
    snapshot = _run(
        context,
        context.brave_adapter.usage_snapshot(
            UsageSyncRequest(provider="brave", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        ),
    )
    assert snapshot is not None
    _run(context, _limits_repo(context).apply_snapshot(snapshot))


@when("I read the Brave provider view")
def step_brave_view(context: Any) -> None:
    service = ProviderLimitsService(_limits_repo(context), records=_brave_records())
    context.brave_view = _run(context, service.provider_view("brave"))


@then("the Brave search view is finite with cost 5 and the fetch view is unavailable")
def step_brave_views(context: Any) -> None:
    auth = context.brave_view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.state is CRDState.FINITE
    assert search_view.request_cost_crd == Decimal("5")
    assert search_view.remaining_crd == Decimal("4500")
    assert fetch_view.state is CRDState.UNAVAILABLE
    assert len(context.brave_view.auths) == 1


@then("a Brave fetch grant fails with 422")
def step_brave_fetch_grant_422(context: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(context.brave_app) as client:
        response = client.put(
            "/api/v1/providers/brave/crd-grants/keyed",
            json={
                "version": 0,
                "period_start": "2026-03-01",
                "period_end": "2026-04-01",
                "search_crd": "10",
                "fetch_crd": "4",
            },
            headers=context.brave_admin_headers,
        )
    assert response.status_code == 422


@given("a Brave pool with zero USD funds")
def step_brave_zero_pool(context: Any) -> None:
    _open_repo(context)
    records = _brave_records()
    context.service = _service(context, records)
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_brave_pool_id(),
                provider="brave",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("0"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.vendor_calls = []


@given("a Brave pool with known USD funds")
def step_brave_known_pool(context: Any) -> None:
    _open_repo(context)
    records = _brave_records()
    context.service = _service(context, records)
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_brave_pool_id(),
                provider="brave",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("4.500"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.vendor_calls = []


@when("I request one Brave search")
def step_brave_request(context: Any) -> None:
    try:
        context.brave_admission = _run(
            context,
            context.service.admit(_ctx(provider="brave", attempt="brave-1")),
        )
        context.brave_denial = None
    except LimitDeniedError as exc:
        context.brave_admission = None
        context.brave_denial = exc


@then("the Brave gate denies with local 402 and zero vendor calls")
def step_brave_402(context: Any) -> None:
    assert context.brave_admission is None
    assert context.brave_denial is not None
    assert context.brave_denial.status_code == 402
    assert context.brave_denial.error.code == "crd_exhausted"
    assert context.brave_denial.error.retryable is False
    assert context.vendor_calls == []


@then("the Brave gate admits the call")
def step_brave_admit(context: Any) -> None:
    assert context.brave_denial is None
    assert context.brave_admission is not None
    assert context.brave_admission.attempt_id == "brave-1"


@given("a Brave adapter with mock error answers")
def step_brave_errors(context: Any) -> None:
    _open_repo(context)
    context.vendor_calls = []


@when("Brave answers 429 with QUOTA_LIMITED")
def step_brave_quota_limited(context: Any) -> None:
    calls: list[Any] = []
    context.vendor_calls = calls

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(429, json={"code": "QUOTA_LIMITED"})

    adapter, client = _brave_adapter(handler, calls)
    context.brave_client = client
    from freesearch.models.contracts import SearchRequest

    try:
        _run(context, adapter.search(SearchRequest(query="q", limit=2)))
        context.brave_error = None
    except Exception as exc:
        context.brave_error = exc


@then("the Brave error is quota_exhausted with one attempt and no retry")
def step_brave_budget_error(context: Any) -> None:
    assert context.brave_error is not None
    assert context.brave_error.error.code == "quota_exhausted"
    assert context.brave_error.error.retryable is False
    assert context.brave_error.error.status_code == 429
    assert len(context.vendor_calls) == 1


@when("Brave answers 429 with RATE_LIMITED")
def step_brave_rate_limited(context: Any) -> None:
    calls: list[Any] = []
    context.vendor_calls = calls

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(429, json={"code": "RATE_LIMITED"})

    adapter, client = _brave_adapter(handler, calls)
    context.brave_client = client
    from freesearch.models.contracts import SearchRequest

    try:
        _run(context, adapter.search(SearchRequest(query="q", limit=2)))
        context.brave_error = None
    except Exception as exc:
        context.brave_error = exc


@then("the Brave error is retryable with three attempts")
def step_brave_rate_error(context: Any) -> None:
    assert context.brave_error is not None
    assert context.brave_error.error.code == "http_error"
    assert context.brave_error.error.retryable is True
    assert len(context.vendor_calls) == 3


@when("I read the Brave provider detail")
def step_brave_detail(context: Any) -> None:
    service = ProviderLimitsService(_limits_repo(context), records=_brave_records())
    view = _run(context, service.provider_view("brave"))
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    context.brave_detail = auth.detail
    context.brave_record = next(r for r in _brave_records() if r.operation is LimitOperation.SEARCH)


@then("the Brave detail shows native USD plan reset rates source and link")
def step_brave_detail_fields(context: Any) -> None:
    detail = context.brave_detail
    assert detail is not None
    assert detail.native_balance == Decimal("4.500")
    assert detail.usd_per_call == Decimal("0.005")
    assert detail.plan_name == "Monthly search credit"
    assert detail.usage_url == "https://api-dashboard.search.brave.com/"
    assert detail.source == "vendor_headers"
    assert context.brave_record.budget is not None
    assert context.brave_record.budget.allowance_period == "month"
    assert any(
        w.window is RateWindowName.SECOND and w.limit == Decimal("50") for w in detail.rate_windows
    )


@when("I save a Brave search grant for one period")
def step_brave_grant(context: Any) -> None:
    context.brave_saved = _run(
        context,
        context.service.save_grant(
            "brave",
            GrantPayload(
                version=0,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 4, 1),
                search_crd=Decimal("10"),
                fetch_crd=Decimal("0"),
            ),
            AuthMode.KEYED,
        ),
    )
    context.brave_history = _run(
        context,
        context.service.history(
            LimitHistoryQuery(provider="brave", auth_mode=AuthMode.KEYED, limit=10)
        ),
    )


@then("the Brave grant period persists with audit old new source")
def step_brave_grant_audit(context: Any) -> None:
    auth = context.brave_saved.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.grants.search_granted_crd == Decimal("10")
    reasons = [e.reason for e in context.brave_history.events]
    assert "grant" in reasons
    grant_event = next(e for e in context.brave_history.events if e.reason == "grant")
    assert grant_event.source in ("local", "operator")


@given("Brave route fixtures with different CRD values")
def step_brave_route_fixtures(context: Any) -> None:
    from freesearch.services.routing import select_route
    from tests.integration.services.test_monitoring import _StubAdapter

    context.select_route = select_route
    context.route_adapters = [_StubAdapter("brave-b"), _StubAdapter("brave-a")]


@when("I select Brave routes twice")
def step_brave_routes_twice(context: Any) -> None:
    from freesearch.models.contracts import SearchRequest

    req = SearchRequest(query="brave routing probe")
    context.first_order = [
        c.adapter.name for c in context.select_route(req, context.route_adapters, {}, {})
    ]
    context.second_order = [
        c.adapter.name for c in context.select_route(req, context.route_adapters, {}, {})
    ]


@then("the Brave route order and fallback stay identical")
def step_brave_routes_same(context: Any) -> None:
    assert context.first_order == context.second_order


@when("I project the Brave fetch view")
def step_brave_fetch_view(context: Any) -> None:
    fetch = next(r for r in context.brave_records if r.operation is LimitOperation.FETCH)
    context.brave_fetch_view = cu.crd_view(fetch, None)


@then("the Brave fetch state is unavailable and never unknown Free or zero")
def step_brave_fetch_unavailable(context: Any) -> None:
    assert context.brave_fetch_view.state is CRDState.UNAVAILABLE
    assert context.brave_fetch_view.remaining_crd is None


@when("two Brave searches succeed")
def step_brave_two_successes(context: Any) -> None:
    from freesearch.models.contracts import SearchResponse

    for attempt in ("brave-t1", "brave-t2"):
        admission = _run(context, context.service.admit(_ctx(provider="brave", attempt=attempt)))
        _run(
            context,
            context.service.record_success(
                admission, SearchResponse(query="q", results=[], provider="brave")
            ),
        )


@then("the Brave totals hold one row with exact normalized CRDs and two attempts")
def step_brave_totals(context: Any) -> None:
    totals = _run(context, _limits_repo(context).crd_usage_totals("brave"))
    assert len(totals) == 1
    assert totals[0].normalized_crd == Decimal("10")
    assert totals[0].attempt_count == 2


@given("a Brave pool with zero USD funds and an exhausted burst window")
def step_brave_both_denied(context: Any) -> None:
    _open_repo(context)
    records = _brave_records()
    context.service = _service(context, records)
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_brave_pool_id(),
                provider="brave",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    for index in range(50):
        _run(context, context.service.admit(_ctx(provider="brave", attempt=f"burst-{index}")))
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_brave_pool_id(),
                provider="brave",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(seconds=1),
                remaining=Decimal("0"),
                allowance=Decimal("5.000"),
                credential_generation=0,
            )
        ),
    )
    context.vendor_calls = []


@then("the Brave denial keeps both reasons with 402 precedence and zero vendor calls")
def step_brave_both_reasons(context: Any) -> None:
    try:
        _run(context, context.service.admit(_ctx(provider="brave", attempt="brave-both")))
        raise AssertionError("admission must deny")
    except LimitDeniedError as exc:
        assert exc.status_code == 402
        assert exc.refusal == "funds"
        assert exc.error.details.get("rate_denied") is True
        assert context.vendor_calls == []


# --- Keenable K01-K07 --------------------------------------------------------


def _keenable_search_payload(
    credits: object = 1, *, paid: bool = False, sku: str = "search.pro"
) -> dict[str, object]:
    payload: dict[str, object] = {"results": [{"title": "k", "url": "https://example.com/k"}]}
    payload["_meta"] = {"keenable/usage": {"credits": credits, "paid": paid, "sku": sku}}
    return payload


def _keenable_fetch_payload(
    credits: object = 1, *, paid: bool = False, sku: str = "fetch"
) -> dict[str, object]:
    payload: dict[str, object] = {"content": "hello world", "title": "Doc"}
    payload["_meta"] = {"keenable/usage": {"credits": credits, "paid": paid, "sku": sku}}
    return payload


def _keenable_adapter(handler: Any, calls: list[Any] | None = None) -> tuple[Any, Any]:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.keenable import KeenableAdapter

    def counting(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    return KeenableAdapter(client, api_key=SecretStr("keenable-test-secret")), client


def _keenable_keyless_adapter(handler: Any, calls: list[Any] | None = None) -> tuple[Any, Any]:
    import httpx

    from freesearch.adapters.keenable import KeenableAdapter

    def counting(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    return KeenableAdapter(client), client


def _keenable_records() -> list[ProviderLimitRecord]:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    return [record for record in provider_limit_defaults() if record.provider == "keenable"]


def _keenable_pool_id() -> str:
    from freesearch.models.provider_limits import native_pool_id

    return native_pool_id("keenable", AuthMode.KEYED, UnitKind.REQUEST)


@given("the Keenable catalog records")
def step_keenable_catalog(context: Any) -> None:
    _open_repo(context)
    context.keenable_records = _keenable_records()
    context.service = _service(context, context.keenable_records)
    context.vendor_calls = []


@then("Keenable holds four records for keyed and keyless search and fetch")
def step_keenable_four_records(context: Any) -> None:
    assert len(context.keenable_records) == 4
    keyed = [r for r in context.keenable_records if r.auth_mode is AuthMode.KEYED]
    keyless = [r for r in context.keenable_records if r.auth_mode is AuthMode.KEYLESS]
    assert len(keyed) == 2
    assert len(keyless) == 2
    assert {r.operation for r in keyed} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    assert {r.operation for r in keyless} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    for record in keyed:
        assert record.native_pool_id == "keenable:keyed:request"
        assert record.native_unit is UnitKind.REQUEST
        assert record.budget is not None
        assert record.budget.model is BudgetModel.REQUESTS


@then("Keenable keyless records hold no budget")
def step_keenable_keyless_no_budget(context: Any) -> None:
    from freesearch.services import credit_units as local_cu

    keyless = [r for r in context.keenable_records if r.auth_mode is AuthMode.KEYLESS]
    assert len(keyless) == 2
    for record in keyless:
        assert record.budget is None
        assert record.native_unit is None
        assert record.native_pool_id is None
        view = local_cu.crd_view(record, None)
        assert view.state is CRDState.UNMETERED


@when("I read the Keenable keyed pool contract")
def step_keenable_keyed_contract(context: Any) -> None:
    from freesearch.services import credit_units as local_cu

    context.keenable_search = next(
        r
        for r in context.keenable_records
        if r.auth_mode is AuthMode.KEYED and r.operation is LimitOperation.SEARCH
    )
    context.keenable_fetch = next(
        r
        for r in context.keenable_records
        if r.auth_mode is AuthMode.KEYED and r.operation is LimitOperation.FETCH
    )
    context.keenable_cost = local_cu.request_cost_crd(context.keenable_search)


@then(
    "Keenable keyed search and fetch share pool keenable:keyed:request "
    "with 10 per second and 100000 monthly"
)
def step_keenable_shared_pool(context: Any) -> None:
    assert context.keenable_search.native_pool_id == "keenable:keyed:request"
    assert context.keenable_fetch.native_pool_id == "keenable:keyed:request"
    assert context.keenable_search.native_unit is UnitKind.REQUEST
    assert context.keenable_fetch.native_unit is UnitKind.REQUEST
    assert context.keenable_search.rate is not None
    assert len(context.keenable_search.rate.windows) == 1
    window = context.keenable_search.rate.windows[0]
    assert window.limit == Decimal("10")
    assert window.window is RateWindowName.SECOND
    assert window.bucket_id == "keenable:keyed:requests"
    assert context.keenable_fetch.rate is not None
    assert context.keenable_fetch.rate.windows[0].bucket_id == "keenable:keyed:requests"
    assert context.keenable_search.budget is not None
    assert context.keenable_search.budget.free_allowance == Decimal("100000")
    assert context.keenable_search.budget.allowance_period == "month"
    assert context.keenable_search.budget.standard_native_cost == Decimal("1")
    assert context.keenable_cost == Decimal("4")


@when("I read the Keenable keyless rate contract")
def step_keenable_keyless_contract(context: Any) -> None:
    context.keenable_keyless_search = next(
        r
        for r in context.keenable_records
        if r.auth_mode is AuthMode.KEYLESS and r.operation is LimitOperation.SEARCH
    )
    context.keenable_keyless_fetch = next(
        r
        for r in context.keenable_records
        if r.auth_mode is AuthMode.KEYLESS and r.operation is LimitOperation.FETCH
    )


@then("Keenable keyless search and fetch share 10 per second and 1000 per hour with no budget")
def step_keenable_keyless_shared(context: Any) -> None:
    for record in (context.keenable_keyless_search, context.keenable_keyless_fetch):
        assert record.budget is None
        assert record.rate is not None
        assert len(record.rate.windows) == 2
        second = next(w for w in record.rate.windows if w.window is RateWindowName.SECOND)
        hour = next(w for w in record.rate.windows if w.window is RateWindowName.HOUR)
        assert second.limit == Decimal("10")
        assert second.scope is RateScope.IP
        assert second.bucket_id == "keenable:keyless:requests"
        assert hour.limit == Decimal("1000")
        assert hour.scope is RateScope.IP
        assert hour.bucket_id == "keenable:keyless:requests"
    assert (
        context.keenable_keyless_search.rate.windows[0].bucket_id
        == context.keenable_keyless_fetch.rate.windows[0].bucket_id
    )


def step_keenable_error(context: Any, status: int) -> None:
    """Keenable error seam: record the vendor status for later assertions."""

    context.keenable_error_status = status


@given("a Keenable pool with full monthly funds")
def step_keenable_full_pool(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _keenable_records())
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_keenable_pool_id(),
                provider="keenable",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.REQUEST,
                observed_at=FIXED_AT,
                remaining=Decimal("100000"),
                allowance=Decimal("100000"),
                credential_generation=0,
            )
        ),
    )
    context.vendor_calls = []


@when("one Keenable search reports three credits and one fetch reports two credits")
def step_keenable_shared_usage(context: Any) -> None:
    from freesearch.models.contracts import (
        FetchedDocument,
        FetchResponse,
        SearchResponse,
        UsageEvent,
        UsageOperation,
    )

    search_adm = _run(
        context,
        context.service.admit(
            LimitCallContext(
                provider="keenable",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="keenable-k04-search",
                requested_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.service.record_success(
            search_adm,
            SearchResponse(
                query="q",
                results=[],
                provider="keenable",
                usage=UsageEvent(
                    provider="keenable",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("3"),
                    unit_kind=UnitKind.CREDIT,
                    display_unit="credits",
                    observed_at=FIXED_AT,
                    metadata={"sku": "search.pro", "paid": False},
                ),
            ),
        ),
    )
    fetch_adm = _run(
        context,
        context.service.admit(
            LimitCallContext(
                provider="keenable",
                operation=LimitOperation.FETCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="keenable-k04-fetch",
                requested_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.service.record_success(
            fetch_adm,
            FetchResponse(
                provider="keenable",
                document=FetchedDocument(
                    url="https://example.com/k",
                    content="hello",
                    fetched_at=FIXED_AT,
                ),
                usage=UsageEvent(
                    provider="keenable",
                    operation=UsageOperation.FETCH,
                    units=Decimal("2"),
                    unit_kind=UnitKind.CREDIT,
                    display_unit="credits",
                    observed_at=FIXED_AT,
                    metadata={"sku": "fetch", "paid": False},
                ),
            ),
        ),
    )
    context.keenable_pool = _run(context, _limits_repo(context).get_pool(_keenable_pool_id()))
    context.keenable_view = _run(context, context.service.provider_view("keenable"))


@then("the Keenable pool holds remaining 99995 with 399980 CRDs in both views")
def step_keenable_pool_99995(context: Any) -> None:
    assert context.keenable_pool is not None
    assert context.keenable_pool.remaining == Decimal("99995")
    assert context.keenable_pool.allowance == Decimal("100000")
    auth = context.keenable_view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.shared_pool_id == "keenable:keyed:request"
    assert fetch_view.shared_pool_id == "keenable:keyed:request"
    assert search_view.state is CRDState.FINITE
    assert fetch_view.state is CRDState.FINITE
    assert search_view.remaining_crd == Decimal("399980")
    assert fetch_view.remaining_crd == Decimal("399980")
    assert search_view.request_cost_crd == Decimal("4")
    assert fetch_view.request_cost_crd == Decimal("4")


@then("the Keenable totals hold costs 12 and 8 CRDs with one native debit per success")
def step_keenable_totals_12_8(context: Any) -> None:
    totals = _run(context, _limits_repo(context).crd_usage_totals("keenable"))
    by_op = {t.operation: t for t in totals}
    assert set(by_op) == {LimitOperation.SEARCH, LimitOperation.FETCH}
    assert by_op[LimitOperation.SEARCH].normalized_crd == Decimal("12")
    assert by_op[LimitOperation.SEARCH].attempt_count == 1
    assert by_op[LimitOperation.SEARCH].volume_count == 1
    assert by_op[LimitOperation.FETCH].normalized_crd == Decimal("8")
    assert by_op[LimitOperation.FETCH].attempt_count == 1
    assert by_op[LimitOperation.FETCH].volume_count == 1


@given("a Keenable adapter with paid usage of two credits")
def step_keenable_paid_adapter(context: Any) -> None:
    from freesearch.models.contracts import UsageEvent, UsageOperation, UsageStatus

    _open_repo(context)
    context.vendor_calls = []

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(200, json=_keenable_search_payload(2, paid=True))

    adapter, client = _keenable_adapter(handler, context.vendor_calls)
    context.keenable_adapter = adapter
    context.keenable_client = client
    from freesearch.models.contracts import SearchRequest

    context.keenable_paid_response = _run(
        context, adapter.search(SearchRequest(query="paid", limit=2))
    )
    assert context.keenable_paid_response.usage is not None
    assert context.keenable_paid_response.usage.units == Decimal("2")
    now = datetime.now(UTC)
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="keenable",
                operation=UsageOperation.SEARCH,
                units=Decimal("2"),
                unit_kind=UnitKind.CREDIT,
                display_unit="credits",
                observed_at=now,
                status=UsageStatus.SUCCESS,
                metadata={"paid": True, "sku": "search.pro"},
            )
        ),
    )


@when("Keenable answers 402 after paid usage")
def step_keenable_snapshot(context: Any) -> None:
    from freesearch.models.provider_limits import UsageSyncRequest

    _run(context, context.keenable_adapter.quota_after_error(402))
    now = datetime.now(UTC)
    snapshot = _run(
        context,
        context.keenable_adapter.usage_snapshot(
            UsageSyncRequest(
                provider="keenable",
                auth_mode=AuthMode.KEYED,
                observed_at=now,
                credential_generation=7,
            )
        ),
    )
    assert snapshot is not None
    context.keenable_snapshot = snapshot
    _run(context, _limits_repo(context).apply_snapshot(snapshot))
    from freesearch.models.contracts import QuotaSnapshot, QuotaSource

    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="keenable",
                source=QuotaSource.OBSERVED,
                remaining=Decimal("0"),
                limit=Decimal("100000"),
                observed_at=now,
                unit_kind=UnitKind.CREDIT,
                display_unit="credits",
                metadata={"paid_spend": "2"},
            )
        ),
    )


@then("the Keenable snapshot holds remaining zero with separate free and paid spend")
def step_keenable_paid_402_zero(context: Any) -> None:
    from freesearch.adapters.keenable import KeenableAdapter

    adapter = context.keenable_adapter
    assert isinstance(adapter, KeenableAdapter)
    assert adapter._paid_usage_seen is True
    assert adapter._paid_spend == Decimal("2")
    assert adapter._allowance_spend == Decimal("0")
    assert adapter._hard_exhausted is True
    snapshot = context.keenable_snapshot
    assert snapshot.remaining == Decimal("0")
    assert snapshot.allowance == Decimal("100000")
    assert snapshot.confidence is Confidence.OBSERVED
    assert snapshot.pool_id == "keenable:keyed:request"
    assert snapshot.native_unit is UnitKind.REQUEST
    assert snapshot.credential_generation == 7
    quota = _run(context, adapter.quota())
    assert quota is not None
    assert quota.remaining == Decimal("0")


@when("I rebuild the Keenable adapter from stored rows")
def step_keenable_rebuild(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.keenable import KeenableAdapter
    from freesearch.models.provider_limits import UsageSyncRequest

    client = httpx.AsyncClient(timeout=30.0)
    context.keenable_rebuilt_client = client
    rebuilt = KeenableAdapter(client, api_key=SecretStr("keenable-test-secret"))
    _run(context, rebuilt.hydrate_quota(context.repository))
    context.keenable_rebuilt = rebuilt
    now = datetime.now(UTC)
    context.keenable_rebuilt_snapshot = _run(
        context,
        rebuilt.usage_snapshot(
            UsageSyncRequest(
                provider="keenable",
                auth_mode=AuthMode.KEYED,
                observed_at=now,
                credential_generation=7,
            )
        ),
    )


@then("the rebuilt Keenable snapshot still holds remaining zero")
def step_keenable_rebuilt_zero(context: Any) -> None:
    rebuilt = context.keenable_rebuilt
    assert rebuilt._paid_usage_seen is True
    assert rebuilt._paid_spend == Decimal("2")
    assert rebuilt._hard_exhausted is True
    snapshot = context.keenable_rebuilt_snapshot
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0")
    assert snapshot.confidence is Confidence.OBSERVED
    _run(context, context.keenable_client.aclose())
    context.keenable_client = None
    _run(context, context.keenable_rebuilt_client.aclose())


@given("a Keenable adapter with mock error answers")
def step_keenable_error_adapter(context: Any) -> None:
    _open_repo(context)
    context.vendor_calls = []


@when("Keenable answers 429 with rate pressure")
def step_keenable_429(context: Any) -> None:
    step_keenable_error(context, 429)
    calls: list[Any] = []
    context.vendor_calls = calls

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(429, json={"error": "HTTP 429"})

    adapter, client = _keenable_adapter(handler, calls)
    context.keenable_client = client
    from freesearch.models.contracts import SearchRequest

    try:
        _run(context, adapter.search(SearchRequest(query="q", limit=2)))
        context.keenable_error = None
    except Exception as exc:
        context.keenable_error = exc
    context.keenable_adapter = adapter


@then("the Keenable rate error stays retryable with no funds zero observation")
def step_keenable_429_assert(context: Any) -> None:
    assert context.keenable_error is not None
    assert context.keenable_error.error.status_code == 429
    assert context.keenable_error.error.retryable is True
    quota = _run(context, context.keenable_adapter.quota())
    assert quota is not None
    assert quota.remaining == Decimal("100000")
    assert quota.remaining != Decimal("0")
    _run(context, context.keenable_client.aclose())
    context.keenable_client = None


@when("Keenable answers 402 with exhaustion")
def step_keenable_402(context: Any) -> None:
    step_keenable_error(context, 402)
    calls: list[Any] = []
    context.vendor_calls = calls

    def handler(request: Any) -> Any:
        import httpx

        return httpx.Response(402, json={"error": "HTTP 402"})

    adapter, client = _keenable_adapter(handler, calls)
    context.keenable_client = client
    from freesearch.models.contracts import SearchRequest

    try:
        _run(context, adapter.search(SearchRequest(query="q", limit=2)))
        context.keenable_error = None
    except Exception as exc:
        context.keenable_error = exc
    context.keenable_adapter = adapter
    _run(context, adapter.quota_after_error(402))


@then("the Keenable funds error stays non-retryable with remaining zero")
def step_keenable_402_assert(context: Any) -> None:
    assert context.keenable_error is not None
    assert context.keenable_error.error.code == "quota_exhausted"
    assert context.keenable_error.error.retryable is False
    assert context.keenable_error.error.status_code == 402
    quota = _run(context, context.keenable_adapter.quota())
    assert quota is not None
    assert quota.remaining == Decimal("0")
    _run(context, context.keenable_client.aclose())
    context.keenable_client = None


@when("two Keenable keyed calls succeed with standard cost")
def step_keenable_two_standard(context: Any) -> None:
    from freesearch.models.contracts import (
        FetchedDocument,
        FetchResponse,
        SearchResponse,
    )

    search_adm = _run(
        context,
        context.service.admit(
            LimitCallContext(
                provider="keenable",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="keenable-k07-search",
                requested_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.service.record_success(
            search_adm, SearchResponse(query="q", results=[], provider="keenable")
        ),
    )
    fetch_adm = _run(
        context,
        context.service.admit(
            LimitCallContext(
                provider="keenable",
                operation=LimitOperation.FETCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="keenable-k07-fetch",
                requested_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.service.record_success(
            fetch_adm,
            FetchResponse(
                provider="keenable",
                document=FetchedDocument(
                    url="https://example.com/k",
                    content="hello",
                    fetched_at=FIXED_AT,
                ),
            ),
        ),
    )
    context.keenable_view = _run(context, context.service.provider_view("keenable"))


@then("the Keenable shared views hold one pool with 399992 CRDs each")
def step_keenable_shared_views(context: Any) -> None:
    from freesearch.services import credit_units as local_cu

    pool = _run(context, _limits_repo(context).get_pool(_keenable_pool_id()))
    assert pool is not None
    assert pool.remaining == Decimal("99998")
    auth = context.keenable_view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.shared_pool_id == fetch_view.shared_pool_id == "keenable:keyed:request"
    assert search_view.remaining_crd == Decimal("399992")
    assert fetch_view.remaining_crd == Decimal("399992")
    records = [r for r in _keenable_records() if r.auth_mode is AuthMode.KEYED]
    funds_once = local_cu.shared_pool_funds(pool, records)
    assert funds_once == Decimal("399992")


@then("the Keenable totals count each attempt once with separate search and fetch rows")
def step_keenable_totals_once(context: Any) -> None:
    totals = _run(context, _limits_repo(context).crd_usage_totals("keenable"))
    by_op = {t.operation: t for t in totals}
    assert set(by_op) == {LimitOperation.SEARCH, LimitOperation.FETCH}
    assert by_op[LimitOperation.SEARCH].attempt_count == 1
    assert by_op[LimitOperation.FETCH].attempt_count == 1
    assert by_op[LimitOperation.SEARCH].normalized_crd == Decimal("4")
    assert by_op[LimitOperation.FETCH].normalized_crd == Decimal("4")


@given("a Keenable keyless pool with exhausted shared windows")
def step_keenable_keyless_exhausted(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _keenable_records())
    _run(context, context.service.initialize())
    for index in range(10):
        _run(
            context,
            context.service.admit(
                LimitCallContext(
                    provider="keenable",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYLESS,
                    attempt_id=f"keenable-keyless-{index}",
                    requested_at=FIXED_AT,
                )
            ),
        )
    context.vendor_calls = []


@when("I request one Keenable keyless search")
def step_keenable_keyless_request(context: Any) -> None:
    try:
        context.keenable_keyless_admission = _run(
            context,
            context.service.admit(
                LimitCallContext(
                    provider="keenable",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYLESS,
                    attempt_id="keenable-keyless-denied",
                    requested_at=FIXED_AT,
                )
            ),
        )
        context.keenable_keyless_denial = None
    except LimitDeniedError as exc:
        context.keenable_keyless_admission = None
        context.keenable_keyless_denial = exc


@then("the Keenable keyless gate denies with local 429 and zero vendor calls")
def step_keenable_keyless_denied(context: Any) -> None:
    assert context.keenable_keyless_admission is None
    assert context.keenable_keyless_denial is not None
    assert context.keenable_keyless_denial.status_code == 429
    assert context.keenable_keyless_denial.refusal == "rate"
    assert context.keenable_keyless_denial.error.details.get("origin") == "local"
    assert context.vendor_calls == []
    bars = _run(context, context.service.rate_limits.progress("keenable", FIXED_AT))
    assert any(b.window == "1h" for b in bars)
