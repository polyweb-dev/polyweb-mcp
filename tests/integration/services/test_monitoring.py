"""Stage 4.5 monitoring acceptance and boundary tests.

These tests intentionally target the not-yet-implemented read-only monitoring
surface. They use local adapters and temporary SQLite repositories only; no
provider network or credentials are involved.
"""

import asyncio
import gc
import inspect
import json
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.server import _quota_state_changed, close_adapters, create_server
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
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    CRDPriceProfile,
    CRDUsageTotal,
    LimitCallContext,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services import monitoring
from freesearch.services.parallel_oauth import clear_oauth_poll_state
from freesearch.services.provider_limits import ProviderLimitsService


class _StubAdapter(ProviderAdapter):
    """Deterministic adapter with independently selectable search/fetch usage."""

    def __init__(
        self,
        name: str,
        *,
        search_units: Decimal | None = Decimal("1.25"),
        fetch_units: Decimal | None = Decimal("2.50"),
        search_at: datetime | None = None,
        fetch_at: datetime | None = None,
        fail_search: bool = False,
        fail_fetch: bool = False,
    ) -> None:
        self._name = name
        self._search_units = search_units
        self._fetch_units = fetch_units
        self.search_at = search_at or datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)
        self.fetch_at = fetch_at or self.search_at + timedelta(seconds=1)
        self._fail_search = fail_search
        self._fail_fetch = fail_fetch

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    def _usage(
        self,
        operation: UsageOperation,
        units: Decimal | None,
        observed_at: datetime,
    ) -> UsageEvent | None:
        if units is None:
            return None
        return UsageEvent(
            provider=self._name,
            operation=operation,
            units=units,
            observed_at=observed_at,
            metadata={"credits": 3, "tokens": 12, "latency_ms": 8.5},
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail_search:
            raise RuntimeError("adapter exploded")
        return SearchResponse(
            query=request.query,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/result",
                    snippet="offline result",
                )
            ],
            provider=self._name,
            total_results=1,
            usage=self._usage(UsageOperation.SEARCH, self._search_units, self.search_at),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        if self._fail_fetch:
            raise RuntimeError("adapter exploded")
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=self.fetch_at,
            ),
            usage=self._usage(UsageOperation.FETCH, self._fetch_units, self.fetch_at),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))


class _HydratingStubAdapter(_StubAdapter):
    """Adapter double that restores a quota snapshot during app startup."""

    async def hydrate_quota(self, repository: SQLiteRepository) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=self.name,
            source=QuotaSource.OBSERVED,
            remaining=Decimal("1000"),
            limit=Decimal("1000"),
            reset_at=datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
            observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata={"window": "hourly"},
        )


class _FailingTelemetryRepository:
    """Write-only repository double that makes telemetry persistence fail."""

    async def record_usage(self, event: UsageEvent) -> None:
        raise OSError("telemetry database unavailable")

    async def record_health(self, health: ProviderHealth) -> None:
        raise OSError("telemetry database unavailable")


class _ReadFailingRepository:
    """Repository double whose monitoring reads consistently fail."""

    async def usage_totals(self, *, since: datetime | None = None) -> list[Any]:
        raise OSError("monitoring read unavailable")

    async def recent_usage(self, *, limit: int = 20) -> list[UsageEvent]:
        raise OSError("monitoring read unavailable")

    async def latest_quota(
        self, provider: str, *, source: QuotaSource | None = None
    ) -> QuotaSnapshot | None:
        raise OSError("monitoring read unavailable")

    async def latest_health(self, provider: str) -> ProviderHealth | None:
        raise OSError("monitoring read unavailable")


class _LeakyRepository:
    """Monitoring-read double that returns payload-bearing storage models."""

    def __init__(self, event: UsageEvent, health: ProviderHealth) -> None:
        self._event = event
        self._health = health

    async def usage_totals(self, *, since: datetime | None = None) -> list[Any]:
        return []

    async def recent_usage(self, *, limit: int = 20) -> list[UsageEvent]:
        return [self._event]

    async def latest_quota(
        self, provider: str, *, source: QuotaSource | None = None
    ) -> QuotaSnapshot | None:
        return None

    async def latest_health(self, provider: str) -> ProviderHealth | None:
        return self._health if provider == self._health.provider else None


