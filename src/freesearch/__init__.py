"""Shared foundation and contracts for the FreeSearch application."""

from freesearch.contracts import (
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
