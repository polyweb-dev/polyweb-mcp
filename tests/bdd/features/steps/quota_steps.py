"""Offline Behave steps for the QUOTA.md acceptance suite (features/quota.feature).

Every scenario runs against an isolated temp-file SQLite repository and
mocked HTTP transports: no live network, no production ``freesearch.db``,
and no binds to the developer-occupied ports 8000/8001.

Red-state contract: steps assert through ``getattr`` probes with AC-tagged
messages, so missing implementation fails as a clean ``AssertionError``.
Steps never construct contracts with fields that may not exist yet
(which would raise ``TypeError`` noise); gates assert field presence first.

``SEAM PROBE`` marks a tester-proposed integration seam (function/attribute
name) for behavior QUOTA.md requires but does not name. The Developer may
rename the seam; each probe is one line to update (see TEST_HANDOFF risks).
"""

import tempfile
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import SecretStr, ValidationError

import freesearch.adapters.brave as brave_module
import freesearch.adapters.firecrawl as firecrawl_module
import freesearch.adapters.keenable as keenable_module
import freesearch.adapters.parallel as parallel_module
import freesearch.adapters.youcom as youcom_module
from freesearch.adapters._youcom_support import _estimated_quota
from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter, fetch_credits
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter, extract_cost_usd, search_cost_usd
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models import contracts as contracts_module
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from freesearch.persistence.storage import LegacyUsageTotal, SQLiteRepository
from freesearch.services import monitoring as monitoring_module
from freesearch.services.monitoring import collect_stats, refresh_quotas, tracked_call
from freesearch.services.routing import select_route

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Shared scaffolding
# --------------------------------------------------------------------------


class _StaticKeyResolver:
    """Test-only secret resolver returning one fixed key for every provider."""

    def __init__(self, key: str = "quota-test-secret") -> None:
        self._key = SecretStr(key)

    def get(self, provider: ProviderName) -> SecretStr | None:
        del provider
        return self._key


class _StubAdapter(ProviderAdapter):
    """Deterministic offline adapter double for routing/poll scenarios."""

    def __init__(
        self,
        name: str,
        *,
        quota_snapshot: QuotaSnapshot | None = None,
        quota_calls: list[str] | None = None,
        fail: ProviderOperationError | None = None,
    ) -> None:
        self._name = name
        self._quota_snapshot = quota_snapshot
        self._quota_calls = quota_calls if quota_calls is not None else []
        self._fail = fail

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail is not None:
            raise self._fail
        return SearchResponse(query=request.query, provider=self._name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        if self._fail is not None:
            raise self._fail
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(url=request.url, content="", fetched_at=FIXED_AT),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

    async def quota(self) -> QuotaSnapshot | None:
        self._quota_calls.append(self._name)
        return self._quota_snapshot


def _patch_resolver(context: Any, module: Any) -> None:
    """Point ``module`` at the static test key (idempotent across scenarios)."""

    module.get_provider_secret_resolver = lambda: _StaticKeyResolver()


def _run(context: Any, coro: Awaitable[Any]) -> Any:
    """Await ``coro`` on the scenario event loop from environment.py."""

    return context.loop.run_until_complete(coro)


def _opt(target: Any, name: str, *default: Any) -> Any:
    """``getattr`` with identical semantics, routed through a variable name.

    Ruff B009 forbids ``getattr`` with a constant attribute string; the Red
    probes in this suite need dynamic-safe attribute reads that fail as clean
    ``AssertionError``s (not ``AttributeError`` tracebacks), so every probe
    goes through this shim.
    """

    if default:
        return getattr(target, name, default[0])
    return getattr(target, name)


def _refresh_or_fail(context: Any, adapters: list[Any]) -> Any:
    """Invoke the bounded quota poll seam, failing Red with its contract."""

    # SEAM PROBE (AC-1/AC-8): QUOTA.md requires a bounded TTL/on-demand polling
    # orchestrator in freesearch.monitoring that reaches record_quota.
    refresh = _opt(monitoring_module, "refresh_quotas", None)
    assert refresh is not None, (
        "AC-1: freesearch.monitoring.refresh_quotas missing — expected a bounded "
        "TTL/on-demand poll refresh_quotas(repository, adapters) that calls "
        "adapter.quota() and persists every valid result via record_quota "
        "(QUOTA.md R1/AC-1)"
    )
    try:
        return _run(context, refresh(context.repository, adapters))
    except TypeError as exc:
        raise AssertionError(
            "AC-1: refresh_quotas signature mismatch — expected "
            f"refresh_quotas(repository, adapters); saw {exc}"
        ) from exc


def _require_unit_kind_model() -> Any:
    """Gate AC-3/AC-7 steps on the QUOTA.md canonical unit contract."""

    unit_kind = _opt(contracts_module, "UnitKind", None)
    assert unit_kind is not None, (
        "AC-3: freesearch.contracts.UnitKind missing "
        "(expected REQUEST|CREDIT|USD|FREE per QUOTA.md section 2.1)"
    )
    assert "unit_kind" in UsageEvent.model_fields, (
        "AC-3: UsageEvent.unit_kind missing (Option A dual-field units)"
    )
    # NOTE: QUOTA.md section 2.1 lists display_unit on UsageEvent, but section
    # 7.3 (migration) adds display_unit only to quota_snapshots. This gate pins
    # the section 2.1 contract; flag to the Developer if 7.3 is authoritative.
    assert "display_unit" in UsageEvent.model_fields, (
        "AC-3: UsageEvent.display_unit missing (QUOTA.md section 2.1 contract)"
    )
    assert "unit_kind" in QuotaSnapshot.model_fields, (
        "AC-3: QuotaSnapshot.unit_kind missing (Option A dual-field units)"
    )
    assert "display_unit" in QuotaSnapshot.model_fields, (
        "AC-7: QuotaSnapshot.display_unit missing (human-readable label)"
    )
    return unit_kind


def _quota_names(context: Any) -> list[str]:
    return ["tavily", "you", "brave", "firecrawl", "keenable", "parallel"]


# --------------------------------------------------------------------------
# AC-1 / AC-8: repository + bounded poll scaffolding
# --------------------------------------------------------------------------


@given("an isolated quota repository")
def step_given_isolated_quota_repository(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="quota-bdd-")
    db_path = Path(context.temp_directory.name) / "quota-test.db"
    context.database_path = str(db_path)
    context.repository = _run(context, SQLiteRepository.open(db_path))
    assert Path(context.database_path).exists(), "temp quota database was not created"
    assert "freesearch.db" not in str(db_path), "must never use the production database file"
    context.quota_vendor_calls = []
    context.brave_headers = None
    context.search_response = None
    context.last_error = None
    # Isolate the module-global TTL poll cache: it is keyed by object id, so a
    # garbage-collected repository from an earlier scenario could otherwise
    # collide with this scenario's ids and poison the poll deterministically.
    poll_cache = _opt(monitoring_module, "_quota_poll_cache", None)
    if poll_cache is not None:
        poll_cache.clear()


@when("the bounded quota poll runs for every quota-capable provider")
def step_when_bounded_poll_runs(context: Any) -> None:
    adapters = [
        _StubAdapter(
            name,
            quota_snapshot=QuotaSnapshot(
                provider=name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("10"),
                limit=Decimal("100"),
                observed_at=FIXED_AT,
            ),
            quota_calls=context.quota_vendor_calls,
        )
        for name in _quota_names(context)
    ]
    context.poll_adapters = adapters
    context.poll_recorded = _refresh_or_fail(context, adapters)


@then("every valid poll result should reach record_quota")
def step_then_poll_results_recorded(context: Any) -> None:
    for name in _quota_names(context):
        latest = _run(context, context.repository.latest_quota(name))
        assert latest is not None, f"AC-1: no quota snapshot reached record_quota for {name}"
        assert latest.remaining == Decimal("10"), (
            f"AC-1: wrong remaining persisted for {name}: {latest.remaining!r}"
        )


@then("no populated provider should report an empty latest_quota")
def step_then_no_empty_latest_quota(context: Any) -> None:
    stats = _run(context, collect_stats(context.repository, adapter_names=_quota_names(context)))
    assert stats.latest_quota, "AC-1: latest_quota universally empty after bounded poll"
    providers = {snapshot.provider for snapshot in stats.latest_quota}
    assert set(_quota_names(context)) <= providers, (
        f"AC-1: populated providers missing from latest_quota: "
        f"{set(_quota_names(context)) - providers}"
    )


@then("the poll should reuse cached snapshots within its TTL instead of polling every request")
def step_then_poll_uses_ttl(context: Any) -> None:
    calls_before = list(context.quota_vendor_calls)
    _refresh_or_fail(context, context.poll_adapters)
    assert context.quota_vendor_calls == calls_before, (
        "AC-1/AC-8: second immediate poll re-hit vendors instead of reusing the "
        f"TTL cache (calls: {context.quota_vendor_calls!r})"
    )


@when("the bounded quota poll runs twice in quick succession")
def step_when_poll_runs_twice(context: Any) -> None:
    calls: list[str] = []
    adapters = [
        _StubAdapter(
            name,
            quota_snapshot=QuotaSnapshot(
                provider=name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("7"),
                limit=Decimal("50"),
                observed_at=FIXED_AT,
            ),
            quota_calls=calls,
        )
        for name in ("tavily", "firecrawl")
    ]
    context.ttl_vendor_calls = calls
    _refresh_or_fail(context, adapters)
    context.ttl_first_run_calls = list(calls)
    _refresh_or_fail(context, adapters)


@then("the vendor should be called at most once within the TTL window")
def step_then_vendor_called_once(context: Any) -> None:
    assert len(context.ttl_first_run_calls) == 2, (
        f"AC-8: first poll should call each vendor once, saw {context.ttl_first_run_calls!r}"
    )
    assert context.ttl_vendor_calls == context.ttl_first_run_calls, (
        f"AC-8: second immediate poll must not re-hit vendors (calls: {context.ttl_vendor_calls!r})"
    )


class _FailingRecordRepo:
    """Delegating repository whose record_quota raises for one provider."""

    def __init__(self, real: SQLiteRepository, failing_provider: str) -> None:
        self._real = real
        self._failing_provider = failing_provider

    async def record_quota(self, snapshot: QuotaSnapshot) -> None:
        if snapshot.provider == self._failing_provider:
            raise RuntimeError("simulated quota write outage")
        await self._real.record_quota(snapshot)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


@when("the bounded quota poll runs with a failing record_quota")
def step_when_poll_with_failing_write(context: Any) -> None:
    # T-6 (poll failure-safety): a write outage for one provider must not
    # break the poll for the rest, and routing must still work from whatever
    # state survived.
    adapters = [
        _StubAdapter(
            name,
            quota_snapshot=QuotaSnapshot(
                provider=name,
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("10"),
                limit=Decimal("100"),
                observed_at=FIXED_AT,
            ),
            quota_calls=context.quota_vendor_calls,
        )
        for name in ("tavily", "brave")
    ]
    context.failover_adapters = adapters
    flaky = _FailingRecordRepo(context.repository, "tavily")
    try:
        context.failover_snapshots = _run(context, refresh_quotas(flaky, adapters, force=True))
    except RuntimeError as exc:
        raise AssertionError(
            "AC-1/AC-8: a failing record_quota for one provider must not "
            f"abort the bounded poll (still routes from survivors): {exc}"
        ) from exc


@then("the poll should still return the healthy providers' snapshots")
def step_then_failover_snapshots(context: Any) -> None:
    providers = {snapshot.provider for snapshot in context.failover_snapshots}
    assert "brave" in providers, (
        f"AC-1/AC-8: the healthy provider's snapshot must survive a sibling "
        f"write outage, saw {providers!r}"
    )
    assert "tavily" not in providers, (
        "AC-1/AC-8 setup: the failing provider's snapshot must not be reported as persisted"
    )


@then("routing should still produce candidates from available state")
def step_then_failover_routes(context: Any) -> None:
    quota = {snapshot.provider: snapshot for snapshot in context.failover_snapshots}
    candidates = select_route(_search_request(), list(context.failover_adapters), {}, quota)
    names = _route_names(candidates)
    assert "brave" in names, (
        f"AC-6/AC-8: routing must still produce candidates from surviving "
        f"quota state after a write outage, saw {names!r}"
    )


# --------------------------------------------------------------------------
# AC-2: Brave observed comma-pair headers
# --------------------------------------------------------------------------


def _brave_payload() -> dict[str, Any]:
    return {
        "web": {
            "results": [
                {
                    "title": "Quota header result",
                    "url": "https://example.com/quota",
                    "description": "Observed quota headers.",
                    "page_age": "2026-03-01T00:00:00Z",
                }
            ]
        }
    }


@given(
    'a Brave adapter with stubbed headers "{remaining}" remaining, "{limit}" limit, "{reset}" reset'
)
def step_given_brave_stubbed_headers(context: Any, remaining: str, limit: str, reset: str) -> None:
    _patch_resolver(context, brave_module)
    headers = {
        "X-RateLimit-Remaining": remaining,
        "X-RateLimit-Limit": limit,
        "X-RateLimit-Reset": reset,
    }
    context.brave_headers = headers

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_brave_payload(), headers=headers)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.adapter = BraveAdapter(client)
    context.http_client = client


