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
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

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
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.api_keys import mcp_key_credentials


class _CapabilityStub(ProviderAdapter):
    """Scenario-specific stub with explicit capabilities and call recording."""

    def __init__(self, name: str, *, search: bool = True, fetch: bool = True) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=search, fetch=fetch, cost_estimate=True)
        self.calls: list[str] = []
        self.search_requests: list[SearchRequest] = []
        self.fetch_requests: list[FetchRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append("search")
        self.search_requests.append(request)
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
        self.fetch_requests.append(request)
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


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "capability.db")
    yield repo
    await repo.close()


async def _authed_server(
    repository: SQLiteRepository, adapters: list[ProviderAdapter], prefix: str
) -> tuple[FastMCP, str]:
    """Build one tool server with a real project API key as its stdio credential."""

    service, key, pid = await mcp_key_credentials(repository, prefix)
    server = create_server(
        adapters,
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(key.get_secret_value()),
    )
    return server, pid


# --- (a) {"request": ...} schema works for both tools ---


async def test_search_tool_accepts_request_schema(repository: SQLiteRepository) -> None:
    server, pid = await _authed_server(repository, [_CapabilityStub("brave")], "cap-search")

    payload = _payload(
        await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "python asyncio"}}
        )
    )

    assert payload["provider"] == "brave"
    assert payload["query"] == "python asyncio"


async def test_fetch_tool_accepts_request_schema(repository: SQLiteRepository) -> None:
    server, pid = await _authed_server(repository, [_CapabilityStub("youcom")], "cap-fetch")

    payload = _payload(
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com/page"}}
        )
    )

    assert payload["provider"] == "youcom"
    assert payload["document"]["content"] == "youcom content"


async def test_search_tool_accepts_provider_options_and_preserves_vendor_metadata(
    repository: SQLiteRepository,
) -> None:
    class _MetadataStub(_CapabilityStub):
        async def search(self, request: SearchRequest) -> SearchResponse:
            self.calls.append("search")
            self.search_requests.append(request)
            return SearchResponse(
                query=request.query,
                provider=self.name,
                results=[],
                provider_metadata={"search_id": "native-search-id"},
            )

    stub = _MetadataStub("brave")
    server, pid = await _authed_server(repository, [stub], "cap-search-provider-options")
    payload = _payload(
        await server.call_tool(
            "search",
            {
                "request": {
                    "project_id": pid,
                    "query": "context",
                    "providerOptions": {"exa": {"type": "deep-lite"}},
                }
            },
        )
    )

    assert payload["provider"] == "brave"
    assert payload["provider_metadata"] == {"search_id": "native-search-id"}
    assert stub.search_requests[0].provider_options is not None
    assert stub.search_requests[0].provider_options.exa is not None
    assert stub.search_requests[0].provider_options.exa.type == "deep-lite"


async def test_fetch_tool_accepts_operation_specific_provider_options(
    repository: SQLiteRepository,
) -> None:
    stub = _CapabilityStub("youcom")
    server, pid = await _authed_server(repository, [stub], "cap-fetch-provider-options")

    payload = _payload(
        await server.call_tool(
            "fetch",
            {
                "request": {
                    "project_id": pid,
                    "url": "https://example.com/page",
                    "providerOptions": {"you": {"formats": ["html"]}},
                }
            },
        )
    )

    assert payload["provider"] == "youcom"
    assert stub.fetch_requests[0].provider_options is not None
    assert stub.fetch_requests[0].provider_options.you is not None
    assert stub.fetch_requests[0].provider_options.you.formats == ("html",)


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
    repository: SQLiteRepository,
    payload: dict[str, Any],
) -> None:
    stub = _CapabilityStub("brave")
    server, _pid = await _authed_server(repository, [stub], "cap-bad-search")

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
    repository: SQLiteRepository,
    payload: dict[str, Any],
) -> None:
    stub = _CapabilityStub("youcom")
    server, _pid = await _authed_server(repository, [stub], "cap-bad-fetch")

    with pytest.raises(ToolError):
        await server.call_tool("fetch", payload)

    assert stub.calls == []


# --- (c) capability-excluded routing: incapable adapters never invoked ---


async def test_search_excludes_fetch_only_adapter(repository: SQLiteRepository) -> None:
    stub = _CapabilityStub("fetchonly", search=False, fetch=True)
    server, pid = await _authed_server(repository, [stub], "cap-exclude-search")

    with pytest.raises(ToolError):
        await server.call_tool("search", {"request": {"project_id": pid, "query": "ok"}})

    assert stub.calls == []