_MONITORING_DB_ROOT = Path(".runtime-tmp/monitoring-pytest-dbs")


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles.

    Mirrors the BDD harness helper: retry only PermissionError with a bounded
    pause, propagate every other error immediately, and re-raise once the
    bound is exhausted instead of silently leaking the file.
    """

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def repository() -> AsyncIterator[SQLiteRepository]:
    # An isolated per-test database file: a shared cwd temp name collides with
    # concurrent runs and pytest tmp_path is unavailable in this sandbox.
    _MONITORING_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _MONITORING_DB_ROOT / f"monitoring-{uuid.uuid4().hex}.db"
    db = await SQLiteRepository.open(db_path)
    try:
        yield db
    finally:
        await db.close()
        # Public eviction helpers only: cached quota/OAuth poll state is keyed
        # by id(repository), and a recycled id must never inherit a stale entry.
        monitoring.clear_quota_poll_cache(db)
        clear_oauth_poll_state(db)
        _unlink_with_retries(db_path)
        _unlink_with_retries(Path(f"{db_path}.migration.lock"))


def _event(
    provider: str,
    operation: UsageOperation,
    units: str,
    observed_at: datetime,
    *,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=Decimal(units),
        observed_at=observed_at,
        metadata={"tokens": 1} if metadata is None else metadata,
    )


def _quota(provider: str, source: QuotaSource, observed_at: datetime) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider=provider,
        source=source,
        remaining=Decimal("97.5"),
        limit=Decimal("100"),
        reset_at=observed_at + timedelta(hours=1),
        observed_at=observed_at,
    )


def _health(provider: str, status: HealthStatus, checked_at: datetime) -> ProviderHealth:
    return ProviderHealth(provider=provider, status=status, checked_at=checked_at, message=None)


_DASHBOARD_KEYS = {
    "notice",
    "usage_totals",
    "recent_usage",
    "latest_quota",
    "latest_health",
    "generated_at",
    "crd_usage_totals",
    "provider_limits",
}

_STATS_KEYS = {
    "notice",
    "usage_totals",
    "recent_usage",
    "latest_quota",
    "latest_health",
    "crd_usage_totals",
}


def _dashboard_response_model() -> Any:
    """Return the planned response model, failing cleanly before implementation."""
    model = getattr(monitoring, "DashboardResponse", None)
    assert model is not None, "DashboardResponse has not been implemented"
    return model


def _parse_utc_datetime(value: Any) -> datetime:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    return parsed


def _assert_dashboard_contract_keys(body: Any) -> None:
    assert isinstance(body, dict)
    assert set(body) == _DASHBOARD_KEYS
    assert body["notice"] == monitoring.MONITORING_NOTICE
    assert isinstance(body["crd_usage_totals"], list)
    assert isinstance(body["provider_limits"], list)


def _assert_stats_contract_keys(body: Any) -> None:
    assert isinstance(body, dict)
    assert set(body) == _STATS_KEYS


async def test_rest_search_persists_usage_and_healthy_health(
    repository: SQLiteRepository,
) -> None:
    adapter = _StubAdapter("rest-provider", fetch_units=None)
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "offline"})

    assert response.status_code == 200
    assert response.json()["provider"] == "rest-provider"
    assert await repository.list_usage() == [
        UsageEvent(
            provider="rest-provider",
            operation=UsageOperation.SEARCH,
            units=Decimal("1.25"),
            observed_at=adapter.search_at,
            metadata={"credits": 3, "tokens": 12, "latency_ms": 8.5},
        )
    ]
    assert await repository.latest_health("rest-provider") == ProviderHealth(
        provider="rest-provider",
        status=HealthStatus.HEALTHY,
        checked_at=adapter.search_at,
        message=None,
    )


async def test_usage_write_rejection_does_not_skip_healthy_health(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    usage = UsageEvent(
        provider="usage-rejected",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=observed_at,
        metadata={"query": "x"},
    )
    response = SearchResponse(
        query="not persisted",
        results=[],
        provider="usage-rejected",
        usage=usage,
    )

    await monitoring.record_response_telemetry(repository, response)

    assert await repository.list_usage() == []
    assert await repository.latest_health("usage-rejected") == ProviderHealth(
        provider="usage-rejected",
        status=HealthStatus.HEALTHY,
        checked_at=observed_at,
        message=None,
    )


async def test_numeric_exa_usage_persists_with_healthy_health(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    usage = UsageEvent(
        provider="exa",
        operation=UsageOperation.SEARCH,
        units=Decimal("0.0042"),
        observed_at=observed_at,
        metadata={},
    )
    response = SearchResponse(query="exa", results=[], provider="exa", usage=usage)

    await monitoring.record_response_telemetry(repository, response)

    assert await repository.list_usage() == [usage]
    assert await repository.latest_health("exa") == ProviderHealth(
        provider="exa",
        status=HealthStatus.HEALTHY,
        checked_at=observed_at,
        message=None,
    )


async def test_rest_fetch_and_mcp_search_fetch_persist_identical_usage(
    repository: SQLiteRepository,
) -> None:
    adapter = _StubAdapter("shared-provider")
    rest_app = create_app([adapter], repository=repository)
    with TestClient(rest_app) as client:
        rest_response = client.post("/fetch", json={"url": "https://example.com/rest"})

    server = create_server([adapter], repository=repository)
    mcp_search = await server.call_tool("search", {"request": {"query": "mcp"}})
    mcp_fetch = await server.call_tool("fetch", {"request": {"url": "https://example.com/mcp"}})

    assert rest_response.status_code == 200
    assert isinstance(mcp_search[0], Sequence)
    assert not isinstance(mcp_search[0], bool)
    assert isinstance(mcp_fetch[0], Sequence)
    assert not isinstance(mcp_fetch[0], bool)
    assert mcp_search[1]["provider"] == "shared-provider"
    assert mcp_search[1]["usage"]["operation"] == "search"
    assert mcp_fetch[1]["usage"]["operation"] == "fetch"
    usage_pairs = [(event.operation.value, event.units) for event in await repository.list_usage()]
    assert sorted(usage_pairs) == sorted(
        [
            (UsageOperation.FETCH.value, Decimal("2.50")),
            (UsageOperation.SEARCH.value, Decimal("1.25")),
            (UsageOperation.FETCH.value, Decimal("2.50")),
        ]
    )
    shared_health = await repository.latest_health("shared-provider")
    assert shared_health is not None
    assert shared_health.status is HealthStatus.HEALTHY


async def test_usage_none_still_records_healthy_health(repository: SQLiteRepository) -> None:
    adapter = _StubAdapter("health-only", search_units=None, fetch_units=None)
    app = create_app([adapter], repository=repository)
    start = datetime.now(UTC) - timedelta(seconds=1)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "no usage"})

    end = datetime.now(UTC) + timedelta(seconds=1)
    assert response.status_code == 200
    assert await repository.list_usage() == []
    health = await repository.latest_health("health-only")
    assert health is not None
    assert health.provider == "health-only"
    assert health.status is HealthStatus.HEALTHY
    assert health.message is None
    assert start <= health.checked_at <= end


async def test_fetch_without_usage_uses_document_fetched_at_for_health(
    repository: SQLiteRepository,
) -> None:
    adapter = _StubAdapter("fetch-health-only", search_units=None, fetch_units=None)
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        response = client.post("/fetch", json={"url": "https://example.com/no-usage"})

    assert response.status_code == 200
    assert response.json()["usage"] is None
    assert await repository.list_usage() == []
    assert await repository.latest_health("fetch-health-only") == ProviderHealth(
        provider="fetch-health-only",
        status=HealthStatus.HEALTHY,
        checked_at=adapter.fetch_at,
        message=None,
    )


async def test_adapter_failure_records_degraded_and_preserves_rest_and_mcp_errors(
    repository: SQLiteRepository,
) -> None:
    rest_app = create_app(
        [_StubAdapter("rest-failure", fail_search=True)],
        repository=repository,
    )
    with TestClient(rest_app, raise_server_exceptions=False) as client:
        rest_response = client.post("/search", json={"query": "failure"})

    assert rest_response.status_code == 500
    rest_health = await repository.latest_health("rest-failure")
    assert rest_health is not None
    assert rest_health.provider == "rest-failure"
    assert rest_health.status is HealthStatus.DEGRADED
    assert rest_health.message is None

    mcp_server = create_server(
        [_StubAdapter("mcp-failure", fail_search=True)],
        repository=repository,
    )
    with pytest.raises(ToolError, match="adapter exploded"):
        await mcp_server.call_tool("search", {"request": {"query": "failure"}})
    mcp_health = await repository.latest_health("mcp-failure")
    assert mcp_health is not None
    assert mcp_health.provider == "mcp-failure"
    assert mcp_health.status is HealthStatus.DEGRADED
    assert mcp_health.message is None


async def test_telemetry_failure_never_breaks_rest_request() -> None:
    adapter = _StubAdapter("telemetry-down")
    app = create_app([adapter], repository=_FailingTelemetryRepository())

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "still works"})

    assert response.status_code == 200
    assert response.json()["provider"] == "telemetry-down"


async def test_privacy_gate_blocks_sensitive_keys_allows_benign_telemetry(
    repository: SQLiteRepository,
) -> None:
    """Pin the approved metadata blocklist through the telemetry write path.

    Sensitive keys are rejected for any value type (proving key-based, not
    value-based, blocking); benign telemetry — including plain strings and
    substring lookalikes such as url_count — persists and round-trips.
    """
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    invalid_events = [
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"query": 7}),
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"url": 7}),
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"api_key": 7}),
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"token": "x"}),
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"session": "abc"}),
        _event("private", UsageOperation.SEARCH, "1", observed_at, metadata={"content": "doc"}),
    ]

    for invalid_event in invalid_events:
        with pytest.raises(ValueError):
            await repository.record_usage(invalid_event)
        assert await repository.list_usage() == []
    benign = _event(
        "private",
        UsageOperation.SEARCH,
        "1",
        observed_at,
        metadata={"note": "secret-free note", "url_count": 4},
    )
    await repository.record_usage(benign)
    assert await repository.list_usage() == [benign]


async def test_privacy_gate_rejects_credential_aliases(
    repository: SQLiteRepository,
) -> None:
    """Critic OBJECT-1 through the telemetry write path: credential aliases.

    passwd, private_key, client_secret, x-api-key, and id_token — in every
    case/separator spelling, for string and non-string values — must be
    rejected exactly like their canonical keys.
    """
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    invalid_metadatas = [
        {"passwd": "x"},
        {"PASSWD": "x"},
        {"private_key": "sek"},
        {"Private-Key": "sek"},
        {"client_secret": "s"},
        {"CLIENT-SECRET": "s"},
        {"x-api-key": "sk"},
        {"X-Api-Key": "sk"},
        {"id_token": "t"},
        {"ID-TOKEN": "t"},
        {"passwd": 12345},
        {"private_key": ["a", "b"]},
        {"client_secret": {"nested": 1}},
        {"x-api-key": 7},
        {"id_token": True},
    ]
    for metadata in invalid_metadatas:
        with pytest.raises(ValueError):
            await repository.record_usage(
                _event("private", UsageOperation.SEARCH, "1", observed_at, metadata=metadata)
            )
        assert await repository.list_usage() == []


async def test_collect_stats_shape_ordering_grouping_and_quota_provenance(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        _event("alpha", UsageOperation.SEARCH, "123.456789", t0),
        _event("alpha", UsageOperation.SEARCH, "0.000001", t0 + timedelta(seconds=1)),
        _event("alpha", UsageOperation.FETCH, "2", t0 + timedelta(seconds=2)),
        _event("beta", UsageOperation.SEARCH, "3", t0 + timedelta(seconds=3)),
    ]
    for event in events:
        await repository.record_usage(event)
    await repository.record_quota(_quota("alpha", QuotaSource.AUTHORITATIVE, t0))
    await repository.record_quota(_quota("beta", QuotaSource.OBSERVED, t0 + timedelta(seconds=1)))
    await repository.record_health(_health("alpha", HealthStatus.HEALTHY, t0))
    await repository.record_health(_health("beta", HealthStatus.DEGRADED, t0))

    stats = await monitoring.collect_stats(
        repository,
        adapter_names=("alpha", "beta", "empty"),
        recent_limit=monitoring.DEFAULT_RECENT_LIMIT,
    )

    assert set(stats.model_dump()) == {
        "notice",
        "usage_totals",
        "recent_usage",
        "latest_quota",
        "latest_health",
        "crd_usage_totals",
    }
    assert stats.notice == monitoring.MONITORING_NOTICE
    assert stats.crd_usage_totals == []
    assert [
        (total.provider, total.operation, total.total_units, total.event_count)
        for total in stats.usage_totals
    ] == [
        ("alpha", UsageOperation.FETCH, Decimal("2"), 1),
        ("alpha", UsageOperation.SEARCH, Decimal("123.456790"), 2),
        ("beta", UsageOperation.SEARCH, Decimal("3"), 1),
    ]
    assert [event.provider for event in stats.recent_usage] == [
        "beta",
        "alpha",
        "alpha",
        "alpha",
    ]
    assert {snapshot.provider for snapshot in stats.latest_quota} == {"alpha", "beta"}
    assert {snapshot.source for snapshot in stats.latest_quota} == {
        QuotaSource.AUTHORITATIVE,
        QuotaSource.OBSERVED,
    }
    assert all(snapshot.source is not None for snapshot in stats.latest_quota)
    assert {health.provider for health in stats.latest_health} == {"alpha", "beta"}


async def test_crd_usage_totals_sum_exact_success_volume_only(
    repository: SQLiteRepository,
) -> None:
    """T2: populated totals sum exact success debits; a released failure is absent."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    record = ProviderLimitRecord(
        provider="totals-provider",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=[], published=False),
        budget=BudgetBlock(
            model=BudgetModel.USD, standard_native_cost=Decimal("0.005")
        ),
        native_unit=UnitKind.USD,
        native_pool_id="totals-provider:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )
    limits = ProviderLimitsService(
        repository.limits, records=[record], tier_defaults={}
    )
    await limits.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="totals-provider:keyed:USD",
            provider="totals-provider",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=t0,
            remaining=Decimal("5.000"),
            allowance=Decimal("5.000"),
            credential_generation=0,
        )
    )
    for attempt in ("totals-1", "totals-2"):
        admission = await limits.admit(
            LimitCallContext(
                provider="totals-provider",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id=attempt,
                requested_at=t0,
            )
        )
        await limits.record_success(
            admission,
            SearchResponse(query="totals", results=[], provider="totals-provider"),
        )
    released = await limits.admit(
        LimitCallContext(
            provider="totals-provider",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            attempt_id="totals-3",
            requested_at=t0,
        )
    )
    await limits.record_failure(
        released,
        ProviderError(
            provider="totals-provider", code="timeout", message="synthetic timeout"
        ),
    )

    stats = await monitoring.collect_stats(repository, adapter_names=(), limits=limits)

    assert stats.crd_usage_totals == [
        CRDUsageTotal(
            provider="totals-provider",
            operation=LimitOperation.SEARCH,
            normalized_crd=Decimal("10"),
            attempt_count=2,
            volume_count=2,
        )
    ]


