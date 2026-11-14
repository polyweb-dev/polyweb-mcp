"""Focused unit and boundary matrix for the QUOTA.md acceptance criteria.

Offline only: temp-file SQLite repositories (``tmp_path``), mocked HTTPX
transports, and one fixed fake API key injected explicitly at every keyed
adapter constructor. No live network, no production ``polyweb.db``, no
port binds. Decimal assertions throughout — never float.

Red-state contract: tests probe new seams with ``getattr`` and fail as clean
``AssertionError``s naming the AC. ``SEAM PROBE`` marks a tester-proposed name
the Developer may rename (one line each; see TEST_HANDOFF risks).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

import polyweb.adapters.brave as brave_module
import polyweb.adapters.exa as exa_module
from polyweb.adapters._youcom_support import _estimated_quota
from polyweb.adapters.exa import ExaAdapter
from polyweb.adapters.firecrawl import FirecrawlAdapter, fetch_credits
from polyweb.adapters.keenable import KeenableAdapter
from polyweb.adapters.parallel import ParallelAdapter
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models import contracts as contracts_module
from polyweb.models.contracts import (
    HealthStatus,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from polyweb.persistence.storage import LegacyUsageTotal, SQLiteRepository
from polyweb.services import monitoring as monitoring_module
from polyweb.services.monitoring import effective_quota, refresh_quotas, tracked_call
from polyweb.services.routing import select_route
from tests.fixtures.execution import seed_execution_project

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

# Fixed fake key: adapters are keyed via explicit constructor injection
# (``api_key=``), never through a global secret-resolver seam. Keyless
# behavior is selected by passing no key at all (see the keyless cases).
TEST_API_KEY = SecretStr("quota-unit-secret")


@pytest_asyncio.fixture
async def repo(tmp_path):  # type: ignore[no-untyped-def]
    repository = await SQLiteRepository.open(tmp_path / "quota-unit.db")
    yield repository
    await repository.close()


def _opt(target: object, name: str, *default: object) -> object:
    """``getattr`` with identical semantics, routed through a variable name.

    Ruff B009 forbids ``getattr`` with a constant attribute string; the Red
    probes in this suite need dynamic-safe attribute reads, so every probe
    goes through this shim.
    """

    if default:
        return getattr(target, name, default[0])
    return getattr(target, name)


def _unit_kind():  # type: ignore[no-untyped-def]
    unit_kind = _opt(contracts_module, "UnitKind", None)
    assert unit_kind is not None, (
        "AC-3: polyweb.contracts.UnitKind missing (REQUEST|CREDIT|USD|FREE)"
    )
    return unit_kind


# --------------------------------------------------------------------------
# AC-3/AC-7: canonical unit contract
# --------------------------------------------------------------------------


class TestUnitKindContract:
    def test_unit_kind_has_four_dimensions(self) -> None:
        assert {member.name for member in _unit_kind()} == {"REQUEST", "CREDIT", "USD", "FREE"}

    def test_usage_event_fields_additive_nullable(self) -> None:
        _unit_kind()
        assert "unit_kind" in UsageEvent.model_fields, "AC-3: UsageEvent.unit_kind missing"
        assert "display_unit" in UsageEvent.model_fields, "AC-7: UsageEvent.display_unit missing"
        event = UsageEvent(
            provider="exa",
            operation=UsageOperation.SEARCH,
            units=Decimal("0.001"),
            observed_at=FIXED_AT,
        )
        assert event.unit_kind is None, "AC-8: new fields must be nullable (legacy compat)"

    def test_quota_snapshot_fields_additive_nullable(self) -> None:
        _unit_kind()
        assert "unit_kind" in QuotaSnapshot.model_fields, "AC-3: QuotaSnapshot.unit_kind missing"
        assert "display_unit" in QuotaSnapshot.model_fields, (
            "AC-7: QuotaSnapshot.display_unit missing"
        )
        snapshot = QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("5"),
            observed_at=FIXED_AT,
        )
        assert snapshot.unit_kind is None and snapshot.display_unit is None, (
            "AC-8: new fields must be nullable (legacy compat)"
        )

    def test_serialization_exposes_units_and_source(self) -> None:
        kind = _unit_kind()
        payload = QuotaSnapshot(
            provider="firecrawl",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("9"),
            observed_at=FIXED_AT,
            unit_kind=_opt(kind, "REQUEST"),
            display_unit="requests",
        ).model_dump(mode="json")
        assert payload["unit_kind"] == _opt(kind, "REQUEST").value, (
            f"AC-7: unit_kind must serialize, saw {payload!r}"
        )
        assert payload["display_unit"] == "requests", f"AC-7: display_unit missing: {payload!r}"
        assert payload["source"] == "observed", f"AC-7: source confidence missing: {payload!r}"


class TestRemainingPercentContract:
    def _snapshot(self, remaining: str | None, limit: str | None) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal(remaining) if remaining is not None else None,
            limit=Decimal(limit) if limit is not None else None,
            observed_at=FIXED_AT,
            unit_kind=_opt(_unit_kind(), "CREDIT"),
            display_unit="credits",
        )

    def test_bounded_percentage_is_decimal_exact(self) -> None:
        snapshot = self._snapshot("25", "100")
        assert snapshot.remaining_percent == Decimal("25"), (
            f"Quota percentage must derive from native Decimal values, saw {snapshot!r}"
        )
        assert Decimal(snapshot.model_dump(mode="json")["remaining_percent"]) == Decimal("25"), (
            "Bounded remaining_percent must be present on the canonical wire contract"
        )

    def test_promotional_balance_clamps_at_one_hundred(self) -> None:
        snapshot = self._snapshot("250", "100")
        assert snapshot.remaining_percent == Decimal("100"), (
            "A remaining balance above the plan baseline must clamp to 100%"
        )

    @pytest.mark.parametrize("remaining,limit", [("0", "0"), ("0", None), ("10", None)])
    def test_unbounded_or_zero_limit_is_unknown(self, remaining: str, limit: str | None) -> None:
        snapshot = self._snapshot(remaining, limit)
        assert snapshot.remaining_percent is None
        assert snapshot.model_dump(mode="json")["remaining_percent"] is None

    async def test_dashboard_serializes_the_same_derived_percentage(
        self, repo: SQLiteRepository
    ) -> None:
        await repo.record_quota(self._snapshot("25", "100"))
        stats = await monitoring_module.collect_stats(repo, adapter_names=["tavily"])
        payload = stats.model_dump(mode="json")
        assert Decimal(payload["latest_quota"][0]["remaining_percent"]) == Decimal("25"), (
            "Dashboard serialization must expose the canonical derived percentage"
        )


# --------------------------------------------------------------------------
# Decimal rules (QUOTA.md section 2.3)
# --------------------------------------------------------------------------


class TestDecimalRules:
    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "-5", True, "abc", None])
    def test_strict_parser_rejects_bad_inputs(self, bad: object) -> None:
        parser = _opt(contracts_module, "parse_decimal", None)
        assert parser is not None, "AC-3/2.3: polyweb.contracts.parse_decimal missing"
        try:
            value = parser(bad)
        except (ValueError, TypeError):
            return
        pytest.fail(f"strict parser must reject {bad!r} (parsed as {value!r})")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("250", Decimal("250")), ("0.001", Decimal("0.001")), (250, Decimal("250"))],
    )
    def test_strict_parser_accepts_good_inputs(self, raw: object, expected: Decimal) -> None:
        parser = _opt(contracts_module, "parse_decimal", None)
        assert parser is not None, "AC-3/2.3: polyweb.contracts.parse_decimal missing"
        assert parser(raw) == expected, f"strict parser mangled {raw!r}"

    async def test_totals_stay_decimal_exact(self, repo: SQLiteRepository) -> None:
        kind = _unit_kind()
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.001"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )
        totals = await repo.installation_usage_totals()
        assert totals[0].total_units == Decimal("0.001"), (
            f"totals must stay Decimal-exact, saw {totals[0].total_units!r}"
        )
        assert isinstance(totals[0].total_units, Decimal), "no float casts in aggregation"


# --------------------------------------------------------------------------
# AC-3: safe aggregation + FAILURE exclusion
# --------------------------------------------------------------------------


class TestSafeAggregation:
    async def test_groups_by_provider_operation_kind(self, repo: SQLiteRepository) -> None:
        kind = _unit_kind()
        specs = [
            ("brave", UsageOperation.SEARCH, "1", "REQUEST"),
            ("brave", UsageOperation.SEARCH, "1", "REQUEST"),
            ("exa", UsageOperation.SEARCH, "0.001", "USD"),
            ("tavily", UsageOperation.FETCH, "0.2", "CREDIT"),
        ]
        for index, (provider, op, units, name) in enumerate(specs):
            await repo.record_usage(
                UsageEvent(
                    provider=provider,
                    operation=op,
                    units=Decimal(units),
                    observed_at=FIXED_AT + timedelta(seconds=index),
                    unit_kind=_opt(kind, name),
                    display_unit=name.lower(),
                ),
                attribution=await seed_execution_project(repo),
            )
        totals = await repo.installation_usage_totals()
        assert all(hasattr(total, "unit_kind") for total in totals), (
            "AC-3: UsageTotal must carry unit_kind (group by provider, operation, kind)"
        )
        keyed = {
            (total.provider, str(total.operation), str(_opt(total, "unit_kind"))): total
            for total in totals
        }
        assert keyed[("brave", "search", "REQUEST")].total_units == Decimal("2")
        assert keyed[("exa", "search", "USD")].total_units == Decimal("0.001")
        assert len(totals) == 3, f"AC-3: cross-kind sums forbidden, saw {totals!r}"

    async def test_mixed_known_and_legacy_totals(self, repo: SQLiteRepository) -> None:
        # T-6: known-kind and legacy rows coexist without ever merging.
        kind = _unit_kind()
        await repo.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "REQUEST"),
                display_unit="requests",
            ),
            attribution=await seed_execution_project(repo),
        )
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.001"),
                observed_at=FIXED_AT + timedelta(seconds=1),
            ),
            attribution=await seed_execution_project(repo),
        )
        totals = await repo.installation_usage_totals()
        known = [total for total in totals if _opt(total, "unit_kind", None) is not None]
        assert len(known) == 1 and known[0].total_units == Decimal("1"), (
            f"AC-3: known totals stay exact beside legacy rows, saw {totals!r}"
        )
        for total in totals:
            if _opt(total, "unit_kind", None) is None:
                assert isinstance(total, LegacyUsageTotal), (
                    f"AC-8: kind-less totals must be LegacyUsageTotal, saw {type(total).__name__}"
                )
        rows = await repo.list_provider_usage(provider="exa")
        assert len(rows) == 1 and rows[0].units == Decimal("0.001"), (
            "AC-8: legacy rows stay listed in history with exact raw units"
        )
        assert _opt(rows[0], "unit_kind", None) is None, (
            "AC-8: legacy rows read back with unknown unit kind"
        )

    async def test_legacy_only_totals_are_legacy_compatible(self, repo: SQLiteRepository) -> None:
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.001"),
                observed_at=FIXED_AT,
            ),
            attribution=await seed_execution_project(repo),
        )
        totals = await repo.installation_usage_totals()
        assert len(totals) == 1 and isinstance(totals[0], LegacyUsageTotal), (
            f"AC-8: legacy-only data must aggregate as LegacyUsageTotal, saw {totals!r}"
        )
        assert totals[0].total_units == Decimal("0.001"), "AC-8: legacy totals keep exact raw units"

    async def test_failure_zeros_excluded(self, repo: SQLiteRepository) -> None:
        kind = _unit_kind()
        await repo.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "REQUEST"),
                display_unit="requests",
            ),
            attribution=await seed_execution_project(repo),
        )
        await repo.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("0"),
                observed_at=FIXED_AT + timedelta(seconds=1),
                status=UsageStatus.FAILURE,
                unit_kind=_opt(kind, "REQUEST"),
                display_unit="requests",
            ),
            attribution=await seed_execution_project(repo),
        )
        totals = await repo.installation_usage_totals()
        assert len(totals) == 1, f"AC-3: FAILURE row must not form its own total: {totals!r}"
        assert totals[0].event_count == 1, (
            f"AC-3: FAILURE zeros excluded from counts (saw {totals[0].event_count})"
        )
        assert totals[0].total_units == Decimal("1"), (
            f"AC-3: FAILURE zeros excluded from sums (saw {totals[0].total_units!r})"
        )


# --------------------------------------------------------------------------
# AC-2: Brave comma-pair parsing (boundary matrix through the parsing seam)
# --------------------------------------------------------------------------


def _brave_monthly() -> object:
    # SEAM PROBE (AC-2): per-header comma-pair element parser.
    parser = _opt(brave_module, "monthly_header_value", None)
    if parser is None:
        parser = _opt(brave_module, "parse_monthly_element", None)
    assert parser is not None, (
        "AC-2: no Brave comma-pair parser found on polyweb.adapters.brave "
        "(expected e.g. monthly_header_value: split on ',', index [1], strip, "
        "int >= 0 else None; per-second index [0] ignored)"
    )
    return parser


class TestBraveHeaderParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("11, 1000", 1000),
            ("60,15000", 15000),
            ("5, 2592000", 2592000),
            ("11,1000 ", 1000),
            ("0, 0", 0),
        ],
    )
    def test_valid_pairs_take_monthly_element(self, raw: str, expected: int) -> None:
        assert _brave_monthly()(raw) == expected, f"AC-2: monthly element of {raw!r}"

    @pytest.mark.parametrize(
        "raw",
        ["11", "11,", "11, ", "11, -4", "11, abc", "", "  ", "11, 1.5", "11, x"],
    )
    def test_malformed_is_none_never_zero(self, raw: str) -> None:
        assert _brave_monthly()(raw) is None, (
            f"AC-2: malformed monthly element {raw!r} must be None, never 0"
        )

    def test_none_is_none(self) -> None:
        assert _brave_monthly()(None) is None, "AC-2: absent header must be None, never 0"

    def test_per_second_element_ignored(self) -> None:
        assert _brave_monthly()("1, 1000") == 1000, (
            "AC-2: index [0] is per-second pressure, monthly index [1] rules"
        )


# --------------------------------------------------------------------------
# AC-4: You.com flooring + gap
# --------------------------------------------------------------------------


class TestYoucomQuota:
    @pytest.mark.parametrize(
        ("cents", "balance_usd", "search", "fetch"),
        [
            (100, "1.00", 200, 1000),
            (101, "1.01", 202, 1010),
            (2, "0.02", 4, 20),
            (1, "0.01", 2, 10),
            (0, "0", 0, 0),
        ],
    )
    def test_balance_persists_as_usd_with_call_equivalents(
        self, cents: int, balance_usd: str, search: int, fetch: int
    ) -> None:
        # T-4 (pairs with D-1): remaining is the authoritative monetary balance
        # in USD; search/fetch counts are derived equivalents in metadata.
        snapshot = _estimated_quota({"data": {"attributes": {"balance": cents}}}, "you")
        assert snapshot.source == QuotaSource.ESTIMATED, "AC-4: You.com stays ESTIMATED"
        assert snapshot.limit is None, "AC-4: You.com limit stays None"
        assert snapshot.remaining == Decimal(balance_usd), (
            f"AC-4: {cents}c must persist as remaining USD {balance_usd}, "
            f"saw {snapshot.remaining!r}"
        )
        assert _opt(snapshot, "unit_kind", None) is not None and str(
            _opt(snapshot, "unit_kind")
        ).upper().endswith("USD"), (
            f"AC-4: You.com remaining is money (unit_kind USD), "
            f"saw {_opt(snapshot, 'unit_kind', None)!r}"
        )
        exposed = dict(_opt(snapshot, "metadata", None) or {})
        assert exposed.get("search_calls") == Decimal(search), (
            f"AC-4: metadata must carry floored search calls ({search}), saw {exposed!r}"
        )
        assert exposed.get("fetch_calls") == Decimal(fetch), (
            f"AC-4: metadata must carry floored fetch calls ({fetch}), saw {exposed!r}"
        )

    def test_gap_marker_stays_off_wire(self) -> None:
        # Critic caveat: usage_gap is an in-memory marker; it must never leak
        # into serialized payloads.
        from polyweb.models.contracts import SearchResponse

        response = SearchResponse(
            query="q",
            provider="you",
            results=[],
            usage_gap={"reason": "metering-unavailable", "estimated": True},
        )
        assert response.usage_gap is not None, "AC-4 setup: gap marker missing"
        assert "usage_gap" not in response.model_dump(mode="json"), (
            "AC-4/AC-8: usage_gap must stay off the wire (in-memory marker only)"
        )

    @pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "100", None])
    def test_balance_validation(self, bad: object) -> None:
        with pytest.raises(ValueError):
            _estimated_quota({"data": {"attributes": {"balance": bad}}}, "you")


# --------------------------------------------------------------------------
# AC-FC: Firecrawl estimates
# --------------------------------------------------------------------------


class TestFirecrawlEstimates:
    @pytest.mark.parametrize(
        ("limit", "credits"), [(1, 2), (10, 2), (11, 4), (20, 4), (21, 6), (25, 6)]
    )
    async def test_search_formula(self, limit: int, credits: int) -> None:
        client = httpx.AsyncClient(timeout=30.0)
        try:
            adapter = FirecrawlAdapter(client, sdk_client=object())
            estimate = await adapter.estimate_cost(
                SearchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=limit
                )
            )
        finally:
            await client.aclose()
        assert estimate.units == Decimal(credits), (
            f"AC-FC-3: search limit {limit} must cost {credits} credits "
            f"(ceil(limit/10)*2), saw {estimate.units!r}"
        )
        assert str(estimate.currency).upper().startswith("CREDIT"), (
            f"AC-FC-3: Firecrawl estimates are credits, saw {estimate.currency!r}"
        )

    async def test_fetch_base_one_credit(self) -> None:
        from polyweb.models.contracts import FetchRequest as FetchReq

        client = httpx.AsyncClient(timeout=30.0)
        try:
            adapter = FirecrawlAdapter(client, sdk_client=object())
            estimate = await adapter.estimate_cost(
                FetchReq(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://example.com/doc",
                )
            )
        finally:
            await client.aclose()
        assert estimate.units == Decimal("1"), (
            f"AC-FC-3: base fetch must cost 1 credit, saw {estimate.units!r}"
        )

    @pytest.mark.parametrize(
        ("pdf", "json_extract", "enhanced", "zdr", "credits"),
        [(0, False, False, False, 1), (2, False, False, False, 3), (0, True, False, False, 5)],
    )
    async def test_fetch_estimate_matches_executed_options(
        self,
        pdf: int,
        json_extract: bool,
        enhanced: bool,
        zdr: bool,
        credits: int,
    ) -> None:
        # T-6 (estimate≡executed options): the estimate must read the same
        # FetchRequest options an executed fetch would bill.
        from polyweb.models.contracts import FetchRequest as FetchReq

        client = httpx.AsyncClient(timeout=30.0)
        try:
            adapter = FirecrawlAdapter(client, sdk_client=object())
            request = FetchReq(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://example.com/doc",
                pdf_pages=pdf,
                json_extract=json_extract,
                enhanced=enhanced,
                zero_data_retention=zdr,
            )
            estimate = await adapter.estimate_cost(request)
        finally:
            await client.aclose()
        modifiers = (
            Decimal(pdf) + Decimal("4") * int(json_extract) + Decimal("4") * int(enhanced)
        ) + Decimal("1") * int(zdr)
        assert fetch_credits(Decimal("1"), modifiers) == Decimal(credits), (
            "AC-FC-3 setup: pricing-function cross-check out of sync with the row"
        )
        assert estimate.units == Decimal(credits), (
            f"AC-FC-3: estimate must equal the executed-option price "
            f"({credits} credits for pdf={pdf} json={json_extract} "
            f"enhanced={enhanced} zdr={zdr}), saw {estimate.units!r}"
        )
        assert str(estimate.currency).upper().startswith("CREDIT"), (
            f"AC-FC-3: Firecrawl estimates are credits, saw {estimate.currency!r}"
        )


# --------------------------------------------------------------------------
# AC-5/AC-PA: cost estimates
# --------------------------------------------------------------------------


class TestCostEstimates:
    async def test_keenable_keyed_usd_estimate(self) -> None:
        client = httpx.AsyncClient(timeout=30.0)
        try:
            adapter = KeenableAdapter(client, api_key=TEST_API_KEY)
            estimate = await adapter.estimate_cost(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=3)
            )
        finally:
            await client.aclose()
        assert estimate.units == Decimal("0.004"), (
            f"AC-5: keyed Keenable estimate must be USD 0.004, saw {estimate.units!r}"
        )
        assert estimate.currency == "USD", f"AC-5: currency must be USD, saw {estimate.currency!r}"

    async def test_parallel_default_search_usd(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        adapter: ParallelAdapter | None = None
        try:
            adapter = ParallelAdapter(client, api_key=TEST_API_KEY)
            estimate = await adapter.estimate_cost(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=3)
            )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
        assert estimate.currency == "USD", (
            f"AC-PA-2: Parallel estimates must be USD, saw {estimate.currency!r}"
        )
        assert estimate.units == Decimal("0.005"), (
            f"AC-PA-2: omitted/default-advanced search must be USD 0.005, saw {estimate.units!r}"
        )

    @pytest.mark.parametrize(
        ("mode", "bundles", "expected"),
        [
            (None, 0, "0.005"),
            ("omitted", 0, "0.005"),
            ("turbo", 0, "0.001"),
            ("basic", 0, "0.005"),
            ("advanced", 2, "0.007"),
        ],
    )
    def test_parallel_search_price_table(
        self, mode: str | None, bundles: int, expected: str
    ) -> None:
        # T-5: the documented pricing function prices every mode directly.
        from polyweb.adapters.parallel import search_cost_usd

        assert search_cost_usd(mode, bundles) == Decimal(expected), (
            f"AC-PA-2: search_cost_usd({mode!r}, {bundles}) must be USD {expected}"
        )

    @pytest.mark.parametrize(("urls", "expected"), [(1, "0.001"), (4, "0.004")])
    def test_parallel_extract_price_projection(self, urls: int, expected: str) -> None:
        # T-3: url_count prices per URL; counts above 1 are projection-only
        # until a batch fetch path exists (executable path is 1 URL).
        from polyweb.adapters.parallel import extract_cost_usd

        assert extract_cost_usd(urls) == Decimal(expected), (
            f"AC-PA-2: extract_cost_usd({urls}) must be USD {expected}"
        )

    async def test_parallel_mode_aware_estimate_cost(self) -> None:
        # T-5: estimate_cost driven with the P1-6 mode-aware request contract.
        from pydantic import ValidationError

        from polyweb.adapters.parallel import search_cost_usd

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        adapter: ParallelAdapter | None = None
        try:
            adapter = ParallelAdapter(client, api_key=TEST_API_KEY)
            try:
                request = SearchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    query="q",
                    limit=3,
                    mode="turbo",
                    extra_bundles=0,
                )
            except ValidationError as exc:
                raise AssertionError(
                    "AC-PA-2: SearchRequest lacks the mode-aware estimate "
                    f"contract (P1-6: mode/extra_bundles fields): {exc}"
                ) from exc
            estimate = await adapter.estimate_cost(request)
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
        assert estimate.units == search_cost_usd("turbo", 0) == Decimal("0.001"), (
            f"AC-PA-2: turbo estimate must equal the documented price, saw {estimate.units!r}"
        )
        assert estimate.currency == "USD", (
            f"AC-PA-2: Parallel estimates must be USD, saw {estimate.currency!r}"
        )


# --------------------------------------------------------------------------
# Keenable 402/429 error semantics (AC-5)
# --------------------------------------------------------------------------


def _keenable_client(status: int) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": f"HTTP {status}"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)


class TestKeenableErrors:
    async def test_402_hard_exhaustion_recorded(self, repo: SQLiteRepository) -> None:
        client = _keenable_client(402)
        try:
            adapter = KeenableAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError) as exc_info:
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
        finally:
            await client.aclose()
        assert exc_info.value.error.retryable is False, "AC-5: keyed 402 is non-retryable"
        assert exc_info.value.error.status_code == 402, "AC-5: 402 status must survive"
        latest = await repo.latest_quota("keenable")
        assert latest is not None and latest.remaining == Decimal("0"), (
            "AC-5: keyed 402 must persist remaining=0 hard exhaustion "
            f"(saw {latest!r}); routing steers away only from recorded state"
        )

    async def test_429_never_exhaustion(self, repo: SQLiteRepository) -> None:
        client = _keenable_client(429)
        try:
            adapter = KeenableAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError) as exc_info:
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
        finally:
            await client.aclose()
        assert exc_info.value.error.retryable is True, "AC-5: 429 stays transient/retryable"
        assert await repo.latest_quota("keenable") is None, (
            "AC-5: 429 must never persist as quota exhaustion"
        )

    async def test_paid_usage_preserves_free_allowance(self, repo: SQLiteRepository) -> None:
        # T-2: a real paid call through _meta usage detail; the combined free
        # remaining becomes unknown (None) while both counters survive (D-2).
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [{"title": "k", "url": "https://example.com/k"}],
                    "_meta": {"keenable/usage": {"credits": 2, "paid": True, "sku": "search.pro"}},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        try:
            adapter = KeenableAdapter(client, api_key=TEST_API_KEY)
            response = await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="paid", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        assert response.usage is not None and response.usage.units == Decimal("2"), (
            f"AC-5 setup: paid call must report 2 credits, saw {response.usage!r}"
        )
        assert response.usage.metadata.get("paid") is True, (
            f"AC-5 setup: paid usage must carry paid=true, saw {response.usage.metadata!r}"
        )
        live = await adapter.quota()
        assert live is not None and live.remaining is None, (
            f"AC-5: combined free remaining must be unknown after paid use, saw {live!r}"
        )
        assert live.limit == Decimal("100000"), "AC-5: allowance limit must survive"
        assert live.metadata.get("free") == Decimal("100000"), (
            f"AC-5: free counter preserved separately, saw {live.metadata!r}"
        )
        assert live.metadata.get("paid") == Decimal("2"), (
            f"AC-5: paid counter preserved separately, saw {live.metadata!r}"
        )
        latest = await repo.latest_quota("keenable")
        assert latest is not None and latest.remaining is None, (
            f"AC-5: persisted remaining must be None after paid use, saw {latest!r}"
        )


# --------------------------------------------------------------------------
# AC-6: routing semantics
# --------------------------------------------------------------------------


def _health(name: str, status: HealthStatus) -> ProviderHealth:
    return ProviderHealth(provider=name, status=status, checked_at=FIXED_AT)


def _parallel_route_adapter() -> object:
    """Offline routable stand-in named exactly 'parallel'."""
    from polyweb.adapters.base import ProviderAdapter
    from polyweb.models.contracts import (
        CostEstimate,
        FetchedDocument,
        FetchRequest,
        FetchResponse,
    )

    class ParallelStub(ProviderAdapter):
        @property
        def name(self) -> str:
            return "parallel"

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(search=True, fetch=True)

        async def search(self, request: SearchRequest):  # type: ignore[no-untyped-def]
            from polyweb.models.contracts import SearchResponse as SR

            return SR(query=request.query, provider="parallel", results=[])

        async def fetch(self, request: FetchRequest):  # type: ignore[no-untyped-def]
            return FetchResponse(
                provider="parallel",
                document=FetchedDocument(url=request.url, content="", fetched_at=FIXED_AT),
            )

        async def estimate_cost(self, request):  # type: ignore[no-untyped-def]
            operation = (
                UsageOperation.SEARCH
                if isinstance(request, SearchRequest)
                else UsageOperation.FETCH
            )
            return CostEstimate(provider="parallel", operation=operation, units=Decimal("0"))

    return ParallelStub()


class TestRoutingSemantics:
    def _adapters(self) -> list:
        from polyweb.adapters.base import ProviderAdapter
        from polyweb.models.contracts import (
            CostEstimate,
            FetchedDocument,
            FetchRequest,
            FetchResponse,
        )

        class Stub(ProviderAdapter):
            def __init__(self, name: str) -> None:
                self._name = name

            @property
            def name(self) -> str:
                return self._name

            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(search=True, fetch=True)

            async def search(self, request: SearchRequest):  # type: ignore[no-untyped-def]
                from polyweb.models.contracts import SearchResponse as SR

                return SR(query=request.query, provider=self._name, results=[])

            async def fetch(self, request: FetchRequest):  # type: ignore[no-untyped-def]
                return FetchResponse(
                    provider=self._name,
                    document=FetchedDocument(url=request.url, content="", fetched_at=FIXED_AT),
                )

            async def estimate_cost(self, request):  # type: ignore[no-untyped-def]
                operation = (
                    UsageOperation.SEARCH
                    if isinstance(request, SearchRequest)
                    else UsageOperation.FETCH
                )
                return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

        return [Stub("tavily"), Stub("brave")]

    def test_hard_exhaustion_excluded(self) -> None:
        adapters = self._adapters()
        quota = {
            "tavily": QuotaSnapshot(
                provider="tavily",
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("0"),
                limit=Decimal("100"),
                observed_at=FIXED_AT,
            )
        }
        health = {"tavily": _health("tavily", HealthStatus.HEALTHY)}
        route = select_route(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
            adapters,
            health,
            quota,
        )
        names = [c.adapter.name for c in route]
        assert "tavily" not in names, f"AC-6: hard exhaustion must steer away: {names!r}"
        assert names[0] == "brave", f"AC-6: fallback must lead: {names!r}"

    def test_unknown_quota_eligible(self) -> None:
        adapters = self._adapters()
        names = [
            c.adapter.name
            for c in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                adapters,
                {},
                {},
            )
        ]
        assert names == ["tavily", "brave"], (
            f"AC-6: unknown quota must stay eligible, never 0: {names!r}"
        )

    def test_genuine_depletion_hard_excluded(self) -> None:
        # T-6: AUTHORITATIVE depletion with a unit kind and no soft markers is
        # genuine exhaustion and must steer routing away.
        adapters = self._adapters()
        quota = {
            "tavily": QuotaSnapshot(
                provider="tavily",
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("0"),
                limit=Decimal("100"),
                observed_at=FIXED_AT,
                unit_kind=_opt(_unit_kind(), "CREDIT"),
                display_unit="credits",
                metadata={},
            )
        }
        health = {"tavily": _health("tavily", HealthStatus.HEALTHY)}
        names = [
            c.adapter.name
            for c in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                adapters,
                health,
                quota,
            )
        ]
        assert "tavily" not in names, f"AC-6: genuine depletion must steer away: {names!r}"
        assert names[0] == "brave", f"AC-6: fallback must lead: {names!r}"

    def test_parallel_estimated_zero_stays_routable(self) -> None:
        # T-6: a Parallel ESTIMATED zero is a soft signal, never a hard lockout.
        quota = {
            "parallel": QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("0"),
                observed_at=FIXED_AT,
            )
        }
        names = [
            c.adapter.name
            for c in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                [_parallel_route_adapter()],
                {},
                quota,
            )
        ]
        assert names == ["parallel"], (
            f"AC-6/AC-PA-5: Parallel soft zero must stay routable, saw {names!r}"
        )

    def test_keyless_local_hourly_zero_stays_routable(self) -> None:
        # The local keyless counter cannot observe shared traffic from the
        # same IP/pool, so 0/1000 is pressure metadata rather than hard
        # exhaustion; a vendor 429 remains the authoritative signal.
        adapters = self._adapters()
        adapters[0]._name = "keenable"  # type: ignore[attr-defined]
        quota = {
            "keenable": QuotaSnapshot(
                provider="keenable",
                source=QuotaSource.OBSERVED,
                remaining=Decimal("0"),
                limit=Decimal("1000"),
                observed_at=FIXED_AT,
                unit_kind=_opt(_unit_kind(), "REQUEST"),
                display_unit="requests",
                metadata={
                    "mode": "keyless",
                    "window": "hourly",
                    "scope": "shared_pool_local_observation",
                },
            )
        }
        health = {"keenable": _health("keenable", HealthStatus.HEALTHY)}
        names = [
            candidate.adapter.name
            for candidate in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                adapters,
                health,
                quota,
            )
        ]
        assert names[0] == "keenable", (
            "AC-6: keyless local 0/1000 must stay eligible despite shared-pool uncertainty"
        )

    async def test_soft_zero_clears_on_success(self, repo: SQLiteRepository) -> None:
        # AC-6/AC-PA-5 through the real effective-quota view: a Parallel soft
        # zero recorded before a later billed success resolves to unknown.
        kind = _unit_kind()
        await repo.record_quota(
            QuotaSnapshot(
                provider="parallel",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("0"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            )
        )
        await repo.record_usage(
            UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.005"),
                observed_at=FIXED_AT + timedelta(seconds=60),
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )
        view = await effective_quota(repo, "parallel")
        assert view is not None and view.remaining is None, (
            f"AC-6: soft zero must clear after later billed success, saw {view!r}"
        )
        names = [
            c.adapter.name
            for c in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                [_parallel_route_adapter()],
                {},
                {"parallel": view},
            )
        ]
        assert names == ["parallel"], (
            f"AC-6: Parallel must route again once the soft zero clears: {names!r}"
        )


# --------------------------------------------------------------------------
# AC-8: privacy + bounded polling TTL range
# --------------------------------------------------------------------------


class TestCompatibilityPrivacy:
    async def test_credential_metadata_rejected(self, repo: SQLiteRepository) -> None:
        with pytest.raises(ValueError):
            await repo.record_usage(
                UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=FIXED_AT,
                    metadata={"api_key": "sk-never-persist"},
                ),
                attribution=await seed_execution_project(repo),
            )
        assert await repo.list_provider_usage(provider="tavily") == [], (
            "AC-8: rejected credential write must persist nothing"
        )

    @pytest.mark.parametrize(
        "metadata",
        [
            {"api_key": 12345},
            {"authorization": ["Bearer", "sekret"]},
            {"mode": "keyed", "api_key": {"nested": "sekret"}},
        ],
    )
    async def test_non_string_credential_rejected(
        self, repo: SQLiteRepository, metadata: dict
    ) -> None:
        # T-6: secrets smuggled as non-string JSON must be rejected exactly
        # like plain-string credentials.
        with pytest.raises(ValueError):
            await repo.record_usage(
                UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=FIXED_AT,
                    metadata=metadata,
                ),
                attribution=await seed_execution_project(repo),
            )
        assert await repo.list_provider_usage(provider="tavily") == [], (
            "AC-8: rejected credential write must persist nothing"
        )

    async def test_non_string_metadata_key_rejected(self, repo: SQLiteRepository) -> None:
        with pytest.raises(ValueError):
            await repo.record_usage(
                UsageEvent(
                    provider="tavily",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=FIXED_AT,
                    metadata={(1, 2): "x"},  # type: ignore[dict-item]
                ),
                attribution=await seed_execution_project(repo),
            )

    async def test_quota_metadata_public_round_trip(self, repo: SQLiteRepository) -> None:
        # T-6, behavioral only: quota routing metadata must survive a public
        # record_quota/latest_quota round-trip. No approved storage column
        # exists yet, so this documents the schema-plan gap without reaching
        # into private row state.
        kind = _unit_kind()
        recorded = {"free": Decimal("99995"), "paid": Decimal("2")}
        await repo.record_quota(
            QuotaSnapshot(
                provider="keenable",
                source=QuotaSource.OBSERVED,
                remaining=None,
                limit=Decimal("100000"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "CREDIT"),
                display_unit="credits",
                metadata=dict(recorded),
            )
        )
        latest = await repo.latest_quota("keenable")
        assert latest is not None, "AC-8 setup: recorded quota snapshot missing"
        assert dict(latest.metadata) == recorded, (
            "AC-8: quota snapshot metadata must survive a public round-trip "
            "(pending explicit schema-plan approval for a metadata column); "
            f"saw {latest.metadata!r}"
        )

    def test_poll_ttl_bounds(self) -> None:
        # SEAM PROBE (AC-8/AC-FC-4): bounded TTL inside 60-300 seconds.
        ttl = _opt(monitoring_module, "QUOTA_POLL_TTL_SECONDS", None)
        if ttl is None:
            poller = _opt(monitoring_module, "QuotaPoller", None)
            ttl = _opt(poller, "ttl_seconds", None) if poller is not None else None
        assert ttl is not None, (
            "AC-8: no bounded quota-poll TTL found on polyweb.monitoring "
            "(expected e.g. QUOTA_POLL_TTL_SECONDS within 60-300s; polling must "
            "be on-demand/cached, never per request)"
        )
        assert 60 <= int(ttl) <= 300, f"AC-8: TTL must sit within 60-300s (saw {ttl!r})"

    def test_error_details_carry_no_secrets(self) -> None:
        error = ProviderError(provider="tavily", code="http_error", message="HTTP 429")
        assert "sk-" not in error.model_dump_json(), "AC-8: errors must stay redaction-safe"


# --------------------------------------------------------------------------
# T-6: poll failure-safety + unseeded Parallel ledger (AC-1/AC-8/AC-PA-3)
# --------------------------------------------------------------------------


class _QuotaStub:
    """Offline quota-capable adapter double for poll failure-safety."""

    def __init__(self, name: str, snapshot: QuotaSnapshot) -> None:
        from polyweb.adapters.base import ProviderAdapter

        class Stub(ProviderAdapter):
            @property
            def name(self) -> str:
                return name

            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(search=True, fetch=True, quota=True)

            async def search(self, request: SearchRequest):  # type: ignore[no-untyped-def]
                from polyweb.models.contracts import SearchResponse as SR

                return SR(query=request.query, provider=name, results=[])

            async def fetch(self, request):  # type: ignore[no-untyped-def]

                del request
                raise NotImplementedError

            async def estimate_cost(self, request):  # type: ignore[no-untyped-def]
                from polyweb.models.contracts import CostEstimate as CE

                operation = (
                    UsageOperation.SEARCH
                    if isinstance(request, SearchRequest)
                    else UsageOperation.FETCH
                )
                return CE(provider=name, operation=operation, units=Decimal("0"))

            async def quota(self) -> QuotaSnapshot:
                return snapshot

        self._stub = Stub()

    def __getattr__(self, name: str) -> object:
        return getattr(self._stub, name)


class _FailingRecordRepo:
    """Delegating repository whose record_quota raises for one provider."""

    def __init__(self, real: SQLiteRepository, failing_provider: str) -> None:
        self._real = real
        self._failing_provider = failing_provider

    async def record_quota(self, snapshot: QuotaSnapshot) -> None:
        if snapshot.provider == self._failing_provider:
            raise RuntimeError("simulated quota write outage")
        await self._real.record_quota(snapshot)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class TestPollFailureSafety:
    async def test_failing_write_does_not_break_poll_or_routing(
        self, repo: SQLiteRepository
    ) -> None:
        # T-6: a write outage for one provider must not abort the bounded poll;
        # routing still works from whatever state survived.
        cache = _opt(monitoring_module, "_quota_poll_cache", None)
        if cache is not None:
            cache.clear()
        adapters = [
            _QuotaStub(
                name,
                QuotaSnapshot(
                    provider=name,
                    source=QuotaSource.AUTHORITATIVE,
                    remaining=Decimal("10"),
                    limit=Decimal("100"),
                    observed_at=FIXED_AT,
                ),
            )
            for name in ("tavily", "brave")
        ]
        flaky = _FailingRecordRepo(repo, "tavily")
        try:
            snapshots = await refresh_quotas(flaky, adapters, force=True)
        except RuntimeError as exc:
            raise AssertionError(
                "AC-1/AC-8: a failing record_quota for one provider must not "
                f"abort the bounded poll: {exc}"
            ) from exc
        providers = {snapshot.provider for snapshot in snapshots}
        assert "brave" in providers, (
            "AC-1/AC-8: the healthy provider's snapshot must survive a sibling "
            f"write outage, saw {providers!r}"
        )
        quota = {snapshot.provider: snapshot for snapshot in snapshots}
        health = {
            name: ProviderHealth(provider=name, status=HealthStatus.HEALTHY, checked_at=FIXED_AT)
            for name in ("tavily", "brave")
        }
        names = [
            candidate.adapter.name
            for candidate in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                [a._stub for a in adapters],
                health,
                quota,
            )
        ]
        assert "brave" in names, (
            f"AC-6/AC-8: routing must still route from surviving state, saw {names!r}"
        )


class TestUnseededParallelLedger:
    async def test_unseeded_spend_reports_unknown(self, repo: SQLiteRepository) -> None:
        # T-6/AC-PA-3: without an enabled seed, spend is tracked but no
        # balance may be fabricated; remaining/limit stay unknown.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        adapter: ParallelAdapter | None = None
        try:
            adapter = ParallelAdapter(client, api_key=TEST_API_KEY)
            assert adapter.record_success_spend(Decimal("1.25")) is None, (
                "AC-PA-3: unseeded spend must not materialize a snapshot"
            )
            assert await adapter.quota() is None, (
                "AC-PA-3: unseeded accounts report no quota snapshot"
            )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
        latest = await repo.latest_quota("parallel")
        assert latest is None or (latest.remaining is None and latest.limit is None), (
            f"AC-PA-3: unseeded spend must leave remaining/limit unknown, saw {latest!r}"
        )


# --------------------------------------------------------------------------
# ITERATION 2: persisted Parallel fetch usage (R2 guard — url_count metadata)
# --------------------------------------------------------------------------


def _parallel_extract_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "extract_id": "ex-r2",
            "results": [
                {
                    "url": "https://example.com/doc",
                    "full_content": "extracted body",
                }
            ],
            "usage": [{"sku": "extract", "count": 1}],
        },
    )


class TestParallelFetchUsagePersistence:
    async def test_fetch_usage_event_persists_url_count(self, repo: SQLiteRepository) -> None:
        # R2 guard: the executed-fetch usage event carries url_count in
        # metadata, and the metadata filter must let it through — otherwise
        # persisted spend ledgers silently lose the batch dimension.
        from polyweb.models.contracts import FetchRequest as FetchReq
        from polyweb.services.monitoring import tracked_call as tracked

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_parallel_extract_handler), timeout=30.0
        )
        adapter: ParallelAdapter | None = None
        try:
            adapter = ParallelAdapter(client, api_key=TEST_API_KEY)
            response = await tracked(
                repo,
                adapter,
                lambda running: running.fetch(
                    FetchReq(
                        project_id="00000000-0000-4000-8000-0000000000aa",
                        url="https://example.com/doc",
                        url_count=4,
                    )
                ),
                operation=UsageOperation.FETCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
        assert response.usage is not None, "AC-PA-1 setup: fetch must report usage"
        assert response.usage.metadata.get("url_count") == 4, (
            f"AC-PA-1 setup: executed fetch must tag url_count=4, saw {response.usage.metadata!r}"
        )
        events = await repo.list_provider_usage(provider="parallel", operation=UsageOperation.FETCH)
        assert len(events) == 1, f"AC-PA-1/R2: fetch usage must persist, saw {events!r}"
        assert events[0].metadata.get("url_count") == 4, (
            "AC-PA-1/R2: url_count must survive the metadata filter and the "
            f"storage round-trip as int 4, saw {events[0].metadata!r}"
        )
        assert isinstance(events[0].metadata.get("url_count"), int), (
            "AC-PA-1/R2: url_count must keep its int type (spend math does "
            "int(url_count); a string would price but mislead)"
        )


# --------------------------------------------------------------------------
# ITERATION 2: Keenable rebuild persistence — rollover, hydration,
# 402-persistence across adapter rebuild (R3 guards)
# --------------------------------------------------------------------------


def _keenable_search_handler(usage_meta: dict | None = None, *, status: int = 200) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": f"HTTP {status}"})
        payload: dict = {"results": [{"title": "k", "url": "https://example.com/k"}]}
        if usage_meta is not None:
            payload["_meta"] = {"keenable/usage": usage_meta}
        return httpx.Response(200, json=payload)

    return handler


async def _keenable_hydrated(adapter: object, repo: SQLiteRepository) -> object:
    """Rebuild adapter quota state from persisted snapshots/ledger (R3 seam)."""
    hydrate = _opt(adapter, "hydrate_quota", None)
    assert hydrate is not None, (
        "AC-5/R3: KeenableAdapter.hydrate_quota(repository) missing — allowance "
        "spend, paid counters, and 402 exhaustion live only in memory, so an "
        "adapter rebuild (restart/redeploy) forgets them. Hydration must "
        "rebuild state from persisted snapshots and the usage ledger."
    )
    return await hydrate(repo)


class TestKeenableRebuildPersistence:
    async def test_hydration_restores_spend_across_rebuild(self, repo: SQLiteRepository) -> None:
        from polyweb.services.monitoring import tracked_call as tracked

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_keenable_search_handler()), timeout=30.0
        )
        try:
            first = KeenableAdapter(client, api_key=TEST_API_KEY)
            for _ in range(3):
                await tracked(
                    repo,
                    first,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
            assert (await first.quota()).remaining == Decimal("99997")
            rebuilt = KeenableAdapter(client, api_key=TEST_API_KEY)
            assert (await rebuilt.quota()).remaining == Decimal("100000"), (
                "R3 setup: a rebuilt adapter starts amnesiac (full allowance)"
            )
            await _keenable_hydrated(rebuilt, repo)
        finally:
            await client.aclose()
        assert (await rebuilt.quota()).remaining == Decimal("99997"), (
            "AC-5/R3: hydration must restore the persisted 3-credit spend across rebuild"
        )

    async def test_402_exhaustion_survives_rebuild(self, repo: SQLiteRepository) -> None:
        from polyweb.infrastructure.resilience import ProviderOperationError as OpError
        from polyweb.services.monitoring import tracked_call as tracked

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_keenable_search_handler(status=402)),
            timeout=30.0,
        )
        try:
            first = KeenableAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(OpError):
                await tracked(
                    repo,
                    first,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
            assert (await first.quota()).remaining == Decimal("0")
            rebuilt = KeenableAdapter(client, api_key=TEST_API_KEY)
            await _keenable_hydrated(rebuilt, repo)
        finally:
            await client.aclose()
        assert (await rebuilt.quota()).remaining == Decimal("0"), (
            "AC-5/R3: 402 hard exhaustion must persist across rebuild — a "
            "restart must not resurrect a depleted allowance into routing"
        )

    async def test_allowance_rolls_over_at_month_boundary(self, repo: SQLiteRepository) -> None:
        # Last month's spend must not leak into the new month's allowance:
        # only current-month ledger activity counts after hydration.
        kind = _unit_kind()
        last_month = datetime(2026, 2, 15, 12, 0, tzinfo=UTC)
        for index in range(5):
            await repo.record_usage(
                UsageEvent(
                    provider="keenable",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=last_month + timedelta(seconds=index),
                    status=UsageStatus.SUCCESS,
                    unit_kind=_opt(kind, "CREDIT"),
                    display_unit="credits",
                ),
                attribution=await seed_execution_project(repo),
            )
        await repo.record_quota(
            QuotaSnapshot(
                provider="keenable",
                source=QuotaSource.OBSERVED,
                remaining=Decimal("99995"),
                limit=Decimal("100000"),
                observed_at=last_month + timedelta(seconds=60),
                unit_kind=_opt(kind, "CREDIT"),
                display_unit="credits",
            )
        )
        client = httpx.AsyncClient(timeout=30.0)
        try:
            rebuilt = KeenableAdapter(client, api_key=TEST_API_KEY)
            await _keenable_hydrated(rebuilt, repo)
        finally:
            await client.aclose()
        assert (await rebuilt.quota()).remaining == Decimal("100000"), (
            "AC-5/R3: hydration after a month boundary must roll the allowance "
            "over (last month's 5-credit spend expired), saw "
            f"{(await rebuilt.quota()).remaining!r}"
        )


# --------------------------------------------------------------------------
# ITERATION 2: metadata type preservation (critic extra)
# --------------------------------------------------------------------------


class TestMetadataTypePreservation:
    async def test_int_and_bool_and_none_round_trip_exactly(self, repo: SQLiteRepository) -> None:
        await repo.record_usage(
            UsageEvent(
                provider="alpha",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT,
                metadata={"count": 4, "paid": False, "missing": None},
            ),
            attribution=await seed_execution_project(repo),
        )
        (event,) = await repo.list_provider_usage(provider="alpha")
        assert event.metadata["count"] == 4 and isinstance(event.metadata["count"], int)
        assert event.metadata["paid"] is False
        assert event.metadata["missing"] is None

    async def test_numeric_strings_never_coerce_to_numbers(self, repo: SQLiteRepository) -> None:
        # A numeric string is telemetry text, not a number: "4" must come back
        # as str (never int), "0.005" as str (never float/Decimal).
        await repo.record_usage(
            UsageEvent(
                provider="alpha",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT,
                metadata={"label": "4", "price_text": "0.005"},
            ),
            attribution=await seed_execution_project(repo),
        )
        (event,) = await repo.list_provider_usage(provider="alpha")
        assert event.metadata["label"] == "4" and isinstance(event.metadata["label"], str), (
            f"numeric strings must not coerce to numbers, saw {event.metadata!r}"
        )
        assert event.metadata["price_text"] == "0.005" and isinstance(
            event.metadata["price_text"], str
        ), f"numeric strings must not coerce to numbers, saw {event.metadata!r}"

    async def test_decimal_never_contaminates_with_float(self, repo: SQLiteRepository) -> None:
        await repo.record_usage(
            UsageEvent(
                provider="alpha",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT,
                metadata={"mode": "keyed", "price": Decimal("1.25")},
            ),
            attribution=await seed_execution_project(repo),
        )
        (event,) = await repo.list_provider_usage(provider="alpha")
        back = event.metadata["price"]
        assert not isinstance(back, float), (
            f"Decimal telemetry must never round-trip through float, saw {back!r}"
        )
        assert back in (Decimal("1.25"), "1.25"), (
            "Decimal telemetry must survive exactly (as Decimal once storage "
            f"preserves types, else as its exact decimal string), saw {back!r}"
        )


# --------------------------------------------------------------------------
# ITERATION 2: quota-poll backoff + poll-state eviction via public API
# --------------------------------------------------------------------------


class TestQuotaPollBackoffAndEviction:
    async def test_quota_poll_backs_off_on_429_then_succeeds(self) -> None:
        # Failure backoff through the public ResilientRunner seams (injected
        # clock/sleeper, deterministic jitter): two 429s on the quota poll
        # sleep capped exponential backoff, then the poll succeeds.
        from polyweb.adapters.youcom import YoucomAdapter
        from polyweb.infrastructure.resilience import ResilientRunner

        sleeps: list[float] = []

        async def sleeper(delay: float) -> None:
            sleeps.append(delay)

        responses = [
            httpx.Response(429, json={}),
            httpx.Response(429, json={}),
            httpx.Response(200, json={"data": {"attributes": {"balance": 50}}}),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        caller = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        clock = [0.0]
        adapter: YoucomAdapter | None = None
        try:
            runner = ResilientRunner(
                caller,
                max_attempts=3,
                base_delay=1.0,
                max_delay=10.0,
                backoff_factor=2.0,
                clock=lambda: clock[0],
                sleeper=sleeper,
                random_source=lambda: 1.0,
            )
            adapter = YoucomAdapter(caller, runner=runner, api_key=TEST_API_KEY)
            try:
                snapshot = await adapter.quota()
            finally:
                if adapter is not None:
                    await adapter.aclose()
        finally:
            await caller.aclose()
        assert snapshot.remaining == Decimal("0.50"), (
            f"quota poll must succeed after backoff, saw {snapshot.remaining!r}"
        )
        assert sleeps == [1.0, 2.0], (
            f"quota 429s must sleep capped exponential backoff [1.0, 2.0], saw {sleeps!r}"
        )

    async def test_poll_state_eviction_forces_repoll(self, repo: SQLiteRepository) -> None:
        # Lock/cache eviction through the public seam: after eviction the next
        # bounded poll must hit vendors again instead of serving stale state.
        from polyweb.services.monitoring import clear_quota_poll_cache, refresh_quotas

        calls: list[str] = []

        class Stub:
            def __init__(self, name: str) -> None:
                self._name = name

            @property
            def name(self) -> str:
                return self._name

            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(search=True, fetch=True, quota=True)

            async def quota(self) -> QuotaSnapshot:
                calls.append(self._name)
                return QuotaSnapshot(
                    provider=self._name,
                    source=QuotaSource.AUTHORITATIVE,
                    remaining=Decimal("9"),
                    limit=Decimal("10"),
                    observed_at=FIXED_AT,
                )

        adapters = [Stub("tavily"), Stub("brave")]
        clear_quota_poll_cache()
        await refresh_quotas(repo, adapters, force=True)
        assert sorted(calls) == ["brave", "tavily"]
        await refresh_quotas(repo, adapters)
        assert sorted(calls) == ["brave", "tavily"], "second poll must reuse the TTL cache"
        clear_quota_poll_cache()
        await refresh_quotas(repo, adapters)
        assert sorted(calls) == ["brave", "brave", "tavily", "tavily"], (
            f"post-eviction poll must re-hit vendors, saw {calls!r}"
        )


# --------------------------------------------------------------------------
# ITERATION 3: legacy unknown-mode hydration (Critic OBJECT-2)
# --------------------------------------------------------------------------


class TestParallelHydrationUnknownMode:
    async def test_hydrate_skips_unknown_legacy_mode(self, repo: SQLiteRepository) -> None:
        """Critic OBJECT-2: an unrecognized mode must not break hydration.

        A legacy/request row carrying a mode the price table never defined
        (forward-compat: a newer mode written before this code knew it) must
        be skipped — never raise out of hydrate_quota — while the
        current-month spend from well-formed rows is preserved exactly.
        """
        now = datetime.now(UTC)
        kind = _unit_kind()

        def row(*, mode: str, observed_at: datetime) -> UsageEvent:
            return UsageEvent(
                provider="parallel",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=observed_at,
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "REQUEST"),
                display_unit="requests",
                metadata={
                    "skus": [{"sku": "search", "count": 1}],
                    "mode": mode,
                    "extra_bundles": 0,
                },
            )

        await repo.record_usage(
            row(mode="turbo", observed_at=now), attribution=await seed_execution_project(repo)
        )
        await repo.record_usage(
            row(mode="ultra-mega", observed_at=now),
            attribution=await seed_execution_project(repo),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        adapter: ParallelAdapter | None = None
        try:
            adapter = ParallelAdapter(client, free_seed=Decimal("5.00"), api_key=TEST_API_KEY)
            try:
                snapshot = await adapter.hydrate_quota(repo)
            except ValueError as exc:
                raise AssertionError(
                    "AC-PA-3: hydrate_quota must skip (and report) rows with an "
                    "unknown legacy mode instead of raising out of hydration; "
                    f"current-month spend is lost with it: {exc}"
                ) from exc
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
        assert snapshot is not None, "AC-PA-3 setup: seeded hydration must produce a snapshot"
        # Only the well-formed turbo row prices: 5.00 - 0.001.
        assert snapshot.remaining == Decimal("4.999"), (
            "AC-PA-3: unknown-mode rows contribute no spend; the known "
            f"current-month row must price exactly, saw {snapshot.remaining!r}"
        )


# --------------------------------------------------------------------------
# Brave derived USD spend (manual dashboard math, no scraping)
# --------------------------------------------------------------------------


def _brave_search_handler(headers: dict[str, str]) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"web": {"results": [{"title": "t", "url": "https://example.com/t"}]}},
            headers=headers,
        )

    return handler


class TestBraveDerivedSpend:
    def test_cost_constants_are_decimal_exact(self) -> None:
        cost = _opt(brave_module, "COST_USD_PER_REQUEST", None)
        allowance = _opt(brave_module, "FREE_CREDITS_USD", None)
        assert cost is not None, "Brave COST_USD_PER_REQUEST missing"
        assert allowance is not None, "Brave FREE_CREDITS_USD missing"
        assert cost == Decimal("0.005"), f"Brave cost must be 0.005, saw {cost!r}"
        assert allowance == Decimal("5.00"), f"Brave allowance must be 5.00, saw {allowance!r}"
        assert isinstance(cost, Decimal) and isinstance(allowance, Decimal), (
            "Brave cost constants must stay Decimal-exact, never float"
        )
        assert not isinstance(cost, float) and not isinstance(allowance, float)

    def test_spend_helper_is_decimal_exact(self) -> None:
        spend = _opt(brave_module, "brave_spend_usd", None)
        assert spend is not None, "Brave brave_spend_usd helper missing"
        assert spend(176) == Decimal("0.88"), f"176 reqs must cost 0.88, saw {spend(176)!r}"
        assert spend(0) == Decimal("0"), "zero requests must cost zero"
        assert spend(1000) == Decimal("5.00"), "1000 reqs must cost exactly the allowance"
        assert isinstance(spend(176), Decimal), "spend must stay Decimal-exact"

    @staticmethod
    @pytest.mark.parametrize("bad", [True, False, 1.5, "176", None, float("nan")])
    def test_spend_helper_rejects_non_decimal_inputs(bad: object) -> None:
        spend = _opt(brave_module, "brave_spend_usd", None)
        assert spend is not None, "Brave brave_spend_usd helper missing"
        with pytest.raises((TypeError, ValueError)):
            spend(bad)  # type: ignore[arg-type]

    @staticmethod
    @pytest.mark.parametrize("bad", [-1, Decimal("-1"), Decimal("NaN"), Decimal("1.5")])
    def test_spend_helper_rejects_bad_counts(bad: object) -> None:
        spend = _opt(brave_module, "brave_spend_usd", None)
        assert spend is not None, "Brave brave_spend_usd helper missing"
        with pytest.raises((TypeError, ValueError)):
            spend(bad)  # type: ignore[arg-type]

    async def test_snapshot_keeps_throttle_but_carries_cost_metadata(self) -> None:
        from polyweb.adapters.brave import BraveAdapter

        headers = {"X-RateLimit-Remaining": "49, 0", "X-RateLimit-Limit": "50, 0"}
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            response = await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            )
        finally:
            await client.aclose()
        snapshot = response.quota_snapshot
        assert snapshot is not None, "AC-2 setup: Brave snapshot missing"
        assert snapshot.remaining is None and snapshot.limit is None, (
            f"AC-2: unlimited 0/0 stays None/None, saw {snapshot.remaining!r}/{snapshot.limit!r}"
        )
        assert str(_opt(snapshot, "unit_kind")) == "REQUEST", "AC-2: unit stays REQUEST"
        assert snapshot.source == QuotaSource.OBSERVED, "AC-2: source stays OBSERVED"
        assert _opt(snapshot, "window", None) == "monthly", "AC-2: window stays monthly"
        assert snapshot.remaining_percent is None, "AC-7a: unlimited Brave has no percent"
        metadata = dict(_opt(snapshot, "metadata", None) or {})
        assert metadata.get("cost_per_req") == Decimal("0.005"), (
            f"spend metadata must carry cost_per_req 0.005, saw {metadata!r}"
        )
        assert metadata.get("allowance_usd") == Decimal("5.00"), (
            f"spend metadata must carry allowance 5.00, saw {metadata!r}"
        )

    async def test_collect_stats_projects_176_requests_to_088(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.brave import BraveAdapter

        kind = _unit_kind()
        for index in range(175):
            await repo.record_usage(
                UsageEvent(
                    provider="brave",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=FIXED_AT + timedelta(seconds=index),
                    status=UsageStatus.SUCCESS,
                    unit_kind=_opt(kind, "REQUEST"),
                    display_unit="requests",
                ),
                attribution=await seed_execution_project(repo),
            )
        headers = {
            "X-RateLimit-Remaining": "49, 0",
            "X-RateLimit-Limit": "50, 0",
            "X-RateLimit-Reset": "1, 0",
        }
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="spend", limit=3
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        stats = await monitoring_module.collect_stats(repo, adapter_names=["brave"])
        rows = [snap for snap in stats.latest_quota if snap.provider == "brave"]
        assert rows, "dashboard must include a Brave quota row"
        view = rows[0]
        assert view.remaining is None and view.limit is None, (
            f"unlimited throttle stays None/None, saw {view.remaining!r}/{view.limit!r}"
        )
        assert view.remaining_percent is None, "AC-7a: Brave percent stays None"
        metadata = dict(view.metadata)
        assert metadata.get("spend_usd") == Decimal("0.88") or metadata.get("spend_usd") == Decimal(
            "0.880"
        ), f"176 REQUEST successes must project spend 0.88, saw {metadata!r}"
        assert metadata.get("allowance_usd") == Decimal("5.00"), (
            f"allowance must be 5.00, saw {metadata!r}"
        )
        assert metadata.get("cost_per_req") == Decimal("0.005"), (
            f"cost_per_req must be 0.005, saw {metadata!r}"
        )
        totals = {
            (total.provider, str(total.operation), str(_opt(total, "unit_kind"))): total
            for total in await repo.installation_usage_totals()
        }
        assert totals[("brave", "search", "REQUEST")].total_units == Decimal("176"), (
            "AC-3: Brave REQUEST ledger stays exact (175 plus the tracked search)"
        )

    async def test_per_second_headroom_in_usage_metadata(self) -> None:
        from polyweb.adapters.brave import BraveAdapter

        headers = {"X-RateLimit-Remaining": "49, 0"}
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            response = await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            )
        finally:
            await client.aclose()
        assert response.usage is not None, "Brave usage missing"
        assert response.usage.metadata.get("rate_limit_remaining") == 49, (
            f"usage must carry per-second headroom 49, saw {response.usage.metadata!r}"
        )

    async def test_other_dimensions_never_inflate_brave_spend(self, repo: SQLiteRepository) -> None:
        kind = _unit_kind()
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.500"),
                observed_at=FIXED_AT,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )
        await repo.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=FIXED_AT + timedelta(seconds=1),
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "REQUEST"),
                display_unit="requests",
            ),
            attribution=await seed_execution_project(repo),
        )
        headers = {"X-RateLimit-Remaining": "49, 0", "X-RateLimit-Limit": "50, 0"}
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            from polyweb.adapters.brave import BraveAdapter

            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        stats = await monitoring_module.collect_stats(repo, adapter_names=["brave", "exa"])
        view = next(snap for snap in stats.latest_quota if snap.provider == "brave")
        assert dict(view.metadata).get("spend_usd") == Decimal("0.010"), (
            "AC-3: only Brave REQUEST units price spend (2 reqs), Exa USD must not mix, "
            f"saw {view.metadata!r}"
        )


class TestBraveExhaustionMapping:
    @staticmethod
    @pytest.mark.parametrize("code", ["CREDIT_EXHAUSTED", "QUOTA_LIMITED", "USAGE_LIMIT_EXCEEDED"])
    async def test_body_code_maps_to_quota_exhausted(code: str) -> None:
        from polyweb.adapters.brave import BraveAdapter

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"code": code})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError) as exc_info:
                await adapter.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                )
        finally:
            await client.aclose()
        assert exc_info.value.error.code == "quota_exhausted", (
            f"body {code} must map to quota_exhausted, saw {exc_info.value.error.code!r}"
        )
        assert exc_info.value.error.retryable is False, "exhaustion is non-retryable"
        assert exc_info.value.error.status_code == 402

    async def test_429_quota_limited_never_retries_as_exhaustion(self) -> None:
        from polyweb.adapters.brave import BraveAdapter

        calls: list[object] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(429, json={"code": "QUOTA_LIMITED"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError) as exc_info:
                await adapter.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                )
        finally:
            await client.aclose()
        assert exc_info.value.error.code == "quota_exhausted", (
            "PLAN rev6 line 561: 429 QUOTA_LIMITED is budget exhaustion, saw "
            f"{exc_info.value.error.code!r}"
        )
        assert exc_info.value.error.retryable is False
        assert exc_info.value.error.status_code == 429
        assert len(calls) == 1, f"budget 429 must not retry, saw {len(calls)} attempts"

    async def test_429_rate_limited_retries_as_rate_pressure(self) -> None:
        from polyweb.adapters.brave import BraveAdapter

        calls: list[object] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(429, json={"code": "RATE_LIMITED"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError) as exc_info:
                await adapter.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                )
        finally:
            await client.aclose()
        assert exc_info.value.error.code == "http_error"
        assert exc_info.value.error.retryable is True
        assert len(calls) == 3, f"rate 429 must retry, saw {len(calls)} attempts"

    async def test_quota_after_error_402_records_exhaustion_without_limit(
        self, repo: SQLiteRepository
    ) -> None:
        from polyweb.adapters.brave import BraveAdapter

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"code": "CREDIT_EXHAUSTED"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            with pytest.raises(ProviderOperationError):
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
        finally:
            await client.aclose()
        latest = await repo.latest_quota("brave")
        assert latest is not None, "402 must persist an exhaustion observation"
        assert latest.remaining == Decimal("0"), f"exhaustion remaining must be 0, saw {latest!r}"
        assert latest.limit is None, (
            f"unlimited throttle must not invent a limit on exhaustion, saw {latest.limit!r}"
        )
        assert latest.remaining_percent is None, "AC-7a: percent stays None"

    async def test_genuine_throttle_zero_still_excludes(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.base import ProviderAdapter
        from polyweb.adapters.brave import BraveAdapter
        from polyweb.models.contracts import (
            CostEstimate,
            FetchedDocument,
            FetchRequest,
            FetchResponse,
            SearchResponse,
        )

        headers = {
            "X-RateLimit-Remaining": "1, 0",
            "X-RateLimit-Limit": "60, 1000",
            "X-RateLimit-Reset": "5, 2592000",
        }
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="depleted", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        latest = await repo.latest_quota("brave")
        assert latest is not None and latest.remaining == Decimal("0"), (
            "AC-6 setup: genuine depletion must persist remaining=0"
        )
        assert latest.limit == Decimal("1000")

        class Stub(ProviderAdapter):
            def __init__(self, name: str) -> None:
                self._name = name

            @property
            def name(self) -> str:
                return self._name

            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(search=True, fetch=True)

            async def search(self, request: SearchRequest) -> SearchResponse:
                return SearchResponse(query=request.query, provider=self._name, results=[])

            async def fetch(self, request: FetchRequest) -> FetchResponse:
                return FetchResponse(
                    provider=self._name,
                    document=FetchedDocument(url=request.url, content="", fetched_at=FIXED_AT),
                )

            async def estimate_cost(self, request: object) -> CostEstimate:
                operation = (
                    UsageOperation.SEARCH
                    if isinstance(request, SearchRequest)
                    else UsageOperation.FETCH
                )
                return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

        adapters = [Stub("brave"), Stub("tavily")]
        health = {"brave": _health("brave", HealthStatus.HEALTHY)}
        names = [
            c.adapter.name
            for c in select_route(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q"),
                adapters,
                health,
                {"brave": latest},
            )
        ]
        assert "brave" not in names, f"AC-6: genuine 0/1000 must steer away: {names!r}"
        assert names[0] == "tavily", f"AC-6: fallback must lead: {names!r}"


class TestBraveMonthlyCounterLedger:
    async def test_tracked_bare_search_persists_bounded_quota(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.brave import BraveAdapter

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler({"X-RateLimit-Remaining": "49"})),
            timeout=30.0,
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        latest = await repo.latest_quota("brave")
        assert latest is not None, "bare-header search must persist a quota row"
        assert latest.remaining == Decimal("999"), f"counter must leave 999, saw {latest!r}"
        assert latest.limit == Decimal("1000")
        assert latest.source == QuotaSource.ESTIMATED
        assert latest.remaining_percent == Decimal("99.9")

    async def test_hydrate_restores_counter_after_restart(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.brave import BraveAdapter

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler({})), timeout=30.0
        )
        try:
            first = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                first,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
            rebuilt = BraveAdapter(client, api_key=TEST_API_KEY)
            snapshot = await rebuilt.hydrate_quota(repo)
        finally:
            await client.aclose()
        assert snapshot is not None, "hydrate must project the restored ledger"
        assert snapshot.remaining == Decimal("999"), (
            f"rebuilt counter must leave 999, saw {snapshot!r}"
        )
        assert snapshot.limit == Decimal("1000")

    async def test_header_limit_preferred_over_implied(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.brave import BraveAdapter

        headers = {
            "X-RateLimit-Remaining": "5, 1990",
            "X-RateLimit-Limit": "10, 2000",
            "X-RateLimit-Reset": "5, 2592000",
        }
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(_brave_search_handler(headers)), timeout=30.0
        )
        try:
            adapter = BraveAdapter(client, api_key=TEST_API_KEY)
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            await client.aclose()
        latest = await repo.latest_quota("brave")
        assert latest is not None
        assert latest.remaining == Decimal("1990")
        assert latest.limit == Decimal("2000")
        assert latest.source == QuotaSource.OBSERVED


# --------------------------------------------------------------------------
# Exa monthly spend ledger (AC-EXA: local spend tracking in USD, opt-in budget)
# --------------------------------------------------------------------------


class _FakeExaSDKClient:
    async def aclose(self) -> None:
        pass


class _FakeExaSDK:
    def __init__(
        self,
        search_response: object = None,
        search_error: Exception | None = None,
    ) -> None:
        self.search_response = search_response
        self.search_error = search_error
        self.client = _FakeExaSDKClient()

    async def search(self, **kwargs: object) -> object:
        if self.search_error is not None:
            raise self.search_error
        return self.search_response


class TestExaMonthlyLedger:
    async def test_unbudgeted_spend_reports_unknown(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        sdk = _FakeExaSDK(
            search_response=ExaSDKResponse(
                results=[Result(id="1", url="https://example.com/1", title="Exa 1")],
                resolved_search_type=None,
                auto_date=None,
                cost_dollars=CostDollars(total=0.007),
            )
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=None)
            response = await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="test", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
            assert response.usage is not None
            assert response.usage.units == Decimal("0.007")
            assert response.usage.unit_kind == _opt(_unit_kind(), "USD")
            snapshot = await adapter.quota()
            assert snapshot is not None
            assert snapshot.source is QuotaSource.ESTIMATED
            assert snapshot.remaining is None
            assert snapshot.limit is None
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

        latest = await repo.latest_quota("exa")
        assert latest is not None
        assert latest.remaining is None and latest.limit is None

    async def test_budgeted_spend_tracks_remaining_and_derived_percent(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        sdk = _FakeExaSDK(
            search_response=ExaSDKResponse(
                results=[Result(id="1", url="https://example.com/1", title="Exa 1")],
                resolved_search_type=None,
                auto_date=None,
                cost_dollars=CostDollars(total=0.007),
            )
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=Decimal("10.00"))
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="test1", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
            # Second call
            sdk.search_response = ExaSDKResponse(
                results=[Result(id="2", url="https://example.com/2", title="Exa 2")],
                resolved_search_type=None,
                auto_date=None,
                cost_dollars=CostDollars(total=0.003),
            )
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="test2", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

        latest = await repo.latest_quota("exa")
        assert latest is not None
        assert latest.limit == Decimal("10.00")
        assert latest.remaining == Decimal("9.990")
        assert latest.unit_kind == _opt(_unit_kind(), "USD")
        assert latest.display_unit == "USD"
        assert latest.remaining_percent == Decimal("99.9")

        stats = await monitoring_module.collect_stats(repo, adapter_names=["exa"])
        payload = stats.model_dump(mode="json")
        exa_quota = next(q for q in payload["latest_quota"] if q["provider"] == "exa")
        assert Decimal(exa_quota["limit"]) == Decimal("10.00")
        assert Decimal(exa_quota["remaining"]) == Decimal("9.99")
        assert exa_quota["unit_kind"] == "USD"
        assert Decimal(exa_quota["remaining_percent"]) == Decimal("99.9")

    async def test_observed_zero_on_402_cleared_on_subsequent_success(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        sdk = _FakeExaSDK(
            search_error=ValueError("Request failed with status code 402: Payment Required")
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=Decimal("10.00"))
            with pytest.raises(ProviderOperationError) as exc_info:
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="fail", limit=1
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
            assert exc_info.value.error.status_code == 402
            assert exc_info.value.error.code == "quota_exhausted"
            assert exc_info.value.error.retryable is False

            latest = await repo.latest_quota("exa")
            assert latest is not None
            assert latest.source is QuotaSource.OBSERVED
            assert latest.remaining == Decimal("0")
            assert latest.limit == Decimal("10.00")
            assert latest.reset_at is None
            assert latest.metadata.get("soft_zero") is True
            assert latest.metadata.get("exhaustion") is True
            assert latest.metadata.get("exhaustion_status") == 402
            assert contracts_module.is_soft_quota_zero("exa", latest) is False

            # Subsequent successful operation clears soft zero
            sdk.search_error = None
            sdk.search_response = ExaSDKResponse(
                results=[Result(id="1", url="https://example.com/1", title="Exa 1")],
                resolved_search_type=None,
                auto_date=None,
                cost_dollars=CostDollars(total=0.005),
            )
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="success", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )

            latest_after = await repo.latest_quota("exa")
            assert latest_after is not None
            assert latest_after.remaining == Decimal("9.995")
            assert latest_after.metadata.get("soft_zero") is not True
            assert contracts_module.is_soft_quota_zero("exa", latest_after) is False
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

    async def test_429_records_observed_zero_and_stays_retryable(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sdk = _FakeExaSDK(
            search_error=ValueError("Request failed with status code 429: Too Many Requests")
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=Decimal("10.00"))
            with pytest.raises(ProviderOperationError) as exc_info:
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa",
                            query="rate_limited",
                            limit=1,
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
            assert exc_info.value.error.status_code == 429
            assert exc_info.value.error.code == "rate_limited"
            assert exc_info.value.error.retryable is True
            latest = await repo.latest_quota("exa")
            assert latest is not None
            assert latest.source is QuotaSource.OBSERVED
            assert latest.remaining == Decimal("0")
            assert latest.metadata.get("exhaustion_status") == 429
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

    async def test_hydrate_quota_restores_current_month_spend(self, repo: SQLiteRepository) -> None:
        now = datetime.now(UTC)
        kind = _unit_kind()
        # Two events in current month
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.005"),
                observed_at=now,
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("0.008"),
                observed_at=now,
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )
        # Previous month event: should not be counted
        last_month = (now.replace(day=1) - timedelta(days=1)).replace(day=15)
        await repo.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("2.000"),
                observed_at=last_month,
                status=UsageStatus.SUCCESS,
                unit_kind=_opt(kind, "USD"),
                display_unit="USD",
            ),
            attribution=await seed_execution_project(repo),
        )

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=Decimal("10.00"))
            snapshot = await adapter.hydrate_quota(repo)
            assert snapshot is not None
            assert snapshot.limit == Decimal("10.00")
            assert snapshot.remaining == Decimal("9.987")
            assert snapshot.unit_kind == _opt(kind, "USD")
            assert snapshot.display_unit == "USD"
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

    async def test_fallback_spend_with_manual_credits_round_trip(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from exa_py.api import Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        sdk = _FakeExaSDK(
            search_response=ExaSDKResponse(
                results=[
                    Result(id="1", url="https://example.com/1", title="Exa 1"),
                    Result(id="2", url="https://example.com/2", title="Exa 2"),
                ],
                resolved_search_type=None,
                auto_date=None,
            )
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(
                client,
                api_key=TEST_API_KEY,
                manual_starting_credits=Decimal("10.00"),
            )
            response = await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="fallback", limit=5
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
            assert response.usage is not None
            assert response.usage.units == Decimal("0.007")
            assert response.usage.metadata.get("provenance") == "exa_pricing_fallback"
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

        latest = await repo.latest_quota("exa")
        assert latest is not None
        assert latest.limit == Decimal("10.00")
        assert latest.remaining == Decimal("9.993")
        assert latest.unit_kind == _opt(_unit_kind(), "USD")
        assert latest.metadata.get("limit_source") == "manual_starting_credits"

    async def test_429_zero_cleared_by_later_success_via_tracked_call(
        self, repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        sdk = _FakeExaSDK(
            search_error=ValueError("Request failed with status code 429: Too Many Requests")
        )
        monkeypatch.setattr(exa_module, "AsyncExa", lambda **kw: sdk)

        client = httpx.AsyncClient(timeout=30.0)
        adapter: ExaAdapter | None = None
        try:
            adapter = ExaAdapter(client, api_key=TEST_API_KEY, monthly_budget=Decimal("10.00"))
            with pytest.raises(ProviderOperationError):
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa",
                            query="limited",
                            limit=1,
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
            latest = await repo.latest_quota("exa")
            assert latest is not None
            assert latest.source is QuotaSource.OBSERVED
            assert latest.remaining == Decimal("0")

            sdk.search_error = None
            sdk.search_response = ExaSDKResponse(
                results=[Result(id="1", url="https://example.com/1", title="Exa 1")],
                resolved_search_type=None,
                auto_date=None,
                cost_dollars=CostDollars(total=0.005),
            )
            await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa",
                        query="recovered",
                        limit=1,
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
            latest_after = await repo.latest_quota("exa")
            assert latest_after is not None
            assert latest_after.source is QuotaSource.ESTIMATED
            assert latest_after.remaining == Decimal("9.995")
            assert latest_after.metadata.get("soft_zero") is not True
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()


# --------------------------------------------------------------------------
# Tavily legacy coexistence: failed/empty debits, stale-positive vs 402
# --------------------------------------------------------------------------


class _TavilyFakeSDK:
    """Recording stand-in for the Tavily SDK (no network)."""

    def __init__(self) -> None:
        self.search_response: object = None
        self.search_error: Exception | None = None

    async def search(self, **kwargs: object) -> object:
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def extract(self, **kwargs: object) -> object:
        raise NotImplementedError


class TestTavilyQuotaCoexistence:
    async def test_failed_call_records_zero_debit(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.tavily import TavilyAdapter

        sdk = _TavilyFakeSDK()
        sdk.search_error = ValueError("boom")
        client = httpx.AsyncClient(timeout=30.0)
        adapter: TavilyAdapter | None = None
        try:
            adapter = TavilyAdapter(client, sdk_client=sdk, api_key=TEST_API_KEY)  # type: ignore[arg-type]
            with pytest.raises(ProviderOperationError):
                await tracked_call(
                    repo,
                    adapter,
                    lambda running: running.search(
                        SearchRequest(
                            project_id="00000000-0000-4000-8000-0000000000aa", query="fail", limit=1
                        )
                    ),
                    operation=UsageOperation.SEARCH,
                    attribution=await seed_execution_project(repo),
                )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

        totals = await repo.limits.crd_usage_totals("tavily")
        assert all(t.normalized_crd == Decimal("0") for t in totals)

    async def test_empty_valid_documents_debit_reported_only(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.tavily import TavilyAdapter

        sdk = _TavilyFakeSDK()
        sdk.search_response = {"results": []}
        client = httpx.AsyncClient(timeout=30.0)
        adapter: TavilyAdapter | None = None
        try:
            adapter = TavilyAdapter(client, sdk_client=sdk, api_key=TEST_API_KEY)  # type: ignore[arg-type]
            response = await tracked_call(
                repo,
                adapter,
                lambda running: running.search(
                    SearchRequest(
                        project_id="00000000-0000-4000-8000-0000000000aa", query="empty", limit=1
                    )
                ),
                operation=UsageOperation.SEARCH,
                attribution=await seed_execution_project(repo),
            )
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()

        assert response.results == []
        assert response.usage is None

    async def test_stale_positive_cache_loses_to_vendor_402(self, repo: SQLiteRepository) -> None:
        from polyweb.adapters.tavily import TavilyAdapter
        from polyweb.models.contracts import UnitKind

        sdk = _TavilyFakeSDK()
        sdk.search_response = {"results": []}
        client = httpx.AsyncClient(timeout=30.0)
        adapter: TavilyAdapter | None = None
        try:
            adapter = TavilyAdapter(client, sdk_client=sdk, api_key=TEST_API_KEY)  # type: ignore[arg-type]
            latest = await effective_quota(repo, "tavily")
            assert latest is None
            zero = await adapter.quota_after_error(402)
            assert zero is not None and zero.remaining == Decimal("0")
            assert zero.unit_kind == UnitKind.CREDIT
            assert zero.display_unit == "Credits"
        finally:
            if adapter is not None:
                await adapter.aclose()
            await client.aclose()
