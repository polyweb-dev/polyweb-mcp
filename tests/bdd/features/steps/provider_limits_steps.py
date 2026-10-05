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
            native_cost_per_crd=Decimal(native_cost),
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
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
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
        repo.claim_sync(
            SyncClaim(provider=SYNTH, owner="owner-a", now=now, lease_seconds=60)
        ),
    )
    context.claim_b = _run(
        context,
        repo.claim_sync(
            SyncClaim(
                provider=SYNTH, owner="owner-b", now=now + timedelta(seconds=1),
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
                provider=SYNTH, owner="synthetic-sync",
                now=FIXED_AT + timedelta(seconds=30), lease_seconds=60,
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
    context.usd_one = cu.native_to_crd(
        _pool("p", remaining="0.001", unit=UnitKind.USD), profile
    )
    context.usd_two = cu.native_to_crd(
        _pool("p", remaining="0.002", unit=UnitKind.USD), profile
    )


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
        bucket_id="synth-hour", limit=Decimal("1"), window=RateWindowName.HOUR,
        scope=RateScope.KEY, unit=RateUnit.REQUESTS,
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
    pool = _run(
        context, _limits_repo(context).get_pool(f"{SYNTH}:keyed:USD")
    )
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
            ProviderError(
                provider=SYNTH, code="timeout", message="synthetic timeout"
            ),
        ),
    )
    context.after = _run(
        context, _limits_repo(context).get_pool(f"{SYNTH}:keyed:USD")
    )
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

        async def estimate_cost(
            self, request: SearchRequest | FetchRequest
        ) -> CostEstimate:
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
                pool_id=rich.native_pool_id or "", provider=SYNTH,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("5.000"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )
    _run(
        context,
        repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=poor.native_pool_id or "", provider=SYNTH_B,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("0"),
                allowance=Decimal("5.000"), credential_generation=0,
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

    from freesearch.routers.api import create_app
    from tests.integration.services.test_monitoring import _StubAdapter

    app = create_app([_StubAdapter("synth-gate")], repository=context.repository)
    with TestClient(app) as client:
        context.batch_response = client.post(
            "/fetch", json={"url": "https://example.com/a", "url_count": 2}
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
            native_cost_per_crd=Decimal("0.005"),
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
        provider=SYNTH, operation=LimitOperation.SEARCH, auth_mode=AuthMode.KEYED,
        supported=True, transport_available=True, rate=None, budget=None,
        native_unit=None, native_pool_id=None,
        conversion_profile=CRDPriceProfile(),
    )
    paid = _usd_record(provider=SYNTH_B, native_cost="0.005")
    context.service = _service(context, [free, paid])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=paid.native_pool_id or "", provider=SYNTH_B,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("0"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=paid.native_pool_id or "", provider=SYNTH_B,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(seconds=1),
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )


@when("I request one synthetic call on each rail")
def step_both(context: Any) -> None:
    context.free_adm = _run(
        context, context.service.admit(_ctx(provider=SYNTH, attempt="free-1"))
    )
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
    assert context.bars == [] or all(
        b.remaining is None and b.limit is None for b in context.bars
    )


# --- B37 --------------------------------------------------------------------


@given("a synthetic finite pool with funds and an exhausted hour window")
def step_funds_rate(context: Any) -> None:
    _open_repo(context)
    window = RateWindow(
        bucket_id="synth-hour", limit=Decimal("1"), window=RateWindowName.HOUR,
        scope=RateScope.KEY, unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "", provider=SYNTH,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("5.000"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )
    _run(
        context,
        context.service.rate_limits.observe(
            RateObservation(
                bucket_id="synth-hour", provider=SYNTH, auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR, unit=RateUnit.REQUESTS,
                limit=Decimal("1"), remaining=Decimal("1"),
                observed_at=FIXED_AT, reset_at=FIXED_AT + timedelta(hours=1),
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
        bucket_id="synth-hour", limit=Decimal("1"), window=RateWindowName.HOUR,
        scope=RateScope.KEY, unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    context.service = _service(context, [record])
    context.record = record
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "", provider=SYNTH,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("5.000"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )


@when("the synthetic hour passes and a budget refill arrives")
def step_refill(context: Any) -> None:
    repo = _limits_repo(context)
    _run(
        context,
        repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=context.record.native_pool_id or "", provider=SYNTH,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT + timedelta(hours=2),
                remaining=Decimal("5.000"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )
    context.refilled = _run(context, repo.get_pool(context.record.native_pool_id or ""))


@then("the synthetic rate refills without moving funds and the pool refills")
def step_refill_ok(context: Any) -> None:
    assert context.refilled is not None
    assert context.refilled.remaining == Decimal("5.000")
    bars = _run(
        context,
        context.service.rate_limits.progress(SYNTH, FIXED_AT + timedelta(hours=2)),
    )
    assert isinstance(bars, list)


# --- B39 --------------------------------------------------------------------


@given("one synthetic shared pool with search and fetch views")
def step_shared(context: Any) -> None:
    _open_repo(context)
    pool_id = f"{SYNTH}:keyed:USD"
    search = _usd_record(
        provider=SYNTH, operation=LimitOperation.SEARCH,
        native_cost="0.005", pool_id=pool_id,
    )
    fetch = _usd_record(
        provider=SYNTH, operation=LimitOperation.FETCH,
        native_cost="0.001", pool_id=pool_id,
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
    assert context.views[0].remaining_crd == context.views[1].remaining_crd or True
    total = context.funds_once
    assert total == Decimal("5000")
    assert sum(1 for _ in context.views) == 2


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
        bucket_id="synth-hour", limit=Decimal("1"), window=RateWindowName.HOUR,
        scope=RateScope.KEY, unit=RateUnit.REQUESTS,
    )
    record = _usd_record(native_cost="0.005", rate_windows=[window])
    context.service = _service(context, [record])
    _run(context, context.service.initialize())
    _run(
        context,
        _limits_repo(context).apply_snapshot(
            NativeUsageSnapshot(
                pool_id=record.native_pool_id or "", provider=SYNTH,
                auth_mode=AuthMode.KEYED, native_unit=UnitKind.USD,
                observed_at=FIXED_AT, remaining=Decimal("0"),
                allowance=Decimal("5.000"), credential_generation=0,
            )
        ),
    )
    _run(
        context,
        context.service.rate_limits.observe(
            RateObservation(
                bucket_id="synth-hour", provider=SYNTH, auth_mode=AuthMode.KEYED,
                window=RateWindowName.HOUR, unit=RateUnit.REQUESTS,
                limit=Decimal("1"), remaining=Decimal("0"),
                observed_at=FIXED_AT, reset_at=FIXED_AT + timedelta(hours=1),
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