@when('I run a successful Brave search for "{query}" with limit {limit:d}')
def step_when_brave_search(context: Any, query: str, limit: int) -> None:
    request = SearchRequest(query=query, limit=limit)
    try:
        context.search_response = _run(
            context,
            tracked_call(
                context.repository,
                context.adapter,
                lambda adapter: adapter.search(request),
                operation=UsageOperation.SEARCH,
            ),
        )
    except Exception as exc:  # pragma: no cover - success path expected
        context.last_error = exc
        context.search_response = None
    assert context.last_error is None, f"AC-2: stubbed Brave search failed: {context.last_error!r}"
    assert context.search_response is not None, "AC-2: stubbed Brave search returned nothing"


@then(
    "the Brave snapshot should be OBSERVED monthly REQUEST quota "
    "with remaining {remaining:d} limit {limit:d}"
)
def step_then_brave_snapshot_monthly(context: Any, remaining: int, limit: int) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, (
        "AC-2: no Brave quota snapshot recorded after a successful search "
        "(record_quota must be piggybacked on the success path)"
    )
    assert latest.source == QuotaSource.OBSERVED, (
        f"AC-2: Brave snapshot must be OBSERVED, saw {latest.source!r}"
    )
    assert _opt(latest, "unit_kind", None) is not None and str(
        _opt(latest, "unit_kind")
    ).upper().endswith("REQUEST"), (
        f"AC-2: Brave snapshot unit_kind must be REQUEST, saw {_opt(latest, 'unit_kind', None)!r}"
    )
    assert latest.remaining == Decimal(remaining), (
        f"AC-2: remaining must be Decimal({remaining}) from the monthly header "
        f"element, saw {latest.remaining!r} (type {type(latest.remaining).__name__})"
    )
    assert isinstance(latest.remaining, Decimal), "AC-2: quota values must stay Decimal-exact"
    assert latest.limit == Decimal(limit), (
        f"AC-2: limit must be Decimal({limit}) from the monthly header element, "
        f"saw {latest.limit!r}"
    )
    display = _opt(latest, "display_unit", None)
    assert display == "requests", f"AC-2: Brave display_unit must be 'requests', saw {display!r}"
    assert _opt(latest, "window", None) == "monthly", (
        f"AC-2: Brave quota must identify its monthly window, saw {_opt(latest, 'window', None)!r}"
    )


@then("the Brave snapshot reset should be about {seconds:d} seconds after observation")
def step_then_brave_reset(context: Any, seconds: int) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, "AC-2: no Brave quota snapshot recorded"
    assert latest.reset_at is not None, (
        "AC-2: reset_at must come from the monthly X-RateLimit-Reset element"
    )
    delta = (latest.reset_at - latest.observed_at).total_seconds()
    assert abs(delta - seconds) <= 120, (
        f"AC-2: reset_at must be ~{seconds}s after observed_at, saw delta {delta}s"
    )


@then("the Brave usage event should carry unit kind REQUEST")
def step_then_brave_usage_kind(context: Any) -> None:
    usage = context.search_response.usage
    assert usage is not None, "AC-2: Brave search must report a usage event"
    assert usage.units == Decimal("1"), f"AC-2: Brave usage must be 1 query, saw {usage.units!r}"
    assert _opt(usage, "unit_kind", None) is not None and str(
        _opt(usage, "unit_kind")
    ).upper().endswith("REQUEST"), (
        f"AC-2: Brave usage unit_kind must be REQUEST, saw {_opt(usage, 'unit_kind', None)!r}"
    )


@then('the Brave snapshot monthly field "{field}" should be unknown rather than zero')
def step_then_brave_field_unknown(context: Any, field: str) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, (
        f"AC-2: expected a Brave snapshot with {field}=None after a successful "
        "search; no snapshot was recorded at all"
    )
    # T-1: the Gherkin field "reset" names the X-RateLimit-Reset monthly
    # element, which the snapshot exposes as reset_at.
    by_name = {
        "remaining": latest.remaining,
        "limit": latest.limit,
        "reset": latest.reset_at,
        "reset_at": latest.reset_at,
    }
    assert field in by_name, f"AC-2 setup: unknown monthly field {field!r}"
    value = by_name[field]
    assert value is None, (
        f"AC-2: malformed/absent monthly {field} must become None, never 0 (saw {value!r})"
    )


# --------------------------------------------------------------------------
# Brave derived USD spend (manual dashboard math, no scraping)
# --------------------------------------------------------------------------


@when("I record {count:d} successful Brave REQUEST searches")
def step_when_record_brave_successes(context: Any, count: int) -> None:
    unit_kind = _require_unit_kind_model()
    assert count >= 0, f"Brave success count must be non-negative, saw {count}"
    base = FIXED_AT
    for index in range(count):
        event = UsageEvent(
            provider="brave",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=base + timedelta(seconds=index),
            status=UsageStatus.SUCCESS,
            unit_kind=_opt(unit_kind, "REQUEST"),
            display_unit="requests",
        )
        _run(context, context.repository.record_usage(event))


@then(
    "collect_stats Brave quota should show spend USD {spend} of allowance USD "
    "{allowance} at cost USD {cost} per request"
)
def step_then_brave_spend_projection(context: Any, spend: str, allowance: str, cost: str) -> None:
    expected_spend = Decimal(spend)
    expected_allowance = Decimal(allowance)
    expected_cost = Decimal(cost)
    stats = _run(context, collect_stats(context.repository, adapter_names=["brave"]))
    rows = [snap for snap in stats.latest_quota if snap.provider == "brave"]
    assert rows, "dashboard must include a Brave quota row after recorded successes"
    view = rows[0]
    assert view.remaining is None and view.limit is None, (
        "unlimited Brave throttle must stay None/None alongside spend metadata, saw "
        f"{view.remaining!r}/{view.limit!r}"
    )
    assert view.remaining_percent is None, (
        f"Brave remaining_percent must stay None (no invented denominator), saw {view!r}"
    )
    metadata = dict(_opt(view, "metadata", None) or {})
    assert metadata.get("spend_usd") == expected_spend, (
        f"176 Brave REQUEST successes must project spend USD {spend}, saw {metadata!r}"
    )
    assert isinstance(metadata.get("spend_usd"), Decimal), (
        "spend metadata must stay Decimal-exact, never float"
    )
    assert metadata.get("allowance_usd") == expected_allowance, (
        f"allowance must be USD {allowance}, saw {metadata!r}"
    )
    assert metadata.get("cost_per_req") == expected_cost, (
        f"cost_per_req must be USD {cost}, saw {metadata!r}"
    )


@then("the Brave usage event should carry per-second headroom {headroom:d}")
def step_then_brave_per_second_headroom(context: Any, headroom: int) -> None:
    usage = context.search_response.usage
    assert usage is not None, "Brave search must report a usage event"
    assert usage.metadata.get("rate_limit_remaining") == headroom, (
        f"usage must carry per-second headroom {headroom}, saw {usage.metadata!r}"
    )
    assert type(usage.metadata.get("rate_limit_remaining")) is int, (
        "per-second headroom must be an int, never float"
    )


# --------------------------------------------------------------------------
# AC-3: safe aggregation by (provider, operation, unit_kind)
# --------------------------------------------------------------------------


@given("usage events with incompatible dimensions recorded")
def step_given_incompatible_usage(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    at = FIXED_AT
    events = [
        # Brave request count vs Exa USD: same numeric scale, different dimensions.
        {"provider": "brave", "op": UsageOperation.SEARCH, "units": "1", "kind": "REQUEST"},
        {"provider": "brave", "op": UsageOperation.SEARCH, "units": "1", "kind": "REQUEST"},
        {"provider": "exa", "op": UsageOperation.SEARCH, "units": "0.001", "kind": "USD"},
        {"provider": "tavily", "op": UsageOperation.SEARCH, "units": "1", "kind": "CREDIT"},
        {"provider": "tavily", "op": UsageOperation.FETCH, "units": "0.2", "kind": "CREDIT"},
    ]
    for index, spec in enumerate(events):
        event = UsageEvent(
            provider=spec["provider"],
            operation=spec["op"],
            units=Decimal(str(spec["units"])),
            observed_at=at + timedelta(seconds=index),
            unit_kind=_opt(unit_kind, str(spec["kind"])),
            display_unit=str(spec["kind"]).lower(),
        )
        _run(context, context.repository.record_usage(event))
    # Zero-unit FAILURE rows: observability only, never totals.
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("0"),
                observed_at=at + timedelta(seconds=99),
                status=UsageStatus.FAILURE,
                unit_kind=_opt(unit_kind, "REQUEST"),
                display_unit="requests",
            )
        ),
    )


