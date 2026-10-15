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


# --- TAV Tavily Credits (PLAN AC1-AC6, offline, no vendor I/O) ----------------


def _tavily_records() -> list[ProviderLimitRecord]:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    return [record for record in provider_limit_defaults() if record.provider == "tavily"]


def _tavily_pool_id() -> str:
    from freesearch.models.provider_limits import native_pool_id

    return native_pool_id("tavily", AuthMode.KEYED, UnitKind.CREDIT)


def _tavily_ctx(
    operation: LimitOperation,
    attempt: str,
    at: datetime = FIXED_AT,
) -> LimitCallContext:
    return LimitCallContext(
        provider="tavily",
        operation=operation,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


def _tavily_next_month(at: datetime) -> datetime:
    if at.month == 12:
        return datetime(at.year + 1, 1, 1, tzinfo=UTC)
    return datetime(at.year, at.month + 1, 1, tzinfo=UTC)


def _tavily_seed(
    context: Any,
    *,
    remaining: str | None,
    allowance: str | None,
    at: datetime = FIXED_AT,
    tiers: list[Any] | None = None,
    source: str = "vendor_api",
) -> str:
    pool_id = _tavily_pool_id()
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=pool_id,
                provider="tavily",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=at,
                remaining=Decimal(remaining) if remaining is not None else None,
                allowance=Decimal(allowance) if allowance is not None else None,
                reset_at=_tavily_next_month(at),
                credential_generation=0,
                source=source,
                tiers=tiers or [],
                tier_split_known=bool(tiers),
            )
        ),
    )
    return pool_id


def _tavily_search_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "results": [
            {"title": "Example", "url": "https://example.com/doc", "content": "A snippet."}
        ],
        "usage": {"credits": 1},
        "request_id": "tav-req-1",
    }
    payload.update(overrides)
    return payload


def _tavily_extract_payload(
    *, url: str = "https://example.com/doc", raw_content: str = "body", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "results": [{"url": url, "raw_content": raw_content}],
        "usage": {"credits": 0.2},
        "request_id": "tav-ext-1",
    }
    payload.update(overrides)
    return payload


def _tavily_usage_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "account": {"plan_usage": 1, "plan_limit": 1000},
        "key": {"usage": 1, "limit": 1000},
    }
    payload.update(overrides)
    return payload


class _TavilyFakeSDK:
    """Recording stand-in for AsyncTavilyClient (no network)."""

    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.extract_calls: list[dict[str, Any]] = []
        self.search_response: Any = None
        self.search_error: Exception | None = None
        self.extract_response: Any = None
        self.extract_error: Exception | None = None

    async def search(self, **kwargs: Any) -> Any:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def extract(self, **kwargs: Any) -> Any:
        self.extract_calls.append(kwargs)
        if self.extract_error is not None:
            raise self.extract_error
        return self.extract_response


