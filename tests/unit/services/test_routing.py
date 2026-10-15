"""Deterministic tests for provider-neutral routing.

Every timestamp is fixed UTC and every quota value is an explicit ``Decimal``
so route order and provenance assertions never depend on the clock or float
comparison. Only the public ``select_route`` API and its observable outputs
are asserted.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import AnyHttpUrl

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    RoutingMode,
    RoutingPreference,
    SearchRequest,
    SearchResponse,
)
from freesearch.services.routing import RouteCandidate, RoutingError, select_route

FIXED_AT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


class Adapter(ProviderAdapter):
    """Minimal adapter double with configurable name and capabilities."""

    def __init__(self, name: str, *, search: bool = True, fetch: bool = False) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=search, fetch=fetch)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self.name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="",
                fetched_at=FIXED_AT,
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        raise NotImplementedError


def adapter(name: str, *, search: bool = True, fetch: bool = False) -> Adapter:
    return Adapter(name, search=search, fetch=fetch)


def health(name: str, status: HealthStatus) -> ProviderHealth:
    return ProviderHealth(provider=name, status=status, checked_at=FIXED_AT)


def quota(
    name: str,
    remaining: Decimal | None,
    source: QuotaSource = QuotaSource.AUTHORITATIVE,
) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider=name,
        source=source,
        remaining=remaining,
        limit=Decimal("100"),
        observed_at=FIXED_AT,
    )


def route(
    request: SearchRequest | FetchRequest,
    adapters: list[Adapter],
    health_snapshots: dict[str, ProviderHealth] | None = None,
    quota_snapshots: dict[str, QuotaSnapshot] | None = None,
) -> tuple[RouteCandidate, ...]:
    return select_route(
        request,
        adapters,
        health_snapshots or {},
        quota_snapshots or {},
    )


def names(candidates: tuple[RouteCandidate, ...]) -> list[str]:
    return [candidate.adapter.name for candidate in candidates]


def search_request(
    mode: RoutingMode = RoutingMode.AUTO,
    providers: tuple[str, ...] = (),
    allow_fallback: bool = True,
) -> SearchRequest:
    return SearchRequest(
        query="routing",
        routing=RoutingPreference(mode=mode, providers=providers, allow_fallback=allow_fallback),
    )


# --- Capability filtering ---------------------------------------------------


def test_search_route_excludes_adapters_without_search_capability() -> None:
    adapters = [adapter("search-only"), adapter("fetch-only", search=False, fetch=True)]

    candidates = route(search_request(), adapters)

    assert names(candidates) == ["search-only"]


def test_fetch_route_excludes_adapters_without_fetch_capability() -> None:
    adapters = [adapter("search-only"), adapter("fetch-only", search=False, fetch=True)]

    candidates = route(
        FetchRequest(url=AnyHttpUrl("https://example.com/doc"), routing=RoutingPreference()),
        adapters,
    )

    assert names(candidates) == ["fetch-only"]


def test_provider_options_do_not_select_or_reorder_providers() -> None:
    request = SearchRequest(
        query="routing",
        provider_options={"exa": {"type": "deep"}},
    )

    candidates = route(request, [adapter("brave"), adapter("exa")])

    assert names(candidates) == ["brave", "exa"]


# --- Health and quota exclusion --------------------------------------------


def test_unavailable_provider_is_excluded() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.UNAVAILABLE),
        "beta": health("beta", HealthStatus.HEALTHY),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(), adapters, snapshots)

    assert names(candidates) == ["beta", "gamma"]


def test_zero_remaining_quota_is_excluded() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {"alpha": quota("alpha", Decimal("0")), "beta": quota("beta", Decimal("0"))}
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(), adapters, health_snapshots, snapshots)

    assert candidates == ()


def test_missing_quota_snapshot_keeps_provider_eligible() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(),
        adapters,
        health_snapshots,
        {"alpha": quota("alpha", Decimal("5"))},
    )

    assert names(candidates) == ["alpha", "beta"]
    assert candidates[0].quota is not None
    assert candidates[1].quota is None


def test_unknown_remaining_quota_keeps_provider_eligible() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }
    quota_snapshots = {"alpha": quota("alpha", None), "beta": quota("beta", None)}

    candidates = route(search_request(), adapters, health_snapshots, quota_snapshots)

    assert names(candidates) == ["alpha", "beta"]


# --- Quota source provenance ------------------------------------------------


def test_quota_source_is_preserved_including_estimated() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }
    quota_snapshots = {
        "alpha": quota("alpha", Decimal("10"), QuotaSource.AUTHORITATIVE),
        "beta": quota("beta", Decimal("20"), QuotaSource.OBSERVED),
        "gamma": quota("gamma", Decimal("30"), QuotaSource.ESTIMATED),
    }

    candidates = route(search_request(), adapters, health_snapshots, quota_snapshots)

    assert len(candidates) == 3
    expected = [
        (QuotaSource.AUTHORITATIVE, Decimal("10")),
        (QuotaSource.OBSERVED, Decimal("20")),
        (QuotaSource.ESTIMATED, Decimal("30")),
    ]
    for candidate, (source, remaining) in zip(candidates, expected, strict=True):
        assert candidate.quota is not None
        assert candidate.quota.source is source
        assert candidate.quota.remaining == remaining
        assert candidate.quota.provider == candidate.adapter.name


# --- Ranking ----------------------------------------------------------------


def test_healthy_before_degraded_before_unknown_ranking() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.DEGRADED),
        "beta": health("beta", HealthStatus.UNKNOWN),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(), adapters, snapshots)

    assert names(candidates) == ["gamma", "alpha", "beta"]


def test_missing_health_snapshot_synthesizes_unknown_and_ranks_last() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {"alpha": health("alpha", HealthStatus.HEALTHY)}

    candidates = route(search_request(), adapters, snapshots)

    assert names(candidates) == ["alpha", "beta"]
    beta = candidates[1]
    assert beta.health.status is HealthStatus.UNKNOWN
    assert beta.health.provider == "beta"
    assert beta.health.message == "no local health snapshot"
    assert beta.health.checked_at == datetime(1970, 1, 1, tzinfo=UTC)


def test_repeated_identical_calls_produce_equal_routes() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.DEGRADED),
        "beta": health("beta", HealthStatus.HEALTHY),
    }
    quota_snapshots = {
        "alpha": quota("alpha", Decimal("10")),
        "beta": quota("beta", None, QuotaSource.OBSERVED),
        "gamma": quota("gamma", Decimal("30"), QuotaSource.ESTIMATED),
    }

    first = route(search_request(), adapters, health_snapshots, quota_snapshots)
    second = route(search_request(), adapters, health_snapshots, quota_snapshots)

    assert names(first) == names(second) == ["beta", "alpha", "gamma"]
    assert first == second


def test_routing_does_not_mutate_inputs_and_preserves_snapshot_identity() -> None:
    request = search_request(RoutingMode.AUTO)
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    health_snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.DEGRADED),
    }
    quota_snapshots = {
        "alpha": quota("alpha", Decimal("10")),
        "gamma": quota("gamma", Decimal("30"), QuotaSource.ESTIMATED),
    }
    request_before = request.model_copy(deep=True)
    health_before = {name: snap.model_copy(deep=True) for name, snap in health_snapshots.items()}
    quota_before = {name: snap.model_copy(deep=True) for name, snap in quota_snapshots.items()}

    candidates = route(request, adapters, health_snapshots, quota_snapshots)

    assert request == request_before
    assert health_snapshots == health_before
    assert quota_snapshots == quota_before
    assert set(health_snapshots) == {"alpha", "beta"}
    assert set(quota_snapshots) == {"alpha", "gamma"}

    by_name = {candidate.adapter.name: candidate for candidate in candidates}
    assert by_name["alpha"].health is health_snapshots["alpha"]
    assert by_name["beta"].health is health_snapshots["beta"]
    assert by_name["gamma"].health.status is HealthStatus.UNKNOWN
    assert by_name["gamma"].quota is quota_snapshots["gamma"]


def test_supplied_order_is_priority_tie_breaker() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(), adapters, snapshots)

    assert names(candidates) == ["alpha", "beta", "gamma"]


# --- Routing mode behavior --------------------------------------------------


def test_auto_mode_returns_all_eligible_in_ranked_order() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.UNKNOWN),
        "beta": health("beta", HealthStatus.DEGRADED),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(RoutingMode.AUTO), adapters, snapshots)

    assert names(candidates) == ["gamma", "beta", "alpha"]


def test_prefer_moves_recognized_provider_ahead_within_health_group() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(RoutingMode.PREFER, providers=("beta",)),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["beta", "alpha"]


def test_prefer_does_not_override_health_ranking() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.DEGRADED),
    }

    candidates = route(
        search_request(RoutingMode.PREFER, providers=("beta",)),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["alpha", "beta"]


def test_prefer_ignores_unknown_provider_names_preserving_configured_order() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(RoutingMode.PREFER, providers=("ghost",)),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["alpha", "beta"]


def test_require_considers_only_required_providers() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.DEGRADED),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(RoutingMode.REQUIRE, providers=("beta", "gamma")),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["gamma", "beta"]


def test_require_with_unknown_provider_raises_routing_error() -> None:
    adapters = [adapter("alpha")]

    with pytest.raises(RoutingError) as exc_info:
        route(search_request(RoutingMode.REQUIRE, providers=("ghost",)), adapters)

    assert exc_info.value.code == "no_eligible_provider"
    assert exc_info.value.providers == ("ghost",)
    assert "ghost" not in str(exc_info.value)


def test_require_with_no_eligible_provider_raises_routing_error() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.UNAVAILABLE),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    with pytest.raises(RoutingError) as exc_info:
        route(search_request(RoutingMode.REQUIRE, providers=("alpha",)), adapters, snapshots)

    assert exc_info.value.code == "no_eligible_provider"
    assert exc_info.value.providers == ("alpha",)


# --- Fallback ---------------------------------------------------------------


def test_allow_fallback_false_returns_only_ranked_primary_candidate() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.DEGRADED),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(RoutingMode.AUTO, allow_fallback=False),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["beta"]


def test_allow_fallback_default_returns_all_ordered_candidates() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.DEGRADED),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    candidates = route(search_request(), adapters, snapshots)

    assert names(candidates) == ["beta", "alpha"]


# --- Input validation -------------------------------------------------------


def test_duplicate_adapter_names_are_rejected() -> None:
    adapters = [adapter("alpha"), adapter("alpha")]

    with pytest.raises(RoutingError) as exc_info:
        route(search_request(), adapters)

    assert exc_info.value.code == "duplicate_adapter"
    assert exc_info.value.providers == ("alpha",)


def test_fanout_returns_all_eligible_candidates_ignoring_allow_fallback() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.DEGRADED),
        "beta": health("beta", HealthStatus.HEALTHY),
        "gamma": health("gamma", HealthStatus.UNKNOWN),
    }

    candidates = route(
        search_request(RoutingMode.FANOUT, allow_fallback=False),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["beta", "alpha", "gamma"]


def test_fanout_filters_to_requested_providers_when_specified() -> None:
    adapters = [adapter("alpha"), adapter("beta"), adapter("gamma")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
        "gamma": health("gamma", HealthStatus.HEALTHY),
    }

    candidates = route(
        search_request(RoutingMode.FANOUT, ("alpha", "gamma")),
        adapters,
        snapshots,
    )

    assert names(candidates) == ["alpha", "gamma"]


def test_fanout_with_no_eligible_provider_raises_routing_error() -> None:
    adapters = [adapter("alpha"), adapter("beta")]
    snapshots = {
        "alpha": health("alpha", HealthStatus.HEALTHY),
        "beta": health("beta", HealthStatus.HEALTHY),
    }

    with pytest.raises(RoutingError) as exc_info:
        route(
            search_request(RoutingMode.FANOUT, providers=("ghost",)),
            adapters,
            snapshots,
        )

    assert exc_info.value.code == "no_eligible_provider"
    assert exc_info.value.providers == ("ghost",)
