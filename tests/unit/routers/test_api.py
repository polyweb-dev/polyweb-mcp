"""Unit tests for REST route planning and single-attempt dispatch.

Offline only: stub adapters, injected store doubles, and a real
``SQLiteRepository`` is never required here. Every timestamp is fixed UTC.
Symbols are patched at their consumer lookup sites inside
``freesearch.routers.api``. Each case clears both config caches and quota
poll state first and relies on the ``monkeypatch`` fixture for restore.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import AnyHttpUrl

import freesearch.routers.api as api_module
from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.provider_config import ProviderConfig
from freesearch.models.contracts import (
    CostEstimate,
    FallbackPolicy,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    RoutingConfigResponse,
    RoutingMode,
    RoutingPreference,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.routers.api import _dispatch, _plan_route, _routing_state
from freesearch.routers.control import clear_config_cache
from freesearch.services.monitoring import clear_quota_poll_cache

FIXED_AT = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_caches() -> Any:
    """Clear config caches and quota poll state before each case."""

    clear_config_cache()
    clear_quota_poll_cache()
    yield
    clear_config_cache()
    clear_quota_poll_cache()


class StubAdapter(ProviderAdapter):
    """Minimal offline adapter double with a fixed name and capabilities."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=True, quota=False)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self._name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url, content="stub body", fetched_at=FIXED_AT
            ),
        )

    async def estimate_cost(
        self, request: SearchRequest | FetchRequest
    ) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))


class SpyBatchRepository:
    """Injected store double that records batch name lists."""

    def __init__(self) -> None:
        self.health_batch_names: list[list[str]] = []
        self.quota_batch_names: list[list[str]] = []

    async def latest_health_batch(
        self, providers: Sequence[str]
    ) -> dict[str, ProviderHealth]:
        self.health_batch_names.append(list(providers))
        return {}

    async def latest_quota_batch(
        self, providers: Sequence[str]
    ) -> dict[str, QuotaSnapshot]:
        self.quota_batch_names.append(list(providers))
        return {}

    async def list_usage(self, **kwargs: Any) -> list[Any]:
        return []

    async def record_usage(self, event: Any) -> None:
        return None

    async def record_health(self, observation: Any) -> None:
        return None


class BatchlessRepository:
    """Injected store without ``latest_*_batch`` methods (legacy fake seam)."""

    def __init__(
        self,
        health: dict[str, ProviderHealth] | None = None,
        quotas: dict[str, QuotaSnapshot] | None = None,
    ) -> None:
        self._health = health or {}
        self._quotas = quotas or {}

    async def latest_health(self, provider: str) -> ProviderHealth | None:
        return self._health.get(provider)

    async def latest_quota(self, provider: str) -> QuotaSnapshot | None:
        return self._quotas.get(provider)

    async def list_usage(self, **kwargs: Any) -> list[Any]:
        return []


class ExplodingBatchRepository:
    """Injected store whose batch reads always fail."""

    async def latest_health_batch(
        self, providers: Sequence[str]
    ) -> dict[str, ProviderHealth]:
        raise RuntimeError("health store down")

    async def latest_quota_batch(
        self, providers: Sequence[str]
    ) -> dict[str, QuotaSnapshot]:
        raise RuntimeError("quota store down")


def _install_plan_spies(
    monkeypatch: pytest.MonkeyPatch,
    config_names: list[str],
    scheduled: list[int],
) -> None:
    """Patch consumer lookup sites used by ``_plan_route``/``_routing_state``."""

    async def _fake_config(
        repository: Any, name: str, *, strict: bool = False
    ) -> ProviderConfig:
        config_names.append(name)
        return ProviderConfig()

    async def _fake_policy(repository: Any) -> Any:
        return RoutingConfigResponse()

    def _fake_schedule(
        repository: Any, routes: Sequence[ProviderAdapter], secret_store: Any
    ) -> None:
        scheduled.append(len(list(routes)))

    monkeypatch.setattr(api_module, "effective_config_for_name", _fake_config)
    monkeypatch.setattr(api_module, "routing_policy", _fake_policy)
    monkeypatch.setattr(api_module, "_schedule_quota_refresh", _fake_schedule)


def _search_require(names: tuple[str, ...]) -> SearchRequest:
    return SearchRequest(
        query="narrow",
        routing=RoutingPreference(mode=RoutingMode.REQUIRE, providers=names),
    )


def _fetch_require(names: tuple[str, ...]) -> FetchRequest:
    return FetchRequest(
        url=AnyHttpUrl("https://example.com/doc"),
        routing=RoutingPreference(mode=RoutingMode.REQUIRE, providers=names),
    )


