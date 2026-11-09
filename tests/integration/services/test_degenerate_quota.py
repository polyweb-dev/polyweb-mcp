"""S4 regression: shared normalize_degenerate_quota through BOTH read paths.

Offline only: temp-file SQLite repositories (``tmp_path``), fixed UTC
timestamps, explicit ``Decimal`` values. No live network, no production
``polyweb.db``, no port binds.

Contract under test (FINAL REVIEW PLAN, RTC consensus):
  one shared pure backend helper
  ``polyweb.monitoring.normalize_degenerate_quota(snapshot)``
  mapping ``limit == Decimal("0")`` to remaining/limit/reset ``None``
  (else identity), used by BOTH ``effective_quota`` and the dashboard path
  (``_latest_quotas``/``collect_stats``).

Regression: ``record_quota`` Brave OBSERVED REQUEST 0/0 ->
  ``collect_stats`` latest_quota[brave] has remaining None AND limit None AND
  reset_at None, AND ``select_route`` stays eligible, AND ``effective_quota``
  returns the same view.

RF-safety: non-zero limits (``"100000.10"``) pass through verbatim;
  ``limit=None`` rows untouched.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest_asyncio

from polyweb.adapters.base import ProviderAdapter
from polyweb.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services import monitoring as monitoring_module
from polyweb.services.monitoring import collect_stats, effective_quota
from polyweb.services.routing import select_route

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


def _opt(target: object, name: str, *default: object) -> object:
    """``getattr`` shim routing through a variable name (Ruff B009).

    Mirrors the Red-probe style in tests/test_quota_units.py: dynamic-safe
    attribute reads fail as clean ``AssertionError``s, not ``AttributeError``
    tracebacks or lint violations.
    """

    if default:
        return getattr(target, name, default[0])
    return getattr(target, name)


def _normalize():
    helper = _opt(monitoring_module, "normalize_degenerate_quota", None)
    assert helper is not None, (
        "S4/AC-2: polyweb.monitoring.normalize_degenerate_quota missing — "
        "expected a shared pure helper normalize_degenerate_quota(snapshot) "
        "mapping limit==Decimal('0') to remaining/limit/reset None (else "
        "identity), used by BOTH effective_quota and _latest_quotas/collect_stats"
    )
    return helper


def _unit_kind_request():
    from polyweb.models import contracts as contracts_module

    kind = _opt(contracts_module, "UnitKind", None)
    assert kind is not None, "AC-3 setup: polyweb.contracts.UnitKind missing"
    return _opt(kind, "REQUEST")


def _brave_zero_snapshot() -> QuotaSnapshot:
    return QuotaSnapshot(
        provider="brave",
        source=QuotaSource.OBSERVED,
        remaining=Decimal("0"),
        limit=Decimal("0"),
        reset_at=FIXED_AT,
        observed_at=FIXED_AT,
        unit_kind=_unit_kind_request(),
        display_unit="requests",
    )


class _SearchAdapter(ProviderAdapter):
    """Minimal offline adapter double named ``brave`` with search support."""

    @property
    def name(self) -> str:
        return "brave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self.name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(url=request.url, content="", fetched_at=FIXED_AT),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def repo(tmp_path):  # type: ignore[no-untyped-def]
    repository = await SQLiteRepository.open(tmp_path / "degenerate-quota.db")
    yield repository
    await repository.close()


class TestNormalizeDegenerateQuota:
    def test_zero_limit_maps_to_unknown(self) -> None:
        helper = _normalize()
        view = helper(_brave_zero_snapshot())
        assert view.remaining is None, f"S4: remaining must be None, saw {view.remaining!r}"
        assert view.limit is None, f"S4: limit must be None, saw {view.limit!r}"
        assert view.reset_at is None, f"S4: reset_at must be None, saw {view.reset_at!r}"
        # Provenance survives normalization.
        assert view.provider == "brave", f"S4: provider must survive, saw {view.provider!r}"
        assert view.source == QuotaSource.OBSERVED, f"S4: source must survive, saw {view.source!r}"

    def test_zero_limit_does_not_mutate_input(self) -> None:
        helper = _normalize()
        recorded = _brave_zero_snapshot()
        view = helper(recorded)
        assert recorded.remaining == Decimal("0") and recorded.limit == Decimal("0"), (
            "S4: helper must be pure (input snapshot unchanged), "
            f"saw {recorded.remaining!r}/{recorded.limit!r}"
        )
        assert view is not recorded, "S4: normalized view must be a copy, not the input"
        assert (view.remaining, view.limit, view.reset_at) == (None, None, None)

    def test_nonzero_limit_passes_through_verbatim(self) -> None:
        helper = _normalize()
        snapshot = QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("90000.05"),
            limit=Decimal("100000.10"),
            observed_at=FIXED_AT,
        )
        view = helper(snapshot)
        assert view.remaining == Decimal("100000.10") or view.remaining == Decimal("90000.05"), (
            f"S4 RF-safety: non-zero snapshot must pass through, saw {view!r}"
        )
        assert view.limit == Decimal("100000.10"), (
            "S4 RF-safety: limit '100000.10' must pass through verbatim "
            f"(never 100000.1), saw {view.limit!r}"
        )
        assert str(view.limit) == "100000.10", (
            f"S4 RF-safety: Decimal string form must stay '100000.10', saw {str(view.limit)!r}"
        )
        assert view.reset_at == snapshot.reset_at

    def test_none_limit_untouched(self) -> None:
        helper = _normalize()
        snapshot = QuotaSnapshot(
            provider="you",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("4.75"),
            limit=None,
            observed_at=FIXED_AT,
        )
        view = helper(snapshot)
        assert view.remaining == Decimal("4.75"), (
            f"S4 RF-safety: limit=None rows untouched (remaining), saw {view.remaining!r}"
        )
        assert view.limit is None, f"S4 RF-safety: limit=None stays None, saw {view.limit!r}"

    def test_genuine_zero_with_positive_limit_not_normalized(self) -> None:
        helper = _normalize()
        snapshot = QuotaSnapshot(
            provider="brave",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=Decimal("1000"),
            observed_at=FIXED_AT,
        )
        view = helper(snapshot)
        assert view.remaining == Decimal("0"), (
            "S4/AC-6: genuine depletion (remaining=0, limit>0) must NOT normalize; "
            f"saw {view.remaining!r}"
        )
        assert view.limit == Decimal("1000"), (
            f"S4/AC-6: genuine limit must survive, saw {view.limit!r}"
        )


class TestDegenerateReadPaths:
    async def test_collect_stats_normalizes_degenerate(self, repo: SQLiteRepository) -> None:
        await repo.record_quota(_brave_zero_snapshot())
        stats = await collect_stats(repo, adapter_names=["brave"])
        rows = [snap for snap in stats.latest_quota if snap.provider == "brave"]
        assert rows, "S4/AC-2 setup: no brave row in collect_stats after record_quota 0/0"
        view = rows[0]
        assert view.remaining is None, (
            "S4/AC-2: collect_stats must normalize degenerate remaining "
            f"to None, saw {view.remaining!r}"
        )
        assert view.limit is None, (
            f"S4/AC-2: collect_stats must normalize degenerate limit to None, saw {view.limit!r}"
        )
        assert view.reset_at is None, (
            f"S4/AC-2: collect_stats must normalize degenerate reset to None, saw {view.reset_at!r}"
        )

    async def test_effective_quota_matches_dashboard_view(self, repo: SQLiteRepository) -> None:
        await repo.record_quota(_brave_zero_snapshot())
        stats = await collect_stats(repo, adapter_names=["brave"])
        dashboard = next(snap for snap in stats.latest_quota if snap.provider == "brave")
        view = await effective_quota(repo, "brave")
        assert view is not None, "S4/AC-2 setup: effective_quota returned None for brave"
        assert (view.remaining, view.limit, view.reset_at) == (None, None, None), (
            "S4/AC-2: effective_quota must return the same normalized unknown view "
            f"(None/None/None), saw {view.remaining!r}/{view.limit!r}/{view.reset_at!r}"
        )
        assert (view.remaining, view.limit, view.reset_at) == (
            dashboard.remaining,
            dashboard.limit,
            dashboard.reset_at,
        ), (
            "S4/AC-2: effective_quota and collect_stats must agree "
            f"(effective={view!r} dashboard={dashboard!r})"
        )

    async def test_normalized_view_stays_routable(self, repo: SQLiteRepository) -> None:
        await repo.record_quota(_brave_zero_snapshot())
        view = await effective_quota(repo, "brave")
        assert view is not None, "S4/AC-6 setup: expected a normalized view for brave"
        health = {
            "brave": ProviderHealth(
                provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
            )
        }
        candidates = select_route(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="routing probe"),
            [_SearchAdapter()],
            health,
            {"brave": view},
        )
        names = [c.adapter.name for c in candidates]
        assert names == ["brave"], (
            "S4/AC-6: normalized unknown Brave quota must stay eligible, "
            f"saw {names!r} (view={view!r})"
        )

    async def test_genuine_depletion_still_excluded(self, repo: SQLiteRepository) -> None:
        genuine = QuotaSnapshot(
            provider="brave",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=Decimal("1000"),
            observed_at=FIXED_AT,
        )
        await repo.record_quota(genuine)
        view = await effective_quota(repo, "brave")
        assert view is not None, "S4/AC-6 setup: expected a view for genuine depletion"
        assert view.remaining == Decimal("0") and view.limit == Decimal("1000"), (
            f"S4/AC-6 setup: genuine depletion must survive both paths, saw {view!r}"
        )
        health = {
            "brave": ProviderHealth(
                provider="brave", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
            )
        }
        candidates = select_route(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="routing probe"),
            [_SearchAdapter()],
            health,
            {"brave": view},
        )
        assert [c.adapter.name for c in candidates] == [], (
            "S4/AC-6: genuine remaining=0 with limit>0 must steer routing away"
        )

    async def test_nonzero_verbatim_through_dashboard(self, repo: SQLiteRepository) -> None:
        snapshot = QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("90000.05"),
            limit=Decimal("100000.10"),
            observed_at=FIXED_AT,
        )
        await repo.record_quota(snapshot)
        stats = await collect_stats(repo, adapter_names=["tavily"])
        row = next(snap for snap in stats.latest_quota if snap.provider == "tavily")
        assert row.limit == Decimal("100000.10"), (
            f"S4 RF-safety: dashboard must preserve '100000.10' verbatim, saw {row.limit!r}"
        )
        assert str(row.limit) == "100000.10"
        assert row.remaining == Decimal("90000.05")