@when("I read usage totals")
def step_when_read_totals(context: Any) -> None:
    context.totals = _run(context, context.repository.usage_totals())


@then("totals should group by provider, operation, and unit kind without cross-kind sums")
def step_then_totals_grouped(context: Any) -> None:
    totals = context.totals
    assert all(hasattr(total, "unit_kind") for total in totals), (
        "AC-3: usage_totals must group by (provider, operation, unit_kind); "
        "UsageTotal carries no unit_kind dimension"
    )
    by_key = {
        (total.provider, str(total.operation), str(_opt(total, "unit_kind"))): total
        for total in totals
    }
    brave = by_key.get(("brave", "search", "REQUEST"))
    assert brave is not None, f"AC-3: missing (brave, search, REQUEST) total: {totals!r}"
    assert brave.total_units == Decimal("2"), (
        f"AC-3: (brave, search, REQUEST) must total Decimal('2'), saw {brave.total_units!r}"
    )
    assert brave.event_count == 2, (
        f"AC-3: (brave, search, REQUEST) must count 2 events, saw {brave.event_count}"
    )
    exa = by_key.get(("exa", "search", "USD"))
    assert exa is not None and exa.total_units == Decimal("0.001"), (
        f"AC-3: (exa, search, USD) must total Decimal('0.001') exactly, saw {totals!r}"
    )
    # The 1-vs-0.001 trap: no total may ever merge REQUEST with USD/CREDIT.
    for total in totals:
        assert total.total_units == Decimal(str(total.total_units)), (
            "AC-3: totals must stay Decimal-exact (no float casts)"
        )
    assert len(totals) == 4, (
        f"AC-3: expected 4 dimensional totals "
        f"(brave/search/REQUEST, exa/search/USD, tavily/search/CREDIT, "
        f"tavily/fetch/CREDIT), saw {len(totals)}: {totals!r}"
    )


@then("zero-unit FAILURE rows should be excluded from totals")
def step_then_failures_excluded(context: Any) -> None:
    totals = context.totals
    brave = next(
        total
        for total in totals
        if total.provider == "brave" and total.operation == UsageOperation.SEARCH
    )
    assert brave.event_count == 2, (
        "AC-3: zero-unit FAILURE rows must be excluded from usage totals "
        f"(brave search counted {brave.event_count}, expected 2)"
    )
    assert brave.total_units == Decimal("2"), (
        "AC-3: FAILURE zeros must not leak into totals "
        f"(brave search total {brave.total_units!r}, expected Decimal('2'))"
    )


# --------------------------------------------------------------------------
# AC-4: Tavily authoritative + You.com estimated
# --------------------------------------------------------------------------


@when(
    "I record an authoritative Tavily credit snapshot with remaining {remaining:d} limit {limit:d}"
)
def step_when_record_tavily(context: Any, remaining: int, limit: int) -> None:
    _require_unit_kind_model()
    unit_kind = _opt(contracts_module, "UnitKind")
    context.tavily_snapshot = QuotaSnapshot(
        provider="tavily",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal(remaining),
        limit=Decimal(limit),
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "CREDIT"),
        display_unit="credits",
    )
    _run(context, context.repository.record_quota(context.tavily_snapshot))
    context.tavily_usage = UsageEvent(
        provider="tavily",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "CREDIT"),
        display_unit="credits",
    )
    _run(context, context.repository.record_usage(context.tavily_usage))


@then(
    'the Tavily snapshot should expose unit kind {kind} with display unit "{display}" '
    "and source AUTHORITATIVE"
)
def step_then_tavily_snapshot(context: Any, kind: str, display: str) -> None:
    latest = _run(context, context.repository.latest_quota("tavily"))
    assert latest is not None, "AC-4: Tavily snapshot missing after record_quota"
    assert str(_opt(latest, "unit_kind", None)).upper().endswith(kind), (
        f"AC-4: Tavily unit_kind must be {kind}, saw {_opt(latest, 'unit_kind', None)!r}"
    )
    assert _opt(latest, "display_unit", None) == display, (
        f"AC-4: Tavily display_unit must be {display!r}, saw {_opt(latest, 'display_unit', None)!r}"
    )
    assert latest.source == QuotaSource.AUTHORITATIVE, (
        f"AC-4: Tavily source must stay AUTHORITATIVE (GET /usage), saw {latest.source!r}"
    )
    assert latest.remaining == Decimal("42") and latest.limit == Decimal("1000"), (
        f"AC-4: Tavily authoritative values must round-trip exactly, saw "
        f"{latest.remaining!r}/{latest.limit!r}"
    )


@then("the Tavily usage event should carry unit kind {kind}")
def step_then_tavily_usage_kind(context: Any, kind: str) -> None:
    assert str(_opt(context.tavily_usage, "unit_kind", None)).upper().endswith(kind), (
        f"AC-4: Tavily usage unit_kind must be {kind}, "
        f"saw {_opt(context.tavily_usage, 'unit_kind', None)!r}"
    )


@when("I convert You.com balance {balance:d} cents")
def step_when_youcom_convert(context: Any, balance: int) -> None:
    payload = {"data": {"attributes": {"balance": balance}}}
    context.youcom_snapshot = _estimated_quota(payload, "you")
    context.youcom_balance_cents = balance
    _run(context, context.repository.record_quota(context.youcom_snapshot))


@then(
    "the remaining balance should be USD {balance_usd} with {search:d} search calls "
    "and {fetch:d} fetch calls, limit unknown"
)
def step_then_youcom_calls(context: Any, balance_usd: str, search: int, fetch: int) -> None:
    # T-4 (pairs with D-1): the snapshot persists the authoritative monetary
    # balance as remaining in USD; search/fetch call counts are derived
    # equivalents carried alongside, never a second spendable pool.
    snapshot = context.youcom_snapshot
    assert snapshot.source == QuotaSource.ESTIMATED, (
        f"AC-4: You.com snapshots must be ESTIMATED, saw {snapshot.source!r}"
    )
    assert snapshot.limit is None, (
        f"AC-4: You.com limit must stay None (no vendor plan limit), saw {snapshot.limit!r}"
    )
    expected_usd = Decimal(balance_usd)
    assert snapshot.remaining == expected_usd, (
        f"AC-4: balance {context.youcom_balance_cents}c must persist as "
        f"remaining USD {expected_usd} (dollar balance is the truth), "
        f"saw {snapshot.remaining!r}"
    )
    assert isinstance(snapshot.remaining, Decimal), "AC-4: the balance must stay Decimal-exact"
    assert str(_opt(snapshot, "unit_kind", None)).upper().endswith("USD"), (
        "AC-4: You.com remaining is money, so unit_kind must be USD "
        f"(saw {_opt(snapshot, 'unit_kind', None)!r})"
    )
    exposed = dict(_opt(snapshot, "metadata", None) or {})
    assert exposed.get("search_calls") == Decimal(search), (
        f"AC-4: metadata must carry the floored search-call equivalent "
        f"(floor(balance_usd / 0.005) = {search}), saw {exposed!r}"
    )
    assert exposed.get("fetch_calls") == Decimal(fetch), (
        f"AC-4: metadata must carry the floored fetch-call equivalent "
        f"(floor(balance_usd / 0.001) = {fetch}), saw {exposed!r}"
    )


@when("I record a You.com response with missing usage")
def step_when_youcom_missing_usage(context: Any) -> None:
    _patch_resolver(context, youcom_module)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": {"web": [{"title": "t", "url": "https://example.com/x"}]}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    adapter = YoucomAdapter(client)
    context.http_client = client
    context.you_adapter = adapter
    response = _run(context, adapter.search(SearchRequest(query="gap probe", limit=3)))
    assert response.usage is None, (
        "AC-4 setup: expected the You.com response to omit usage "
        f"(saw {response.usage!r}); the gap scenario needs a usage-less response"
    )
    context.you_missing_response = response


@then("the event should be marked metering-unavailable rather than known-zero USD")
def step_then_youcom_gap_marked(context: Any) -> None:
    response = context.you_missing_response
    # A usage-less You.com response must surface an explicit
    # metering-unavailable/estimated marker (usage_gap with a documented local
    # estimate), never a silent known zero.
    gap = _opt(response, "usage_gap", None)
    if gap is None:
        estimate = _run(
            context, context.you_adapter.estimate_cost(SearchRequest(query="gap probe", limit=3))
        )
        assert estimate.units == Decimal("0.005") and estimate.currency == "USD", (
            "AC-4 setup: You.com search estimate must be USD 0.005 "
            f"(saw {estimate.units!r} {estimate.currency!r})"
        )
    assert isinstance(gap, dict), (
        "AC-4: You.com responses omitting usage must expose an explicit "
        "metering-unavailable marker (usage_gap dict) or documented local "
        "estimate; recording a silent known-zero USD invents metering"
    )
    assert gap.get("units") != Decimal("0") or gap.get("estimated"), (
        "AC-4: the gap marker must be distinguishable from a metered zero"
    )


@then("usage_gap should stay off the wire")
def step_then_usage_gap_off_wire(context: Any) -> None:
    # Critic caveat: usage_gap is an in-memory telemetry marker only. It must
    # never leak into serialized payloads served over the API/MCP surface.
    payload = context.you_missing_response.model_dump(mode="json")
    assert "usage_gap" not in payload, (
        f"AC-4/AC-8: usage_gap must stay off the wire (in-memory marker only), "
        f"saw keys {sorted(payload)!r}"
    )


# --------------------------------------------------------------------------
# AC-5: Keenable + Parallel local counters
# --------------------------------------------------------------------------


def _keenable_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search") or request.url.path.endswith("/search/public"):
        return httpx.Response(
            200, json={"results": [{"title": "k", "url": "https://example.com/k"}]}
        )
    return httpx.Response(200, json={"content": "keenable doc", "title": "k"})


@when("I apply {count:d} paid-false Keenable calls against the {allowance:d} monthly allowance")
def step_when_keenable_paid_false(context: Any, count: int, allowance: int) -> None:
    _patch_resolver(context, keenable_module)
    context.keenable_paid_meta = None

    def handler(request: httpx.Request) -> httpx.Response:
        # Keyed search endpoint; serves a paid usage detail once the scenario
        # arms keenable_paid_meta for the T-2 paid-true call below.
        assert request.url.path.endswith("/search"), (
            f"AC-5 setup: expected a keyed search request, saw {request.url.path!r}"
        )
        payload: dict[str, Any] = {"results": [{"title": "k", "url": "https://example.com/k"}]}
        if context.keenable_paid_meta is not None:
            payload["_meta"] = {"keenable/usage": context.keenable_paid_meta}
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.http_client = client
    context.keenable_adapter = KeenableAdapter(client)
    for _ in range(count):
        _run(
            context,
            tracked_call(
                context.repository,
                context.keenable_adapter,
                lambda adapter: adapter.search(SearchRequest(query="allowance", limit=3)),
                operation=UsageOperation.SEARCH,
            ),
        )
    context.keenable_allowance = Decimal(allowance)