async def test_stats_projection_strips_health_message_usage_metadata_and_request_id() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    event = UsageEvent(
        provider="leaky",
        operation=UsageOperation.SEARCH,
        units=Decimal("1.5"),
        observed_at=observed_at,
        request_id="r-1",
        metadata={"query": "private text"},
    )
    health = ProviderHealth(
        provider="leaky",
        status=HealthStatus.HEALTHY,
        checked_at=observed_at,
        message="https://secret.example/x api_key=zzz",
    )
    repository = cast(SQLiteRepository, _LeakyRepository(event, health))

    stats = await monitoring.collect_stats(repository, adapter_names=())

    recent_dump = stats.recent_usage[0].model_dump()
    assert set(recent_dump) == {
        "provider",
        "operation",
        "units",
        "observed_at",
        "latency_ms",
        "status",
    }
    assert "metadata" not in recent_dump
    assert "request_id" not in recent_dump
    assert recent_dump["provider"] == "leaky"
    assert recent_dump["operation"] is UsageOperation.SEARCH
    assert recent_dump["units"] == Decimal("1.5")
    assert recent_dump["observed_at"] == observed_at

    health_dump = stats.latest_health[0].model_dump()
    assert set(health_dump) == {"provider", "status", "checked_at"}
    assert "message" not in health_dump
    assert health_dump["provider"] == "leaky"
    assert health_dump["status"] is HealthStatus.HEALTHY
    assert health_dump["checked_at"] == observed_at


