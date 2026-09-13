"""Server-level capability equivalence for the retired legacy surface contract.

The legacy single-adapter facade raised a dedicated error when an adapter
declared an operation unsupported. The active server (``create_server``) does
not preserve that error contract: incapable adapters are excluded by routing
(``select_route``/``_eligible``), so a request with no eligible adapter
surfaces as a ``ToolError`` instead, and the adapter is never called.

These tests pin the server-level behavior that replaces the surface contract:
valid ``{"request": ...}`` payloads route and return JSON-stable response
dicts, invalid payloads are rejected before any adapter call, and
capability-excluded routing never invokes the incapable adapter.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

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
    UsageOperation,
)


class _CapabilityStub(ProviderAdapter):
    """Scenario-specific stub with explicit capabilities and call recording."""

    def __init__(self, name: str, *, search: bool = True, fetch: bool = True) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=search, fetch=fetch, cost_estimate=True)
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append("search")
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/r",
                    snippet="snippet",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.calls.append("fetch")
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
            currency="queries",
        )

    async def health(self) -> None:
        pass

    async def quota(self) -> None:
        pass


def _payload(result: Any) -> dict[str, Any]:
    """Unwrap the ``call_tool`` response tuple to the tool result dict."""

    assert isinstance(result, tuple)
    assert isinstance(result[1], dict)
    return result[1]


# --- (a) {"request": ...} schema works for both tools ---


async def test_search_tool_accepts_request_schema() -> None:
    server = create_server([_CapabilityStub("brave")])

    payload = _payload(await server.call_tool("search", {"request": {"query": "python asyncio"}}))

    assert payload["provider"] == "brave"
    assert payload["query"] == "python asyncio"


async def test_fetch_tool_accepts_request_schema() -> None:
    server = create_server([_CapabilityStub("youcom")])

    payload = _payload(
        await server.call_tool("fetch", {"request": {"url": "https://example.com/page"}})
    )

    assert payload["provider"] == "youcom"
    assert payload["document"]["content"] == "youcom content"


# --- (b) invalid payloads rejected without adapter call ---


@pytest.mark.parametrize(
    "payload",
    [
        {"request": {"query": ""}},  # blank query
        {"request": {"query": "ok", "limit": 0}},  # limit out of range
        {"request": {"query": "ok", "unknown_field": "x"}},  # extra field forbidden
    ],
)
async def test_invalid_search_payload_rejected_without_adapter_call(
    payload: dict[str, Any],
) -> None:
    stub = _CapabilityStub("brave")
    server = create_server([stub])

    with pytest.raises(ToolError):
        await server.call_tool("search", payload)

    assert stub.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"request": {"url": "not-a-url"}},  # invalid URL
        {"request": {"url": "https://example.com", "max_chars": 0}},  # max_chars out of range
    ],
)
async def test_invalid_fetch_payload_rejected_without_adapter_call(
    payload: dict[str, Any],
) -> None:
    stub = _CapabilityStub("youcom")
    server = create_server([stub])

    with pytest.raises(ToolError):
        await server.call_tool("fetch", payload)

    assert stub.calls == []


# --- (c) capability-excluded routing: incapable adapters never invoked ---


async def test_search_excludes_fetch_only_adapter() -> None:
    stub = _CapabilityStub("fetchonly", search=False, fetch=True)
    server = create_server([stub])

    with pytest.raises(ToolError):
        await server.call_tool("search", {"request": {"query": "ok"}})

    assert stub.calls == []


async def test_fetch_excludes_search_only_adapter() -> None:
    stub = _CapabilityStub("searchonly", search=True, fetch=False)
    server = create_server([stub])

    with pytest.raises(ToolError):
        await server.call_tool("fetch", {"request": {"url": "https://example.com"}})

    assert stub.calls == []


async def test_split_capabilities_route_to_capable_adapter() -> None:
    search_only = _CapabilityStub("searchonly", search=True, fetch=False)
    fetch_only = _CapabilityStub("fetchonly", search=False, fetch=True)
    server = create_server([search_only, fetch_only])

    search_payload = _payload(await server.call_tool("search", {"request": {"query": "hi"}}))
    fetch_payload = _payload(
        await server.call_tool("fetch", {"request": {"url": "https://example.com"}})
    )

    assert search_payload["provider"] == "searchonly"
    assert fetch_payload["provider"] == "fetchonly"
    assert search_only.calls == ["search"]
    assert fetch_only.calls == ["fetch"]


# --- (d) outputs JSON-stable + response-contract round-trip ---


async def test_search_output_is_json_stable_per_response_contract() -> None:
    server = create_server([_CapabilityStub("brave")])

    payload = _payload(await server.call_tool("search", {"request": {"query": "json check"}}))

    assert isinstance(payload, dict)
    json.dumps(payload)  # must serialize without error
    assert payload["query"] == "json check"
    assert payload["provider"] == "brave"
    assert isinstance(payload["results"][0]["url"], str)
    round_tripped = SearchResponse.model_validate(payload)
    assert round_tripped.model_dump(mode="json") == payload


async def test_fetch_output_is_json_stable_per_response_contract() -> None:
    server = create_server([_CapabilityStub("youcom")])

    payload = _payload(
        await server.call_tool("fetch", {"request": {"url": "https://example.com/document"}})
    )

    assert isinstance(payload, dict)
    json.dumps(payload)  # must serialize without error
    assert payload["provider"] == "youcom"
    assert payload["document"]["url"] == "https://example.com/document"
    round_tripped = FetchResponse.model_validate(payload)
    assert round_tripped.model_dump(mode="json") == payload


# --- (e) no-provider ToolError ---


async def test_search_without_any_adapter_raises_no_provider() -> None:
    server = create_server([])

    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("search", {"request": {"query": "anything"}})


async def test_fetch_without_any_adapter_raises_no_provider() -> None:
    server = create_server([])

    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("fetch", {"request": {"url": "https://example.com"}})
