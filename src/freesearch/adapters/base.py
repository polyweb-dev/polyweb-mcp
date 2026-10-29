"""The shared async adapter contract implemented by every provider."""

from abc import ABC, abstractmethod

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
)
from freesearch.models.provider_limits import (
    AuthMode,
    NativeUsageSnapshot,
    UsageSyncRequest,
)


class ProviderAdapter(ABC):
    """Provider-neutral interface for search, fetch, cost, health, and quota."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Describe the operations supported by this adapter."""
        pass

    @abstractmethod
    async def search(self, request: SearchRequest) -> SearchResponse:
        """Search for documents matching ``request``."""
        pass

    @abstractmethod
    async def fetch(self, request: FetchRequest) -> FetchResponse:
        """Fetch and normalize the document at ``request.url``."""
        pass

    @abstractmethod
    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        """Estimate usage for an operation without executing it."""
        pass

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

    @property
    def limit_auth_mode(self) -> AuthMode:
        """Return the auth rail this adapter instance uses for limit records."""

        return AuthMode.KEYED

    @property
    def dispatch_runner(self) -> object | None:
        """Return the retrying runner that dispatches this adapter's sends.

        The telemetry wrapper installs a per-send capacity observer on such a
        runner, so an internal HTTP retry is charged as its own upstream
        attempt. Adapters without a runner dispatch exactly once.
        """

        runner = getattr(self, "_runner", None)
        if runner is None:
            return None
        from freesearch.infrastructure.resilience import ResilientRunner

        return runner if isinstance(runner, ResilientRunner) else None

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        """Return a native usage observation, or None when the provider exposes none."""

        return None

    async def aclose(self) -> None:
        """Release any underlying client or network resources owned by this adapter."""

        return None