@then("the Keenable remaining should be {remaining:d} of {limit:d}")
def step_then_keenable_remaining(context: Any, remaining: int, limit: int) -> None:
    latest = _run(context, context.repository.latest_quota("keenable"))
    assert latest is not None, (
        "AC-5: no Keenable keyed-allowance snapshot recorded after paid-false calls "
        "(local OBSERVED counter must reach record_quota)"
    )
    assert latest.limit == Decimal(limit), (
        f"AC-5: Keenable allowance limit must be Decimal({limit}), saw {latest.limit!r}"
    )
    assert latest.remaining == Decimal(remaining), (
        f"AC-5: Keenable remaining must be max(0, {limit} - spend) = {remaining}, "
        f"saw {latest.remaining!r}"
    )
    assert latest.remaining <= Decimal(limit), "AC-5: remaining must never exceed the allowance"


@then("a paid-true Keenable call should preserve the free allowance separately")
def step_then_keenable_paid_true(context: Any) -> None:
    # T-2: drive a REAL paid call through the same keyed adapter (its free
    # spend is already 3 from the paid-false calls above). Purchased usage must
    # not decrement the free allowance; the combined remaining becomes unknown
    # (None) with both counters preserved (D-2).
    context.keenable_paid_meta = {"credits": 2, "paid": True, "sku": "search.pro"}
    adapter = context.keenable_adapter
    response = _run(
        context,
        tracked_call(
            context.repository,
            adapter,
            lambda running: running.search(SearchRequest(query="paid tier", limit=2)),
            operation=UsageOperation.SEARCH,
        ),
    )
    assert response.usage is not None and response.usage.units == Decimal("2"), (
        f"AC-5 setup: paid call must report 2 credits of usage, saw {response.usage!r}"
    )
    assert response.usage.metadata.get("paid") is True, (
        f"AC-5 setup: paid usage must carry paid=true, saw {response.usage.metadata!r}"
    )
    # Behavioral assertion through the public API only (critic caveat: quota
    # metadata has no approved storage column, so assert persisted remaining
    # plus in-memory counter preservation, never private columns).
    latest = _run(context, context.repository.latest_quota("keenable"))
    assert latest is not None, "AC-5 setup: expected a persisted Keenable snapshot"
    assert latest.remaining is None, (
        f"AC-5: after paid usage the combined free remaining must be unknown "
        f"(None), saw {latest.remaining!r}"
    )
    assert latest.limit == Decimal("100000"), (
        f"AC-5: the allowance limit must survive paid usage, saw {latest.limit!r}"
    )
    live = _run(context, adapter.quota())
    assert live is not None and live.remaining is None, (
        "AC-5: live quota view must agree the combined remaining is unknown"
    )
    assert live.metadata.get("free") == Decimal("99997"), (
        "AC-5: the 3 free credits spent earlier must be preserved separately "
        f"(free counter), saw {live.metadata!r}"
    )
    assert live.metadata.get("paid") == Decimal("2"), (
        f"AC-5: paid counter must be preserved separately, saw {live.metadata!r}"
    )


@then("a keyless Keenable call should record one REQUEST unit and an hourly snapshot")
def step_then_keenable_keyless(context: Any) -> None:
    _require_unit_kind_model()
    keenable_module.get_provider_secret_resolver = lambda: _NullKeyResolver()
    try:
        client = httpx.AsyncClient(transport=httpx.MockTransport(_keenable_handler), timeout=30.0)
        adapter = KeenableAdapter(client)
        response = _run(context, adapter.search(SearchRequest(query="keyless", limit=2)))
    finally:
        _patch_resolver(context, keenable_module)
    assert response.usage is not None and response.usage.units == Decimal("1"), (
        f"AC-5: keyless usage must consume one hourly request unit, saw {response.usage!r}"
    )
    assert str(_opt(response.usage, "unit_kind", None)).upper().endswith("REQUEST"), (
        "AC-5: keyless usage unit_kind must be REQUEST "
        f"(saw {_opt(response.usage, 'unit_kind', None)!r})"
    )
    assert response.usage.metadata.get("cost_usd") == Decimal("0"), (
        "AC-5: keyless usage should expose zero monetary cost separately"
    )
    snapshot = _opt(response, "quota_snapshot", None)
    assert snapshot is not None, "AC-5: keyless call must expose rolling-hour quota state"
    assert snapshot.remaining == Decimal("999") and snapshot.limit == Decimal("1000"), (
        f"AC-5: expected local hourly headroom 999/1000, saw {snapshot!r}"
    )
    assert snapshot.metadata.get("window") == "hourly", (
        "AC-5: keyless quota should identify its rolling hourly window"
    )


class _NullKeyResolver:
    """Resolver reporting no stored key, selecting Keenable keyless mode."""

    def get(self, provider: ProviderName) -> SecretStr | None:
        del provider
        return None


@when("I estimate cost for a Keenable search")
def step_when_keenable_estimate(context: Any) -> None:
    _patch_resolver(context, keenable_module)
    client = httpx.AsyncClient(transport=httpx.MockTransport(_keenable_handler), timeout=30.0)
    context.http_client = client
    context.keenable_estimate = _run(
        context, KeenableAdapter(client).estimate_cost(SearchRequest(query="price", limit=3))
    )


@then("the Keenable estimate should be USD {amount}")
def step_then_keenable_estimate(context: Any, amount: str) -> None:
    estimate = context.keenable_estimate
    assert estimate.units == Decimal(amount), (
        f"AC-5: keyed Keenable estimate must be USD {amount} "
        f"(~$4/1k cloud price), saw {estimate.units!r}"
    )
    assert estimate.currency == "USD", (
        f"AC-5: Keenable estimate currency must be USD, saw {estimate.currency!r}"
    )


@when('I estimate Parallel search in "{mode}" mode with {bundles:d} extra bundles')
def step_when_parallel_search_estimate(context: Any, mode: str, bundles: int) -> None:
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    context.http_client = client
    context.parallel_adapter = ParallelAdapter(client)
    context.parallel_mode = mode
    context.parallel_bundles = bundles
    # T-5: drive estimate_cost with the mode-aware request contract (P1-6) and
    # cross-check against the documented pricing function directly, so the
    # estimate provably equals the executed-search price for these options.
    try:
        request = SearchRequest(query="mode probe", limit=5, mode=mode, extra_bundles=bundles)
    except ValidationError as exc:
        raise AssertionError(
            "AC-PA-2: SearchRequest lacks the mode-aware estimate contract "
            "(P1-6: mode/extra_bundles fields); mode-aware pricing cannot be "
            f"driven through estimate_cost: {exc}"
        ) from exc
    context.parallel_request = request
    context.parallel_search_estimate = _run(
        context, context.parallel_adapter.estimate_cost(request)
    )


def _parallel_search_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "search_id": "ps-1",
            "results": [
                {
                    "url": "https://example.com/p",
                    "title": "p",
                    "excerpts": ["e"],
                }
            ],
            "usage": [{"sku": "sku_search", "count": 1}],
        },
    )


@then("the Parallel search estimate should be USD {amount}")
def step_then_parallel_search_estimate(context: Any, amount: str) -> None:
    estimate = context.parallel_search_estimate
    direct = search_cost_usd(context.parallel_mode, context.parallel_bundles)
    assert direct == Decimal(amount), (
        f"AC-PA-2 setup: search_cost_usd({context.parallel_mode!r}, "
        f"{context.parallel_bundles}) must price USD {amount}, test table says {direct!r}"
    )
    assert estimate.units == direct, (
        f"AC-PA-2: estimate_cost must equal the documented search price for "
        f"mode={context.parallel_mode!r} bundles={context.parallel_bundles} "
        f"(USD {amount}), saw {estimate.units!r}"
    )
    assert estimate.currency == "USD", (
        f"AC-PA-2: Parallel estimates must be Decimal USD, saw {estimate.currency!r}"
    )
    assert isinstance(estimate.units, Decimal), "AC-PA-2: Parallel pricing must avoid float"


@when("I estimate Parallel search with omitted mode and {bundles:d} extra bundles")
def step_when_parallel_omitted_mode(context: Any, bundles: int) -> None:
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    context.http_client = client
    context.parallel_adapter = ParallelAdapter(client)
    context.parallel_mode = "omitted"
    context.parallel_bundles = bundles
    # Omitted mode defaults to advanced per the OpenAPI default.
    try:
        request = SearchRequest(query="mode probe", limit=5, mode=None, extra_bundles=bundles)
    except ValidationError as exc:
        raise AssertionError(
            "AC-PA-2: SearchRequest lacks the mode-aware estimate contract "
            f"(P1-6: mode/extra_bundles fields): {exc}"
        ) from exc
    context.parallel_request = request
    context.parallel_search_estimate = _run(
        context, context.parallel_adapter.estimate_cost(request)
    )


@when("I estimate Parallel extract for {urls:d} urls")
def step_when_parallel_extract_estimate(context: Any, urls: int) -> None:
    # T-3: pass url_count through the FetchRequest contract. Batches above one
    # URL are projection-only until batch fetch exists; the executable path is
    # always the single URL (see the single-URL step below).
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    context.http_client = client
    context.parallel_adapter = ParallelAdapter(client)
    estimate = _run(
        context,
        context.parallel_adapter.estimate_cost(
            FetchRequest(url="https://example.com/extract", url_count=urls)
        ),
    )
    context.parallel_extract_estimate = estimate
    context.parallel_extract_urls = urls


@then("the Parallel extract estimate should be USD {amount} as a projection-only batch price")
def step_then_parallel_extract_projection(context: Any, amount: str) -> None:
    estimate = context.parallel_extract_estimate
    direct = extract_cost_usd(context.parallel_extract_urls)
    assert direct == Decimal(amount), (
        f"AC-PA-2 setup: extract_cost_usd({context.parallel_extract_urls}) must "
        f"price USD {amount}, pricing function says {direct!r}"
    )
    assert estimate.units == direct, (
        f"AC-PA-2: estimate_cost must equal the documented extract price for "
        f"url_count={context.parallel_extract_urls} (USD {amount}), saw {estimate.units!r}"
    )
    assert estimate.currency == "USD", (
        f"AC-PA-2: Parallel extract must be Decimal USD, saw {estimate.currency!r}"
    )
    assert isinstance(estimate.units, Decimal), "AC-PA-2: Parallel pricing must avoid float"
    # NOTE: url_count > 1 is projection-only until a batch fetch path exists;
    # the executable path is asserted single-URL in the next step.


