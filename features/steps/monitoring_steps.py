"""Offline Behave steps for the Stage 4.5 monitoring contracts."""

import json
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.api import create_app
from freesearch.contracts import (
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
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.server import create_server
from freesearch.storage import SQLiteRepository


class _MonitoringStubAdapter(ProviderAdapter):
    """Deterministic, offline adapter used by every monitoring scenario."""

    def __init__(
        self,
        name: str,
        *,
        search_enabled: bool = True,
        fetch_enabled: bool = True,
        search_units: Decimal = Decimal("1.25"),
        fetch_units: Decimal = Decimal("2.50"),
        fail: bool = False,
    ) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(
            search=search_enabled,
            fetch=fetch_enabled,
            cost_estimate=True,
        )
        self._search_units = search_units
        self._fetch_units = fetch_units
        self._fail = fail
        self._search_at = datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)
        self._fetch_at = self._search_at + timedelta(seconds=1)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _usage(
        self, operation: UsageOperation, units: Decimal, observed_at: datetime
    ) -> UsageEvent:
        return UsageEvent(
            provider=self._name,
            operation=operation,
            units=units,
            observed_at=observed_at,
            metadata={"credits": 3, "tokens": 12, "latency_ms": 8.5},
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail:
            raise RuntimeError("stub adapter exploded")
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/result",
                    snippet="offline result",
                )
            ],
            total_results=1,
            usage=self._usage(UsageOperation.SEARCH, self._search_units, self._search_at),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        if self._fail:
            raise RuntimeError("stub adapter exploded")
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} document",
                fetched_at=self._fetch_at,
            ),
            usage=self._usage(UsageOperation.FETCH, self._fetch_units, self._fetch_at),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self._name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def quota(self) -> QuotaSnapshot | None:
        return None


