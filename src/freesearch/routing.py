"""Provider-neutral routing that orders adapters without calling them.

The selector consumes the existing ``ProviderAdapter`` contract and the
``freesearch.contracts`` models only. Callers supply enabled adapters in
configured priority order plus local health and quota snapshots; no network,
database, configuration, or provider calls happen here.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import (
    FetchRequest,
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    RoutingMode,
    RoutingPreference,
    SearchRequest,
    is_soft_quota_zero,
)

_HEALTH_ORDER = (HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN)
_UNKNOWN_HEALTH_CHECKED_AT = datetime(1970, 1, 1, tzinfo=UTC)


class RoutingError(Exception):
    """Provider-neutral failure when a route cannot be produced.

    ``code`` distinguishes invalid router input (``duplicate_adapter``) from an
    unsatisfied ``REQUIRE`` preference (``no_eligible_provider``). Messages
    never include secrets or vendor response data.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        providers: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.providers = providers


@dataclass(frozen=True)
class RouteCandidate:
    """An eligible adapter paired with its health and optional quota snapshot."""

    adapter: ProviderAdapter
    health: ProviderHealth
    quota: QuotaSnapshot | None


def select_route(
    request: SearchRequest | FetchRequest,
    adapters: Sequence[ProviderAdapter],
    health_snapshots: Mapping[str, ProviderHealth],
    quota_snapshots: Mapping[str, QuotaSnapshot],
) -> tuple[RouteCandidate, ...]:
    """Return ordered route candidates for ``request``.

    ``adapters`` supplies enabled providers in configured priority order and is
    preserved as the tie breaker. Snapshots are keyed by adapter name; a
    provider without a health snapshot ranks as ``UNKNOWN`` and one without a
    quota snapshot stays eligible.
    """

    _reject_duplicate_names(adapters)

    preference = request.routing
    candidates: list[RouteCandidate] = []
    for adapter in adapters:
        candidate = _eligible(request, adapter, health_snapshots, quota_snapshots)
        if candidate is not None:
            candidates.append(candidate)

    if preference.mode is RoutingMode.REQUIRE:
        required = set(preference.providers)
        candidates = [candidate for candidate in candidates if candidate.adapter.name in required]
        if not candidates:
            raise RoutingError(
                "no required provider is eligible",
                code="no_eligible_provider",
                providers=preference.providers,
            )

    ranked = sorted(
        candidates,
        key=lambda candidate: (
            _HEALTH_ORDER.index(candidate.health.status),
            _preference_rank(candidate.adapter.name, preference),
        ),
    )

    if preference.allow_fallback:
        return tuple(ranked)
    return tuple(ranked[:1])


def _eligible(
    request: SearchRequest | FetchRequest,
    adapter: ProviderAdapter,
    health_snapshots: Mapping[str, ProviderHealth],
    quota_snapshots: Mapping[str, QuotaSnapshot],
) -> RouteCandidate | None:
    """Return a candidate for ``adapter`` or ``None`` when it must be excluded."""

    if isinstance(request, SearchRequest):
        supports = adapter.capabilities.search
    else:
        supports = adapter.capabilities.fetch
    if not supports:
        return None

    health = health_snapshots.get(adapter.name)
    if health is not None and health.status == HealthStatus.UNAVAILABLE:
        return None
    if health is None:
        health = ProviderHealth(
            provider=adapter.name,
            status=HealthStatus.UNKNOWN,
            checked_at=_UNKNOWN_HEALTH_CHECKED_AT,
            message="no local health snapshot",
        )

    quota = quota_snapshots.get(adapter.name)
    if quota is not None and _hard_quota_exhaustion(adapter.name, quota):
        return None

    return RouteCandidate(adapter=adapter, health=health, quota=quota)


def _hard_quota_exhaustion(name: str, quota: QuotaSnapshot) -> bool:
    """Return whether a known positive allowance has reached zero."""

    return (
        quota.remaining == Decimal("0")
        and quota.limit is not None
        and quota.limit > Decimal("0")
        and not is_soft_quota_zero(name, quota)
    )


def _preference_rank(name: str, preference: RoutingPreference) -> int:
    """Return 0 for recognized ``PREFER`` names and 1 otherwise."""

    if preference.mode is RoutingMode.PREFER and name in preference.providers:
        return 0
    return 1


def _reject_duplicate_names(adapters: Sequence[ProviderAdapter]) -> None:
    """Raise when ``adapters`` repeats a provider name."""

    seen: set[str] = set()
    for adapter in adapters:
        if adapter.name in seen:
            raise RoutingError(
                f"duplicate adapter name {adapter.name!r}",
                code="duplicate_adapter",
                providers=(adapter.name,),
            )
        seen.add(adapter.name)