async def test_require_filters_before_state_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQUIRE narrows routes before config reads and batch snapshot reads."""

    adapters = [StubAdapter("alpha"), StubAdapter("beta"), StubAdapter("gamma")]
    repository = SpyBatchRepository()
    config_names: list[str] = []
    scheduled: list[int] = []
    _install_plan_spies(monkeypatch, config_names, scheduled)

    plan = await _plan_route(_search_require(("beta",)), adapters, repository, None)

    assert [adapter.name for adapter in plan] == ["beta"]
    assert config_names == ["beta"]
    assert repository.health_batch_names == [["beta"]]
    assert repository.quota_batch_names == [["beta"]]
    assert scheduled == [1]

    config_names.clear()
    repository.health_batch_names.clear()
    repository.quota_batch_names.clear()
    scheduled.clear()
    fetch_plan = await _plan_route(
        _fetch_require(("alpha", "gamma")), adapters, repository, None
    )

    assert [adapter.name for adapter in fetch_plan] == ["alpha", "gamma"]
    assert sorted(config_names) == ["alpha", "gamma"]
    assert repository.health_batch_names == [["alpha", "gamma"]]
    assert repository.quota_batch_names == [["alpha", "gamma"]]
    assert scheduled == [2]

    config_names.clear()
    repository.health_batch_names.clear()
    repository.quota_batch_names.clear()
    scheduled.clear()
    with pytest.raises(HTTPException) as exc_info:
        await _plan_route(_search_require(("ghost",)), adapters, repository, None)

    assert exc_info.value.status_code == 503
    assert config_names == []
    assert repository.health_batch_names == []
    assert repository.quota_batch_names == []
    assert scheduled == []


@pytest.mark.parametrize(
    ("fallback_policy", "allow_fallback", "operation"),
    [
        (FallbackPolicy.CHAINED, True, "search"),
        (FallbackPolicy.FIRST_ONLY, True, "search"),
        (FallbackPolicy.CHAINED, False, "search"),
        (FallbackPolicy.CHAINED, True, "fetch"),
        (FallbackPolicy.FIRST_ONLY, True, "fetch"),
        (FallbackPolicy.CHAINED, False, "fetch"),
    ],
)
async def test_dispatch_uses_one_candidate(
    monkeypatch: pytest.MonkeyPatch,
    fallback_policy: FallbackPolicy,
    allow_fallback: bool,
    operation: str,
) -> None:
    """Dispatch invokes only the first candidate; a primary failure never retries."""

    adapters = [StubAdapter("alpha"), StubAdapter("beta"), StubAdapter("gamma")]
    config_names: list[str] = []
    scheduled: list[int] = []
    _install_plan_spies(monkeypatch, config_names, scheduled)

    async def _fake_policy(repository: Any) -> RoutingConfigResponse:
        return RoutingConfigResponse(fallback_policy=fallback_policy)

    monkeypatch.setattr(api_module, "routing_policy", _fake_policy)

    if operation == "search":
        request: SearchRequest | FetchRequest = SearchRequest(
            query="single",
            routing=RoutingPreference(mode=RoutingMode.AUTO, allow_fallback=allow_fallback),
        )
        usage_operation = UsageOperation.SEARCH
    else:
        request = FetchRequest(
            url=AnyHttpUrl("https://example.com/doc"),
            routing=RoutingPreference(mode=RoutingMode.AUTO, allow_fallback=allow_fallback),
        )
        usage_operation = UsageOperation.FETCH

    plan = await _plan_route(request, adapters, None, None)
    if fallback_policy is FallbackPolicy.CHAINED and allow_fallback:
        assert [adapter.name for adapter in plan] == ["alpha", "beta", "gamma"]
    else:
        assert [adapter.name for adapter in plan] == ["alpha"]

    calls: dict[str, int] = {"alpha": 0, "beta": 0, "gamma": 0}

    async def _invoke(
        adapter: ProviderAdapter, current: SearchRequest | FetchRequest
    ) -> SearchResponse | FetchResponse:
        calls[adapter.name] += 1
        raise RuntimeError("primary boom")

    invoke: Callable[[ProviderAdapter, Any], Awaitable[Any]] = _invoke
    with pytest.raises(RuntimeError, match="primary boom"):
        await _dispatch(
            request,
            usage_operation,
            invoke,
            routes=adapters,
            repository=None,
            secret_store=None,
        )

    assert calls == {"alpha": 1, "beta": 0, "gamma": 0}


async def test_batchless_repository_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stores without batch methods still route; batch errors stay tolerant."""

    adapters = [StubAdapter("alpha"), StubAdapter("beta")]
    config_names: list[str] = []
    scheduled: list[int] = []
    _install_plan_spies(monkeypatch, config_names, scheduled)

    health = {
        "alpha": ProviderHealth(
            provider="alpha", status=HealthStatus.HEALTHY, checked_at=FIXED_AT
        )
    }
    quotas = {
        "alpha": QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("5"),
            limit=Decimal("100"),
            observed_at=FIXED_AT,
        )
    }
    legacy = BatchlessRepository(health=health, quotas=quotas)
    assert not hasattr(legacy, "latest_health_batch")
    assert not hasattr(legacy, "latest_quota_batch")

    state_health, state_quotas = await _routing_state(legacy, adapters, None)

    assert state_health == health
    assert state_quotas == quotas
    assert scheduled == [2]

    plan = await _plan_route(SearchRequest(query="legacy"), adapters, legacy, None)

    assert [adapter.name for adapter in plan] == ["alpha", "beta"]

    exploding = ExplodingBatchRepository()
    tolerant_health, tolerant_quotas = await _routing_state(exploding, adapters, None)

    assert tolerant_health == {}
    assert tolerant_quotas == {}

    empty_health, empty_quotas = await _routing_state(legacy, [], None)

    assert empty_health == {}
    assert empty_quotas == {}

    none_health, none_quotas = await _routing_state(None, adapters, None)

    assert none_health == {}
    assert none_quotas == {}

    with pytest.raises(HTTPException) as exc_info:
        await _plan_route(SearchRequest(query="empty"), [], legacy, None)

    assert exc_info.value.status_code == 503