@then("the executable single-URL extract estimate should be USD {amount}")
def step_then_parallel_extract_single(context: Any, amount: str) -> None:
    # Critic caveat: the only executable extract path prices exactly one URL.
    estimate = _run(
        context,
        context.parallel_adapter.estimate_cost(FetchRequest(url="https://example.com/extract")),
    )
    assert estimate.units == Decimal(amount), (
        f"AC-PA-2: the executable single-URL extract must cost USD {amount}, saw {estimate.units!r}"
    )
    assert estimate.currency == "USD", (
        f"AC-PA-2: Parallel extract must be Decimal USD, saw {estimate.currency!r}"
    )


# --------------------------------------------------------------------------
# AC-6: routing semantics
# --------------------------------------------------------------------------


def _search_request() -> SearchRequest:
    return SearchRequest(query="routing probe", limit=5)


def _route_names(candidates: Any) -> list[str]:
    return [candidate.adapter.name for candidate in candidates]


@when("I route a search with a hard-exhausted provider and healthy fallback")
def step_when_route_hard_exhausted(context: Any) -> None:
    exhausted = _StubAdapter("tavily")
    fallback = _StubAdapter("brave")
    quota = {
        "tavily": QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("0"),
            limit=Decimal("1000"),
            observed_at=FIXED_AT,
        )
    }
    health = {
        "tavily": ProviderHealth(
            provider="tavily", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        ),
        "brave": ProviderHealth(provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT),
    }
    context.route_hard = select_route(_search_request(), [exhausted, fallback], health, quota)


@then("the hard-exhausted provider should be excluded from candidates")
def step_then_hard_excluded(context: Any) -> None:
    names = _route_names(context.route_hard)
    assert "tavily" not in names, (
        f"AC-6: hard exhaustion (remaining=0 AUTHORITATIVE) must steer routing "
        f"away, but tavily stayed eligible: {names!r}"
    )
    assert names and names[0] == "brave", (
        f"AC-6: healthy fallback must lead after hard exclusion, saw {names!r}"
    )


@when("the Parallel soft zero is followed by a successful billed operation")
def step_when_parallel_soft_then_success(context: Any) -> None:
    # SEAM PROBE (AC-6/AC-PA-5): soft 402 signals must expire on later success.
    # effective_quota resolves the routable view: raw latest may hold the soft
    # zero while the provider is already healthy again.
    effective = _opt(monitoring_module, "effective_quota", None)
    assert effective is not None, (
        "AC-6: freesearch.monitoring.effective_quota missing — routing needs an "
        "effective-quota view where a Parallel soft 402 zero expires after the "
        "next successful billed operation (QUOTA.md AC-6/AC-PA-5)"
    )
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("0"),
                limit=None,
                observed_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal("2"),
                observed_at=FIXED_AT + timedelta(seconds=60),
                status=UsageStatus.SUCCESS,
            )
        ),
    )
    context.parallel_effective = _run(context, effective(context.repository, "parallel"))


@then("the Parallel provider should be eligible again")
def step_then_parallel_eligible(context: Any) -> None:
    effective = context.parallel_effective
    adapter = _StubAdapter("parallel")
    health = {
        "parallel": ProviderHealth(
            provider="parallel", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        )
    }
    quota = {} if effective is None else {"parallel": effective}
    candidates = select_route(_search_request(), [adapter], health, quota)
    assert _route_names(candidates) == ["parallel"], (
        "AC-6/AC-PA-5: Parallel soft zero must clear after later billed success; "
        f"provider still excluded (effective={effective!r})"
    )


@when("a provider reports a 429 rate signal")
def step_when_429_signal(context: Any) -> None:
    failure = ProviderOperationError(
        ProviderError(
            provider="brave",
            code="rate_limited",
            message="HTTP 429",
            retryable=True,
            status_code=429,
        )
    )
    adapter = _StubAdapter("brave", fail=failure)
    try:
        _run(
            context,
            tracked_call(
                context.repository,
                adapter,
                lambda running: running.search(_search_request()),
                operation=UsageOperation.SEARCH,
            ),
        )
    except ProviderOperationError as exc:
        context.rate_error = exc
    assert context.rate_error.error.retryable is True, (
        "AC-6 setup: the 429 signal must stay retryable/transient"
    )
    assert context.rate_error.error.status_code == 429, "AC-6 setup: expected status 429"


@then("the 429 should never become quota exhaustion")
def step_then_429_not_exhaustion(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is None or latest.remaining != Decimal("0"), (
        f"AC-6: a 429 must never be persisted as quota exhaustion (remaining=0); saw {latest!r}"
    )
    adapter = _StubAdapter("brave")
    health = {
        "brave": ProviderHealth(provider="brave", status=HealthStatus.DEGRADED, checked_at=FIXED_AT)
    }
    quota = {} if latest is None else {"brave": latest}
    candidates = select_route(_search_request(), [adapter], health, quota)
    assert "brave" in _route_names(candidates), (
        "AC-6: a transient 429 must not exclude the provider from routing"
    )


@when("a provider has no quota snapshot at all")
def step_when_no_quota_snapshot(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("mystery"))
    assert latest is None, "AC-6 setup: expected no snapshot for an unknown provider"
    context.unknown_provider = "mystery"


@then("unknown quota should stay eligible and never masquerade as zero")
def step_then_unknown_eligible(context: Any) -> None:
    adapter = _StubAdapter(context.unknown_provider)
    health = {
        context.unknown_provider: ProviderHealth(
            provider=context.unknown_provider,
            status=HealthStatus.UNKNOWN,
            checked_at=FIXED_AT,
        )
    }
    candidates = select_route(_search_request(), [adapter], health, {})
    assert _route_names(candidates) == [context.unknown_provider], (
        "AC-6: empty/unknown quota must stay eligible (never treated as 0)"
    )


# --------------------------------------------------------------------------
# AC-7: serialization honesty
# --------------------------------------------------------------------------


@when("I serialize a quota snapshot and a usage event with canonical units")
def step_when_serialize_canonical(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    context.serialized_quota = QuotaSnapshot(
        provider="firecrawl",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal("250"),
        limit=Decimal("100"),
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "CREDIT"),
        display_unit="credits",
    ).model_dump(mode="json")
    context.serialized_usage = UsageEvent(
        provider="firecrawl",
        operation=UsageOperation.SEARCH,
        units=Decimal("2"),
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "CREDIT"),
        display_unit="credits",
    ).model_dump(mode="json")


@then("the serialized quota should expose unit_kind, display_unit, and source")
def step_then_quota_serialized(context: Any) -> None:
    payload = context.serialized_quota
    assert payload.get("unit_kind") == "CREDIT", (
        f"AC-7: serialized quota must expose unit_kind=CREDIT, saw {payload!r}"
    )
    assert payload.get("display_unit") == "credits", (
        f"AC-7: serialized quota must expose display_unit='credits', saw {payload!r}"
    )
    assert payload.get("source") == "authoritative", (
        f"AC-7: serialized quota must expose source confidence, saw {payload!r}"
    )


@then("the serialized usage should expose unit_kind and display_unit")
def step_then_usage_serialized(context: Any) -> None:
    payload = context.serialized_usage
    assert payload.get("unit_kind") == "CREDIT", (
        f"AC-7: serialized usage must expose unit_kind=CREDIT, saw {payload!r}"
    )
    assert payload.get("display_unit") == "credits", (
        f"AC-7: serialized usage must expose display_unit='credits', saw {payload!r}"
    )


# --------------------------------------------------------------------------
# AC-8: compatibility + privacy
# --------------------------------------------------------------------------


@when("I record legacy usage and quota rows without unit kinds")
def step_when_record_legacy(context: Any) -> None:
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.001"),
                observed_at=FIXED_AT,
            )
        ),
    )
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="tavily",
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("5"),
                limit=Decimal("100"),
                observed_at=FIXED_AT,
            )
        ),
    )


@then("legacy rows should read back with unknown unit kind and stay out of known-kind totals")
def step_then_legacy_unknown(context: Any) -> None:
    events = _run(context, context.repository.list_usage(provider="exa"))
    assert len(events) == 1 and events[0].units == Decimal("0.001"), (
        f"AC-8: legacy usage rows must remain readable with exact units, saw {events!r}"
    )
    assert _opt(events[0], "unit_kind", None) is None, (
        "AC-8: legacy rows predate unit kinds and must read back as unknown "
        f"(None), saw {_opt(events[0], 'unit_kind', None)!r}"
    )
    latest = _run(context, context.repository.latest_quota("tavily"))
    assert latest is not None and latest.remaining == Decimal("5"), (
        "AC-8: legacy quota rows must remain readable"
    )
    assert _opt(latest, "unit_kind", None) is None, (
        "AC-8: legacy quota rows must read back with unknown unit kind"
    )
    totals = _run(context, context.repository.usage_totals())
    if any(hasattr(total, "unit_kind") for total in totals):
        for total in totals:
            assert _opt(total, "unit_kind", None) is not None, (
                "AC-8: legacy/unknown rows must never merge into known-kind totals"
            )


@when("I record usage metadata containing credential keys")
def step_when_record_credential_metadata(context: Any) -> None:
    context.credential_error = None
    try:
        _run(
            context,
            context.repository.record_usage(
                UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=FIXED_AT,
                    metadata={"api_key": "sk-secret-should-never-persist"},
                )
            ),
        )
    except ValueError as exc:
        context.credential_error = exc


@then("the metadata write should be rejected without persisting secrets")
def step_then_credentials_rejected(context: Any) -> None:
    assert context.credential_error is not None, (
        "AC-8: usage metadata containing credential keys (api_key) must be "
        "rejected, but the write was accepted"
    )
    events = _run(context, context.repository.list_usage(provider="tavily"))
    for event in events:
        assert "sk-secret-should-never-persist" not in repr(event.metadata), (
            "AC-8: credential material must never persist in usage metadata"
        )


# --------------------------------------------------------------------------
# T-6: mixed known-kind + legacy totals (AC-3/AC-8)
# --------------------------------------------------------------------------


@given("known-kind and legacy usage events recorded together")
def step_given_mixed_usage(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    known = [
        ("brave", UsageOperation.SEARCH, Decimal("1"), "REQUEST"),
        ("brave", UsageOperation.SEARCH, Decimal("1"), "REQUEST"),
        ("exa", UsageOperation.SEARCH, Decimal("0.001"), "USD"),
    ]
    for index, (provider, op, units, kind) in enumerate(known):
        _run(
            context,
            context.repository.record_usage(
                UsageEvent(
                    provider=provider,
                    operation=op,
                    units=units,
                    observed_at=FIXED_AT + timedelta(seconds=index),
                    unit_kind=_opt(unit_kind, kind),
                    display_unit=kind.lower(),
                )
            ),
        )
    # Legacy row predating unit dimensions: raw value preserved, kind unknown.
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="tavily",
                operation=UsageOperation.SEARCH,
                units=Decimal("5"),
                observed_at=FIXED_AT + timedelta(seconds=90),
            )
        ),
    )


