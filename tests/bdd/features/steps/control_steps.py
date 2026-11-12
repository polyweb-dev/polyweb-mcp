"""Offline Behave steps for the provider control-plane contracts."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from polyweb.adapters.base import ProviderAdapter
from polyweb.models.contracts import (
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
from polyweb.models.provider_access import is_operation_enabled
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.credentials import credential_secret_slot
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    auth_service_for,
    configure_bdd_secret,
    promote_to_system_admin,
    temp_email,
)
from tests.fixtures.execution import (
    _install_bdd_adapters,
    account_id_from_headers,
    seed_member_project,
)


class _ScenarioDirectory:
    """Plain-mode scenario directory accepted by the constrained Windows runner."""

    def __init__(self) -> None:
        self._path = Path.cwd() / f"polyweb-control-cwd-{uuid4().hex}"
        self._path.mkdir()
        self.name = str(self._path)

    def cleanup(self) -> None:
        shutil.rmtree(self._path, ignore_errors=True)


class _ControlAdapter(ProviderAdapter):
    """Small deterministic adapter used by every control scenario."""

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        search_capable: bool = True,
        fetch_capable: bool = True,
    ) -> None:
        self._name = name
        self.fail = fail
        self._search_capable = search_capable
        self._fetch_capable = fetch_capable
        self.search_calls = 0
        self.fetch_calls = 0
        self._checked_at = datetime(2026, 1, 1, tzinfo=UTC)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            search=self._search_capable, fetch=self._fetch_capable, cost_estimate=True
        )

    def reset_counts(self) -> None:
        """Reset deterministic call counters to zero."""

        self.search_calls = 0
        self.fetch_calls = 0

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
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
        self.fetch_calls += 1
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
        prefix="polyweb-control-",
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


def _login_headers(context: Any, prefix: str, *, system_admin: bool = False) -> dict[str, str]:
    # Register one ordinary account; grant system_admin (trusted) only when the
    # scenario exercises a system-scoped control surface (A1).
    email = temp_email(prefix)
    with _client(context) as client:
        registered = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": TEMP_PASSWORD,
                "username": email.split("@")[0][:64],
                "first_name": "Test",
                "last_name": "User",
            },
        )
        assert registered.status_code == 201
        if system_admin:
            context.loop.run_until_complete(promote_to_system_admin(context.repository, email))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        token = logged_in.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _reset_counts(context: Any) -> None:
    for adapter in getattr(context, "adapters", []):
        reset = getattr(adapter, "reset_counts", None)
        if callable(reset):
            reset()


def _adapter_by_name(context: Any, name: str) -> _ControlAdapter:
    for adapter in context.adapters:
        if adapter.name == name:
            return adapter
    raise AssertionError(f"unknown stub adapter {name!r}")


def _patch_for_choice(choice: str) -> dict[str, Any]:
    if choice == "both-on":
        return {"enable_mask": 7}
    if choice == "search-off":
        return {"search_enabled": False}
    if choice == "fetch-off":
        return {"fetch_enabled": False}
    if choice == "global-off":
        return {"enabled": False}
    if choice == "global-on":
        return {"enabled": True}
    raise AssertionError(f"unknown access choice {choice!r}")


def _reopen_control_repository(context: Any) -> None:
    context.loop.run_until_complete(context.repository.close())
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )
    _build_app(context)
    if getattr(context, "server", None) is not None:
        context.server = _build_mcp_server(context)


def _control_headers(context: Any) -> dict[str, str]:
    """Return the Developer headers, creating the account on first use."""

    existing = getattr(context, "developer_headers", None)
    if existing is not None:
        return existing
    headers = _login_headers(context, "control-reader", system_admin=True)
    context.developer_headers = headers
    return headers


def _build_mcp_server(context: Any) -> Any:
    """Use the same project and vault pools as the REST requests."""

    from polyweb.mcp.server import create_server
    from tests.fixtures.api_keys import key_for_account

    key = context.loop.run_until_complete(
        key_for_account(
            context.repository,
            account_id_from_headers(context.developer_headers),
            UUID(context.project_id),
        )
    )
    server = create_server(
        context.adapters,
        repository=context.repository,
        auth_service=auth_service_for(context.repository),
        stdio_token=key.key,
    )
    session = server._mcp_server.lifespan(server)
    context.loop.run_until_complete(session.__aenter__())
    sessions = getattr(context, "_bdd_mcp_sessions", None)
    if sessions is None:
        sessions = []
        context._bdd_mcp_sessions = sessions
    sessions.append((session, server))
    context.mcp_pid = context.project_id
    return server


def _setup_control_project(context: Any) -> None:
    attribution = context.loop.run_until_complete(
        seed_member_project(context.repository, context.developer_headers)
    )
    context.project_id = str(attribution.project_id)
    context.execution_headers = _login_headers(context, "control-developer")
    secrets = {adapter.name: f"offline-control-{adapter.name}" for adapter in context.adapters}
    with _client(context) as client:
        member = client.post(
            f"/api/v1/projects/{context.project_id}/members",
            headers=context.developer_headers,
            json={
                "user_id": str(account_id_from_headers(context.execution_headers)),
                "permissions": 3,
            },
        )
        assert member.status_code == 201, member.text
        assert member.json()["role"] == "developer" and member.json()["permissions"] == 3
        for provider in ("keenable", "tavily"):
            response = client.patch(
                f"/api/v1/providers/{provider}",
                json={"enabled": False},
                headers=context.admin_headers,
            )
            assert response.status_code == 200, response.text
        for adapter in context.adapters:
            key = client.post(
                "/api/v1/account/vault/keys",
                headers=context.developer_headers,
                json={
                    "provider_type": adapter.name,
                    "label": f"Control {adapter.name}",
                    "secret": secrets[adapter.name],
                },
            )
            assert key.status_code == 201, key.text
            operations = ["search"]
            if adapter.capabilities.fetch:
                operations.append("fetch")
            pool = client.post(
                f"/api/v1/account/vault/keys/{key.json()['id']}/pools",
                headers=context.developer_headers,
                json={
                    "label": "Control pool",
                    "project_id": context.project_id,
                    "operations": operations,
                },
            )
            assert pool.status_code == 201, pool.text
        for operation in ("search", "fetch"):
            order = [
                adapter.name
                for adapter in context.adapters
                if getattr(adapter.capabilities, operation)
            ]
            response = client.put(
                f"/api/v1/projects/{context.project_id}/routing/order/{operation}",
                headers=context.developer_headers,
                json={"strategy": "custom", "order": order},
            )
            assert response.status_code == 200, response.text
    _install_bdd_adapters(context, context.adapters, secrets)


@given("an offline control API with stub adapters")
def step_given_control_api(context: Any) -> None:
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [_ControlAdapter("exa"), _ControlAdapter("brave", fetch_capable=False)]
    _build_app(context)
    # Admin owns mutations, Developer owns reads. One account per role is enough.
    context.admin_headers = _login_headers(context, "control-admin", system_admin=True)
    context.developer_headers = _login_headers(context, "control-reader", system_admin=True)
    _setup_control_project(context)


@given("an offline control API with stub adapters and call counters")
def step_given_control_api_counters(context: Any) -> None:
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [
        _ControlAdapter("exa", search_capable=True, fetch_capable=True),
        _ControlAdapter("brave", search_capable=True, fetch_capable=False),
    ]
    _reset_counts(context)
    context.server = None
    _build_app(context)
    # Reads and searches need an account; mutations need Admin.
    context.admin_headers = _login_headers(context, "control-admin", system_admin=True)
    context.developer_headers = _login_headers(context, "control-reader", system_admin=True)
    _setup_control_project(context)


@given("an offline control API with stub adapters and call counters and an MCP server")
def step_given_control_api_counters_mcp(context: Any) -> None:
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [
        _ControlAdapter("exa", search_capable=True, fetch_capable=True),
        _ControlAdapter("brave", search_capable=True, fetch_capable=False),
    ]
    _reset_counts(context)
    _build_app(context)
    context.admin_headers = _login_headers(context, "control-admin", system_admin=True)
    context.developer_headers = _login_headers(context, "control-reader", system_admin=True)
    _setup_control_project(context)
    context.server = _build_mcp_server(context)


@given("an offline control API with an encrypted vault")
def step_given_control_api_secret_store(context: Any) -> None:
    configure_bdd_secret(context)
    _open_repository(context)
    context.temp_directory = _ScenarioDirectory()
    context.control_directory = Path(context.temp_directory.name)
    context.adapters = [_ControlAdapter("exa"), _ControlAdapter("brave")]
    _build_app(context)
    # Secret writes need the Admin role.
    context.admin_headers = _login_headers(context, "control-admin", system_admin=True)


@given("an offline control API with a failing adapter")
def step_given_failing_control_api(context: Any) -> None:
    configure_bdd_secret(context)
    _open_repository(context)
    context.adapters = [
        _ControlAdapter("exa", fail=True),
        _ControlAdapter("brave", fetch_capable=False),
    ]
    _build_app(context)
    # Search needs any role, stats and dashboard need the Reader role.
    context.developer_headers = _login_headers(context, "control-reader", system_admin=True)
    context.admin_headers = context.developer_headers
    _setup_control_project(context)


@when("I list the control-plane providers")
def step_when_list_control_providers(context: Any) -> None:
    with _client(context) as client:
        context.providers_response = client.get(
            "/api/v1/providers", headers=context.developer_headers
        )


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
            f"/api/v1/providers/{provider}",
            json={"enabled": False},
            headers=context.admin_headers,
        )
        context.provider_response = client.get(
            f"/api/v1/providers/{provider}", headers=context.developer_headers
        )


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
        response = client.get("/api/v1/providers/exa", headers=context.developer_headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is False


@when('I write a secret for "{provider}" through the control API')
def step_when_write_secret(context: Any, provider: str) -> None:
    context.raw_key = "offline-control-secret"
    with _client(context) as client:
        context.secret_write_response = client.post(
            "/api/v1/account/vault/keys",
            json={"provider_type": provider, "label": "control secret", "secret": context.raw_key},
            headers=context.admin_headers,
        )


@then("the vault response should be configured without exposing the secret")
def step_then_secret_configured(context: Any) -> None:
    from polyweb.models.vault import VaultKeyDetails

    assert context.secret_write_response.status_code == 201, context.secret_write_response.text
    body = context.secret_write_response.json()
    assert set(body) == set(VaultKeyDetails.model_fields)
    assert body["status"] == "active" and body["auth_mode"] == "api_key"
    assert context.raw_key not in context.secret_write_response.text
    slot = credential_secret_slot(UUID(body["id"]), body["generation"])
    assert (
        context.loop.run_until_complete(context.app.state.secret_store.get(slot)) == context.raw_key
    )


@when('I delete the "{provider}" secret through the control API')
def step_when_delete_secret(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_delete_response = client.delete(
            f"/api/v1/account/vault/keys/{context.secret_write_response.json()['id']}",
            headers=context.admin_headers,
        )


@then("the vault value should be removed without exposing the secret")
def step_then_secret_missing(context: Any) -> None:
    assert context.secret_delete_response.status_code == 200, context.secret_delete_response.text
    assert context.raw_key not in context.secret_delete_response.text
    body = context.secret_write_response.json()
    slot = credential_secret_slot(UUID(body["id"]), body["generation"])
    assert context.loop.run_until_complete(context.app.state.secret_store.get(slot)) is None
    with _client(context) as client:
        listed = client.get("/api/v1/account/vault/keys", headers=context.admin_headers)
    assert listed.status_code == 200, listed.text
    assert all(key["id"] != body["id"] for key in listed.json())
    assert context.raw_key not in listed.text


@when("I update routing to first_only with 2 attempts")
def step_when_update_routing(context: Any) -> None:
    with _client(context) as client:
        context.routing_response = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "first_only",
                "max_attempts": 2,
            },
            headers=context.admin_headers,
        )


@then("the routing GET should equal first_only and 2 attempts")
def step_then_routing_round_trip(context: Any) -> None:
    assert context.routing_response.status_code == 200
    with _client(context) as client:
        response = client.get("/api/v1/routing/config", headers=context.developer_headers)
    assert response.status_code == 200
    assert response.json() == {
        "fallback_policy": "first_only",
        "max_attempts": 2,
    }


@when("I submit an offline control search")
def step_when_control_search(context: Any) -> None:
    with _client(context) as client:
        context.search_response = client.post(
            "/search",
            json={
                "project_id": context.project_id,
                "query": "control activity",
            },
            headers=context.execution_headers,
        )
        context.dashboard_response = client.get("/dashboard", headers=context.developer_headers)


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
        context.failure_response = client.post(
            "/search",
            json={
                "project_id": context.project_id,
                "query": "control failure",
            },
            headers=context.execution_headers,
        )
        context.stats_response = client.get("/stats", headers=context.developer_headers)
        context.dashboard_response = client.get("/dashboard", headers=context.developer_headers)


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


@when('I apply the "{choice}" access choice to "{provider}"')
def step_when_apply_access_choice(context: Any, choice: str, provider: str) -> None:
    headers = getattr(context, "admin_headers", None) or _login_headers(
        context, "control-admin", system_admin=True
    )
    context.admin_headers = headers
    with _client(context) as client:
        response = client.patch(
            f"/api/v1/providers/{provider}", json=_patch_for_choice(choice), headers=headers
        )
    assert response.status_code == 200, response.text
    context.last_patch_response = response


@then(
    'the control-plane GET for "{provider}" should report enable mask '
    "{enable_mask:d} and support mask {support_mask:d}"
)
def step_then_provider_masks(
    context: Any, provider: str, enable_mask: int, support_mask: int
) -> None:
    with _client(context) as client:
        response = client.get(f"/api/v1/providers/{provider}", headers=_control_headers(context))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_id"] == provider
    assert body["enable_mask"] == enable_mask, body
    assert body["support_mask"] == support_mask, body
    assert body["enabled"] == bool(enable_mask & support_mask & 1), body


def _store_search(context: Any, status: int, body: Any) -> None:
    context.rest_search_status = status
    context.rest_search_body = body


def _store_fetch(context: Any, status: int, body: Any) -> None:
    context.rest_fetch_status = status
    context.rest_fetch_body = body


def _store_fanout(context: Any, status: int, body: Any) -> None:
    context.rest_fanout_status = status
    context.rest_fanout_body = body


@when("I submit offline search and fetch via REST")
def step_when_rest_search_and_fetch(context: Any) -> None:
    headers = context.execution_headers
    with _client(context) as client:
        search = client.post(
            "/search",
            json={"project_id": context.project_id, "query": "offline mask probe"},
            headers=headers,
        )
        fetch = client.post(
            "/fetch",
            json={"project_id": context.project_id, "url": "https://example.com/doc"},
            headers=headers,
        )
    _store_search(context, search.status_code, search.json() if search.content else None)
    _store_fetch(context, fetch.status_code, fetch.json() if fetch.content else None)


@when("I submit offline search via REST")
def step_when_rest_search_only(context: Any) -> None:
    with _client(context) as client:
        search = client.post(
            "/search",
            json={
                "project_id": context.project_id,
                "query": "offline mask probe",
            },
            headers=context.execution_headers,
        )
    _store_search(context, search.status_code, search.json() if search.content else None)


@when('I submit an offline fetch requiring provider "{provider}" via REST')
def step_when_rest_fetch_require(context: Any, provider: str) -> None:
    payload = {
        "url": "https://example.com/doc",
        "routing": {"mode": "require", "providers": [provider]},
    }
    with _client(context) as client:
        fetch = client.post(
            "/fetch",
            json={"project_id": context.project_id, **payload},
            headers=context.execution_headers,
        )
    _store_fetch(context, fetch.status_code, fetch.json() if fetch.content else None)


@when('I submit an offline search requiring provider "{provider}" via REST')
def step_when_rest_search_require(context: Any, provider: str) -> None:
    payload = {
        "query": "offline mask probe",
        "routing": {"mode": "require", "providers": [provider]},
    }
    with _client(context) as client:
        search = client.post(
            "/search",
            json={"project_id": context.project_id, **payload},
            headers=context.execution_headers,
        )
    _store_search(context, search.status_code, search.json() if search.content else None)


@when('I submit an offline search preferring provider "{provider}" via REST')
def step_when_rest_search_prefer(context: Any, provider: str) -> None:
    payload = {
        "query": "offline mask probe",
        "routing": {"mode": "prefer", "providers": [provider]},
    }
    with _client(context) as client:
        search = client.post(
            "/search",
            json={"project_id": context.project_id, **payload},
            headers=context.execution_headers,
        )
    _store_search(context, search.status_code, search.json() if search.content else None)


@when("I submit an offline auto search via REST")
def step_when_rest_search_auto(context: Any) -> None:
    with _client(context) as client:
        search = client.post(
            "/search",
            json={
                "project_id": context.project_id,
                "query": "offline mask probe",
                "routing": {"mode": "auto"},
            },
            headers=context.execution_headers,
        )
    _store_search(context, search.status_code, search.json() if search.content else None)


@when("I submit an offline fanout search via REST")
def step_when_rest_fanout(context: Any) -> None:
    with _client(context) as client:
        response = client.post(
            "/search",
            json={
                "project_id": context.project_id,
                "query": "offline mask probe",
                "fanout": True,
            },
            headers=context.execution_headers,
        )
    _store_fanout(context, response.status_code, response.json() if response.content else None)


@when('I submit an offline fanout search restricted to providers "{allow_list}" via REST')
def step_when_rest_fanout_restricted(context: Any, allow_list: str) -> None:
    providers = [name.strip() for name in allow_list.split(",") if name.strip()]
    payload = {
        "query": "offline mask probe",
        "fanout": True,
        "routing": {"mode": "fanout", "providers": providers},
    }
    with _client(context) as client:
        response = client.post(
            "/search",
            json={"project_id": context.project_id, **payload},
            headers=context.execution_headers,
        )
    _store_fanout(context, response.status_code, response.json() if response.content else None)


@when("I reset the adapter call counters")
def step_when_reset_counters(context: Any) -> None:
    _reset_counts(context)


@when("I call the MCP search tool")
def step_when_mcp_search(context: Any) -> None:
    assert getattr(context, "server", None) is not None, "MCP server is not configured"
    try:
        result = context.loop.run_until_complete(
            context.server.call_tool(
                "search",
                {"request": {"project_id": context.mcp_pid, "query": "offline mask probe"}},
            )
        )
        context.mcp_search_status = 200
        context.mcp_search_body = result[1]
        context.mcp_search_error = None
    except Exception as exc:
        context.mcp_search_status = 503
        context.mcp_search_body = None
        context.mcp_search_error = str(exc)


@when("I call the MCP fetch tool")
def step_when_mcp_fetch(context: Any) -> None:
    assert getattr(context, "server", None) is not None, "MCP server is not configured"
    try:
        result = context.loop.run_until_complete(
            context.server.call_tool(
                "fetch",
                {
                    "request": {
                        "project_id": context.mcp_pid,
                        "url": "https://example.com/doc",
                    }
                },
            )
        )
        context.mcp_fetch_status = 200
        context.mcp_fetch_body = result[1]
        context.mcp_fetch_error = None
    except Exception as exc:
        context.mcp_fetch_status = 503
        context.mcp_fetch_body = None
        context.mcp_fetch_error = str(exc)


@then('the REST search provider should be "{expected}"')
def step_then_rest_search_provider(context: Any, expected: str) -> None:
    assert getattr(context, "rest_search_status", None) == 200, (
        context.rest_search_status,
        context.rest_search_body,
    )
    assert context.rest_search_body["provider"] == expected, context.rest_search_body


@then('the REST search should fail with {status:d} containing "{detail}"')
def step_then_rest_search_error(context: Any, status: int, detail: str) -> None:
    assert getattr(context, "rest_search_status", None) == status, (
        context.rest_search_status,
        context.rest_search_body,
    )
    body = context.rest_search_body
    text = body.get("detail", body) if isinstance(body, dict) else str(body)
    assert detail in str(text), text


@then('the REST fetch outcome should be "{outcome}"')
def step_then_rest_fetch_outcome(context: Any, outcome: str) -> None:
    if outcome == "fail-503":
        assert getattr(context, "rest_fetch_status", None) == 503, (
            context.rest_fetch_status,
            context.rest_fetch_body,
        )
        body = context.rest_fetch_body
        text = body.get("detail", body) if isinstance(body, dict) else str(body)
        assert "eligible" in str(text), text
    elif outcome.startswith("succeed-"):
        expected = outcome.removeprefix("succeed-")
        assert getattr(context, "rest_fetch_status", None) == 200, (
            context.rest_fetch_status,
            context.rest_fetch_body,
        )
        assert context.rest_fetch_body["provider"] == expected, context.rest_fetch_body
    else:
        raise AssertionError(f"unknown fetch outcome {outcome!r}")


@then('the REST fetch should fail with {status:d} containing "{detail}"')
def step_then_rest_fetch_error(context: Any, status: int, detail: str) -> None:
    assert context.rest_fetch_status == status, (context.rest_fetch_status, context.rest_fetch_body)
    assert detail in str(context.rest_fetch_body), context.rest_fetch_body


@then(
    "the adapter call counts should be exa search {exa_search:d} fetch {exa_fetch:d} "
    "and brave search {brave_search:d} fetch {brave_fetch:d}"
)
def step_then_call_counts(
    context: Any, exa_search: int, exa_fetch: int, brave_search: int, brave_fetch: int
) -> None:
    exa = _adapter_by_name(context, "exa")
    brave = _adapter_by_name(context, "brave")
    assert exa.search_calls == exa_search, (exa.search_calls, exa_search)
    assert exa.fetch_calls == exa_fetch, (exa.fetch_calls, exa_fetch)
    assert brave.search_calls == brave_search, (brave.search_calls, brave_search)
    assert brave.fetch_calls == brave_fetch, (brave.fetch_calls, brave_fetch)


@then('a fresh control-plane read for "{provider}" should still report enable mask {enable_mask:d}')
def step_then_fresh_masks(context: Any, provider: str, enable_mask: int) -> None:
    _reopen_control_repository(context)
    with _client(context) as client:
        response = client.get(f"/api/v1/providers/{provider}", headers=_control_headers(context))
    assert response.status_code == 200, response.text
    assert response.json()["enable_mask"] == enable_mask, response.json()


@then(
    "the pure access predicate should allow search but block fetch "
    "for enable {enable:d} support {support:d}"
)
def step_then_pure_brave(context: Any, enable: int, support: int) -> None:
    assert is_operation_enabled(enable, support, "search") is True
    assert is_operation_enabled(enable, support, "fetch") is False


@then(
    "the pure access predicate should block search and fetch "
    "for enable {enable:d} support {support:d}"
)
def step_then_pure_blocked(context: Any, enable: int, support: int) -> None:
    assert is_operation_enabled(enable, support, "search") is False
    assert is_operation_enabled(enable, support, "fetch") is False


@then('the fanout participating providers should be "{expected}"')
def step_then_fanout_participants(context: Any, expected: str) -> None:
    wanted = [name.strip() for name in expected.split(",") if name.strip()]
    assert getattr(context, "rest_fanout_status", None) == 200, (
        context.rest_fanout_status,
        context.rest_fanout_body,
    )
    assert context.rest_fanout_body["participating_providers"] == wanted, context.rest_fanout_body


@then('the fanout search should fail with {status:d} containing "{detail}"')
def step_then_fanout_error(context: Any, status: int, detail: str) -> None:
    assert getattr(context, "rest_fanout_status", None) == status, (
        context.rest_fanout_status,
        context.rest_fanout_body,
    )
    body = context.rest_fanout_body
    text = body.get("detail", body) if isinstance(body, dict) else str(body)
    assert detail in str(text), text


@then('the MCP search provider should be "{expected}"')
def step_then_mcp_search_provider(context: Any, expected: str) -> None:
    assert getattr(context, "mcp_search_status", None) == 200, (
        context.mcp_search_status,
        context.mcp_search_error,
    )
    assert context.mcp_search_body["provider"] == expected, context.mcp_search_body


@then('the MCP fetch provider should be "{expected}"')
def step_then_mcp_fetch_provider(context: Any, expected: str) -> None:
    assert getattr(context, "mcp_fetch_status", None) == 200, (
        context.mcp_fetch_status,
        context.mcp_fetch_error,
    )
    assert context.mcp_fetch_body["provider"] == expected, context.mcp_fetch_body