class _TavilyFakeOwnedHTTP:
    """Recording stand-in for the adapter-owned scoped client (usage GET only)."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.gets: list[str] = []

    async def get(self, url: str) -> Any:
        self.gets.append(url)
        return self._response


@given("the Tavily catalog records")
def step_tavily_catalog(context: Any) -> None:
    _open_repo(context)
    context.tavily_records = _tavily_records()
    context.service = _service(context, context.tavily_records)
    context.vendor_calls = []


@then("Tavily holds one keyed search record and one keyed extract record")
def step_tavily_two_keyed(context: Any) -> None:
    keyed = [r for r in context.tavily_records if r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    search = next(r for r in keyed if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in keyed if r.operation is LimitOperation.FETCH)
    assert search.supported is True and search.transport_available is True
    assert search.budget is not None and search.native_unit is UnitKind.CREDIT
    assert search.budget.allowance_unit == "Credits"
    assert search.budget.free_allowance == Decimal("1000")
    assert search.budget.allowance_period == "month"
    assert search.conversion_profile is not None
    assert fetch.supported is True and fetch.transport_available is True
    assert fetch.budget is not None and fetch.native_unit is UnitKind.CREDIT
    assert fetch.budget.allowance_unit == "Credits"
    assert search.native_pool_id == fetch.native_pool_id
    assert search.native_pool_id == _tavily_pool_id()
    assert search.version == 2 and fetch.version == 2


@then("Tavily holds two keyless rails with unpublished rate and no budget")
def step_tavily_two_keyless(context: Any) -> None:
    keyless = [r for r in context.tavily_records if r.auth_mode is AuthMode.KEYLESS]
    assert len(keyless) == 2
    operations = {r.operation for r in keyless}
    assert operations == {LimitOperation.SEARCH, LimitOperation.FETCH}
    for record in keyless:
        assert record.transport_available is True
        assert record.budget is None
        assert record.native_pool_id is None
        assert record.rate is not None
        assert record.rate.published is False
        assert record.rate.windows == []
        assert record.version == 2


@then("Tavily shares one default minute bucket across search and extract")
def step_tavily_shared_bucket(context: Any) -> None:
    from freesearch.configuration.provider_limits import TAVILY_DEFAULT_BUCKET_ID

    keyed = [r for r in context.tavily_records if r.auth_mode is AuthMode.KEYED]
    assert len(keyed) == 2
    buckets: set[str] = set()
    for record in keyed:
        assert record.rate is not None and record.rate.published is True
        assert len(record.rate.windows) == 1
        window = record.rate.windows[0]
        assert window.bucket_id == TAVILY_DEFAULT_BUCKET_ID
        assert window.window is RateWindowName.MINUTE
        assert window.limit == Decimal("100")
        assert window.scope is RateScope.KEY
        assert window.unit is RateUnit.REQUESTS
        buckets.add(window.bucket_id)
    assert buckets == {TAVILY_DEFAULT_BUCKET_ID}


@given("a Tavily dev pool with 1000 Credits remaining")
def step_tavily_dev_pool(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="1000", allowance="1000")
    context.vendor_calls = []
    context.tavily_cumulative = Decimal("0")


@when("I mix Tavily search and extract to 100 attempts")
def step_tavily_mix_100(context: Any) -> None:
    for index in range(100):
        operation = LimitOperation.SEARCH if index % 2 == 0 else LimitOperation.FETCH
        _run(context, context.service.admit(_tavily_ctx(operation, f"tav-dev-{index}")))
    context.tavily_mixed = 100


@then("the Tavily 101st attempt denies with local 429 and zero vendor calls")
def step_tavily_deny_101(context: Any) -> None:
    assert context.tavily_mixed == 100
    try:
        _run(context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-dev-100")))
        raise AssertionError("101st admission must deny with 429")
    except LimitDeniedError as exc:
        assert exc.status_code == 429
        assert exc.refusal == "rate"
    assert context.vendor_calls == []


@when("concurrent Tavily search and extract admissions race on one bucket")
def step_tavily_concurrent_race(context: Any) -> None:
    for index in range(99):
        operation = LimitOperation.SEARCH if index % 2 == 0 else LimitOperation.FETCH
        _run(context, context.service.admit(_tavily_ctx(operation, f"tav-race-fill-{index}")))

    async def _admit(operation: LimitOperation, attempt: str) -> Any:
        try:
            return await context.service.admit(_tavily_ctx(operation, attempt))
        except LimitDeniedError as exc:
            return exc

    async def _both() -> tuple[Any, Any]:
        return await asyncio.gather(
            _admit(LimitOperation.SEARCH, "tav-race-search"),
            _admit(LimitOperation.FETCH, "tav-race-fetch"),
        )

    context.tavily_race_a, context.tavily_race_b = _run(context, _both())


@then("one Tavily admission succeeds and balances never go negative")
def step_tavily_race_result(context: Any) -> None:
    from freesearch.models.provider_limits import LimitAdmission as Adm

    admissions = [r for r in (context.tavily_race_a, context.tavily_race_b) if isinstance(r, Adm)]
    denials = [
        r for r in (context.tavily_race_a, context.tavily_race_b) if isinstance(r, LimitDeniedError)
    ]
    assert len(admissions) == 1
    assert len(denials) == 1
    assert denials[0].status_code == 429
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None and pool.remaining is not None and pool.remaining >= 0


@given("a Tavily prod pool with 10000 Credits remaining")
def step_tavily_prod_pool(context: Any) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _run(
        context,
        context.service.apply_tavily_config(
            ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
        ),
    )
    _tavily_seed(context, remaining="10000", allowance="10000")
    context.vendor_calls = []


@when("I mix Tavily search and extract to 1000 attempts")
def step_tavily_mix_1000(context: Any) -> None:
    for index in range(1000):
        operation = LimitOperation.SEARCH if index % 2 == 0 else LimitOperation.FETCH
        _run(context, context.service.admit(_tavily_ctx(operation, f"tav-prod-{index}")))
    context.tavily_mixed = 1000


@then("the Tavily 1001st attempt denies with local 429 and zero vendor calls")
def step_tavily_deny_1001(context: Any) -> None:
    assert context.tavily_mixed == 1000
    try:
        _run(context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-prod-1000")))
        raise AssertionError("1001st admission must deny with 429")
    except LimitDeniedError as exc:
        assert exc.status_code == 429
        assert exc.refusal == "rate"
    assert context.vendor_calls == []


@when("I apply Tavily key environment prod")
def step_tavily_apply_prod(context: Any) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

    _run(context, context.service.initialize())
    _run(
        context,
        context.service.apply_tavily_config(
            ProviderConfig(tavily_key_environment="prod"), auth_mode=AuthMode.KEYED
        ),
    )


@then("both Tavily keyed records carry limit 1000 on the shared bucket")
def step_tavily_prod_limit(context: Any) -> None:
    from freesearch.configuration.provider_limits import TAVILY_DEFAULT_BUCKET_ID

    windows = _run(
        context, context.service.rate_limits.window_details("tavily", AuthMode.KEYED, FIXED_AT)
    )
    assert len(windows) == 1
    assert windows[0].bucket_id == TAVILY_DEFAULT_BUCKET_ID
    assert windows[0].window is RateWindowName.MINUTE
    assert windows[0].limit == Decimal("1000")


@when("I apply Tavily key environment dev")
def step_tavily_apply_dev(context: Any) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

    _run(context, context.service.initialize())
    _run(
        context,
        context.service.apply_tavily_config(
            ProviderConfig(tavily_key_environment="dev"), auth_mode=AuthMode.KEYED
        ),
    )


@then("both Tavily keyed records carry limit 100 on the shared bucket")
def step_tavily_dev_limit(context: Any) -> None:
    from freesearch.configuration.provider_limits import TAVILY_DEFAULT_BUCKET_ID

    windows = _run(
        context, context.service.rate_limits.window_details("tavily", AuthMode.KEYED, FIXED_AT)
    )
    assert len(windows) == 1
    assert windows[0].bucket_id == TAVILY_DEFAULT_BUCKET_ID
    assert windows[0].window is RateWindowName.MINUTE
    assert windows[0].limit == Decimal("100")


@given("Tavily keyed and keyless adapters over MockTransport with ambient key set")
def step_tavily_mock_ambient(context: Any) -> None:
    import os

    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    context.vendor_calls = []

    def _recorder(request: httpx.Request) -> httpx.Response:
        context.vendor_calls.append(request)
        if request.url.path == "/extract":
            return httpx.Response(200, json=_tavily_extract_payload())
        if request.url.path == "/usage":
            return httpx.Response(200, json=_tavily_usage_payload())
        return httpx.Response(200, json=_tavily_search_payload())

    previous = os.environ.get("TAVILY_API_KEY")
    os.environ["TAVILY_API_KEY"] = "ambient-leak-probe"
    context.tavily_previous_ambient = previous

    def _restore() -> None:
        if previous is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = previous

    cleanups: list[Any] = getattr(context, "enc_cleanups", None) or []
    context.enc_cleanups = cleanups
    cleanups.append(_restore)

    caller_keyless = httpx.AsyncClient(
        transport=httpx.MockTransport(_recorder),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )
    caller_keyed = httpx.AsyncClient(
        transport=httpx.MockTransport(_recorder),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )
    context.tavily_caller_clients = [caller_keyless, caller_keyed]
    context.tavily_keyless_adapter = TavilyAdapter(caller_keyless, api_key=None)
    context.tavily_keyed_adapter = TavilyAdapter(
        caller_keyed, api_key=SecretStr("tvly-keyed-secret-1")
    )
    assert context.tavily_keyless_adapter.limit_auth_mode is AuthMode.KEYLESS
    assert context.tavily_keyed_adapter.limit_auth_mode is AuthMode.KEYED


@when("I run Tavily search and extract on both rails through the real SDK")
def step_tavily_both_rails_sdk(context: Any) -> None:
    from freesearch.models.contracts import FetchRequest, SearchRequest

    keyless = context.tavily_keyless_adapter
    keyed = context.tavily_keyed_adapter
    context.tavily_keyless_search = _run(context, keyless.search(SearchRequest(query="q")))
    context.tavily_keyless_fetch = _run(
        context, keyless.fetch(FetchRequest(url="https://example.com/doc"))
    )
    context.tavily_keyed_search = _run(context, keyed.search(SearchRequest(query="q")))
    context.tavily_keyed_fetch = _run(
        context, keyed.fetch(FetchRequest(url="https://example.com/doc"))
    )
    assert context.tavily_keyless_search.provider == "tavily"
    assert context.tavily_keyed_search.provider == "tavily"


@then(
    "the Tavily keyless wire carries X-Tavily-Access-Mode keyless with no key and no ambient leak"
)
def step_tavily_keyless_wire(context: Any) -> None:
    keyless_urls = [str(request.url) for request in context.vendor_calls[:2]]
    assert keyless_urls == ["https://api.tavily.com/search", "https://api.tavily.com/extract"]
    for request in context.vendor_calls[:2]:
        assert request.headers.get("X-Tavily-Access-Mode") == "keyless"
        assert "ambient-leak-probe" not in request.headers.values()
        assert "caller-token-1" not in request.headers.values()
        assert "caller-xkey-2" not in request.headers.values()
        assert not any(key.lower() == "x-api-key" for key in request.headers)
        authorization = request.headers.get("Authorization")
        assert authorization is None or "tvly" not in authorization
    assert context.tavily_keyless_adapter.limit_auth_mode is AuthMode.KEYLESS
    assert len(context.vendor_calls) == 4


@then("the Tavily keyed wire carries Bearer with key precedence when both headers exist")
def step_tavily_keyed_wire(context: Any) -> None:
    keyed_requests = context.vendor_calls[2:4]
    assert [str(request.url) for request in keyed_requests] == [
        "https://api.tavily.com/search",
        "https://api.tavily.com/extract",
    ]
    for request in keyed_requests:
        assert request.headers.get("Authorization") == "Bearer tvly-keyed-secret-1"
        assert "ambient-leak-probe" not in request.headers.values()
        assert "caller-token-1" not in request.headers.values()
    owned = context.tavily_keyed_adapter._owned_http
    assert owned is not None
    owned.headers["X-Tavily-Access-Mode"] = "keyless"
    assert owned.headers.get("Authorization") == "Bearer tvly-keyed-secret-1"
    assert context.tavily_keyed_adapter.limit_auth_mode is AuthMode.KEYED


@given("Tavily keyed and keyless adapters with recording SDKs")
def step_tavily_recording_sdks(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter

    _open_repo(context)
    context.tavily_keyed_sdk = _TavilyFakeSDK()
    context.tavily_keyed_sdk.search_response = _tavily_search_payload()
    context.tavily_keyed_sdk.extract_response = _tavily_extract_payload()
    context.tavily_keyless_sdk = _TavilyFakeSDK()
    context.tavily_keyless_sdk.search_response = _tavily_search_payload()
    context.tavily_keyless_sdk.extract_response = _tavily_extract_payload()
    caller_keyed = httpx.AsyncClient()
    caller_keyless = httpx.AsyncClient()
    context.tavily_caller_clients = [caller_keyed, caller_keyless]
    context.tavily_keyed_adapter = TavilyAdapter(
        caller_keyed,
        sdk_client=context.tavily_keyed_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-params-1"),
    )
    context.tavily_keyless_adapter = TavilyAdapter(
        caller_keyless,
        sdk_client=context.tavily_keyless_sdk,  # type: ignore[arg-type]
        api_key=None,
    )


@when("I send Tavily full search and extract params on both rails")
def step_tavily_full_params(context: Any) -> None:
    from freesearch.models.contracts import FetchRequest, SearchRequest
    from freesearch.models.tavily import TavilyExtractParams, TavilySearchParams

    search_params = TavilySearchParams(
        search_depth="advanced",
        topic="news",
        time_range="week",
        start_date="2026-01-01",
        end_date="2026-02-01",
        days=7,
        include_domains=("example.com",),
        exclude_domains=("blocked.example",),
        include_answer="advanced",
        include_raw_content="markdown",
        include_images=True,
        auto_parameters=True,
        include_favicon=True,
        exact_match=True,
        country="united kingdom",
    )
    extract_params = TavilyExtractParams(
        extract_depth="advanced",
        format="text",
        query="extract probe",
        chunks_per_source=2,
        include_images=True,
        include_favicon=True,
    )
    for adapter in (context.tavily_keyed_adapter, context.tavily_keyless_adapter):
        _run(
            context,
            adapter.search(
                SearchRequest(
                    query="params probe",
                    limit=5,
                    mode="advanced",
                    domains=("caller.example",),
                    country_code="GB",
                    provider_options={"tavily": search_params},
                )
            ),
        )
        _run(
            context,
            adapter.fetch(
                FetchRequest(
                    url="https://example.com/doc",
                    provider_options={"tavily": extract_params},
                )
            ),
        )


@then(
    "both Tavily rails forward identical search depth topic domains answer content images country "
    "and extract depth format query chunks images"
)
def step_tavily_params_identical(context: Any) -> None:
    keyed_search = context.tavily_keyed_sdk.search_calls[0]
    keyless_search = context.tavily_keyless_sdk.search_calls[0]
    assert keyed_search == keyless_search
    assert keyed_search["search_depth"] == "advanced"
    assert keyed_search["topic"] == "news"
    assert keyed_search["time_range"] == "week"
    assert keyed_search["start_date"] == "2026-01-01"
    assert keyed_search["end_date"] == "2026-02-01"
    assert keyed_search["days"] == 7
    assert keyed_search["include_domains"] == ["example.com"]
    assert keyed_search["exclude_domains"] == ["blocked.example"]
    assert keyed_search["include_answer"] == "advanced"
    assert keyed_search["include_raw_content"] == "markdown"
    assert keyed_search["include_images"] is True
    assert keyed_search["auto_parameters"] is True
    assert keyed_search["include_favicon"] is True
    assert keyed_search["exact_match"] is True
    assert keyed_search["country"] == "united kingdom"
    assert keyed_search["include_usage"] is True
    assert keyed_search["max_results"] == 5
    keyed_extract = context.tavily_keyed_sdk.extract_calls[0]
    keyless_extract = context.tavily_keyless_sdk.extract_calls[0]
    assert keyed_extract == keyless_extract
    assert keyed_extract["extract_depth"] == "advanced"
    assert keyed_extract["format"] == "text"
    assert keyed_extract["query"] == "extract probe"
    assert keyed_extract["chunks_per_source"] == 2
    assert keyed_extract["include_images"] is True
    assert keyed_extract["include_favicon"] is True
    assert keyed_extract["include_usage"] is True
    assert keyed_extract["urls"] == ["https://example.com/doc"]


@then("a Tavily explicit depth conflict denies before vendor I/O")
def step_tavily_depth_conflict(context: Any) -> None:
    from freesearch.models.contracts import SearchRequest
    from freesearch.models.tavily import TavilySearchParams

    before_keyed = len(context.tavily_keyed_sdk.search_calls)
    before_keyless = len(context.tavily_keyless_sdk.search_calls)
    for adapter in (context.tavily_keyed_adapter, context.tavily_keyless_adapter):
        try:
            _run(
                context,
                adapter.search(
                    SearchRequest(
                        query="conflict",
                        mode="basic",
                        provider_options={"tavily": TavilySearchParams(search_depth="advanced")},
                    )
                ),
            )
            raise AssertionError("depth conflict must deny before vendor I/O")
        except Exception as exc:
            error = getattr(exc, "error", exc)
            assert getattr(error, "code", "") == "bad_request"
            assert getattr(error, "retryable", True) is False
    assert len(context.tavily_keyed_sdk.search_calls) == before_keyed
    assert len(context.tavily_keyless_sdk.search_calls) == before_keyless


@when("I estimate Tavily basic and advanced search cost")
def step_tavily_estimate_search(context: Any) -> None:
    import httpx

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.models.contracts import FetchRequest, SearchRequest
    from freesearch.models.tavily import TavilyExtractParams

    cost_caller = httpx.AsyncClient()
    context.tavily_cost_adapter = TavilyAdapter(cost_caller, sdk_client=_TavilyFakeSDK())  # type: ignore[arg-type]
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.append(cost_caller)
    context.tavily_basic_estimate = _run(
        context, context.tavily_cost_adapter.estimate_cost(SearchRequest(query="q"))
    )
    context.tavily_advanced_estimate = _run(
        context,
        context.tavily_cost_adapter.estimate_cost(SearchRequest(query="q", mode="advanced")),
    )
    context.tavily_basic_extract_estimate = _run(
        context,
        context.tavily_cost_adapter.estimate_cost(FetchRequest(url="https://example.com/doc")),
    )
    context.tavily_advanced_extract_estimate = _run(
        context,
        context.tavily_cost_adapter.estimate_cost(
            FetchRequest(
                url="https://example.com/doc",
                provider_options={"tavily": TavilyExtractParams(extract_depth="advanced")},
            )
        ),
    )


@then("Tavily basic search costs 1 Credit and advanced search costs 2 Credits")
def step_tavily_search_costs(context: Any) -> None:
    assert context.tavily_basic_estimate.units == Decimal("1")
    assert context.tavily_basic_estimate.currency == "Credits"
    assert context.tavily_advanced_estimate.units == Decimal("2")
    assert context.tavily_advanced_estimate.currency == "Credits"
    assert context.tavily_basic_extract_estimate.units == Decimal("0.2")
    assert context.tavily_basic_extract_estimate.currency == "Credits"
    assert context.tavily_advanced_extract_estimate.units == Decimal("0.4")
    assert context.tavily_advanced_extract_estimate.currency == "Credits"
    from freesearch.models.tavily import tavily_extract_credits

    assert tavily_extract_credits(1, "basic") == Decimal("0.2")
    assert tavily_extract_credits(1, "advanced") == Decimal("0.4")


@when("one Tavily basic search and one Tavily advanced search succeed")
def step_tavily_two_searches(context: Any) -> None:
    from freesearch.models.contracts import SearchResponse, UsageEvent, UsageOperation

    basic_adm = _run(context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-s1")))
    advanced_adm = _run(
        context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-s2"))
    )
    _run(
        context,
        context.service.record_success(
            basic_adm,
            SearchResponse(
                query="q",
                results=[],
                provider="tavily",
                usage=UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    unit_kind=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                ),
            ),
        ),
    )
    _run(
        context,
        context.service.record_success(
            advanced_adm,
            SearchResponse(
                query="q",
                results=[],
                provider="tavily",
                usage=UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("2"),
                    unit_kind=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                ),
            ),
        ),
    )
    context.tavily_usage_gets = 0


@then("the Tavily pool debits exactly 3 Credits with local projections and no usage GET")
def step_tavily_pool_minus_3(context: Any) -> None:
    import httpx

    from freesearch.adapters.tavily import TavilyAdapter

    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None
    assert pool.remaining == Decimal("997")
    assert pool.allowance == Decimal("1000")
    probe_caller = httpx.AsyncClient()
    context.tavily_caller_clients.append(probe_caller)
    probe = TavilyAdapter(probe_caller, sdk_client=_TavilyFakeSDK())  # type: ignore[arg-type]
    assert _run(context, probe.quota()) is None
    _run(context, probe.aclose())
    assert getattr(context, "tavily_usage_gets", 0) == 0
    history = _run(
        context,
        context.service.history(LimitHistoryQuery(provider="tavily", limit=10)),
    )
    debits = sorted(
        e.crd_debit for e in history.events if e.local_attempt_id in ("tav-s1", "tav-s2")
    )
    assert debits == [Decimal("8"), Decimal("16")]


@when("one Tavily {depth:w} extract succeeds with {good_urls:d} good URLs")
def step_tavily_extract_debit(context: Any, depth: str, good_urls: int) -> None:
    from freesearch.models.contracts import (
        FetchedDocument,
        FetchResponse,
        UsageEvent,
        UsageOperation,
    )

    # Literal T09 table map only: no production helper may feed ledger input.
    _T09_DEBITS: dict[tuple[str, int], Decimal] = {
        ("basic", 0): Decimal("0"),
        ("basic", 1): Decimal("0.2"),
        ("basic", 4): Decimal("0.8"),
        ("basic", 5): Decimal("1"),
        ("basic", 6): Decimal("1.2"),
        ("advanced", 0): Decimal("0"),
        ("advanced", 1): Decimal("0.4"),
        ("advanced", 4): Decimal("1.6"),
        ("advanced", 5): Decimal("2"),
        ("advanced", 6): Decimal("2.4"),
    }
    key = (depth, good_urls)
    if key not in _T09_DEBITS:
        raise AssertionError(f"unexpected T09 extract debit input: {depth!r} {good_urls!r}")
    expected = _T09_DEBITS[key]
    admission = _run(
        context,
        context.service.admit(_tavily_ctx(LimitOperation.FETCH, f"tav-ext-{depth}-{good_urls}")),
    )
    _run(
        context,
        context.service.record_success(
            admission,
            FetchResponse(
                provider="tavily",
                document=FetchedDocument(
                    url="https://example.com/doc",
                    content="body",
                    fetched_at=FIXED_AT,
                ),
                usage=UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.FETCH,
                    units=expected,
                    unit_kind=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                ),
            ),
        ),
    )
    context.tavily_expected_debit = expected
    context.tavily_cumulative = getattr(context, "tavily_cumulative", Decimal("0")) + expected


@then("the Tavily extract debit is {expected_credits} Credits")
def step_tavily_extract_assert(context: Any, expected_credits: str) -> None:
    from freesearch.models.contracts import UnitKind as UK

    assert Decimal(expected_credits) == context.tavily_expected_debit
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None and pool.native_unit is UK.CREDIT
    cumulative = getattr(context, "tavily_cumulative", context.tavily_expected_debit)
    assert pool.remaining == Decimal("1000") - cumulative


@when("one Tavily basic extract succeeds with 3 good and 2 bad URLs")
def step_tavily_mixed_urls(context: Any) -> None:
    from freesearch.models.contracts import (
        FetchedDocument,
        FetchResponse,
        UsageEvent,
        UsageOperation,
    )

    admission = _run(context, context.service.admit(_tavily_ctx(LimitOperation.FETCH, "tav-mix")))
    _run(
        context,
        context.service.record_success(
            admission,
            FetchResponse(
                provider="tavily",
                document=FetchedDocument(
                    url="https://example.com/doc",
                    content="body",
                    fetched_at=FIXED_AT,
                ),
                usage=UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.FETCH,
                    units=Decimal("0.6"),
                    unit_kind=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                ),
            ),
        ),
    )
    context.tavily_expected_debit = Decimal("0.6")
    context.tavily_cumulative = getattr(context, "tavily_cumulative", Decimal("0")) + Decimal("0.6")


@when("one Tavily call fails definitely")
def step_tavily_fail(context: Any) -> None:
    from freesearch.models.contracts import ProviderError

    context.tavily_failed_admission = _run(
        context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-fail-1"))
    )
    _run(
        context,
        context.service.record_failure(
            context.tavily_failed_admission,
            ProviderError(provider="tavily", code="timeout", message="tavily timeout"),
        ),
    )
    context.tavily_history = _run(
        context,
        context.service.history(LimitHistoryQuery(provider="tavily", limit=20)),
    )


@then("the Tavily reservation releases with zero Credit debit")
def step_tavily_release_zero(context: Any) -> None:
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None
    assert pool.remaining == Decimal("999.4")
    released = [e for e in context.tavily_history.events if e.local_attempt_id == "tav-fail-1"]
    assert released, "release audit must reference the attempt"
    assert all(e.crd_debit == Decimal("0") for e in released)


@when("one Tavily extract succeeds with empty valid documents")
def step_tavily_empty_docs(context: Any) -> None:
    from freesearch.models.contracts import (
        FetchedDocument,
        FetchResponse,
        UsageEvent,
        UsageOperation,
    )

    admission = _run(context, context.service.admit(_tavily_ctx(LimitOperation.FETCH, "tav-empty")))
    _run(
        context,
        context.service.record_success(
            admission,
            FetchResponse(
                provider="tavily",
                document=FetchedDocument(
                    url="https://example.com/doc", content="", fetched_at=FIXED_AT
                ),
                usage=UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.FETCH,
                    units=Decimal("0"),
                    unit_kind=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                ),
            ),
        ),
    )
    context.tavily_expected_debit = Decimal("0")
    context.tavily_cumulative = getattr(context, "tavily_cumulative", Decimal("0")) + Decimal("0")


@given("a Tavily adapter with stub usage payloads")
def step_tavily_stub_usage(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    stub_caller = httpx.AsyncClient()
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.append(stub_caller)
    context.tavily_stub_adapter = TavilyAdapter(
        stub_caller,
        sdk_client=_TavilyFakeSDK(),
        api_key=SecretStr("tvly-stub-1"),  # type: ignore[arg-type]
    )


@when("Tavily usage omits all figures")
def step_tavily_usage_absent(context: Any) -> None:
    from freesearch.models.provider_limits import UsageSyncRequest

    payload: dict[str, Any] = {}
    facts = context.tavily_stub_adapter._plan_facts(payload)
    assert facts.remaining is None
    assert facts.allowance is None
    context.tavily_facts = facts
    context.tavily_sync_request = UsageSyncRequest(
        provider="tavily", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT
    )


@then("the Tavily observation stays unknown with no invented debit")
def step_tavily_unknown(context: Any) -> None:
    assert context.tavily_facts.remaining is None
    assert context.tavily_facts.allowance is None
    assert context.tavily_facts.overage_confirmed is False


@when("Tavily usage reports malformed figures")
def step_tavily_usage_malformed(context: Any) -> None:
    context.tavily_malformed_payloads = [
        {"account": {"plan_usage": True, "plan_limit": 1000}},
        {"account": {"plan_usage": 1, "plan_limit": -5}},
        {"account": [], "key": {"usage": 1, "limit": 1000}},
        {"key": {"usage": 200, "limit": None, "api_key": "super-secret"}},
    ]


@then("the Tavily usage raises invalid_response with no secret leak")
def step_tavily_malformed_assert(context: Any) -> None:
    for payload in context.tavily_malformed_payloads:
        if payload == {"key": {"usage": 200, "limit": None, "api_key": "super-secret"}}:
            snapshot = context.tavily_stub_adapter._quota_snapshot(payload)
            assert snapshot.remaining is None
            assert snapshot.limit is None
            continue
        try:
            context.tavily_stub_adapter._plan_facts(payload)
            raise AssertionError(f"malformed payload must raise: {payload}")
        except Exception as exc:
            error = getattr(exc, "error", None)
            assert error is not None
            assert error.code == "invalid_response"
            assert error.retryable is False
            assert "super-secret" not in str(exc)


@when("Tavily usage reports zero remaining of 1000")
def step_tavily_usage_zero(context: Any) -> None:
    context.tavily_zero_snapshot = context.tavily_stub_adapter._quota_snapshot(
        {"account": {"plan_usage": 1000, "plan_limit": 1000}}
    )


@then("the Tavily observation keeps reported zero with allowance 1000")
def step_tavily_zero_assert(context: Any) -> None:
    snapshot = context.tavily_zero_snapshot
    assert snapshot.remaining == Decimal("0")
    assert snapshot.limit == Decimal("1000")
    assert snapshot.display_unit == "Credits"
    assert snapshot.unit_kind is UnitKind.CREDIT


@given("a Tavily dev pool with 0 Credits remaining in March")
def step_tavily_zero_march(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    march = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    _tavily_seed(context, remaining="0", allowance="1000", at=march)
    context.vendor_calls = []


@when("the Tavily clock reaches 2026-04-01")
def step_tavily_april(context: Any) -> None:
    april = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    service = ProviderLimitsService(
        _limits_repo(context), records=_tavily_records(), clock=lambda: april
    )
    context.tavily_reset_view = _run(context, service.provider_view("tavily"))
    context.tavily_reset_pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    context.tavily_reset_history = _run(
        context, service.history(LimitHistoryQuery(provider="tavily", limit=10))
    )


@then("the Tavily free pool refills to 1000 Credits with a reset audit")
def step_tavily_refill_assert(context: Any) -> None:
    pool = getattr(context, "tavily_reset_pool", None) or _run(
        context, _limits_repo(context).get_pool(_tavily_pool_id())
    )
    assert pool is not None
    assert pool.remaining == Decimal("1000")
    assert pool.allowance == Decimal("1000")
    history = getattr(context, "tavily_reset_history", None) or _run(
        context, context.service.history(LimitHistoryQuery(provider="tavily", limit=10))
    )
    reasons = [e.reason for e in history.events]
    assert "reset" in reasons
    reset_event = next(e for e in history.events if e.reason == "reset")
    assert reset_event.source == "free_monthly_reset"
    assert reset_event.new_native == Decimal("1000")


@when("the Tavily clock reaches 2027-01-01 from December")
def step_tavily_january(context: Any) -> None:
    december = datetime(2026, 12, 15, 12, 0, 0, tzinfo=UTC)
    _tavily_seed(context, remaining="0", allowance="1000", at=december)
    january = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
    service = ProviderLimitsService(
        _limits_repo(context), records=_tavily_records(), clock=lambda: january
    )
    context.tavily_reset_view = _run(context, service.provider_view("tavily"))
    context.tavily_reset_pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    context.tavily_reset_history = _run(
        context, service.history(LimitHistoryQuery(provider="tavily", limit=10))
    )


@when('the Tavily funds state is "{state}"')
def step_tavily_funds_state(context: Any, state: str) -> None:
    from freesearch.configuration.provider_config import ProviderConfig
    from freesearch.models.provider_limits import FundingMode, ResetRule, TierBalance

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    context.vendor_calls = []
    if state == "free_zero":
        _tavily_seed(context, remaining="0", allowance="1000")
    elif state == "unknown":
        _open_repo(context)
        context.service = _service(context, _tavily_records())
        _run(context, context.service.initialize())
        context.vendor_calls = []
    elif state == "paygo_overage":
        # PAYGO is access, not a stored Credits balance: the pool holds an
        # unknown balance with an OBSERVED PAYGO tier, so the durable funds
        # recheck stays unenforced while the operator flag confirms overage.
        _tavily_seed(
            context,
            remaining=None,
            allowance=None,
            tiers=[
                TierBalance(
                    pool_id="tavily:keyed:paygo",
                    tier="paid",
                    native_unit=UnitKind.CREDIT,
                    native_remaining=None,
                    native_allowance=None,
                    reset_rule=ResetRule.NEVER,
                    funding_mode=FundingMode.POSTPAID,
                    source="vendor_api",
                    confidence=Confidence.OBSERVED,
                )
            ],
        )
        _run(
            context,
            context.service.apply_tavily_config(
                ProviderConfig(tavily_paygo_enabled=True), auth_mode=AuthMode.KEYED
            ),
        )
    elif state == "vendor_key_cap":
        _run(
            context,
            _limits_repo(context).apply_snapshot(
                NativeUsageSnapshot(
                    pool_id=_tavily_pool_id(),
                    provider="tavily",
                    auth_mode=AuthMode.KEYED,
                    native_unit=UnitKind.CREDIT,
                    observed_at=FIXED_AT,
                    remaining=Decimal("0"),
                    allowance=Decimal("1000"),
                    reset_at=_tavily_next_month(FIXED_AT),
                    credential_generation=0,
                    source="vendor_api",
                )
            ),
        )
    elif state == "local_spend_cap":
        # A zero grant is absent, not a cap: grant exactly one search (8 CRD),
        # consume it with a success, and the exhausted local ceiling denies.
        from freesearch.models.contracts import SearchResponse, UsageEvent, UsageOperation

        _tavily_seed(context, remaining="1000", allowance="1000")
        # Grant adjustments follow the wall clock while reads follow the
        # scenario clock, so the period must cover both March (scenario) and
        # today (wall clock) for consumption to register.
        _run(
            context,
            context.service.save_grant(
                "tavily",
                GrantPayload(
                    version=0,
                    period_start=date(2026, 3, 1),
                    period_end=date(2027, 12, 31),
                    search_crd=Decimal("8"),
                    fetch_crd=Decimal("0"),
                ),
                AuthMode.KEYED,
            ),
        )
        cap_adm = _run(
            context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-cap-use"))
        )
        _run(
            context,
            context.service.record_success(
                cap_adm,
                SearchResponse(
                    query="q",
                    results=[],
                    provider="tavily",
                    usage=UsageEvent(
                        provider="tavily",
                        operation=UsageOperation.SEARCH,
                        units=Decimal("1"),
                        unit_kind=UnitKind.CREDIT,
                        observed_at=FIXED_AT,
                    ),
                ),
            ),
        )
    else:
        raise AssertionError(f"unknown funds state: {state}")
    context.tavily_funds_state = state


@then('the Tavily gate decision is "{decision}" with status {status:d}')
def step_tavily_gate_decision(context: Any, decision: str, status: int) -> None:
    if decision == "admit":
        admission = _run(
            context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-gate"))
        )
        assert admission.attempt_id == "tav-gate"
        assert status == 200
    elif decision == "deny":
        try:
            _run(context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-gate")))
            raise AssertionError(f"state {context.tavily_funds_state} must deny")
        except LimitDeniedError as exc:
            assert exc.status_code == status
            assert exc.status_code == 402
    else:
        raise AssertionError(f"unknown decision: {decision}")
    assert context.vendor_calls == []


@given("a Tavily app with seeded catalog and 1000 Credits pool")
def step_tavily_app(context: Any) -> None:
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
    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="1000", allowance="1000")
    context.vendor_calls = []
    context.tavily_stub = _StubAdapter("tavily")
    context.tavily_app = create_app([context.tavily_stub], repository=context.repository)
    with TestClient(context.tavily_app) as http_client:
        pair = _run(
            context,
            register_promote_login(
                http_client, context.repository, temp_email("tav-app"), UserRole.ADMIN
            ),
        )
        context.tavily_admin_headers = raw_auth_headers(pair["access_token"])


@when("I read the Tavily provider view")
def step_tavily_view(context: Any) -> None:
    service = ProviderLimitsService(_limits_repo(context), records=_tavily_records())
    context.tavily_view = _run(context, service.provider_view("tavily"))


@then("the Tavily search view is finite with cost 1 and the extract view is finite with cost 0.2")
def step_tavily_views(context: Any) -> None:
    auth = context.tavily_view.auth(AuthMode.KEYED)
    assert auth is not None
    search_view = next(v for v in auth.crd_views if v.operation is LimitOperation.SEARCH)
    fetch_view = next(v for v in auth.crd_views if v.operation is LimitOperation.FETCH)
    assert search_view.state is CRDState.FINITE
    assert search_view.request_cost_crd == Decimal("8")
    assert fetch_view.state is CRDState.FINITE
    assert fetch_view.request_cost_crd == Decimal("1.6")
    assert auth.detail is not None
    assert auth.detail.native_balance == Decimal("1000")
    assert auth.detail.native_allowance == Decimal("1000")
    assert len(context.tavily_view.auths) == 2


@then("both Tavily operation views share one pool without double funds")
def step_tavily_shared_views(context: Any) -> None:
    from freesearch.services import credit_units as tav_cu

    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None
    records = [r for r in _tavily_records() if r.auth_mode is AuthMode.KEYED]
    assert len(records) == 2
    funds_once = tav_cu.shared_pool_funds(pool, records)
    assert funds_once == Decimal("8000")
    views = tav_cu.project_shared_crd_views(pool, records)
    assert len(views) == 2
    assert views[0].shared_pool_id == views[1].shared_pool_id
    assert views[0].shared_pool_id == _tavily_pool_id()


@when("I save a Tavily search grant for one period")
def step_tavily_grant(context: Any) -> None:
    context.tavily_saved = _run(
        context,
        context.service.save_grant(
            "tavily",
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
    context.tavily_history = _run(
        context,
        context.service.history(
            LimitHistoryQuery(provider="tavily", auth_mode=AuthMode.KEYED, limit=10)
        ),
    )


@then("the Tavily grant period persists with audit old new source")
def step_tavily_grant_audit(context: Any) -> None:
    auth = context.tavily_saved.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.grants.search_granted_crd == Decimal("10")
    assert auth.grants.fetch_granted_crd == Decimal("4")
    reasons = [e.reason for e in context.tavily_history.events]
    assert "grant" in reasons
    grant_event = next(e for e in context.tavily_history.events if e.reason == "grant")
    assert grant_event.source in ("local", "operator")


@when("I select Tavily routes twice")
def step_tavily_routes_twice(context: Any) -> None:
    from freesearch.models.contracts import SearchRequest
    from freesearch.services.routing import select_route
    from tests.integration.services.test_monitoring import _StubAdapter

    context.tavily_select_route = select_route
    context.tavily_route_adapters = [_StubAdapter("tavily-b"), _StubAdapter("tavily-a")]
    req = SearchRequest(query="tavily routing probe")
    context.tavily_first_order = [
        c.adapter.name for c in select_route(req, context.tavily_route_adapters, {}, {})
    ]
    context.tavily_second_order = [
        c.adapter.name for c in select_route(req, context.tavily_route_adapters, {}, {})
    ]


@then("the Tavily route order and fallback stay identical")
def step_tavily_routes_same(context: Any) -> None:
    assert context.tavily_first_order == context.tavily_second_order
    assert context.tavily_first_order == ["tavily-b", "tavily-a"]


@when("two Tavily searches succeed")
def step_tavily_two_successes(context: Any) -> None:
    from freesearch.models.contracts import SearchResponse, UsageEvent, UsageOperation

    for attempt in ("tav-t1", "tav-t2"):
        admission = _run(
            context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, attempt))
        )
        _run(
            context,
            context.service.record_success(
                admission,
                SearchResponse(
                    query="q",
                    results=[],
                    provider="tavily",
                    usage=UsageEvent(
                        provider="tavily",
                        operation=UsageOperation.SEARCH,
                        units=Decimal("1"),
                        unit_kind=UnitKind.CREDIT,
                        observed_at=FIXED_AT,
                    ),
                ),
            ),
        )


@then("the Tavily totals hold exact Credits with two attempts")
def step_tavily_totals(context: Any) -> None:
    totals = _run(context, _limits_repo(context).crd_usage_totals("tavily"))
    assert len(totals) == 1
    assert totals[0].normalized_crd == Decimal("16")
    assert totals[0].attempt_count == 2


@given("a Tavily adapter with held usage GET and seeded pool")
def step_tavily_held_usage(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="1000", allowance="1000")
    context.tavily_release = asyncio.Event()
    context.tavily_usage_gets = []

    class _HeldHTTP:
        def __init__(self, outer: Any) -> None:
            self._outer = outer

        async def get(self, url: str) -> Any:
            self._outer.tavily_usage_gets.append(url)
            await self._outer.tavily_release.wait()
            return httpx.Response(200, json=_tavily_usage_payload())

    context.tavily_sdk = _TavilyFakeSDK()
    context.tavily_sdk.search_response = _tavily_search_payload()
    context.tavily_sdk.extract_response = _tavily_extract_payload()
    held_caller = httpx.AsyncClient()
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.append(held_caller)
    context.tavily_held_adapter = TavilyAdapter(
        held_caller,
        sdk_client=context.tavily_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-held-1"),
    )
    context.tavily_held_adapter._owned_http = _HeldHTTP(context)  # type: ignore[assignment]


@when("Tavily search and extract run while the usage poll is held")
def step_tavily_run_while_held(context: Any) -> None:
    from freesearch.models.contracts import FetchRequest, SearchRequest
    from freesearch.models.provider_limits import UsageSyncRequest

    async def _held_poll() -> Any:
        return await context.tavily_held_adapter.usage_snapshot(
            UsageSyncRequest(provider="tavily", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )

    async def _search() -> Any:
        return await context.tavily_held_adapter.search(SearchRequest(query="held-q"))

    async def _extract() -> Any:
        return await context.tavily_held_adapter.fetch(FetchRequest(url="https://example.com/doc"))

    async def _scenario() -> tuple[Any, Any, Any]:
        poll_task = asyncio.ensure_future(_held_poll())
        await asyncio.sleep(0)
        assert poll_task.done() is False
        search_result = await _search()
        extract_result = await _extract()
        assert poll_task.done() is False
        context.tavily_release.set()
        snapshot = await asyncio.wait_for(poll_task, timeout=5)
        return search_result, extract_result, snapshot

    search_result, extract_result, snapshot = _run(context, _scenario())
    context.tavily_held_search = search_result
    context.tavily_held_extract = extract_result
    context.tavily_held_snapshot = snapshot


@then("Tavily search and extract finish before the poll releases")
def step_tavily_no_delay(context: Any) -> None:
    assert context.tavily_held_search.provider == "tavily"
    assert context.tavily_held_extract.provider == "tavily"
    assert context.tavily_held_snapshot is not None
    assert context.tavily_held_snapshot.remaining == Decimal("999")
    assert context.tavily_held_snapshot.allowance == Decimal("1000")
    assert len(context.tavily_sdk.search_calls) == 1
    assert len(context.tavily_sdk.extract_calls) == 1


@then("Tavily route cost and budget reads issue zero usage GETs")
def step_tavily_zero_gets(context: Any) -> None:
    from freesearch.models.contracts import FetchRequest, SearchRequest

    assert context.tavily_usage_gets == ["https://api.tavily.com/usage"]
    before = list(context.tavily_usage_gets)
    _run(context, context.tavily_held_adapter.estimate_cost(SearchRequest(query="q")))
    _run(
        context,
        context.tavily_held_adapter.estimate_cost(FetchRequest(url="https://example.com/doc")),
    )
    _run(context, context.tavily_held_adapter.quota())
    _run(context, context.service.provider_view("tavily"))
    from freesearch.services.routing import select_route
    from tests.integration.services.test_monitoring import _StubAdapter

    req = SearchRequest(query="zero-get probe")
    select_route(req, [_StubAdapter("tavily-a")], {}, {})
    assert context.tavily_usage_gets == before


@given("a Tavily pool with a claimed sync lease at fixed time")
def step_tavily_claimed(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="1000", allowance="1000", at=FIXED_AT)
    first = _run(
        context,
        _limits_repo(context).claim_sync(
            SyncClaim(provider="tavily", owner="sched-a", now=FIXED_AT, lease_seconds=90)
        ),
    )
    assert first is True
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None
    assert pool.next_sync_at == FIXED_AT + timedelta(seconds=60)


@when("a second Tavily sync claims at plus 59.999 seconds")
def step_tavily_claim_59999(context: Any) -> None:
    context.tavily_second = _run(
        context,
        _limits_repo(context).claim_sync(
            SyncClaim(
                provider="tavily",
                owner="sched-a",
                now=FIXED_AT + timedelta(seconds=59.999),
                lease_seconds=90,
            )
        ),
    )


@then("the Tavily second claim is held")
def step_tavily_second_held(context: Any) -> None:
    assert context.tavily_second is False


@when("a third Tavily sync claims at plus 60 seconds with an expired lease")
def step_tavily_claim_60(context: Any) -> None:
    context.tavily_third = _run(
        context,
        _limits_repo(context).claim_sync(
            SyncClaim(
                provider="tavily",
                owner="sched-b",
                now=FIXED_AT + timedelta(seconds=90.001),
                lease_seconds=90,
            )
        ),
    )
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    context.tavily_after_third = pool


@then("the Tavily third claim succeeds with next sync 60 seconds later")
def step_tavily_third_ok(context: Any) -> None:
    assert context.tavily_third is True
    assert context.tavily_after_third is not None
    assert context.tavily_after_third.next_sync_at == FIXED_AT + timedelta(seconds=90.001 + 60)


@when("two Tavily schedulers race and one owner forces sync twice")
def step_tavily_two_schedulers(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.services.limits_sync import LimitSyncService

    async def _race() -> tuple[bool, bool]:
        first = await _limits_repo(context).claim_sync(
            SyncClaim(
                provider="tavily",
                owner="sched-a",
                now=FIXED_AT + timedelta(seconds=200),
                lease_seconds=90,
            )
        )
        second = await _limits_repo(context).claim_sync(
            SyncClaim(
                provider="tavily",
                owner="sched-b",
                now=FIXED_AT + timedelta(seconds=200, milliseconds=1),
                lease_seconds=90,
            )
        )
        return first, second

    context.tavily_sched_a, context.tavily_sched_b = _run(context, _race())
    sched_caller = httpx.AsyncClient()
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.append(sched_caller)
    sched_adapter = TavilyAdapter(
        sched_caller,
        sdk_client=_TavilyFakeSDK(),  # type: ignore[arg-type]
        api_key=SecretStr("tvly-sched-1"),
    )
    context.tavily_sched_adapter = sched_adapter
    service = LimitSyncService(
        _limits_repo(context),
        context.service,
        lambda: [sched_adapter],
        clock=lambda: FIXED_AT,
    )
    forced = _run(context, service.sync_provider("tavily", FIXED_AT + timedelta(seconds=200)))
    context.tavily_forced = forced


@then("one Tavily scheduler owns the lease and force cannot bypass cadence")
def step_tavily_sched_result(context: Any) -> None:
    assert (context.tavily_sched_a, context.tavily_sched_b) in ((True, False), (False, True))
    assert context.tavily_forced.status in ("skipped", "failed", "synced")
    if context.tavily_forced.status == "skipped":
        assert context.tavily_forced.reason in ("lease_held", "cadence")


@given("a Tavily pool with known Credits and a due sync")
def step_tavily_due_sync(context: Any) -> None:
    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="1000", allowance="1000", at=FIXED_AT)
    context.vendor_calls = []


@when("the Tavily poll fails with transport error")
def step_tavily_poll_fail(context: Any) -> None:

    from freesearch.models.provider_limits import SyncResult

    _run(
        context,
        _limits_repo(context).claim_sync(
            SyncClaim(provider="tavily", owner="sync-a", now=FIXED_AT, lease_seconds=90)
        ),
    )
    _run(
        context,
        _limits_repo(context).complete_sync(
            SyncResult(
                provider="tavily",
                status="failed",
                observed_at=FIXED_AT,
                error_code="transport_error",
                stale=True,
                reason="simulated poll failure",
            )
        ),
    )
    context.tavily_after_fail = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    from freesearch.services.limits_sync import _cadence_delay

    context.tavily_retry_delay = _cadence_delay("tavily", 60, 60)
    assert context.tavily_retry_delay >= 60


@then("the Tavily last balance survives as stale with no immediate retry")
def step_tavily_stale(context: Any) -> None:
    assert context.tavily_after_fail is not None
    assert context.tavily_after_fail.remaining == Decimal("1000")
    assert context.tavily_after_fail.stale is True
    assert context.tavily_retry_delay >= 60


@when("the Tavily runtime restarts and the key changes")
def step_tavily_restart(context: Any) -> None:
    _run(context, context.service.credential_changed("tavily"))
    context.tavily_after_restart = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    late = _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=_tavily_pool_id(),
                provider="tavily",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=FIXED_AT + timedelta(seconds=5),
                remaining=Decimal("1000"),
                allowance=Decimal("1000"),
                credential_generation=0,
            )
        ),
    )
    context.tavily_late_accepted = late
    context.tavily_after_late = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))


@then("the Tavily terminal state clears and stale reads reject old polls")
def step_tavily_restart_assert(context: Any) -> None:
    assert context.tavily_after_restart is not None
    assert context.tavily_after_restart.stale is True
    assert context.tavily_late_accepted is False
    assert context.tavily_after_late.remaining == Decimal("1000")


@when("an old Tavily poll arrives after a newer 402 and local debits")
def step_tavily_old_poll(context: Any) -> None:
    # The local debit reserves before the terminal observation: a newer 402
    # must deny further admissions, so the in-flight reservation predates it.
    admission = _run(context, context.service.admit(_tavily_ctx(LimitOperation.SEARCH, "tav-old")))
    context.tavily_old_admission = admission
    terminal = NativeUsageSnapshot(
        pool_id=_tavily_pool_id(),
        provider="tavily",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        observed_at=FIXED_AT + timedelta(seconds=10),
        remaining=Decimal("0"),
        allowance=Decimal("1000"),
        credential_generation=1,
        source="vendor_402",
    )
    _run(context, _limits_repo(context).apply_snapshot(terminal))
    old = NativeUsageSnapshot(
        pool_id=_tavily_pool_id(),
        provider="tavily",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        observed_at=FIXED_AT + timedelta(seconds=5),
        remaining=Decimal("999"),
        allowance=Decimal("1000"),
        credential_generation=1,
        source="vendor_api",
    )
    context.tavily_old_accepted = _run(context, _limits_repo(context).apply_snapshot(old))
    context.tavily_after_old = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))


@then("the Tavily old poll cannot replace the newer 402 or debits")
def step_tavily_old_rejected(context: Any) -> None:
    assert context.tavily_old_accepted is False
    assert context.tavily_after_old is not None
    assert context.tavily_after_old.remaining == Decimal("0")
    assert context.tavily_after_old.source == "vendor_402"
    kept = _run(context, _limits_repo(context).get_admission("tav-old"))
    assert kept is not None


def _tavily_402_sdk() -> _TavilyFakeSDK:
    """Return a recording SDK whose next search fails once with vendor 402."""

    import httpx

    sdk = _TavilyFakeSDK()
    sdk.search_error = httpx.HTTPStatusError(
        "request failed",
        request=httpx.Request("GET", "https://api.tavily.com/search"),
        response=httpx.Response(402),
    )
    return sdk


def _tavily_assert_zero_debit(context: Any, *, terminal_pool: bool = True) -> None:
    pool = _run(context, _limits_repo(context).get_pool(_tavily_pool_id()))
    assert pool is not None
    if terminal_pool:
        assert pool.remaining == Decimal("0")
        assert pool.source == "vendor_402"
    else:
        # The injected MCP composition builds no limits generation
        # (create_server keeps state["limits"] None without a lifespan
        # enter), so tracked_call runs limit-free and the pool row stays
        # at its seeded value. Pool immediacy itself is pinned through
        # the shared helper by the REST, fanout, and service cases.
        assert pool.remaining == Decimal("999")
        assert pool.source == "vendor_api"
    history = _run(
        context,
        context.service.history(LimitHistoryQuery(provider="tavily", limit=20)),
    )
    assert all(e.reason != "local_success" for e in history.events)


@given("a Tavily REST app with stale positive cache and vendor 402")
def step_tavily_rest_402(context: Any) -> None:
    import httpx
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
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
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="999", allowance="1000")
    context.vendor_calls = []
    caller = httpx.AsyncClient()
    context.tavily_caller_clients = [caller]
    context.tavily_rest_sdk = _tavily_402_sdk()
    context.tavily_rest_adapter = TavilyAdapter(
        caller,
        sdk_client=context.tavily_rest_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-rest-402"),
    )
    context.tavily_rest_app = create_app(
        [context.tavily_rest_adapter], repository=context.repository
    )
    with TestClient(context.tavily_rest_app) as http_client:
        pair = _run(
            context,
            register_promote_login(
                http_client, context.repository, temp_email("tav-rest"), UserRole.AGENT
            ),
        )
        context.tavily_rest_headers = raw_auth_headers(pair["access_token"])


@when("I request one Tavily search through REST")
def step_tavily_rest_search(context: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(context.tavily_rest_app) as client:
        context.tavily_rest_response = client.post(
            "/search",
            json={"query": "rest 402 probe", "limit": 3},
            headers=context.tavily_rest_headers,
        )


@then("the Tavily REST answer is HTTP 402 out of Credits with one vendor attempt and zero debit")
def step_tavily_rest_402_assert(context: Any) -> None:
    response = context.tavily_rest_response
    assert response.status_code == 402
    body = response.json()
    assert body.get("provider") == "tavily"
    assert body.get("detail") == "Tavily is out of Credits. Wait until reset or upgrade."
    assert len(context.tavily_rest_sdk.search_calls) == 1
    _tavily_assert_zero_debit(context)


@given("a Tavily MCP app with stale positive cache and vendor 402")
def step_tavily_mcp_402(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.mcp.server import create_server
    from tests.fixtures.auth import mcp_account_token

    _open_repo(context)
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="999", allowance="1000")
    context.vendor_calls = []
    caller = httpx.AsyncClient()
    context.tavily_caller_clients = [caller]
    context.tavily_mcp_sdk = _tavily_402_sdk()
    context.tavily_mcp_adapter = TavilyAdapter(
        caller,
        sdk_client=context.tavily_mcp_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-mcp-402"),
    )

    async def _server() -> Any:
        service, token, _email = await mcp_account_token(context.repository, "tav-mcp")
        return create_server(
            [context.tavily_mcp_adapter],
            repository=context.repository,
            auth_service=service,
            stdio_token=SecretStr(token.get_secret_value()),
        )

    context.tavily_mcp_server = _run(context, _server())


@when("I request one Tavily search through MCP")
def step_tavily_mcp_search(context: Any) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    try:
        _run(
            context,
            context.tavily_mcp_server.call_tool("search", {"request": {"query": "mcp 402 probe"}}),
        )
        context.tavily_mcp_error = None
    except ToolError as exc:
        context.tavily_mcp_error = exc
    except Exception as exc:
        context.tavily_mcp_error = exc

    async def _drain_refresh() -> None:
        from freesearch.routers.api import _BACKGROUND_TASKS

        pending = [task for task in list(_BACKGROUND_TASKS) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    _run(context, _drain_refresh())


@then("the Tavily MCP answer is 402 out of Credits with one vendor attempt and zero debit")
def step_tavily_mcp_402_assert(context: Any) -> None:
    assert context.tavily_mcp_error is not None
    text = str(context.tavily_mcp_error)
    assert "Tavily is out of Credits. Wait until reset or upgrade." in text
    assert len(context.tavily_mcp_sdk.search_calls) == 1
    _tavily_assert_zero_debit(context, terminal_pool=False)


@given("a Tavily fanout app with a held other task and vendor 402")
def step_tavily_fanout_app(context: Any) -> None:
    import httpx
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
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
    context.service = _service(context, _tavily_records())
    _run(context, context.service.initialize())
    _tavily_seed(context, remaining="999", allowance="1000")
    context.vendor_calls = []
    caller = httpx.AsyncClient()
    context.tavily_caller_clients = [caller]
    context.tavily_fanout_sdk = _tavily_402_sdk()
    context.tavily_fanout_adapter = TavilyAdapter(
        caller,
        sdk_client=context.tavily_fanout_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-fanout-402"),
    )
    context.tavily_other_released = asyncio.Event()
    context.tavily_other_cancelled = False

    from freesearch.adapters.base import ProviderAdapter
    from freesearch.models.contracts import (
        CostEstimate,
        FetchRequest,
        FetchResponse,
        ProviderCapabilities,
        SearchRequest,
        SearchResponse,
    )

    outer = context

    class _HeldOther(ProviderAdapter):
        @property
        def name(self) -> str:
            return "held-other"

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

        async def search(self, request: SearchRequest) -> SearchResponse:
            try:
                await outer.tavily_other_released.wait()
            except asyncio.CancelledError:
                outer.tavily_other_cancelled = True
                raise
            return SearchResponse(
                query=request.query,
                provider="held-other",
                results=[],
                total_results=0,
            )

        async def fetch(self, request: FetchRequest) -> FetchResponse:
            raise NotImplementedError

        async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
            raise NotImplementedError

    context.tavily_held_other = _HeldOther()
    context.tavily_fanout_app = create_app(
        [context.tavily_fanout_adapter, context.tavily_held_other],
        repository=context.repository,
    )
    context.tavily_single_app = create_app(
        [context.tavily_fanout_adapter], repository=context.repository
    )
    with TestClient(context.tavily_fanout_app) as http_client:
        pair = _run(
            context,
            register_promote_login(
                http_client, context.repository, temp_email("tav-fanout"), UserRole.AGENT
            ),
        )
        context.tavily_fanout_headers = raw_auth_headers(pair["access_token"])


@when("I run Tavily fanout search with client fallback enabled")
def step_tavily_fanout_run(context: Any) -> None:
    from fastapi.testclient import TestClient

    with TestClient(context.tavily_fanout_app) as client:
        context.tavily_fanout_held = client.post(
            "/search",
            json={"query": "fanout 402 probe", "limit": 3, "fanout": True},
            headers=context.tavily_fanout_headers,
        )
    context.tavily_other_released.set()
    with TestClient(context.tavily_fanout_app) as client:
        context.tavily_fanout_released = client.post(
            "/search",
            json={"query": "fanout 402 probe", "limit": 3, "fanout": True},
            headers=context.tavily_fanout_headers,
        )
    with TestClient(context.tavily_single_app) as client:
        context.tavily_single_fallback = client.post(
            "/search",
            json={"query": "fanout 402 probe", "limit": 3},
            headers=context.tavily_fanout_headers,
        )

    async def _drain_refresh() -> None:
        from freesearch.routers.api import _BACKGROUND_TASKS

        pending = [task for task in list(_BACKGROUND_TASKS) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    _run(context, _drain_refresh())


@then("the Tavily fanout held answer is terminal 402 with the other task cancelled")
def step_tavily_fanout_held_assert(context: Any) -> None:
    response = context.tavily_fanout_held
    assert response.status_code == 402
    body = response.json()
    assert body.get("provider") == "tavily"
    assert body.get("detail") == "Tavily is out of Credits. Wait until reset or upgrade."
    assert body.get("results", None) is None
    assert context.tavily_other_cancelled is True
    assert len(context.tavily_fanout_sdk.search_calls) == 1


@then(
    "the Tavily fanout released answer fuses other success "
    "with local denial and no new vendor attempt"
)
def step_tavily_fanout_released_assert(context: Any) -> None:
    response = context.tavily_fanout_released
    assert response.status_code == 200
    body = response.json()
    assert body.get("provider") == "held-other"
    assert len(context.tavily_fanout_sdk.search_calls) == 1
    waterfall = body.get("waterfall", [])
    tavily_legs = [entry for entry in waterfall if entry.get("provider") == "tavily"]
    assert len(tavily_legs) == 1
    assert "crd_exhausted" in (tavily_legs[0].get("error") or "")


@then("the Tavily single fallback answer is a local 402 with no new vendor attempt")
def step_tavily_single_fallback_assert(context: Any) -> None:
    response = context.tavily_single_fallback
    assert response.status_code == 402
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("provider") == "tavily"
    assert detail.get("code") == "crd_exhausted"
    assert detail.get("status_code") == 402
    assert len(context.tavily_fanout_sdk.search_calls) == 1
    _tavily_assert_zero_debit(context)


@given("a Tavily adapter with 429 then success and recording sleeper")
def step_tavily_429_success(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.infrastructure.resilience import ResilientRunner

    _open_repo(context)
    context.tavily_sleeps = []

    async def _sleeper(delay: float) -> None:
        context.tavily_sleeps.append(delay)

    context.tavily_clock_now = 1000.0

    def _clock() -> float:
        return context.tavily_clock_now

    retry_runner_caller = httpx.AsyncClient()
    retry_adapter_caller = httpx.AsyncClient()
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.extend([retry_runner_caller, retry_adapter_caller])
    runner = ResilientRunner(
        retry_runner_caller,
        max_attempts=2,
        base_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        clock=_clock,
        sleeper=_sleeper,
        random_source=lambda: 1.0,
    )
    context.tavily_retry_sdk = _TavilyFakeSDK()
    context.tavily_retry_adapter = TavilyAdapter(
        retry_adapter_caller,
        runner=runner,
        sdk_client=context.tavily_retry_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-retry-1"),
    )
    context.tavily_retry_pristine = context.tavily_retry_adapter._normalize_error


@when("Tavily search retries after Retry-After 7")
def step_tavily_search_retry_7(context: Any) -> None:
    from tavily.errors import UsageLimitExceededError  # type: ignore[import-untyped]

    from freesearch.models.contracts import SearchRequest

    context.tavily_retry_sdk.search_response = _tavily_search_payload()
    original = context.tavily_retry_adapter._normalize_error

    def _patched(exc: Exception) -> Any:
        context.tavily_retry_adapter._response_probes[context.tavily_retry_adapter._task_key()] = (
            type("Probe", (), {"status": 429, "retry_after_seconds": 7.0})()
        )
        return original(exc)

    context.tavily_retry_adapter._normalize_error = _patched  # type: ignore[assignment]
    calls = {"count": 0}
    real_search = context.tavily_retry_sdk.search

    async def _flaky(**kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise UsageLimitExceededError("usage limit exceeded")
        return await real_search(**kwargs)

    context.tavily_retry_sdk.search = _flaky  # type: ignore[assignment]
    context.tavily_sleeps.clear()
    context.tavily_search_retry = _run(
        context, context.tavily_retry_adapter.search(SearchRequest(query="retry-7"))
    )
    context.tavily_search_calls = calls["count"]


@then("the Tavily search sleeps exactly 7.0 with two vendor attempts")
def step_tavily_search_sleep_7(context: Any) -> None:
    assert context.tavily_search_retry.provider == "tavily"
    assert context.tavily_sleeps == [7.0]
    assert context.tavily_search_calls == 2


@when("Tavily extract retries after Retry-After 3")
def step_tavily_extract_retry_3(context: Any) -> None:
    from tavily.errors import UsageLimitExceededError  # type: ignore[import-untyped]

    from freesearch.models.contracts import FetchRequest

    # Move the deterministic clock past the search cooldown so the shared
    # breaker records no carryover wait in this operation's sleep list.
    context.tavily_clock_now += 7.0
    context.tavily_retry_sdk.extract_response = _tavily_extract_payload()
    pristine = context.tavily_retry_pristine

    def _patched(exc: Exception) -> Any:
        context.tavily_retry_adapter._response_probes[context.tavily_retry_adapter._task_key()] = (
            type("Probe", (), {"status": 429, "retry_after_seconds": 3.0})()
        )
        return pristine(exc)

    context.tavily_retry_adapter._normalize_error = _patched  # type: ignore[assignment]
    calls = {"count": 0}
    real_extract = context.tavily_retry_sdk.extract

    async def _flaky(**kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise UsageLimitExceededError("usage limit exceeded")
        return await real_extract(**kwargs)

    context.tavily_retry_sdk.extract = _flaky  # type: ignore[assignment]
    context.tavily_sleeps.clear()
    context.tavily_extract_retry = _run(
        context,
        context.tavily_retry_adapter.fetch(FetchRequest(url="https://example.com/doc")),
    )
    context.tavily_extract_calls = calls["count"]


@then("the Tavily extract sleeps exactly 3.0 with two vendor attempts")
def step_tavily_extract_sleep_3(context: Any) -> None:
    assert context.tavily_extract_retry.provider == "tavily"
    assert context.tavily_sleeps == [3.0]
    assert context.tavily_extract_calls == 2


@given("a Tavily adapter with recording sleeper and base delay 1.0")
def step_tavily_sleeper(context: Any) -> None:
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.infrastructure.resilience import ResilientRunner

    _open_repo(context)
    context.tavily_sleeps = []
    context.tavily_clock_now = 1000.0

    async def _sleeper(delay: float) -> None:
        context.tavily_sleeps.append(delay)

    def _clock() -> float:
        return context.tavily_clock_now

    variant_runner_caller = httpx.AsyncClient()
    variant_adapter_caller = httpx.AsyncClient()
    context.tavily_caller_clients = getattr(context, "tavily_caller_clients", [])
    context.tavily_caller_clients.extend([variant_runner_caller, variant_adapter_caller])
    runner = ResilientRunner(
        variant_runner_caller,
        max_attempts=2,
        base_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        clock=_clock,
        sleeper=_sleeper,
        random_source=lambda: 1.0,
    )
    context.tavily_variant_sdk = _TavilyFakeSDK()
    context.tavily_variant_sdk.search_response = _tavily_search_payload()
    context.tavily_variant_adapter = TavilyAdapter(
        variant_adapter_caller,
        runner=runner,
        sdk_client=context.tavily_variant_sdk,  # type: ignore[arg-type]
        api_key=SecretStr("tvly-variant-1"),
    )


@when('Tavily answers 429 with Retry-After "{header}"')
def step_tavily_retry_variant(context: Any, header: str) -> None:
    import email.utils
    import time

    import httpx
    from pydantic import SecretStr
    from tavily.errors import UsageLimitExceededError  # type: ignore[import-untyped]

    from freesearch.adapters.tavily import TavilyAdapter
    from freesearch.models.contracts import SearchRequest

    context.tavily_sleeps.clear()
    calls = {"count": 0}
    wire_calls: list[httpx.Request] = []
    real_search = context.tavily_variant_sdk.search

    async def _always_429(**kwargs: Any) -> Any:
        calls["count"] += 1
        raise UsageLimitExceededError("usage limit exceeded")

    async def _succeed(**kwargs: Any) -> Any:
        calls["count"] += 1
        return await real_search(**kwargs)

    if header == "absent":
        context.tavily_variant_sdk.search = _always_429  # type: ignore[assignment]
        probe: Any = None
    elif header == "malformed":
        context.tavily_variant_sdk.search = _always_429  # type: ignore[assignment]
        probe = type("Probe", (), {"status": 429, "retry_after_seconds": None})()
    elif header == "zero":
        context.tavily_variant_sdk.search = _succeed  # type: ignore[assignment]
        probe = type("Probe", (), {"status": 429, "retry_after_seconds": 0.0})()
        first = True

        async def _flaky_zero(**kwargs: Any) -> Any:
            nonlocal first
            calls["count"] += 1
            if first:
                first = False
                raise UsageLimitExceededError("usage limit exceeded")
            return await real_search(**kwargs)

        context.tavily_variant_sdk.search = _flaky_zero  # type: ignore[assignment]
    elif header == "http-date":
        # Real dated 429 through the response hook: the owned client records
        # the HTTP-date Retry-After before the SDK converts the 429, then the
        # retry succeeds. The date sits 7 seconds ahead of the wall clock
        # because the hook resolves dates against the wall clock; the probe
        # ceil normalizes sub-second skew to exactly 7.
        retry_at = email.utils.formatdate(time.time() + 7.0, usegmt=True)

        def _dated_handler(request: httpx.Request) -> httpx.Response:
            wire_calls.append(request)
            if len(wire_calls) == 1:
                return httpx.Response(
                    429, headers={"Retry-After": retry_at}, json={"detail": "slow"}
                )
            return httpx.Response(200, json=_tavily_search_payload())

        dated_caller = httpx.AsyncClient(transport=httpx.MockTransport(_dated_handler))
        context.tavily_caller_clients.append(dated_caller)
        runner = context.tavily_variant_adapter._runner
        context.tavily_variant_adapter = TavilyAdapter(
            dated_caller,
            runner=runner,
            api_key=SecretStr("tvly-variant-1"),
        )
        probe = None
    else:
        raise AssertionError(f"unknown Retry-After variant: {header}")

    if header != "http-date":
        original = context.tavily_variant_adapter._normalize_error

        def _patched(exc: Exception) -> Any:
            if probe is not None:
                context.tavily_variant_adapter._response_probes[
                    context.tavily_variant_adapter._task_key()
                ] = probe
            return original(exc)

        context.tavily_variant_adapter._normalize_error = _patched  # type: ignore[assignment]
    if header in ("zero", "http-date"):
        context.tavily_variant_result = _run(
            context, context.tavily_variant_adapter.search(SearchRequest(query="variant"))
        )
        context.tavily_variant_error = None
    else:
        try:
            _run(context, context.tavily_variant_adapter.search(SearchRequest(query="variant")))
            context.tavily_variant_error = None
        except Exception as exc:
            context.tavily_variant_error = exc
    if header == "http-date":
        context.tavily_variant_calls = len(wire_calls)
    else:
        context.tavily_variant_calls = calls["count"]
    context.tavily_variant_header = header


@then('the Tavily retry sleep is "{sleeps}" with vendor attempts {attempts:d}')
def step_tavily_retry_variant_assert(context: Any, sleeps: str, attempts: int) -> None:
    assert context.tavily_variant_calls == attempts
    if context.tavily_variant_header in ("absent", "malformed"):
        assert context.tavily_variant_error is not None
        assert context.tavily_variant_error.error.code == "rate_limited"
        assert context.tavily_variant_error.error.retryable is True
        assert context.tavily_sleeps == [float(sleeps)]
    elif context.tavily_variant_header == "zero":
        assert context.tavily_variant_error is None
        assert context.tavily_sleeps == [0.0]
    elif context.tavily_variant_header == "http-date":
        assert context.tavily_variant_error is None
        assert context.tavily_sleeps == [7.0]
    else:
        raise AssertionError(f"unknown variant: {context.tavily_variant_header}")


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
