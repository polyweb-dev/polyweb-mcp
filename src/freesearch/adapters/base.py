"""The shared async adapter contract implemented by every provider."""

from abc import ABC, abstractmethod

from freesearch.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    SearchResponse,
)


class ProviderAdapter(ABC):
    """Provider-neutral interface for search, fetch, cost, health, and quota."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable provider identifier."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Describe the operations supported by this adapter."""

    @abstractmethod
    async def search(self, request: SearchRequest) -> SearchResponse:
        """Search for documents matching ``request``."""

    @abstractmethod
    async def fetch(self, request: FetchRequest) -> FetchResponse:
        """Fetch and normalize the document at ``request.url``."""

    @abstractmethod
    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        """Estimate usage for an operation without executing it."""

    async def health(self) -> ProviderHealth:
        """Return a default unknown health state until a provider overrides it."""

        from datetime import UTC, datetime

        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime.now(UTC),
        )

    async def quota(self) -> QuotaSnapshot | None:
        """Return quota information when a provider exposes it."""

        return None
