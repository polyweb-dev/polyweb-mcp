"""Transport fixture proof: explicit temp accounts coexist with stub transports."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from polyweb.adapters.base import ProviderAdapter
from polyweb.models.contracts import (
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
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    create_temp_user,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import seed_app_bound_project


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="stub result",
                    url="https://example.com/stub",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="stub content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "transport-users.db")
    yield repo
    await repo.close()


async def test_api_search_works_with_explicit_temp_accounts(
    repository: SQLiteRepository, auth_secret: str, monkeypatch
) -> None:
    first = await create_temp_user(repository, temp_email("api-first"))
    second = await create_temp_user(repository, temp_email("api-second"))
    assert first.id != second.id

    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        anonymous = client.post("/search", json={"query": "explicit accounts"})
        assert anonymous.status_code == 401
        assert anonymous.headers["www-authenticate"] == "Bearer"

        pair = register_and_login(client, temp_email("api-search"))
        pid = str(
            (
                await seed_app_bound_project(
                    repository, user_id=account_id_from_pair(pair), app=app, monkeypatch=monkeypatch
                )
            ).project_id
        )
        response = client.post(
            "/search",
            json={"project_id": pid, "query": "explicit accounts"},
            headers=raw_auth_headers(pair["access_token"]),
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "stubby"
