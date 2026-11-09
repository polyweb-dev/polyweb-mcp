from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio

from polyweb.adapters.base import ProviderAdapter
from polyweb.configuration.config import get_settings
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


class FakeAdapter(ProviderAdapter):
    name = "fake"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(fetch=True, cost_estimate=True, quota=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="Example",
                    url="https://example.com/result",
                    snippet="A normalized result.",
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
                content="Fetched example content.",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("1"))


@pytest_asyncio.fixture
async def fake_adapter() -> AsyncIterator[FakeAdapter]:
    yield FakeAdapter()


@pytest.fixture
def auth_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point one test at a generated JWT secret, restored on cleanup.

    Explicit per-test credential only. Not autouse. Each test still creates
    its own temporary accounts and tokens through ``tests.fixtures.auth``.
    """

    from tests.fixtures.auth import install_auth_secret

    secret = install_auth_secret(monkeypatch)
    try:
        yield secret
    finally:
        get_settings.cache_clear()
