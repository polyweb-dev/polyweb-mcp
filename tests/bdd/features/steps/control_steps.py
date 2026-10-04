"""Offline Behave steps for the provider control-plane contracts."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app


class _MemorySecretStore:
    """Scenario-local keyring double; no OS keyring or network is touched."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class _ScenarioDirectory:
    """Plain-mode scenario directory accepted by the constrained Windows runner."""

    def __init__(self) -> None:
        self._path = Path.cwd() / f"freesearch-control-cwd-{uuid4().hex}"
        self._path.mkdir()
        self.name = str(self._path)

    def cleanup(self) -> None:
        shutil.rmtree(self._path, ignore_errors=True)


class _ControlAdapter(ProviderAdapter):
    """Small deterministic adapter used by every control scenario."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self._name = name
        self.fail = fail
        self._checked_at = datetime(2026, 1, 1, tzinfo=UTC)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self.fail:
            raise RuntimeError("offline control adapter failure")
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title=f"{self.name} result",
                    url="https://example.com/control",
                    snippet="offline control result",
                )
            ],
            total_results=1,
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
                metadata={"tokens": 1},
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        if self.fail:
            raise RuntimeError("offline control adapter failure")
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="offline control document",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=self._checked_at,
        )


def _open_repository(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-control-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = Path(temporary_file.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )


def _build_app(context: Any, *, include_secret_store: bool = False) -> None:
    kwargs: dict[str, Any] = {}
    if include_secret_store:
        kwargs["secret_store"] = context.secret_store
    control_directory = getattr(context, "control_directory", None)
    previous_cwd = Path.cwd()
    if control_directory is not None:
        os.chdir(control_directory)
    try:
        context.app = create_app(context.adapters, repository=context.repository, **kwargs)
    finally:
        if control_directory is not None:
            os.chdir(previous_cwd)


@contextmanager
def _client(context: Any, *, raise_server_exceptions: bool = True) -> Iterator[TestClient]:
    control_directory = getattr(context, "control_directory", None)
    previous_cwd = Path.cwd()
    if control_directory is not None:
        os.chdir(control_directory)
    try:
        with TestClient(context.app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client
    finally:
        if control_directory is not None:
            os.chdir(previous_cwd)


@given("an offline control API with stub adapters")
def step_given_control_api(context: Any) -> None:
    _open_repository(context)
    context.adapters = [_ControlAdapter("exa"), _ControlAdapter("brave")]
    _build_app(context)


@given("an offline control API with an in-memory secret store")
def step_given_control_api_secret_store(context: Any) -> None:
    _open_repository(context)
    context.temp_directory = _ScenarioDirectory()
    context.control_directory = Path(context.temp_directory.name)
    context.adapters = [_ControlAdapter("exa"), _ControlAdapter("brave")]
    context.secret_store = _MemorySecretStore()
    _build_app(context)


@given("an offline control API with a failing adapter")
def step_given_failing_control_api(context: Any) -> None:
    _open_repository(context)
    context.adapters = [_ControlAdapter("exa", fail=True), _ControlAdapter("brave")]
    _build_app(context)


@when("I list the control-plane providers")
def step_when_list_control_providers(context: Any) -> None:
    with _client(context) as client:
        context.providers_response = client.get("/api/v1/providers")


@then("the control-plane provider list should contain the eight canonical providers")
def step_then_canonical_providers(context: Any) -> None:
    assert context.providers_response.status_code == 200
    body = context.providers_response.json()
    assert {item["provider_id"] for item in body} == {
        "exa",
        "firecrawl",
        "tavily",
        "parallel",
        "you",
        "brave",
        "keenable",
        "tinyfish",
    }
    assert len(body) == 8


@then("every provider should have a closed circuit breaker and no latency p95")
def step_then_control_defaults(context: Any) -> None:
    for item in context.providers_response.json():
        assert item["circuit_breaker"]["state"] == "closed"
        assert item["latency_p95_ms"] is None


@when('I disable the "{provider}" provider through the control API')
def step_when_disable_provider(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.patch_response = client.patch(
            f"/api/v1/providers/{provider}", json={"enabled": False}
        )
        context.provider_response = client.get(f"/api/v1/providers/{provider}")


def _reopen_control_repository(context: Any) -> None:
    context.loop.run_until_complete(context.repository.close())
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )
    _build_app(context)


@then('the control-plane GET for "{provider}" should report enabled false')
def step_then_provider_disabled(context: Any, provider: str) -> None:
    assert context.patch_response.status_code == 200
    assert context.provider_response.status_code == 200
    assert context.provider_response.json()["provider_id"] == provider
    assert context.provider_response.json()["enabled"] is False


@then("a fresh control-plane read should still report enabled false")
def step_then_provider_disabled_after_reopen(context: Any) -> None:
    _reopen_control_repository(context)
    with _client(context) as client:
        response = client.get("/api/v1/providers/exa")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


@when('I write a secret for "{provider}" through the control API')
def step_when_write_secret(context: Any, provider: str) -> None:
    # The store is injected only for this scenario; the default app path never
    # reaches a platform keyring during offline BDD execution.
    _build_app(context, include_secret_store=True)
    context.raw_key = "offline-control-secret"
    with _client(context) as client:
        context.secret_write_response = client.put(
            f"/api/v1/providers/{provider}/secret", json={"key": context.raw_key}
        )


@then("the secret response should be configured with a masked fingerprint")
def step_then_secret_configured(context: Any) -> None:
    assert context.secret_write_response.status_code == 200
    body = context.secret_write_response.json()
    assert body["presence"] == "configured"
    assert re.fullmatch(r"[A-Z]{3}_•{8}[0-9a-f]{4}", body["fingerprint"])
    assert context.raw_key not in context.secret_write_response.text


@when('I delete the "{provider}" secret through the control API')
def step_when_delete_secret(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_delete_response = client.delete(f"/api/v1/providers/{provider}/secret")


@then("the secret response should report missing and contain no raw key")
def step_then_secret_missing(context: Any) -> None:
    assert context.secret_delete_response.status_code == 200
    assert context.secret_delete_response.json()["presence"] == "missing"
    assert context.raw_key not in context.secret_delete_response.text


@when("I update routing to first_only and free_first with 2 attempts")
def step_when_update_routing(context: Any) -> None:
    with _client(context) as client:
        context.routing_response = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "first_only",
                "cost_optimization_preset": "free_first",
                "max_attempts": 2,
            },
        )


@then("the routing GET should equal first_only free_first and 2 attempts")
def step_then_routing_round_trip(context: Any) -> None:
    assert context.routing_response.status_code == 200
    with _client(context) as client:
        response = client.get("/api/v1/routing/config")
    assert response.status_code == 200
    assert response.json() == {
        "fallback_policy": "first_only",
        "cost_optimization_preset": "free_first",
        "max_attempts": 2,
    }


@when("I submit an offline control search")
def step_when_control_search(context: Any) -> None:
    with _client(context) as client:
        context.search_response = client.post("/search", json={"query": "control activity"})
        context.dashboard_response = client.get("/dashboard")


@then("the dashboard recent activity should contain a non-negative latency and success status")
def step_then_dashboard_latency_status(context: Any) -> None:
    assert context.search_response.status_code == 200
    assert context.dashboard_response.status_code == 200
    recent = context.dashboard_response.json()["recent_usage"]
    assert len(recent) == 1
    assert isinstance(recent[0]["latency_ms"], int)
    assert recent[0]["latency_ms"] >= 0
    assert recent[0]["status"] == "success"


@when("I submit a failing offline control search")
def step_when_failing_control_search(context: Any) -> None:
    with _client(context, raise_server_exceptions=False) as client:
        context.failure_response = client.post("/search", json={"query": "control failure"})
        context.stats_response = client.get("/stats")
        context.dashboard_response = client.get("/dashboard")


@then("the control request should return HTTP 500")
def step_then_failure_status(context: Any) -> None:
    assert context.failure_response.status_code == 500


@then("stats and dashboard should show a failure usage row and degraded health")
def step_then_failure_telemetry(context: Any) -> None:
    assert context.stats_response.status_code == 200
    assert context.dashboard_response.status_code == 200
    stats = context.stats_response.json()
    dashboard = context.dashboard_response.json()
    assert any(
        entry["status"] == "failure" and entry["provider"] == "exa"
        for entry in stats["recent_usage"]
    )
    assert any(
        entry["status"] == "degraded" and entry["provider"] == "exa"
        for entry in dashboard["latest_health"]
    )
