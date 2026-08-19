"""Stage 2 contract tests for the provider-neutral MCP surface.

AC-6: this file depends only on stdlib, pytest, pydantic, and the freesearch
package itself — no vendor or MCP SDK imports anywhere in the suite.
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from conftest import FakeAdapter
from freesearch.contracts import (
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    RoutingMode,
    SearchRequest,
    SearchResponse,
)
from freesearch.mcp.surface import McpSurface, UnsupportedOperationError


class RecordingAdapter(FakeAdapter):
    """FakeAdapter spy that records calls and allows capability overrides."""

    def __init__(self, capabilities: ProviderCapabilities | None = None) -> None:
        self.capabilities_override = capabilities
        self.calls: list[str] = []
        self.last_search_request: SearchRequest | None = None
        self.last_fetch_request: FetchRequest | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.capabilities_override or super().capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append("search")
        self.last_search_request = request
        return await super().search(request)

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.calls.append("fetch")
        self.last_fetch_request = request
        return await super().fetch(request)


# --- AC-1: exactly the `search` and `fetch` public async tool operations ---


async def test_surface_exposes_only_search_and_fetch_operations(fake_adapter) -> None:
    public_operations = {
        name
        for name, member in vars(McpSurface).items()
        if callable(member) and not name.startswith("_")
    }
    assert public_operations == {"search", "fetch"}

    surface = McpSurface(fake_adapter)
    assert not hasattr(surface, "estimate_cost")
    assert not hasattr(surface, "health")
    assert not hasattr(surface, "quota")


# --- AC-2: invalid payloads fail validation before any adapter call ---


async def test_invalid_search_payload_fails_before_adapter_call() -> None:
    adapter = RecordingAdapter()
    surface = McpSurface(adapter)

    for invalid in [
        {"query": ""},  # blank query
        {"query": "ok", "limit": 0},  # limit out of range
        {"query": "ok", "unknown_field": "x"},  # extra field forbidden
    ]:
        with pytest.raises(ValidationError):
            await surface.search(invalid)

    assert adapter.calls == []


async def test_invalid_fetch_payload_fails_before_adapter_call() -> None:
    adapter = RecordingAdapter()
    surface = McpSurface(adapter)

    for invalid in [
        {"url": "not-a-url"},  # invalid URL
        {"url": "https://example.com", "max_chars": 0},  # max_chars out of range
    ]:
        with pytest.raises(ValidationError):
            await surface.fetch(invalid)

    assert adapter.calls == []


# --- AC-3: each operation delegates to the adapter, preserving contract fields ---


async def test_search_delegates_preserving_fields_and_routing() -> None:
    adapter = RecordingAdapter()
    surface = McpSurface(adapter)

    await surface.search(
        {
            "query": "pytest async",
            "limit": 5,
            "language": "en",
            "country_code": "US",
            "domains": ("example.com",),
            "routing": {
                "mode": "prefer",
                "providers": ("fake",),
                "allow_fallback": False,
            },
        }
    )

    assert adapter.calls == ["search"]
    request = adapter.last_search_request
    assert isinstance(request, SearchRequest)
    assert request.query == "pytest async"
    assert request.limit == 5
    assert request.language == "en"
    assert request.country_code == "US"
    assert request.domains == ("example.com",)
    assert request.routing.mode is RoutingMode.PREFER
    assert request.routing.providers == ("fake",)
    assert request.routing.allow_fallback is False


async def test_fetch_delegates_preserving_fields_and_routing() -> None:
    adapter = RecordingAdapter()
    surface = McpSurface(adapter)

    await surface.fetch(
        {
            "url": "https://example.com/document",
            "max_chars": 1000,
            "routing": {"mode": "require"},
        }
    )

    assert adapter.calls == ["fetch"]
    request = adapter.last_fetch_request
    assert isinstance(request, FetchRequest)
    assert str(request.url) == "https://example.com/document"
    assert request.max_chars == 1000
    assert request.routing.mode is RoutingMode.REQUIRE


# --- AC-4: capability-declared unsupported operations fail before execution ---


async def test_unsupported_search_fails_before_adapter_execution() -> None:
    adapter = RecordingAdapter(capabilities=ProviderCapabilities(search=False, fetch=True))
    surface = McpSurface(adapter)

    with pytest.raises(UnsupportedOperationError, match="does not support search"):
        await surface.search({"query": "ok"})

    assert issubclass(UnsupportedOperationError, RuntimeError)
    assert adapter.calls == []


async def test_unsupported_fetch_fails_before_adapter_execution() -> None:
    adapter = RecordingAdapter(capabilities=ProviderCapabilities(search=True, fetch=False))
    surface = McpSurface(adapter)

    with pytest.raises(UnsupportedOperationError, match="does not support fetch"):
        await surface.fetch({"url": "https://example.com"})

    assert adapter.calls == []


# --- AC-5: successful outputs are JSON-compatible dicts per response contracts ---


async def test_search_output_is_json_compatible_per_response_contract(fake_adapter) -> None:
    surface = McpSurface(fake_adapter)

    result = await surface.search({"query": "json check"})

    assert isinstance(result, dict)
    json.dumps(result)  # must serialize without error
    assert result["query"] == "json check"
    assert result["provider"] == "fake"
    assert result["results"][0]["title"] == "Example"
    assert isinstance(result["results"][0]["url"], str)
    usage = result["usage"]
    assert usage["operation"] == "search"  # enum serialized as str
    assert usage["units"] == "1"  # Decimal serialized as str
    assert isinstance(datetime.fromisoformat(usage["observed_at"]), datetime)

    # Output matches the existing response contract exactly.
    round_tripped = SearchResponse.model_validate(result)
    assert round_tripped.model_dump(mode="json") == result


async def test_fetch_output_is_json_compatible_per_response_contract(fake_adapter) -> None:
    surface = McpSurface(fake_adapter)

    result = await surface.fetch({"url": "https://example.com/document"})

    assert isinstance(result, dict)
    json.dumps(result)  # must serialize without error
    assert result["provider"] == "fake"
    document = result["document"]
    assert document["url"] == "https://example.com/document"
    assert document["content"] == "Fetched example content."
    assert isinstance(datetime.fromisoformat(document["fetched_at"]), datetime)

    round_tripped = FetchResponse.model_validate(result)
    assert round_tripped.model_dump(mode="json") == result
