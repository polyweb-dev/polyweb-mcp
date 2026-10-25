"""Error-trace identity: a failed request keeps its query text and provider.

Reproduces the user report where an error trace shows a blank query and a
blank provider while the provider request event still holds the query text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "error-identity.db")
    yield repo
    await repo.close()


class _FailingAdapter(ProviderAdapter):
    """Offline adapter that always fails the search call."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=False, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        raise RuntimeError(f"Provider {self.name} simulated failure")

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise NotImplementedError

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(provider=self.name, operation=UsageOperation.SEARCH, units=Decimal("0"))

    async def quota(self) -> QuotaSnapshot | None:
        return None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name, status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC)
        )


async def test_single_search_error_trace_keeps_query_and_provider(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """An error trace records the query text and provider of the failed call."""
    app = create_app([_FailingAdapter("doomed-provider")], repository=repository)

    with TestClient(app, raise_server_exceptions=False) as client:
        pair = register_and_login(client, temp_email("error-identity"))
        headers = raw_auth_headers(pair["access_token"])
        pid = str(
            (
                await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            ).project_id
        )
        response = client.post(
            "/search",
            json={
                "project_id": pid,
                "query": "Number of timezones around the world?",
                "routing": {"mode": "require", "providers": ["doomed-provider"]},
            },
            headers=headers,
        )
        assert response.status_code == 500
        listing = client.get("/api/v1/traces", headers=headers).json()
        rows = listing["items"] if isinstance(listing, dict) else listing
        assert len(rows) == 1
        trace_id = rows[0]["trace_id"]
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["outcome"] == "error"
    roots = [span for span in detail["spans"] if span["parent_span_id"] is None]
    assert len(roots) == 1
    assert (
        detail["input"],
        roots[0]["provider"],
        rows[0]["provider"],
    ) == (
        "Number of timezones around the world?",
        "doomed-provider",
        "doomed-provider",
    )
