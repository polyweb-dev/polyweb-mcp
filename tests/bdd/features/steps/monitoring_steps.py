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
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.server import create_server
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
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.api_keys import mcp_key_credentials
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    configure_bdd_secret,
    promote_to_system_admin,
    temp_email,
)
from tests.fixtures.execution import bdd_project_id
from tests.fixtures.usage_ledger import all_usage_events


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


def _parse_utc_timestamp(value: Any) -> datetime:
    assert isinstance(value, str)
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)
    return timestamp


def _login_headers(context: Any, prefix: str, *, system_admin: bool = False) -> dict[str, str]:
    # Register one ordinary account; grant system_admin (trusted) only when the
    # scenario reads system-scoped stats/dashboard (A1). Execution uses the
    # account's own project membership.
    email = temp_email(prefix)
    with _rest_client(context) as client:
        registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
        assert registered.status_code == 201
        if system_admin:
            context.loop.run_until_complete(promote_to_system_admin(context.repository, email))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        token = logged_in.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@given("an offline monitoring repository and REST adapters")
def step_given_rest_monitoring(context: Any) -> None:
    configure_bdd_secret(context)
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
    # Stats and dashboard need the Reader role, search and fetch need any role.
    context.auth_headers = _login_headers(context, "monitor-reader", system_admin=True)


@when('I submit REST search query "{query}" and fetch URL "{url}"')
def step_when_rest_search_and_fetch(context: Any, query: str, url: str) -> None:
    with _rest_client(context) as client:
        context.search_response = client.post(
            "/search",
            json={
                "project_id": bdd_project_id(context, context.auth_headers),
                "query": query,
                "limit": 1,
            },
            headers=context.auth_headers,
        )
        context.fetch_response = client.post(
            "/fetch",
            json={"project_id": bdd_project_id(context, context.auth_headers), "url": url},
            headers=context.auth_headers,
        )
        context.stats_response = client.get("/stats", headers=context.auth_headers)
        context.dashboard_response = client.get("/dashboard", headers=context.auth_headers)


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


@then("REST stats and dashboard JSON should show the local-observed notice")
def step_then_rest_notice(context: Any) -> None:
    stats_body = context.stats_response.json()
    dashboard_response = context.dashboard_response
    assert "local-observed only" in stats_body["notice"]
    assert "10\N{EN DASH}15 min" in stats_body["notice"]
    assert dashboard_response.status_code == 200
    assert "application/json" in dashboard_response.headers["content-type"]
    assert "text/html" not in dashboard_response.headers["content-type"]
    dashboard_body = dashboard_response.json()
    assert "local-observed only" in dashboard_body["notice"]
    assert "10\N{EN DASH}15 min" in dashboard_body["notice"]
    assert {entry["source"] for entry in dashboard_body["latest_quota"]} == {
        "authoritative",
        "observed",
    }
    assert "generated_at" in dashboard_body
    _parse_utc_timestamp(dashboard_body["generated_at"])


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

    async def _authed_service() -> tuple[Any, str, str]:
        service, token, pid = await mcp_key_credentials(context.repository, "monitor-mcp")
        return service, token.get_secret_value(), pid

    service, raw_token, context.mcp_pid = context.loop.run_until_complete(_authed_service())
    context.server = create_server(
        context.adapters,
        repository=context.repository,
        auth_service=service,
        stdio_token=SecretStr(raw_token),
    )


@when("I call the MCP search and fetch tools")
def step_when_mcp_search_and_fetch(context: Any) -> None:
    context.mcp_search_result = context.loop.run_until_complete(
        context.server.call_tool(
            "search", {"request": {"project_id": context.mcp_pid, "query": "mcp stage four"}}
        )
    )
    context.mcp_fetch_result = context.loop.run_until_complete(
        context.server.call_tool(
            "fetch", {"request": {"project_id": context.mcp_pid, "url": "https://example.com/mcp"}}
        )
    )