@then("known-kind totals should stay Decimal-exact")
def step_then_known_totals_exact(context: Any) -> None:
    totals = context.totals
    keyed = {
        (total.provider, str(total.operation)): total
        for total in totals
        if _opt(total, "unit_kind", None) is not None
    }
    brave = keyed.get(("brave", "search"))
    assert brave is not None and brave.total_units == Decimal("2"), (
        f"AC-3: (brave, search, REQUEST) must total Decimal('2'), saw {totals!r}"
    )
    exa = keyed.get(("exa", "search"))
    assert exa is not None and exa.total_units == Decimal("0.001"), (
        f"AC-3: (exa, search, USD) must total Decimal('0.001') exactly, saw {totals!r}"
    )
    for total in totals:
        assert isinstance(total.total_units, Decimal), "AC-3: no float casts in totals"


@then("legacy rows should appear only in legacy-compatible totals")
def step_then_legacy_separate(context: Any) -> None:
    totals = context.totals
    for total in totals:
        if _opt(total, "unit_kind", None) is None:
            assert isinstance(total, LegacyUsageTotal), (
                f"AC-8: a total without a unit kind must be a LegacyUsageTotal "
                f"(legacy/unknown group), saw {type(total).__name__}: {total!r}"
            )
    known_providers = {
        (total.provider, str(total.operation))
        for total in totals
        if _opt(total, "unit_kind", None) is not None
    }
    assert ("tavily", "search") not in known_providers, (
        "AC-8: the legacy tavily row must never merge into a known-kind total"
    )
    legacy_rows = _run(context, context.repository.list_usage(provider="tavily"))
    assert len(legacy_rows) == 1 and legacy_rows[0].units == Decimal("5"), (
        f"AC-8: legacy rows stay available in history with exact raw units, saw {legacy_rows!r}"
    )
    assert _opt(legacy_rows[0], "unit_kind", None) is None, (
        "AC-8: the legacy row must read back with unknown unit kind"
    )


# --------------------------------------------------------------------------
# T-6: quota metadata round-trip through the public API only (AC-8)
# --------------------------------------------------------------------------


@when("I record a quota snapshot carrying routing metadata")
def step_when_record_quota_metadata(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    context.quota_metadata = {"free": Decimal("99995"), "paid": Decimal("2")}
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="keenable",
                source=QuotaSource.OBSERVED,
                remaining=None,
                limit=Decimal("100000"),
                observed_at=FIXED_AT,
                unit_kind=_opt(unit_kind, "CREDIT"),
                display_unit="credits",
                metadata=dict(context.quota_metadata),
            )
        ),
    )


@then("latest_quota should return the same metadata")
def step_then_quota_metadata_round_trip(context: Any) -> None:
    # Behavioral assertion via the public read path only: quota metadata has
    # no approved storage column yet, so this documents the schema-plan gap
    # instead of reaching into private row state.
    latest = _run(context, context.repository.latest_quota("keenable"))
    assert latest is not None, "AC-8 setup: recorded quota snapshot missing"
    assert dict(latest.metadata) == {
        key: Decimal(str(value)) for key, value in context.quota_metadata.items()
    }, (
        "AC-8: quota snapshot metadata (free/paid routing counters) must "
        "survive a public record_quota/latest_quota round-trip "
        f"(pending explicit schema-plan approval for a metadata column); "
        f"saw {latest.metadata!r}"
    )


# --------------------------------------------------------------------------
# AC-FC: Firecrawl
# --------------------------------------------------------------------------


@when(
    "I map a Firecrawl credit-usage payload with remaining {remaining:d}, "
    "plan {plan:d}, and a billing end"
)
def step_when_firecrawl_map(context: Any, remaining: int, plan: int) -> None:
    unit_kind = _require_unit_kind_model()
    reset_at = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    context.firecrawl_reset = reset_at
    # The adapter must GET /v2/team/credit-usage with Bearer auth and map
    # remainingCredits (truth) / planCredits (baseline) / billingPeriodEnd.
    context.firecrawl_snapshot = QuotaSnapshot(
        provider="firecrawl",
        source=QuotaSource.AUTHORITATIVE,
        remaining=max(Decimal("0"), Decimal(remaining)),
        limit=Decimal(plan),
        reset_at=reset_at,
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "CREDIT"),
        display_unit="credits",
    )
    _run(context, context.repository.record_quota(context.firecrawl_snapshot))


@then(
    "the Firecrawl snapshot should be AUTHORITATIVE CREDIT with remaining "
    "{remaining:d} limit {limit:d}"
)
def step_then_firecrawl_snapshot(context: Any, remaining: int, limit: int) -> None:
    latest = _run(context, context.repository.latest_quota("firecrawl"))
    assert latest is not None, (
        "AC-FC-1: no Firecrawl snapshot from GET /v2/team/credit-usage (Bearer)"
    )
    assert latest.source == QuotaSource.AUTHORITATIVE, (
        f"AC-FC-1: Firecrawl quota must be AUTHORITATIVE, saw {latest.source!r}"
    )
    assert str(_opt(latest, "unit_kind", None)).upper().endswith("CREDIT"), (
        f"AC-FC-1: Firecrawl unit_kind must be CREDIT (saw {_opt(latest, 'unit_kind', None)!r})"
    )
    # remainingCredits stays truth even above the planCredits baseline.
    assert latest.remaining == Decimal(remaining), (
        f"AC-FC-1: remaining must be Decimal({remaining}) even above baseline, "
        f"saw {latest.remaining!r}"
    )
    assert latest.limit == Decimal(limit), (
        f"AC-FC-1: limit must be the planCredits baseline Decimal({limit}), saw {latest.limit!r}"
    )


@then("the Firecrawl reset should match the billing period end")
def step_then_firecrawl_reset(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("firecrawl"))
    assert latest is not None, "AC-FC-1 setup: Firecrawl snapshot missing"
    assert latest.reset_at == context.firecrawl_reset, (
        f"AC-FC-1: reset_at must parse billingPeriodEnd "
        f"({context.firecrawl_reset!r}), saw {latest.reset_at!r}"
    )


@when('I map a Firecrawl credit-usage payload with remaining "{remaining}" and plan "{plan}"')
def step_when_firecrawl_malformed(context: Any, remaining: str, plan: str) -> None:
    context.firecrawl_raw = {"remaining": remaining, "plan": plan}
    # SEAM PROBE (AC-FC-2): strict finite non-negative Decimal validation for
    # credit-usage fields (reject NaN/inf/negative/bool; absent optionals None).
    parser = _opt(firecrawl_module, "parse_credit", None)
    if parser is None:
        parser = _opt(firecrawl_module, "strict_decimal", None)
    if parser is None:
        parser = _opt(firecrawl_module, "validate_credits", None)
    context.firecrawl_parser = parser
    assert parser is not None, (
        "AC-FC-2: no strict credit parser found on freesearch.adapters.firecrawl "
        "(expected e.g. parse_credit: reject NaN/inf/negative/bool, absent "
        "optionals become None, remainingCredits stays truth above baseline)"
    )


@then('the Firecrawl snapshot field "{field}" should be unknown rather than zero')
def step_then_firecrawl_field_unknown(context: Any, field: str) -> None:
    parser = context.firecrawl_parser
    raw = (
        context.firecrawl_raw["remaining"]
        if field == "remaining"
        else context.firecrawl_raw["plan"]
    )
    try:
        value = parser(raw)
    except (ValueError, TypeError):
        value = None
    assert value is None, (
        f"AC-FC-2: malformed credit field {field}={raw!r} must become None, "
        f"never 0 (parsed as {value!r})"
    )


@when("I estimate Firecrawl search with limit {limit:d}")
def step_when_firecrawl_search_estimate(context: Any, limit: int) -> None:
    _patch_resolver(context, firecrawl_module)
    client = httpx.AsyncClient(timeout=30.0)
    context.http_client = client
    adapter = FirecrawlAdapter(client, sdk_client=object())
    context.firecrawl_adapter = adapter
    context.firecrawl_estimate = _run(
        context, adapter.estimate_cost(SearchRequest(query="credit probe", limit=limit))
    )
    context.firecrawl_limit = limit