async def test_fetch_excludes_search_only_adapter(repository: SQLiteRepository) -> None:
    stub = _CapabilityStub("searchonly", search=True, fetch=False)
    server, pid = await _authed_server(repository, [stub], "cap-exclude-fetch")

    with pytest.raises(ToolError):
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
        )

    assert stub.calls == []


async def test_split_capabilities_route_to_capable_adapter(
    repository: SQLiteRepository,
) -> None:
    search_only = _CapabilityStub("searchonly", search=True, fetch=False)
    fetch_only = _CapabilityStub("fetchonly", search=False, fetch=True)
    server, pid = await _authed_server(repository, [search_only, fetch_only], "cap-split")

    search_payload = _payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "hi"}})
    )
    fetch_payload = _payload(
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
        )
    )

    assert search_payload["provider"] == "searchonly"
    assert fetch_payload["provider"] == "fetchonly"
    assert search_only.calls == ["search"]
    assert fetch_only.calls == ["fetch"]


# --- (d) outputs JSON-stable + response-contract round-trip ---


async def test_search_output_is_json_stable_per_response_contract(
    repository: SQLiteRepository,
) -> None:
    server, pid = await _authed_server(repository, [_CapabilityStub("brave")], "cap-json-search")

    payload = _payload(
        await server.call_tool("search", {"request": {"project_id": pid, "query": "json check"}})
    )

    assert isinstance(payload, dict)
    json.dumps(payload)  # must serialize without error
    assert payload["query"] == "json check"
    assert payload["provider"] == "brave"
    assert isinstance(payload["results"][0]["url"], str)
    round_tripped = SearchResponse.model_validate(payload)
    assert round_tripped.model_dump(mode="json") == payload


async def test_fetch_output_is_json_stable_per_response_contract(
    repository: SQLiteRepository,
) -> None:
    server, pid = await _authed_server(repository, [_CapabilityStub("youcom")], "cap-json-fetch")

    payload = _payload(
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com/document"}}
        )
    )

    assert isinstance(payload, dict)
    json.dumps(payload)  # must serialize without error
    assert payload["provider"] == "youcom"
    assert payload["document"]["url"] == "https://example.com/document"
    round_tripped = FetchResponse.model_validate(payload)
    assert round_tripped.model_dump(mode="json") == payload


# --- (e) no-provider ToolError ---


async def test_search_without_any_adapter_raises_no_provider(
    repository: SQLiteRepository,
) -> None:
    server, pid = await _authed_server(repository, [], "cap-empty-search")

    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("search", {"request": {"project_id": pid, "query": "anything"}})


async def test_fetch_without_any_adapter_raises_no_provider(
    repository: SQLiteRepository,
) -> None:
    server, pid = await _authed_server(repository, [], "cap-empty-fetch")

    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
        )


# --- (f) access masks and capability remain independent gates ---


async def test_capability_gate_blocks_without_call_even_when_masks_allow(
    repository: SQLiteRepository,
) -> None:
    search_only = _CapabilityStub("searchonly", search=True, fetch=False)
    server, pid = await _authed_server(repository, [search_only], "cap-gate")

    with pytest.raises(ToolError):
        await server.call_tool(
            "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
        )

    assert search_only.calls == []


async def test_mask_gate_blocks_without_call_even_when_capability_allows(
    tmp_path: Path,
) -> None:
    from freesearch.persistence.storage import SQLiteRepository

    repository = await SQLiteRepository.open(tmp_path / "capability-mask.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
        )
        stub = _CapabilityStub("exa", search=True, fetch=True)
        server, pid = await _authed_server(repository, [stub], "cap-mask")

        with pytest.raises(ToolError, match="no eligible provider"):
            await server.call_tool("search", {"request": {"project_id": pid, "query": "mask off"}})

        assert stub.calls == []
    finally:
        await repository.close()


async def test_unsupported_brave_fetch_never_calls_adapter(tmp_path: Path) -> None:
    from freesearch.persistence.storage import SQLiteRepository

    repository = await SQLiteRepository.open(tmp_path / "brave-fetch.db")
    try:
        stub = _CapabilityStub("brave", search=True, fetch=False)
        server, pid = await _authed_server(repository, [stub], "cap-brave-fetch")

        with pytest.raises(ToolError):
            await server.call_tool(
                "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
            )

        assert stub.calls == []
    finally:
        await repository.close()
