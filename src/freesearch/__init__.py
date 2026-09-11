"""Shared foundation and contracts for the FreeSearch application."""

from freesearch.models.contracts import (
    CacheMetadata,
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    QuotaSnapshot,
    RoutingPreference,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
)

__all__ = [
    "CacheMetadata",
    "CostEstimate",
    "FetchRequest",
    "FetchResponse",
    "FetchedDocument",
    "ProviderCapabilities",
    "ProviderError",
    "QuotaSnapshot",
    "RoutingPreference",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "UsageEvent",
]