@then("the Firecrawl search estimate should be {credits:d} credits")
def step_then_firecrawl_search_estimate(context: Any, credits: int) -> None:
    estimate = context.firecrawl_estimate
    limit = Decimal(context.firecrawl_limit)
    expected = ((limit + Decimal("9")) // Decimal("10")) * Decimal("2")
    assert expected == Decimal(credits), (
        f"AC-FC-3 setup: ceil({limit}/10)*2 must be {credits}, test math says {expected!r}"
    )
    assert estimate.units == expected, (
        f"AC-FC-3: Firecrawl search limit {limit} must estimate {credits} credits "
        f"(ceil(limit/10)*2), saw {estimate.units!r}"
    )
    assert str(estimate.currency).upper().startswith("CREDIT"), (
        f"AC-FC-3: Firecrawl estimates must be credits, saw {estimate.currency!r}"
    )


@when(
    "I estimate Firecrawl fetch with {pdf:d} pdf pages, json extract {as_json}, "
    "enhanced {enhanced}, retention {zdr}"
)
def step_when_firecrawl_fetch_estimate(
    context: Any, pdf: int, as_json: str, enhanced: str, zdr: str
) -> None:
    # T-6 (estimate≡executed options): the estimate must read the same
    # FetchRequest options an executed fetch would bill, not an abstract
    # modifier count. Documented weights: +1 per PDF page, +4 JSON/LLM
    # extraction, +4 enhanced, +1 zero-data-retention, base 1.
    adapter = _opt(context, "firecrawl_adapter", None)
    if adapter is None:  # pragma: no cover - outline always sets the adapter first
        _patch_resolver(context, firecrawl_module)
        client = httpx.AsyncClient(timeout=30.0)
        context.http_client = client
        adapter = FirecrawlAdapter(client, sdk_client=object())
        context.firecrawl_adapter = adapter
    flags = {
        "pdf_pages": pdf,
        "json_extract": as_json.strip().lower() == "true",
        "enhanced": enhanced.strip().lower() == "true",
        "zero_data_retention": zdr.strip().lower() == "true",
    }
    request = FetchRequest(url="https://example.com/doc", **flags)
    context.firecrawl_fetch_request = request
    context.firecrawl_fetch_estimate = _run(context, adapter.estimate_cost(request))


@then("the Firecrawl fetch estimate should be {credits:d} credits")
def step_then_firecrawl_fetch_estimate(context: Any, credits: int) -> None:
    estimate = context.firecrawl_fetch_estimate
    request = context.firecrawl_fetch_request
    modifiers = (
        Decimal(request.pdf_pages)
        + Decimal("4") * int(request.json_extract)
        + Decimal("4") * int(request.enhanced)
        + Decimal("1") * int(request.zero_data_retention)
    )
    expected = fetch_credits(Decimal("1"), modifiers)
    assert expected == Decimal(credits), (
        f"AC-FC-3 setup: 1 + {modifiers} option credits must be {credits} (outline row out of sync)"
    )
    assert estimate.units == expected, (
        f"AC-FC-3: estimate_cost must equal the executed-option price "
        f"(1 + pdf {request.pdf_pages} + json {request.json_extract} + "
        f"enhanced {request.enhanced} + zdr {request.zero_data_retention} = "
        f"{credits} credits), saw {estimate.units!r}"
    )
    assert str(estimate.currency).upper().startswith("CREDIT"), (
        f"AC-FC-3: Firecrawl estimates must be credits, saw {estimate.currency!r}"
    )


# --------------------------------------------------------------------------
# AC-PA: Parallel
# --------------------------------------------------------------------------


@when("I record a Parallel search response with SKU counts {first:d} and {second:d}")
def step_when_parallel_sku_response(context: Any, first: int, second: int) -> None:
    _patch_resolver(context, parallel_module)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "search_id": "ps-sku",
                "results": [{"url": "https://example.com/a", "title": "a", "excerpts": ["a"]}],
                "usage": [
                    {"sku": "sku_search", "count": first},
                    {"sku": "sku_extra", "count": second},
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.http_client = client
    adapter = ParallelAdapter(client)
    context.parallel_sku_response = _run(
        context, adapter.search(SearchRequest(query="sku probe", limit=3))
    )
    context.parallel_sku_expected = Decimal(first + second)
    context.parallel_oauth_calls = [call for call in calls if "service/v1/balance" in str(call.url)]


@then("the Parallel usage units should be {expected:d} with SKU metadata retained")
def step_then_parallel_sku_units(context: Any, expected: int) -> None:
    usage = context.parallel_sku_response.usage
    assert usage is not None, "AC-PA-1: Parallel search must report raw SKU usage"
    assert usage.units == Decimal(expected), (
        f"AC-PA-1: raw usage must be the SKU sum Decimal({expected}), saw {usage.units!r}"
    )
    assert usage.units == context.parallel_sku_expected, (
        "AC-PA-1: raw SKU math must stay Decimal-exact"
    )
    metadata = _opt(usage, "metadata", None) or {}
    # SEAM PROBE (AC-PA-1): per-SKU entries must survive in usage metadata so
    # the quota layer can price them in Decimal USD later.
    skus = metadata.get("skus", metadata.get("usage"))
    assert skus is not None, (
        f"AC-PA-1: per-SKU breakdown must be retained in usage metadata "
        f"(saw metadata={metadata!r}); pricing needs the SKU table, not just a sum"
    )


@then("the Parallel spend projection should be Decimal USD, never float")
def step_then_parallel_spend_decimal(context: Any) -> None:
    estimate = _run(
        context,
        _parallel_adapter_for(context).estimate_cost(SearchRequest(query="spend probe", limit=5)),
    )
    assert estimate.currency == "USD", (
        "AC-PA-1: Parallel spend projection must be Decimal USD, "
        f"saw currency {estimate.currency!r}"
    )
    assert isinstance(estimate.units, Decimal), "AC-PA-1: Parallel spend must avoid float casts"
    assert estimate.units == Decimal("0.005"), (
        "AC-PA-1/AC-PA-2: default (advanced) Parallel search must project "
        f"USD 0.005, saw {estimate.units!r}"
    )


def _parallel_adapter_for(context: Any) -> ParallelAdapter:
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    return ParallelAdapter(client)


@when("I enable the Parallel USD {seed} monthly seed and record USD {spend} of successful spend")
def step_when_parallel_seed(context: Any, seed: str, spend: str) -> None:
    unit_kind = _require_unit_kind_model()
    context.parallel_seed = Decimal(seed)
    context.parallel_spend = Decimal(spend)
    assert context.parallel_seed == Decimal("5.00"), (
        f"AC-PA-3 setup: eligible free seed must be USD 5.00/month, saw {seed!r}"
    )
    # Success-only ledger: failed requests never decrement the local budget.
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal(spend),
                observed_at=FIXED_AT,
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(unit_kind, "USD"),
                display_unit="USD",
            )
        ),
    )
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal("0"),
                observed_at=FIXED_AT + timedelta(seconds=10),
                status=UsageStatus.FAILURE,
            )
        ),
    )
    remaining = max(Decimal("0"), context.parallel_seed - context.parallel_spend)
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=remaining,
                limit=context.parallel_seed,
                observed_at=FIXED_AT + timedelta(seconds=20),
                unit_kind=_opt(unit_kind, "USD"),
                display_unit="USD",
            )
        ),
    )


@then("the Parallel remaining should be USD {remaining} of USD {limit}")
def step_then_parallel_seed_remaining(context: Any, remaining: str, limit: str) -> None:
    latest = _run(context, context.repository.latest_quota("parallel"))
    assert latest is not None, "AC-PA-3: no Parallel seed-budget snapshot recorded"
    assert latest.remaining == Decimal(remaining), (
        f"AC-PA-3: seed remaining must be max(0, 5.00 - spend) = USD {remaining}, "
        f"saw {latest.remaining!r}"
    )
    assert latest.limit == Decimal(limit), (
        f"AC-PA-3: seed limit must be USD {limit}, saw {latest.limit!r}"
    )
    assert str(_opt(latest, "unit_kind", None)).upper().endswith("USD"), (
        "AC-PA-3: Parallel budget snapshots must be unit_kind USD "
        f"(saw {_opt(latest, 'unit_kind', None)!r})"
    )
    totals = _run(context, context.repository.usage_totals())
    assert totals, "AC-PA-3 setup: spend ledger usage missing"


# --------------------------------------------------------------------------
# T-6: unseeded Parallel spend ledger (AC-PA-3)
# --------------------------------------------------------------------------


@when("I record Parallel spend without enabling the free seed")
def step_when_parallel_unseeded_spend(context: Any) -> None:
    # No free_seed: the account has no verified eligibility, so spend is
    # tracked but no balance may be fabricated.
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    context.http_client = client
    adapter = ParallelAdapter(client)
    context.parallel_unseeded = adapter
    context.parallel_unseeded_recorded = adapter.record_success_spend(Decimal("1.25"))


@then("the Parallel quota should report remaining unknown with limit unknown")
def step_then_parallel_unseeded_unknown(context: Any) -> None:
    adapter = context.parallel_unseeded
    assert context.parallel_unseeded_recorded is None, (
        "AC-PA-3: without an enabled seed, spend must not materialize a "
        "snapshot (no fabricated balance)"
    )
    assert _run(context, adapter.quota()) is None, (
        "AC-PA-3: unseeded accounts report no quota snapshot (spend ledger "
        "only, remaining/limit unknown)"
    )
    latest = _run(context, context.repository.latest_quota("parallel"))
    assert latest is None or (latest.remaining is None and latest.limit is None), (
        f"AC-PA-3: unseeded spend must leave remaining/limit unknown, saw {latest!r}"
    )


@when("a Parallel 402 soft signal arrives")
def step_when_parallel_402(context: Any) -> None:
    _patch_resolver(context, parallel_module)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "insufficient_balance"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.http_client = client
    adapter = ParallelAdapter(client)
    try:
        _run(context, adapter.search(SearchRequest(query="soft probe", limit=3)))
    except ProviderOperationError as exc:
        context.parallel_402_error = exc
    assert _opt(context, "parallel_402_error", None) is not None, (
        "AC-PA-5 setup: expected the stubbed 402 to raise"
    )
    assert context.parallel_402_error.error.retryable is False, (
        "AC-PA-5: Parallel 402 must be non-retryable as an operation"
    )
    # The soft zero must be recorded as a soft (temporary) signal.
    _run(
        context,
        context.repository.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("0"),
                limit=context.parallel_seed,
                observed_at=FIXED_AT + timedelta(minutes=5),
            )
        ),
    )


@then("the Parallel remaining should read soft zero without a hard lockout")
def step_then_parallel_soft_zero(context: Any) -> None:
    # SEAM PROBE (AC-PA-5): the soft zero must be distinguishable from hard
    # month-long exhaustion and must expire on later success/reconciliation.
    effective = _opt(monitoring_module, "effective_quota", None)
    assert effective is not None, (
        "AC-PA-5: freesearch.monitoring.effective_quota missing — a Parallel 402 "
        "soft zero must read as temporary (cleared by later billed success), "
        "never as a hard lockout (same seam as AC-6)"
    )
    view = _run(context, effective(context.repository, "parallel"))
    assert view is not None and view.remaining == Decimal("0"), (
        f"AC-PA-5: soft signal must currently read remaining=0, saw {view!r}"
    )


@when("a later Parallel billed operation succeeds")
def step_when_parallel_success_after_soft(context: Any) -> None:
    unit_kind = _opt(contracts_module, "UnitKind", None)
    kwargs: dict[str, Any] = {"status": UsageStatus.SUCCESS}
    if unit_kind is not None:
        kwargs["unit_kind"] = _opt(unit_kind, "USD")
        kwargs["display_unit"] = "USD"
    _run(
        context,
        context.repository.record_usage(
            UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.005"),
                observed_at=FIXED_AT + timedelta(minutes=10),
                **kwargs,
            )
        ),
    )


@then("the Parallel soft zero should be cleared")
def step_then_parallel_soft_cleared(context: Any) -> None:
    effective = _opt(monitoring_module, "effective_quota", None)
    assert effective is not None, "AC-PA-5: freesearch.monitoring.effective_quota missing"
    view = _run(context, effective(context.repository, "parallel"))
    adapter = _StubAdapter("parallel")
    health = {
        "parallel": ProviderHealth(
            provider="parallel", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        )
    }
    quota = {} if view is None or view.remaining != Decimal("0") else {"parallel": view}
    # A cleared soft zero resolves to a non-zero/unknown effective view.
    assert view is None or view.remaining != Decimal("0"), (
        f"AC-PA-5: soft zero must clear after later billed success, still {view!r}"
    )
    candidates = select_route(_search_request(), [adapter], health, quota)
    assert "parallel" in _route_names(candidates), (
        "AC-PA-5: Parallel must route again once the soft zero clears"
    )


@when("a Parallel 429 transient signal arrives")
def step_when_parallel_429(context: Any) -> None:
    _patch_resolver(context, parallel_module)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.http_client = client
    try:
        _run(context, ParallelAdapter(client).search(SearchRequest(query="transient", limit=2)))
    except ProviderOperationError as exc:
        context.parallel_429_error = exc
    assert _opt(context, "parallel_429_error", None) is not None, (
        "AC-PA-5 setup: expected the stubbed 429 to raise"
    )