async def test_stats_endpoint_omits_sensitive_keys_end_to_end(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.record_health(
        ProviderHealth(
            provider="endpoint-provider",
            status=HealthStatus.HEALTHY,
            checked_at=observed_at,
            message="secret msg",
        )
    )
    await repository.record_usage(
        UsageEvent(
            provider="endpoint-provider",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=observed_at,
            request_id="r-9",
            metadata={"credits": 1},
        )
    )
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert len(body["recent_usage"]) == 1
    assert set(body["recent_usage"][0]) == {
        "provider",
        "operation",
        "units",
        "observed_at",
        "latency_ms",
        "status",
    }
    assert "metadata" not in body["recent_usage"][0]
    assert "request_id" not in body["recent_usage"][0]
    assert len(body["latest_health"]) == 1
    assert set(body["latest_health"][0]) == {"provider", "status", "checked_at"}
    assert "message" not in body["latest_health"][0]


async def test_stats_endpoint_clamps_recent_limit_and_returns_contract_shape(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(monitoring.MAX_RECENT_LIMIT + 1):
        await repository.record_usage(
            _event(
                "alpha",
                UsageOperation.SEARCH,
                "0.000001",
                t0 + timedelta(seconds=index),
            )
        )
    app = create_app([_StubAdapter("alpha")], repository=repository)

    with TestClient(app) as client:
        low = client.get("/stats?limit=0")
        high = client.get("/stats?limit=1000")

    assert low.status_code == 200
    assert high.status_code == 200
    assert set(low.json()) == {
        "notice",
        "usage_totals",
        "recent_usage",
        "latest_quota",
        "latest_health",
        "crd_usage_totals",
    }
    assert low.json()["crd_usage_totals"] == []
    assert len(low.json()["recent_usage"]) == 1
    assert len(high.json()["recent_usage"]) == monitoring.MAX_RECENT_LIMIT
    assert (
        high.json()["recent_usage"][0]["observed_at"]
        > high.json()["recent_usage"][-1]["observed_at"]
    )


def test_dashboard_route_declares_pydantic_response_model() -> None:
    app = create_app([_StubAdapter("response-model")], repository=None)
    dashboard_route = next(route for route in app.routes if route.path == "/dashboard")

    assert dashboard_route.response_model is _dashboard_response_model()


async def test_no_repository_stats_and_dashboard_reads_are_empty_200() -> None:
    app = create_app([_StubAdapter("no-repository")], repository=None)
    before_dashboard = datetime.now(UTC)

    with TestClient(app) as client:
        stats = client.get("/stats")
        dashboard = client.get("/dashboard")

    after_dashboard = datetime.now(UTC)
    assert stats.status_code == 200
    assert stats.json() == {
        "notice": monitoring.MONITORING_NOTICE,
        "usage_totals": [],
        "recent_usage": [],
        "latest_quota": [],
        "latest_health": [],
        "crd_usage_totals": [],
    }
    assert dashboard.status_code == 200
    assert "application/json" in dashboard.headers["content-type"]
    assert "text/html" not in dashboard.headers["content-type"]
    dashboard_body = dashboard.json()
    _assert_dashboard_contract_keys(dashboard_body)
    assert dashboard_body["usage_totals"] == []
    assert dashboard_body["recent_usage"] == []
    assert dashboard_body["latest_quota"] == []
    assert dashboard_body["latest_health"] == []
    assert dashboard_body["crd_usage_totals"] == []
    assert dashboard_body["provider_limits"] == []
    generated_at = _parse_utc_datetime(dashboard_body["generated_at"])
    assert before_dashboard <= generated_at <= after_dashboard


async def test_monitoring_read_failures_return_empty_stats_and_json_dashboard() -> None:
    repository = cast(SQLiteRepository, _ReadFailingRepository())
    app = create_app([_StubAdapter("read-failure")], repository=repository)

    with TestClient(app) as client:
        stats = client.get("/stats")
        dashboard = client.get("/dashboard")

    assert stats.status_code == 200
    assert stats.json() == {
        "notice": monitoring.MONITORING_NOTICE,
        "usage_totals": [],
        "recent_usage": [],
        "latest_quota": [],
        "latest_health": [],
        "crd_usage_totals": [],
    }
    assert dashboard.status_code == 200
    assert "application/json" in dashboard.headers["content-type"]
    assert "text/html" not in dashboard.headers["content-type"]
    dashboard_body = dashboard.json()
    _assert_dashboard_contract_keys(dashboard_body)
    assert dashboard_body["usage_totals"] == []
    assert dashboard_body["recent_usage"] == []
    assert dashboard_body["latest_quota"] == []
    assert dashboard_body["latest_health"] == []
    assert dashboard_body["crd_usage_totals"] == []
    assert dashboard_body["provider_limits"] == []
    _parse_utc_datetime(dashboard_body["generated_at"])


def test_dashboard_response_contract_is_strict_and_decimal_round_trip() -> None:
    dashboard_model = _dashboard_response_model()
    observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    stats = monitoring.StatsResponse(
        notice=monitoring.MONITORING_NOTICE,
        usage_totals=[
            monitoring.ProviderUsageTotal(
                provider="contract-provider",
                operation=UsageOperation.SEARCH,
                total_units=Decimal("123.456789"),
                event_count=7,
            )
        ],
        recent_usage=[
            monitoring.RecentUsageEntry(
                provider="contract-provider",
                operation=UsageOperation.FETCH,
                units=Decimal("0.000001"),
                observed_at=observed_at,
            )
        ],
        latest_quota=[_quota("contract-provider", QuotaSource.AUTHORITATIVE, observed_at)],
        latest_health=[
            monitoring.LatestHealthEntry(
                provider="contract-provider",
                status=HealthStatus.HEALTHY,
                checked_at=observed_at,
            )
        ],
    )
    payload = stats.model_dump()
    payload["generated_at"] = observed_at

    dashboard = dashboard_model.model_validate(payload)
    assert set(dashboard_model.model_fields) == set(monitoring.StatsResponse.model_fields) | {
        "generated_at",
        "provider_limits",
    }
    assert dashboard_model.model_config.get("extra") == "forbid"
    assert dashboard.provider_limits == []
    assert dashboard.crd_usage_totals == []
    assert dashboard.model_dump() == {**payload, "provider_limits": []}
    assert dashboard.usage_totals[0].total_units == Decimal("123.456789")
    assert dashboard.recent_usage[0].units == Decimal("0.000001")
    assert dashboard.latest_quota[0].remaining == Decimal("97.5")

    with pytest.raises(ValidationError):
        dashboard_model.model_validate({**payload, "unexpected": "field"})
    with pytest.raises(ValidationError):
        dashboard_model.model_validate({**payload, "generated_at": datetime(2026, 1, 1, 12, 0)})


async def test_dashboard_endpoint_matches_stats_and_preserves_quota_provenance(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.record_usage(_event("alpha", UsageOperation.SEARCH, "1.25", observed_at))
    await repository.record_usage(
        _event("beta", UsageOperation.FETCH, "2.5", observed_at + timedelta(seconds=1))
    )
    await repository.record_quota(_quota("alpha", QuotaSource.AUTHORITATIVE, observed_at))
    await repository.record_quota(
        _quota("beta", QuotaSource.OBSERVED, observed_at + timedelta(seconds=1))
    )
    await repository.record_health(_health("alpha", HealthStatus.HEALTHY, observed_at))
    await repository.record_health(
        _health("beta", HealthStatus.DEGRADED, observed_at + timedelta(seconds=1))
    )
    app = create_app(
        [_StubAdapter("alpha"), _StubAdapter("beta")],
        repository=repository,
    )
    before_dashboard = datetime.now(UTC)

    with TestClient(app) as client:
        stats_response = client.get("/stats")
        dashboard_response = client.get("/dashboard")

    after_dashboard = datetime.now(UTC)
    assert stats_response.status_code == 200
    assert dashboard_response.status_code == 200
    assert "application/json" in dashboard_response.headers["content-type"]
    assert "text/html" not in dashboard_response.headers["content-type"]
    stats_body = stats_response.json()
    dashboard_body = dashboard_response.json()
    _assert_dashboard_contract_keys(dashboard_body)
    _assert_stats_contract_keys(stats_body)
    assert {
        key: value
        for key, value in dashboard_body.items()
        if key not in ("generated_at", "provider_limits")
    } == stats_body
    assert dashboard_body["crd_usage_totals"] == stats_body["crd_usage_totals"] == []
    assert isinstance(dashboard_body["provider_limits"], list)
    catalog_records = await repository.limits.list_records()
    expected_cards = len({record.provider for record in catalog_records})
    assert len(dashboard_body["provider_limits"]) == expected_cards
    for entry in dashboard_body["provider_limits"]:
        assert set(entry) >= {"provider", "active_auth_mode", "auths"}
    assert {(entry["provider"], entry["source"]) for entry in dashboard_body["latest_quota"]} == {
        ("alpha", "authoritative"),
        ("beta", "observed"),
    }
    assert "local-observed only" in dashboard_body["notice"]
    assert "10\N{EN DASH}15 min" in dashboard_body["notice"]
    generated_at = _parse_utc_datetime(dashboard_body["generated_at"])
    assert before_dashboard <= generated_at <= after_dashboard


async def test_dashboard_endpoint_accepts_canonical_quota_computed_fields(
    repository: SQLiteRepository,
) -> None:
    """Computed wire fields must not be fed back through strict input validation."""

    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    await repository.record_quota(
        QuotaSnapshot(
            provider="tavily",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("996"),
            limit=Decimal("1000"),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=observed_at,
        )
    )
    app = create_app([_StubAdapter("tavily")], repository=repository)

    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    quota = response.json()["latest_quota"][0]
    assert quota["remaining_percent"] == "99.600"
    assert quota["unit_kind"] == "CREDIT"
    assert quota["display_unit"] == "credits"


async def test_dashboard_endpoint_clamps_recent_limit_and_orders_newest_first(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(monitoring.MAX_RECENT_LIMIT + 1):
        await repository.record_usage(
            _event(
                "limit-provider",
                UsageOperation.SEARCH,
                "0.000001",
                observed_at + timedelta(seconds=index),
            )
        )
    app = create_app([_StubAdapter("limit-provider")], repository=repository)

    with TestClient(app) as client:
        low = client.get("/dashboard?limit=0")
        high = client.get("/dashboard?limit=1000")

    assert low.status_code == 200
    assert high.status_code == 200
    assert "application/json" in low.headers["content-type"]
    assert "application/json" in high.headers["content-type"]
    low_body = low.json()
    high_body = high.json()
    _assert_dashboard_contract_keys(low_body)
    _assert_dashboard_contract_keys(high_body)
    assert len(low_body["recent_usage"]) == 1
    assert len(high_body["recent_usage"]) == monitoring.MAX_RECENT_LIMIT
    assert (
        high_body["recent_usage"][0]["observed_at"] > high_body["recent_usage"][-1]["observed_at"]
    )
    _parse_utc_datetime(low_body["generated_at"])
    _parse_utc_datetime(high_body["generated_at"])


async def test_dashboard_endpoint_omits_sensitive_projection_fields_and_values(
    repository: SQLiteRepository,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    private_query = "PRIVATE_QUERY_should_not_be_rendered"
    private_url = "https://secret.example/private-document"
    private_document = "private-provider document"
    await repository.record_usage(
        UsageEvent(
            provider="privacy-provider",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=observed_at,
            request_id=private_query,
            metadata={"credits": 1},
        )
    )
    await repository.record_health(
        ProviderHealth(
            provider="privacy-provider",
            status=HealthStatus.HEALTHY,
            checked_at=observed_at,
            message=(
                f"{private_url} {private_document} Authorization: Bearer token "
                "api_key=top-secret secret msg"
            ),
        )
    )
    await repository.record_quota(_quota("privacy-provider", QuotaSource.OBSERVED, observed_at))
    app = create_app([_StubAdapter("privacy-provider")], repository=repository)

    with TestClient(app) as client:
        stats_response = client.get("/stats")
        dashboard_response = client.get("/dashboard")

    assert stats_response.status_code == 200
    assert dashboard_response.status_code == 200
    assert "application/json" in dashboard_response.headers["content-type"]
    stats_body = stats_response.json()
    dashboard_body = dashboard_response.json()
    _assert_dashboard_contract_keys(dashboard_body)
    _assert_stats_contract_keys(stats_body)
    assert stats_body["crd_usage_totals"] == []
    assert dashboard_body["crd_usage_totals"] == []
    assert isinstance(dashboard_body["provider_limits"], list)
    catalog_records = await repository.limits.list_records()
    expected_cards = len({record.provider for record in catalog_records})
    assert len(dashboard_body["provider_limits"]) == expected_cards
    for body in (stats_body, dashboard_body):
        assert len(body["usage_totals"]) == 1
        assert set(body["usage_totals"][0]) == {
            "provider",
            "operation",
            "total_units",
            "event_count",
        }
        assert len(body["recent_usage"]) == 1
        assert len(body["latest_quota"]) == 1
        assert set(body["latest_quota"][0]) == {
            "provider",
            "source",
            "remaining",
            "limit",
            "reset_at",
            "observed_at",
        }
        assert len(body["latest_health"]) == 1
        assert set(body["recent_usage"][0]) == {
            "provider",
            "operation",
            "units",
            "observed_at",
            "latency_ms",
            "status",
        }
        assert set(body["latest_health"][0]) == {"provider", "status", "checked_at"}
        for entry in body["recent_usage"] + body["latest_health"]:
            assert "metadata" not in entry
            assert "request_id" not in entry
            assert "message" not in entry

    for body in (stats_body, dashboard_body):
        payload_text = json.dumps(body, sort_keys=True)
        for forbidden in (
            private_query,
            private_url,
            private_document,
            "Authorization: Bearer",
            "api_key",
            "secret msg",
        ):
            assert forbidden not in payload_text


async def test_dashboard_generated_at_is_utc_and_non_decreasing_on_empty_repository() -> None:
    app = create_app([_StubAdapter("freshness-provider")], repository=None)

    with TestClient(app) as client:
        first = client.get("/dashboard")
        second = client.get("/dashboard")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "application/json" in first.headers["content-type"]
    assert "application/json" in second.headers["content-type"]
    first_body = first.json()
    second_body = second.json()
    _assert_dashboard_contract_keys(first_body)
    _assert_dashboard_contract_keys(second_body)
    for body in (first_body, second_body):
        assert body["usage_totals"] == []
        assert body["recent_usage"] == []
        assert body["latest_quota"] == []
        assert body["latest_health"] == []
        assert body["crd_usage_totals"] == []
        assert body["provider_limits"] == []
    first_generated_at = _parse_utc_datetime(first_body["generated_at"])
    second_generated_at = _parse_utc_datetime(second_body["generated_at"])
    assert first_generated_at <= second_generated_at


async def test_app_owned_repository_lifespan_creates_and_closes_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("freesearch.routers.api.build_adapters", lambda _client: [])
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    database = tmp_path / "owned-app.db"
    app = create_app(None, database=database)

    with TestClient(app):
        owned = app.state.repository
        assert isinstance(owned, SQLiteRepository)
        assert database.is_file()

    assert app.state.repository is None
    assert closed == [owned]


async def test_app_lifespan_hydrates_local_quota_before_first_dashboard_read(
    repository: SQLiteRepository,
) -> None:
    adapter = _HydratingStubAdapter("keenable")
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.json()["latest_quota"] == [
        {
            "provider": "keenable",
            "source": "observed",
            "remaining": "1000",
            "remaining_percent": "100",
            "limit": "1000",
            "reset_at": "2026-01-01T13:00:00Z",
            "observed_at": "2026-01-01T12:00:00Z",
            "unit_kind": "REQUEST",
            "display_unit": "requests",
            "window": "hourly",
        }
    ]


def test_quota_hydration_refreshes_an_expired_rolling_window() -> None:
    observed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    current = QuotaSnapshot(
        provider="keenable",
        source=QuotaSource.OBSERVED,
        remaining=Decimal("1000"),
        limit=Decimal("1000"),
        reset_at=observed + timedelta(hours=1),
        observed_at=observed,
        unit_kind=UnitKind.REQUEST,
        display_unit="requests",
        metadata={"window": "hourly"},
    )
    refreshed = current.model_copy(
        update={
            "observed_at": observed + timedelta(hours=2),
            "reset_at": observed + timedelta(hours=3),
        }
    )

    assert _quota_state_changed(current, refreshed) is True


async def test_server_owned_repository_lifespan_creates_and_closes_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("freesearch.mcp.server.build_adapters", lambda _client: [])
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    database = tmp_path / "owned-server.db"
    server = create_server(None, database=database)

    async with server._mcp_server.lifespan(server):
        assert database.is_file()

    assert len(closed) == 1
    assert type(closed[0]) is SQLiteRepository


@pytest.mark.parametrize("exit_order", [("a", "b"), ("b", "a")])
async def test_server_owned_lifespan_refcounted_across_overlapping_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_order: tuple[str, str],
) -> None:
    monkeypatch.setattr(
        "freesearch.mcp.server.adapter_factory",
        lambda name: (
            (lambda client, api_key=None: _StubAdapter("x")) if name == "keenable" else None
        ),
    )
    opened: list[SQLiteRepository] = []
    real_open = SQLiteRepository.open

    async def open_spy(cls: type[SQLiteRepository], database: str | Path) -> SQLiteRepository:
        repository = await real_open(database)
        opened.append(repository)
        return repository

    monkeypatch.setattr(SQLiteRepository, "open", classmethod(open_spy))
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    server = create_server(None, database=tmp_path / "ref.db")
    lifespans = {
        "a": server._mcp_server.lifespan(server),
        "b": server._mcp_server.lifespan(server),
    }
    entered: set[str] = set()
    exited: set[str] = set()

    try:
        await lifespans["a"].__aenter__()
        entered.add("a")
        await lifespans["b"].__aenter__()
        entered.add("b")

        assert len(opened) == 1
        repository = opened[0]
        first_result = await server.call_tool("search", {"request": {"query": "session a"}})
        second_result = await server.call_tool("search", {"request": {"query": "session b"}})
        assert first_result[1]["provider"] == "x"
        assert second_result[1]["provider"] == "x"
        assert [
            (event.provider, event.operation, event.units)
            for event in await repository.list_usage()
        ] == [
            ("x", UsageOperation.SEARCH, Decimal("1.25")),
            ("x", UsageOperation.SEARCH, Decimal("1.25")),
        ]

        first_exit, second_exit = exit_order
        await lifespans[first_exit].__aexit__(None, None, None)
        exited.add(first_exit)
        assert closed == []
        between_event = UsageEvent(
            provider="between-sessions",
            operation=UsageOperation.FETCH,
            units=Decimal("2"),
            observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        await repository.record_usage(between_event)
        ledger = await repository.list_usage()
        assert len(ledger) == 3
        assert between_event in ledger
        assert sorted(
            (event.provider, event.operation.value, event.units)
            for event in ledger
            if event.provider == "x"
        ) == [
            ("x", UsageOperation.SEARCH.value, Decimal("1.25")),
            ("x", UsageOperation.SEARCH.value, Decimal("1.25")),
        ]

        await lifespans[second_exit].__aexit__(None, None, None)
        exited.add(second_exit)
        assert closed == [repository]
    finally:
        for name in ("a", "b"):
            if name in entered and name not in exited:
                await lifespans[name].__aexit__(None, None, None)
        for repository in opened:
            if repository not in closed:
                await real_close(repository)


async def test_server_owned_lifespan_sequential_sessions_reuse_fresh_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build_count = 0
    build_clients: list[Any] = []

    def factory_spy(name: str) -> Any:
        if name != "keenable":
            return None

        def build(client: Any, api_key: Any = None) -> ProviderAdapter:
            nonlocal build_count
            build_count += 1
            build_clients.append(client)
            return _StubAdapter("x")

        return build

    monkeypatch.setattr("freesearch.mcp.server.adapter_factory", factory_spy)
    opened: list[SQLiteRepository] = []
    real_open = SQLiteRepository.open

    async def open_spy(cls: type[SQLiteRepository], database: str | Path) -> SQLiteRepository:
        repository = await real_open(database)
        opened.append(repository)
        return repository

    monkeypatch.setattr(SQLiteRepository, "open", classmethod(open_spy))
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    database = tmp_path / "seq.db"
    server = create_server(None, database=database)

    async with server._mcp_server.lifespan(server):
        first_result = await server.call_tool("search", {"request": {"query": "session one"}})
        assert first_result[1]["provider"] == "x"
        assert first_result[1]["usage"]["provider"] == "x"
        assert first_result[1]["usage"]["operation"] == "search"
        assert first_result[1]["usage"]["units"] == "1.25"

    assert len(opened) == 1
    assert len(closed) == 1

    async with server._mcp_server.lifespan(server):
        second_result = await server.call_tool("search", {"request": {"query": "session two"}})
        assert second_result[1]["provider"] == "x"
        assert second_result[1]["usage"]["provider"] == "x"
        assert second_result[1]["usage"]["operation"] == "search"
        assert second_result[1]["usage"]["units"] == "1.25"

    assert build_count == 2
    assert build_clients[0] is not build_clients[1]
    assert len(opened) == 2
    assert len(closed) == 2
    assert closed == opened

    inspection_repository = await real_open(database)
    try:
        usage = await inspection_repository.list_usage()
    finally:
        await real_close(inspection_repository)

    assert [(event.provider, event.operation, event.units) for event in usage] == [
        ("x", UsageOperation.SEARCH, Decimal("1.25")),
        ("x", UsageOperation.SEARCH, Decimal("1.25")),
    ]


async def test_server_owned_lifespan_delayed_teardown_does_not_close_new_session_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build_count = 0
    build_clients: list[Any] = []

    def factory_spy(name: str) -> Any:
        if name != "keenable":
            return None

        def build(client: Any, api_key: Any = None) -> ProviderAdapter:
            nonlocal build_count
            build_count += 1
            build_clients.append(client)
            return _StubAdapter("x")

        return build

    monkeypatch.setattr("freesearch.mcp.server.adapter_factory", factory_spy)
    opened: list[SQLiteRepository] = []
    real_open = SQLiteRepository.open

    async def open_spy(cls: type[SQLiteRepository], database: str | Path) -> SQLiteRepository:
        repository = await real_open(database)
        opened.append(repository)
        return repository

    monkeypatch.setattr(SQLiteRepository, "open", classmethod(open_spy))
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    real_close_adapters = close_adapters
    teardown_gate = asyncio.Event()
    teardown_started = asyncio.Event()

    async def close_adapters_spy(adapters: Sequence[ProviderAdapter], client: Any = None) -> None:
        teardown_started.set()
        await teardown_gate.wait()
        await real_close_adapters(adapters, client)

    monkeypatch.setattr("freesearch.mcp.server.close_adapters", close_adapters_spy)
    server = create_server(None, database=tmp_path / "race.db")
    lifespans = {name: server._mcp_server.lifespan(server) for name in ("a", "b", "c")}
    entered: set[str] = set()
    exited: set[str] = set()
    teardown_task: asyncio.Task[Any] | None = None

    try:
        await lifespans["a"].__aenter__()
        entered.add("a")
        await lifespans["b"].__aenter__()
        entered.add("b")

        first_result = await server.call_tool("search", {"request": {"query": "session a"}})
        assert first_result[1]["provider"] == "x"
        assert first_result[1]["usage"]["operation"] == "search"
        assert first_result[1]["usage"]["units"] == "1.25"

        await lifespans["a"].__aexit__(None, None, None)
        exited.add("a")
        assert closed == []

        teardown_task = asyncio.create_task(lifespans["b"].__aexit__(None, None, None))
        await teardown_started.wait()

        await lifespans["c"].__aenter__()
        entered.add("c")
        assert build_count == 2
        assert len(opened) == 2

        teardown_gate.set()
        await teardown_task
        exited.add("b")

        second_result = await server.call_tool("search", {"request": {"query": "session c"}})
        assert second_result[1]["provider"] == "x"
        assert second_result[1]["usage"]["operation"] == "search"
        assert second_result[1]["usage"]["units"] == "1.25"

        await lifespans["c"].__aexit__(None, None, None)
        exited.add("c")
        assert build_count == 2
        assert len(opened) == 2
        assert len(closed) == 2
        assert closed == opened
    finally:
        teardown_gate.set()
        if teardown_task is not None and not teardown_task.done():
            await teardown_task
            exited.add("b")
        for name in ("a", "b", "c"):
            if name in entered and name not in exited:
                await lifespans[name].__aexit__(None, None, None)

    inspection_repository = await real_open(tmp_path / "race.db")
    try:
        usage = await inspection_repository.list_usage()
    finally:
        await real_close(inspection_repository)

    assert [(event.provider, event.operation, event.units) for event in usage] == [
        ("x", UsageOperation.SEARCH, Decimal("1.25")),
        ("x", UsageOperation.SEARCH, Decimal("1.25")),
    ]


async def test_injected_repository_remains_open_after_app_lifespan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "injected-app.db")
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    try:
        app = create_app([], repository=repository)
        with TestClient(app):
            pass

        assert closed == []
        event = UsageEvent(
            provider="injected-app",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        await repository.record_usage(event)
        assert await repository.list_usage() == [event]
        assert closed == []
    finally:
        await real_close(repository)


async def test_injected_repository_remains_open_after_server_lifespan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "injected-server.db")
    closed: list[SQLiteRepository] = []
    real_close = SQLiteRepository.close

    async def close_spy(repository: SQLiteRepository) -> None:
        closed.append(repository)
        await real_close(repository)

    monkeypatch.setattr(SQLiteRepository, "close", close_spy)
    try:
        server = create_server([], repository=repository)
        async with server._mcp_server.lifespan(server):
            pass

        assert closed == []
        event = UsageEvent(
            provider="injected-server",
            operation=UsageOperation.FETCH,
            units=Decimal("2"),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        await repository.record_usage(event)
        assert await repository.list_usage() == [event]
        assert closed == []
    finally:
        await real_close(repository)


def test_resolve_database_path_prefers_environment_then_argument_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = Path.cwd() / "from-env.db"
    argument_path = Path.cwd() / "from-argument.db"
    monkeypatch.setenv("FREESEARCH_DB", str(env_path))
    assert monitoring.resolve_database_path(argument_path) == env_path

    monkeypatch.delenv("FREESEARCH_DB")
    assert monitoring.resolve_database_path(argument_path) == argument_path
    assert monitoring.resolve_database_path() == Path(monitoring.DEFAULT_DB_FILENAME)


async def test_telemetry_helpers_swallow_repository_exceptions(
    repository: SQLiteRepository,
) -> None:
    adapter = _StubAdapter("helper-provider")
    response = await adapter.search(SearchRequest(query="helper"))
    assert response.usage is not None

    class _BrokenRepository:
        async def record_usage(self, event: UsageEvent) -> None:
            raise RuntimeError("write failed")

        async def record_health(self, health: ProviderHealth) -> None:
            raise RuntimeError("write failed")

    broken = _BrokenRepository()
    await monitoring.record_response_telemetry(broken, response)
    await monitoring.record_failure_telemetry(broken, provider="helper-provider")
    assert await repository.list_usage() == []


def test_monitoring_module_contains_no_html_renderer_or_template_runtime() -> None:
    source = inspect.getsource(monitoring).lower()
    for forbidden in (
        "jinja2",
        "htmlresponse",
        "render_dashboard",
        "html.escape",
        "<script",
        "<form",
    ):
        assert forbidden not in source