@then("MCP telemetry should contain the same usage and health records")
def step_then_mcp_telemetry(context: Any) -> None:
    assert isinstance(context.mcp_search_result[0], Sequence)
    assert not isinstance(context.mcp_search_result[0], bool)
    assert isinstance(context.mcp_fetch_result[0], Sequence)
    assert not isinstance(context.mcp_fetch_result[0], bool)
    assert context.mcp_search_result[1]["provider"] == "mcp-search"
    assert context.mcp_fetch_result[1]["provider"] == "mcp-fetch"

    usage = context.loop.run_until_complete(all_usage_events(context.repository))
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
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [_MonitoringStubAdapter("privacy-provider")]
    context.app = create_app(context.adapters, repository=context.repository)
    # Stats and dashboard need the Reader role, search and fetch need any role.
    context.auth_headers = _login_headers(context, "monitor-reader", system_admin=True)


@when("I submit a private REST search and fetch request")
def step_when_private_rest_requests(context: Any) -> None:
    context.private_query = "PRIVATE_QUERY_should_not_be_rendered"
    context.private_url = "https://secret.example/private-document"
    with _rest_client(context) as client:
        context.private_search_response = client.post(
            "/search",
            json={
                "project_id": bdd_project_id(context, context.auth_headers),
                "query": context.private_query,
            },
            headers=context.auth_headers,
        )
        context.private_fetch_response = client.post(
            "/fetch",
            json={
                "project_id": bdd_project_id(context, context.auth_headers),
                "url": context.private_url,
            },
            headers=context.auth_headers,
        )
        context.private_stats_response = client.get("/stats", headers=context.auth_headers)
        context.private_dashboard_response = client.get("/dashboard", headers=context.auth_headers)


@then("telemetry metadata should contain numeric values only")
def step_then_numeric_metadata(context: Any) -> None:
    assert context.private_search_response.status_code == 200
    assert context.private_fetch_response.status_code == 200
    events = context.loop.run_until_complete(all_usage_events(context.repository))
    assert len(events) == 2
    for event in events:
        assert event.metadata == {"credits": 3, "tokens": 12, "latency_ms": 8.5}
        assert all(isinstance(value, (int, float)) for value in event.metadata.values())


@then("stats and dashboard JSON should not contain request content or secrets")
def step_then_private_values_absent(context: Any) -> None:
    stats_body = context.private_stats_response.json()
    dashboard_response = context.private_dashboard_response
    assert dashboard_response.status_code == 200
    assert "application/json" in dashboard_response.headers["content-type"]
    assert "text/html" not in dashboard_response.headers["content-type"]
    dashboard_body = dashboard_response.json()
    for body in (stats_body, dashboard_body):
        for entry in body["recent_usage"]:
            assert "metadata" not in entry, "recent_usage entry exposes metadata"
            assert "request_id" not in entry, "recent_usage entry exposes request_id"
        for entry in body["latest_health"]:
            assert "message" not in entry, "latest_health entry exposes message"

    stats_text = json.dumps(stats_body, sort_keys=True)
    dashboard_text = json.dumps(dashboard_body, sort_keys=True)
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
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [_MonitoringStubAdapter("resilient-provider")]
    context.app = create_app(context.adapters, repository=context.repository)

    # Keep account access on the real database, fail only telemetry writes.
    async def _fail_usage(event: Any) -> None:
        raise OSError("telemetry database unavailable")

    async def _fail_health(health: Any) -> None:
        raise OSError("telemetry database unavailable")

    context.repository.record_usage = _fail_usage  # type: ignore[method-assign]
    context.repository.record_health = _fail_health  # type: ignore[method-assign]
    # Search needs any authenticated role.
    context.auth_headers = _login_headers(context, "monitor-agent")


@when("I submit a resilient REST search request")
def step_when_resilient_rest_search(context: Any) -> None:
    with _rest_client(context) as client:
        context.resilient_response = client.post(
            "/search",
            json={
                "project_id": bdd_project_id(context, context.auth_headers),
                "query": "resilient",
            },
            headers=context.auth_headers,
        )


@then("the REST request should succeed despite telemetry failure")
def step_then_resilient_request(context: Any) -> None:
    assert context.resilient_response.status_code == 200
    assert context.resilient_response.json()["provider"] == "resilient-provider"