@then("the Parallel 429 should never become quota exhaustion")
def step_then_parallel_429_transient(context: Any) -> None:
    assert context.parallel_429_error.error.retryable is True, (
        "AC-PA-5: Parallel 429 must stay retryable/transient "
        f"(saw retryable={context.parallel_429_error.error.retryable!r})"
    )
    latest = _run(context, context.repository.latest_quota("parallel"))
    assert (
        latest is None
        or latest.remaining != Decimal("0")
        or latest.observed_at < (FIXED_AT + timedelta(minutes=5))
    ), f"AC-PA-5: a 429 must never be recorded as fresh spend exhaustion (saw {latest!r})"


@when("I inspect Parallel quota capabilities")
def step_when_parallel_capabilities(context: Any) -> None:
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    context.http_client = client
    context.parallel_capabilities = ParallelAdapter(client).capabilities


@then("Parallel capabilities quota should stay false")
def step_then_parallel_caps(context: Any) -> None:
    assert context.parallel_capabilities.quota is False, (
        "AC-PA-4: Parallel capabilities.quota must stay False until a supported "
        "credential design exists (API keys cannot poll the OAuth balance)"
    )


@then("no API-key poll of the OAuth balance endpoint should be attempted")
def step_then_no_oauth_poll(context: Any) -> None:
    # The balance endpoint requires an OAuth device-grant Bearer token; the
    # API-key adapter must never attempt it. Behavioral proof: quota() stays
    # unimplemented (None) and no balance URL is ever requested.
    _patch_resolver(context, parallel_module)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_parallel_search_handler), timeout=30.0
    )
    adapter = ParallelAdapter(client)
    assert _run(context, adapter.quota()) is None, (
        "AC-PA-4: Parallel quota() must stay None (no API-key balance poll possible)"
    )
    assert _opt(context, "parallel_oauth_calls", []) == [], (
        "AC-PA-4: no request may target the OAuth-only balance endpoint with an API key"
    )


# --------------------------------------------------------------------------
# B-QUOTA-BRAVE-REGRESSION: degenerate 0/0 is unknown and routable (AC-2/AC-6)
# --------------------------------------------------------------------------


@then(
    "the Brave snapshot remaining should be unknown and limit should be unknown "
    "and reset should be unknown"
)
def step_then_brave_snapshot_all_unknown(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, (
        "AC-2: expected a Brave snapshot after a successful search with degenerate "
        "monthly elements; no snapshot was recorded at all"
    )
    assert latest.remaining is None, (
        "AC-2: a degenerate monthly remaining of 0 with no positive limit must "
        f"be unknown (None), never 0 (saw {latest.remaining!r})"
    )
    assert latest.limit is None, (
        "AC-2: a degenerate monthly limit of 0 carries no allowance and must be "
        f"unknown (None), never 0 (saw {latest.limit!r})"
    )
    assert latest.reset_at is None, (
        "AC-2: a degenerate monthly reset of 0 carries no reset instant and must "
        f"be unknown (None), saw {latest.reset_at!r}"
    )


@then("Brave should stay eligible for search routing despite zero monthly elements")
def step_then_brave_stays_eligible(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, "AC-6 setup: expected a Brave snapshot for routing"
    assert latest.remaining is None and latest.limit is None, (
        f"AC-2/AC-6 setup: degenerate monthly elements must persist as unknown "
        f"(None/None), saw {latest.remaining!r}/{latest.limit!r}"
    )
    adapter = _StubAdapter("brave")
    health = {
        "brave": ProviderHealth(provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT)
    }
    candidates = select_route(_search_request(), [adapter], health, {"brave": latest})
    assert "brave" in _route_names(candidates), (
        "AC-6: unknown Brave quota must stay eligible and never be treated as 0; "
        f"brave was removed from candidates (latest={latest!r})"
    )


@then(
    "Brave should be excluded from search routing when remaining is zero "
    "with a known positive limit"
)
def step_then_brave_genuine_zero_excluded(context: Any) -> None:
    latest = _run(context, context.repository.latest_quota("brave"))
    assert latest is not None, "AC-6 setup: expected a Brave snapshot for routing"
    assert latest.remaining == Decimal("0"), (
        f"AC-6 setup: genuine depletion must persist remaining=0, saw {latest.remaining!r}"
    )
    assert latest.limit == Decimal("1000"), (
        f"AC-6 setup: genuine depletion keeps a known positive limit, saw {latest.limit!r}"
    )
    adapter = _StubAdapter("brave")
    fallback = _StubAdapter("tavily")
    health = {
        "brave": ProviderHealth(provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT),
        "tavily": ProviderHealth(
            provider="tavily", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        ),
    }
    candidates = select_route(_search_request(), [adapter, fallback], health, {"brave": latest})
    assert "brave" not in _route_names(candidates), (
        f"AC-6: genuine remaining=0 with limit>0 must steer routing away, "
        f"but brave stayed eligible: {_route_names(candidates)!r}"
    )
    assert _route_names(candidates) == ["tavily"], (
        f"AC-6: healthy fallback must lead after genuine exclusion, "
        f"saw {_route_names(candidates)!r}"
    )


# --------------------------------------------------------------------------
# S4: shared normalize_degenerate_quota through BOTH read paths (AC-2/AC-6)
# --------------------------------------------------------------------------


def _require_normalize_helper() -> Any:
    """Gate S4 steps on the shared degenerate-quota helper contract."""

    helper = _opt(monitoring_module, "normalize_degenerate_quota", None)
    assert helper is not None, (
        "S4/AC-2: freesearch.monitoring.normalize_degenerate_quota missing — "
        "expected a shared pure helper normalize_degenerate_quota(snapshot) "
        "mapping limit==Decimal('0') to remaining/limit/reset None (else "
        "identity), used by BOTH effective_quota and the dashboard path "
        "(_latest_quotas/collect_stats)"
    )
    return helper


@when("I record a Brave OBSERVED REQUEST quota with remaining 0 limit 0")
def step_when_record_brave_degenerate_zero(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    snapshot = QuotaSnapshot(
        provider="brave",
        source=QuotaSource.OBSERVED,
        remaining=Decimal("0"),
        limit=Decimal("0"),
        reset_at=FIXED_AT,
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "REQUEST"),
        display_unit="requests",
    )
    _run(context, context.repository.record_quota(snapshot))
    context.degenerate_recorded = snapshot


@then("collect_stats latest_quota for brave should be unknown remaining limit and reset")
def step_then_collect_stats_normalized(context: Any) -> None:
    _require_normalize_helper()
    stats = _run(context, collect_stats(context.repository, adapter_names=["brave"]))
    rows = [snap for snap in stats.latest_quota if snap.provider == "brave"]
    assert rows, (
        "S4/AC-2: collect_stats latest_quota has no brave row after record_quota "
        f"0/0 (saw {[s.provider for s in stats.latest_quota]!r})"
    )
    view = rows[0]
    assert view.remaining is None, (
        "S4/AC-2: dashboard path must normalize degenerate remaining 0/0 to "
        f"unknown (None), never 0 (saw {view.remaining!r})"
    )
    assert view.limit is None, (
        "S4/AC-2: dashboard path must normalize degenerate limit 0 to unknown "
        f"(None), never 0 (saw {view.limit!r})"
    )
    assert view.reset_at is None, (
        "S4/AC-2: dashboard path must normalize degenerate reset to unknown "
        f"(None), saw {view.reset_at!r}"
    )
    context.degenerate_dashboard_view = view


@then("effective_quota for brave should match the normalized unknown view")
def step_then_effective_matches_normalized(context: Any) -> None:
    helper = _require_normalize_helper()
    effective = _opt(monitoring_module, "effective_quota", None)
    assert effective is not None, (
        "S4/AC-2: freesearch.monitoring.effective_quota missing — routing needs "
        "the effective-quota view over the normalized degenerate snapshot"
    )
    view = _run(context, effective(context.repository, "brave"))
    assert view is not None, "S4/AC-2 setup: expected an effective_quota view for brave"
    assert view.remaining is None and view.limit is None and view.reset_at is None, (
        "S4/AC-2: effective_quota must return the same normalized unknown view "
        f"(None/None/None), saw {view.remaining!r}/{view.limit!r}/{view.reset_at!r}"
    )
    dashboard = context.degenerate_dashboard_view
    assert (view.remaining, view.limit, view.reset_at) == (
        dashboard.remaining,
        dashboard.limit,
        dashboard.reset_at,
    ), (
        "S4/AC-2: effective_quota and collect_stats must return the same "
        f"normalized view (effective={view!r} dashboard={dashboard!r})"
    )
    # The shared helper is the single source of truth for both paths.
    direct = helper(context.degenerate_recorded)
    assert (direct.remaining, direct.limit, direct.reset_at) == (None, None, None), (
        f"S4/AC-2: normalize_degenerate_quota(0/0) must be (None,None,None), saw {direct!r}"
    )
    context.degenerate_effective_view = view


@then("Brave should stay eligible from the normalized view despite zero limit")
def step_then_brave_eligible_normalized(context: Any) -> None:
    view = context.degenerate_effective_view
    assert view is not None, "S4/AC-6 setup: expected a normalized effective view for brave"
    assert view.remaining is None and view.limit is None, (
        f"S4/AC-2/AC-6 setup: degenerate 0/0 must read as unknown (None/None), "
        f"saw {view.remaining!r}/{view.limit!r}"
    )
    adapter = _StubAdapter("brave")
    health = {
        "brave": ProviderHealth(provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT)
    }
    candidates = select_route(_search_request(), [adapter], health, {"brave": view})
    assert "brave" in _route_names(candidates), (
        "S4/AC-6: normalized unknown Brave quota must stay eligible and never be "
        f"treated as 0; brave was removed (view={view!r})"
    )


@when("I record a keyless local hourly quota at zero remaining")
def step_when_keyless_local_zero(context: Any) -> None:
    unit_kind = _require_unit_kind_model()
    snapshot = QuotaSnapshot(
        provider="keenable",
        source=QuotaSource.OBSERVED,
        remaining=Decimal("0"),
        limit=Decimal("1000"),
        reset_at=FIXED_AT + timedelta(hours=1),
        observed_at=FIXED_AT,
        unit_kind=_opt(unit_kind, "REQUEST"),
        display_unit="requests",
        metadata={
            "mode": "keyless",
            "window": "hourly",
            "scope": "shared_pool_local_observation",
        },
    )
    _run(context, context.repository.record_quota(snapshot))
    context.keyless_local_zero = snapshot


@then("keyless local hourly zero should stay eligible for routing")
def step_then_keyless_local_zero_eligible(context: Any) -> None:
    adapter = _StubAdapter("keenable")
    health = {
        "keenable": ProviderHealth(
            provider="keenable", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        )
    }
    candidates = select_route(
        _search_request(), [adapter], health, {"keenable": context.keyless_local_zero}
    )
    assert "keenable" in _route_names(candidates), (
        "AC-6: local keyless 0/1000 is not authoritative shared-pool exhaustion"
    )
