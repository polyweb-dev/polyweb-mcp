"""Provider-neutral MCP tool surface exposing only async ``search`` and ``fetch``.

This module owns no vendor imports, no transport, and no concrete server; the
integration worktree binds these handlers to an MCP SDK.
"""

from collections.abc import Mapping
from typing import Any

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import FetchRequest, FetchResponse, SearchRequest, SearchResponse


class UnsupportedOperationError(RuntimeError):
    """Raised when a provider declares a requested operation unsupported."""


class McpSurface:
    """Bind the two public tool operations to a single provider adapter."""

    def __init__(self, adapter: ProviderAdapter) -> None:
        self._adapter = adapter

    async def search(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and run a search, returning a JSON-compatible response dict."""

        request = SearchRequest.model_validate(payload)
        if not self._adapter.capabilities.search:
            raise UnsupportedOperationError(
                f"provider '{self._adapter.name}' does not support search"
            )
        response: SearchResponse = await self._adapter.search(request)
        return response.model_dump(mode="json")

    async def fetch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and run a fetch, returning a JSON-compatible response dict."""

        request = FetchRequest.model_validate(payload)
        if not self._adapter.capabilities.fetch:
            raise UnsupportedOperationError(
                f"provider '{self._adapter.name}' does not support fetch"
            )
        response: FetchResponse = await self._adapter.fetch(request)
        return response.model_dump(mode="json")