def _open_repository(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-monitoring-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = Path(temporary_file.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )


def _seed_quota(context: Any, provider: str, source: QuotaSource) -> None:
    snapshot = QuotaSnapshot(
        provider=provider,
        source=source,
        remaining=Decimal("97"),
        limit=Decimal("100"),
        observed_at=datetime(2026, 1, 1, 11, 59, tzinfo=UTC),
    )
    context.loop.run_until_complete(context.repository.record_quota(snapshot))


def _rest_client(context: Any) -> TestClient:
    return TestClient(context.app)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


@given("an offline monitoring repository and REST adapters")
def step_given_rest_monitoring(context: Any) -> None:
    _open_repository(context)
    context.adapters = [
        _MonitoringStubAdapter(
            "rest-search",
            search_enabled=True,
            fetch_enabled=False,
            search_units=Decimal("1.25"),
        ),
        _MonitoringStubAdapter(
            "rest-fetch",
            search_enabled=False,
            fetch_enabled=True,
            fetch_units=Decimal("2.50"),
        ),
    ]
    _seed_quota(context, "rest-search", QuotaSource.AUTHORITATIVE)
    _seed_quota(context, "rest-fetch", QuotaSource.OBSERVED)
    context.app = create_app(context.adapters, repository=context.repository)


@when('I submit REST search query "{query}" and fetch URL "{url}"')
def step_when_rest_search_and_fetch(context: Any, query: str, url: str) -> None:
    with _rest_client(context) as client:
        context.search_response = client.post("/search", json={"query": query, "limit": 1})
        context.fetch_response = client.post("/fetch", json={"url": url})
        context.stats_response = client.get("/stats")
        context.dashboard_response = client.get("/dashboard")


@then("REST telemetry should contain search and fetch totals for their providers")
def step_then_rest_totals(context: Any) -> None:
    assert context.search_response.status_code == 200
    assert context.fetch_response.status_code == 200
    assert context.search_response.json()["provider"] == "rest-search"
    assert context.fetch_response.json()["provider"] == "rest-fetch"
    assert context.stats_response.status_code == 200

    body = context.stats_response.json()
    totals = {(entry["provider"], entry["operation"]): entry for entry in body["usage_totals"]}
    assert set(totals) == {("rest-search", "search"), ("rest-fetch", "fetch")}
    assert _decimal(totals[("rest-search", "search")]["total_units"]) == Decimal("1.25")
    assert totals[("rest-search", "search")]["event_count"] == 1
    assert _decimal(totals[("rest-fetch", "fetch")]["total_units"]) == Decimal("2.50")
    assert totals[("rest-fetch", "fetch")]["event_count"] == 1


@then("REST recent usage should be newest first")
def step_then_rest_recent_usage(context: Any) -> None:
    recent = context.stats_response.json()["recent_usage"]
    assert len(recent) == 2
    assert [event["operation"] for event in recent] == ["fetch", "search"]
    assert [event["provider"] for event in recent] == ["rest-fetch", "rest-search"]
    assert recent[0]["observed_at"] > recent[1]["observed_at"]


@then("REST quota entries should expose their source")
def step_then_rest_quota_sources(context: Any) -> None:
    quota = context.stats_response.json()["latest_quota"]
    assert {(entry["provider"], entry["source"]) for entry in quota} == {
        ("rest-search", "authoritative"),
        ("rest-fetch", "observed"),
    }
    assert all("source" in entry for entry in quota)


@then("REST stats and dashboard should show the local-observed notice")
def step_then_rest_notice(context: Any) -> None:
    assert "local-observed only" in context.stats_response.json()["notice"]
    assert "10\N{EN DASH}15 min" in context.stats_response.json()["notice"]
    assert context.dashboard_response.status_code == 200
    assert "local-observed only" in context.dashboard_response.text
    assert "10\N{EN DASH}15 min" in context.dashboard_response.text
    assert "authoritative" in context.dashboard_response.text
    assert "observed" in context.dashboard_response.text


@given("an offline monitoring repository and MCP adapters")
def step_given_mcp_monitoring(context: Any) -> None:
    _open_repository(context)
    context.adapters = [
        _MonitoringStubAdapter(
            "mcp-search",
            search_enabled=True,
            fetch_enabled=False,
            search_units=Decimal("1.25"),
        ),
        _MonitoringStubAdapter(
            "mcp-fetch",
            search_enabled=False,
            fetch_enabled=True,
            fetch_units=Decimal("2.50"),
        ),
    ]
    context.server = create_server(context.adapters, repository=context.repository)


@when("I call the MCP search and fetch tools")
def step_when_mcp_search_and_fetch(context: Any) -> None:
    context.mcp_search_result = context.loop.run_until_complete(
        context.server.call_tool("search", {"request": {"query": "mcp stage four"}})
    )
    context.mcp_fetch_result = context.loop.run_until_complete(
        context.server.call_tool("fetch", {"request": {"url": "https://example.com/mcp"}})
    )


@then("MCP telemetry should contain the same usage and health records")
def step_then_mcp_telemetry(context: Any) -> None:
    assert isinstance(context.mcp_search_result[0], Sequence)
    assert not isinstance(context.mcp_search_result[0], bool)
    assert isinstance(context.mcp_fetch_result[0], Sequence)
    assert not isinstance(context.mcp_fetch_result[0], bool)
    assert context.mcp_search_result[1]["provider"] == "mcp-search"
    assert context.mcp_fetch_result[1]["provider"] == "mcp-fetch"

    usage = context.loop.run_until_complete(context.repository.list_usage())
    assert [(event.provider, event.operation.value, event.units) for event in usage] == [
        ("mcp-search", "search", Decimal("1.25")),
        ("mcp-fetch", "fetch", Decimal("2.50")),
    ]
    for provider in ("mcp-search", "mcp-fetch"):
        health = context.loop.run_until_complete(context.repository.latest_health(provider))
        assert health is not None
        assert health.provider == provider
        assert health.status is HealthStatus.HEALTHY
        assert health.message is None


@given("an offline monitoring repository and a privacy-safe REST adapter")
def step_given_privacy_safe_monitoring(context: Any) -> None:
    _open_repository(context)
    context.adapters = [_MonitoringStubAdapter("privacy-provider")]
    context.app = create_app(context.adapters, repository=context.repository)


@when("I submit a private REST search and fetch request")
def step_when_private_rest_requests(context: Any) -> None:
    context.private_query = "PRIVATE_QUERY_should_not_be_rendered"
    context.private_url = "https://secret.example/private-document"
    with _rest_client(context) as client:
        context.private_search_response = client.post(
            "/search", json={"query": context.private_query}
        )
        context.private_fetch_response = client.post("/fetch", json={"url": context.private_url})
        context.private_stats_response = client.get("/stats")
        context.private_dashboard_response = client.get("/dashboard")


@then("telemetry metadata should contain numeric values only")
def step_then_numeric_metadata(context: Any) -> None:
    assert context.private_search_response.status_code == 200
    assert context.private_fetch_response.status_code == 200
    events = context.loop.run_until_complete(context.repository.list_usage())
    assert len(events) == 2
    for event in events:
        assert event.metadata == {"credits": 3, "tokens": 12, "latency_ms": 8.5}
        assert all(isinstance(value, (int, float)) for value in event.metadata.values())


@then("stats and dashboard should not contain request content or secrets")
def step_then_private_values_absent(context: Any) -> None:
    stats_body = context.private_stats_response.json()
    for entry in stats_body["recent_usage"]:
        assert "metadata" not in entry, "recent_usage entry exposes metadata"
        assert "request_id" not in entry, "recent_usage entry exposes request_id"
    for entry in stats_body["latest_health"]:
        assert "message" not in entry, "latest_health entry exposes message"

    stats_text = json.dumps(stats_body, sort_keys=True)
    dashboard_text = context.private_dashboard_response.text
    for forbidden in (
        context.private_query,
        context.private_url,
        "private-provider document",
        "Authorization: Bearer",
        "api_key",
    ):
        assert forbidden not in stats_text
        assert forbidden not in dashboard_text


class _FailingTelemetryRepository:
    """Repository double whose telemetry writes fail after the user response exists."""

    async def record_usage(self, event: UsageEvent) -> None:
        raise OSError("telemetry database unavailable")

    async def record_health(self, health: ProviderHealth) -> None:
        raise OSError("telemetry database unavailable")


@given("a REST app with a failing telemetry repository")
def step_given_failing_telemetry_app(context: Any) -> None:
    context.adapters = [_MonitoringStubAdapter("resilient-provider")]
    context.app = create_app(context.adapters, repository=_FailingTelemetryRepository())


@when("I submit a resilient REST search request")
def step_when_resilient_rest_search(context: Any) -> None:
    with _rest_client(context) as client:
        context.resilient_response = client.post("/search", json={"query": "resilient"})


@then("the REST request should succeed despite telemetry failure")
def step_then_resilient_request(context: Any) -> None:
    assert context.resilient_response.status_code == 200
    assert context.resilient_response.json()["provider"] == "resilient-provider"
