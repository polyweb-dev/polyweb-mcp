"""Steps for the core project API key journey (A1, TASK-000041).

One offline REST app and one direct MCP server share a temporary database and
a counting fake provider. The raw key lives only on the scenario context and
is never printed.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.server import create_server
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    auth_service_for,
    configure_bdd_secret,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import bdd_bind_project, seed_execution_project


class _CountingAdapter(ProviderAdapter):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "counting"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls += 1
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[SearchResult(title="t", url="https://example.com/k", snippet="s")],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.calls += 1
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(url=request.url, content="c", fetched_at=datetime.now(UTC)),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


def _mcp_server(context: Any) -> Any:
    return create_server(
        [context.key_adapter],
        repository=context.repository,
        auth_service=auth_service_for(context.repository),
        stdio_token=SecretStr(context.raw_key),
    )


@given("an offline API with a project administrator and a counting provider")
def step_given_key_api(context: Any) -> None:
    configure_bdd_secret(context)
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-keys-", suffix=".db", dir=Path.cwd(), delete=False
    ) as handle:
        context.database_path = Path(handle.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )
    context.key_adapter = _CountingAdapter()
    context.app = create_app([context.key_adapter], repository=context.repository)
    with TestClient(context.app) as client:
        pair = register_and_login(client, temp_email("bdd-key-admin"))
    context.admin_headers = raw_auth_headers(pair["access_token"])
    project = context.loop.run_until_complete(
        seed_execution_project(context.repository, user_id=account_id_from_pair(pair))
    )
    context.key_project_id = str(project.project_id)
    bdd_bind_project(context, context.app, project.project_id, project.actor_id)


@when("the project administrator issues an API key through the API")
def step_when_issue_key(context: Any) -> None:
    with TestClient(context.app) as client:
        response = client.post(
            f"/api/v1/projects/{context.key_project_id}/api-keys",
            json={"label": "agent"},
            headers=context.admin_headers,
        )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    context.raw_key = body["key"]
    context.key_id = body["id"]


@then("the key should be shown once and absent from the key list")
def step_then_key_once(context: Any) -> None:
    with TestClient(context.app) as client:
        listed = client.get(
            f"/api/v1/projects/{context.key_project_id}/api-keys", headers=context.admin_headers
        )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [context.key_id]
    assert context.raw_key not in listed.text


@then("the key should search its project over REST and MCP")
def step_then_key_executes(context: Any) -> None:
    headers = {"Authorization": f"Bearer {context.raw_key}"}
    with TestClient(context.app) as client:
        rest = client.post("/search", json={"query": "rest key"}, headers=headers)
    assert rest.status_code == 200
    result = context.loop.run_until_complete(
        _mcp_server(context).call_tool("search", {"request": {"query": "mcp key"}})
    )
    assert result[1]["provider"] == "counting"
    assert context.key_adapter.calls == 2


@when("the project administrator revokes the key")
def step_when_revoke_key(context: Any) -> None:
    with TestClient(context.app) as client:
        response = client.delete(
            f"/api/v1/projects/{context.key_project_id}/api-keys/{context.key_id}",
            headers=context.admin_headers,
        )
    assert response.status_code == 204


@then("the next REST and MCP calls with the key should fail without provider calls")
def step_then_revoked_fails(context: Any) -> None:
    headers = {"Authorization": f"Bearer {context.raw_key}"}
    with TestClient(context.app) as client:
        rest = client.post("/search", json={"query": "after"}, headers=headers)
    assert rest.status_code == 401
    assert rest.json() == {"detail": "not authenticated"}
    try:
        context.loop.run_until_complete(
            _mcp_server(context).call_tool("search", {"request": {"query": "after"}})
        )
    except ToolError as error:
        assert "authentication is required" in str(error)
    else:
        raise AssertionError("a revoked key served an MCP tool call")
    assert context.key_adapter.calls == 2


@then("the project administrator should still search the project without a key")
def step_then_human_executes(context: Any) -> None:
    with TestClient(context.app) as client:
        response = client.post(
            "/search",
            json={"project_id": context.key_project_id, "query": "browser"},
            headers=context.admin_headers,
        )
    assert response.status_code == 200
    assert context.key_adapter.calls == 3
