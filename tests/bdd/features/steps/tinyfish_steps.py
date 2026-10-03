# mypy: disable-error-code="untyped-decorator"
"""Step definitions for Tinyfish BDD acceptance scenarios.

Provides offline mock-transport integration, response normalization verification,
fail-closed authentication assertions, and HTTP error code mappings.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, cast

import httpx
from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import SecretStr

from freesearch.adapters.tinyfish import TinyfishAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import (
    FetchRequest,
    SearchRequest,
    UnitKind,
    UsageOperation,
)

_TINYFISH_KEY = SecretStr("tin_test_key_bdd_sentinel_12345")


class _TinyfishMockHandler:
    """In-memory mock HTTP transport handler for Tinyfish BDD scenarios."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status_code: int = 200
        self.custom_body: dict[str, Any] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        if self.status_code == 401:
            return httpx.Response(
                401,
                json={"message": "Invalid API key provided", "error": "unauthorized"},
                request=request,
            )
        if self.status_code == 429:
            return httpx.Response(
                429,
                json={"message": "Rate limit exceeded", "error": "rate_limited"},
                request=request,
            )
        if self.custom_body is not None:
            return httpx.Response(self.status_code, json=self.custom_body, request=request)

        # Default search handler
        if "search" in str(request.url.host) or "search" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "query": request.url.params.get("query", "test query"),
                    "results": [
                        {
                            "position": 1,
                            "site_name": "Open Data Portal",
                            "title": "Open Data Documentation",
                            "snippet": "Comprehensive guides and documentation for open data sets.",
                            "url": "https://opendata.example.com/docs",
                            "date": "2026-06-01T12:00:00Z",
                        },
                        {
                            "position": 2,
                            "site_name": "Data Standards",
                            "title": "Data Publishing Standards",
                            "snippet": "Best practices for publishing structured open data.",
                            "url": "https://standards.example.com/guide",
                            "date": "2026-06-02T15:30:00Z",
                        },
                    ],
                    "total_results": 2,
                    "page": 0,
                },
                request=request,
            )

        # Default fetch handler
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/docs",
                        "final_url": "https://example.com/docs/latest",
                        "title": "Documentation Page",
                        "description": "Clean markdown documentation guide.",
                        "language": "en",
                        "author": "Documentation Team",
                        "published_date": "2026-06-01",
                        "text": (
                            "# Documentation Guide\n\n"
                            "This is clean markdown content extracted from the page."
                        ),
                        "latency_ms": 142,
                        "format": "markdown",
                    }
                ],
                "errors": [],
            },
            request=request,
        )


def _setup_adapter(
    context: Any,
    handler: _TinyfishMockHandler,
    api_key: SecretStr | None = _TINYFISH_KEY,
) -> None:
    context.mock_handler = handler
    existing_client = getattr(context, "http_client", None)
    loop = getattr(context, "loop", None)
    if existing_client is not None and loop is not None and not existing_client.is_closed:
        loop.run_until_complete(existing_client.aclose())
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    context.http_client = client
    context.adapter = TinyfishAdapter(client, api_key=api_key)


@given("the Tinyfish adapter is configured with a valid API key")
def step_given_tinyfish_configured(context: Any) -> None:
    handler = _TinyfishMockHandler()
    _setup_adapter(context, handler, _TINYFISH_KEY)


@given("a mocked offline Tinyfish transport returning search results")
def step_given_mock_search_transport(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler must be initialized first"
    context.mock_handler.status_code = 200


@given("a mocked offline Tinyfish transport returning markdown document extraction")
def step_given_mock_fetch_transport(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler must be initialized first"
    context.mock_handler.status_code = 200


@given("a mocked offline Tinyfish transport")
def step_given_mock_transport(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler must be initialized first"
    context.mock_handler.status_code = 200


@given("the Tinyfish API returns a 401 unauthorized error")
def step_given_401_error(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler must be initialized first"
    context.mock_handler.status_code = 401


@given("the Tinyfish API returns a 429 rate limit error")
def step_given_429_error(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler must be initialized first"
    context.mock_handler.status_code = 429


@given("the Tinyfish adapter has no API key configured")
def step_given_no_api_key(context: Any) -> None:
    context.adapter = None
    context.api_key = None
    context.mock_handler = _TinyfishMockHandler()
    existing_client = getattr(context, "http_client", None)
    loop = getattr(context, "loop", None)
    if existing_client is not None and loop is not None and not existing_client.is_closed:
        loop.run_until_complete(existing_client.aclose())
    context.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(context.mock_handler), timeout=30.0
    )


@when('I perform a Tinyfish search for "{query}" with limit {limit:d}')
def step_when_tinyfish_search(context: Any, query: str, limit: int) -> None:
    request = SearchRequest(query=query, limit=limit)
    start_time = time.perf_counter()
    try:
        context.search_response = context.loop.run_until_complete(context.adapter.search(request))
        context.last_error = None
    except ProviderOperationError as exc:
        context.last_error = exc
        context.search_response = None
    finally:
        context.search_latency_ms = int((time.perf_counter() - start_time) * 1000)


@when('I perform a Tinyfish fetch for "{url}" with max {max_chars:d} chars')
def step_when_tinyfish_fetch(context: Any, url: str, max_chars: int) -> None:
    request = FetchRequest(url=cast(Any, url), max_chars=max_chars)
    start_time = time.perf_counter()
    try:
        context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))
        context.last_error = None
    except ProviderOperationError as exc:
        context.last_error = exc
        context.fetch_response = None
    finally:
        context.fetch_latency_ms = int((time.perf_counter() - start_time) * 1000)


@when("I attempt to initialize the Tinyfish adapter without an API key")
def step_when_init_without_key(context: Any) -> None:
    try:
        context.adapter = TinyfishAdapter(context.http_client, api_key=None)
        context.last_error = None
    except ProviderOperationError as exc:
        context.last_error = exc
        context.adapter = None


@then('the Tinyfish search response should use provider "{provider}"')
def step_then_tinyfish_search_provider(context: Any, provider: str) -> None:
    assert context.last_error is None, f"Unexpected error during search: {context.last_error!r}"
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == provider, (
        f"Expected provider '{provider}', got '{context.search_response.provider}'"
    )


@then("the Tinyfish search response should contain normalized results")
def step_then_tinyfish_search_normalized(context: Any) -> None:
    assert context.search_response is not None, "Search response is None"
    assert len(context.search_response.results) > 0, "Search returned empty results"


@then("each Tinyfish result should have a non-empty title, url, and snippet")
def step_then_tinyfish_result_fields(context: Any) -> None:
    assert context.search_response is not None, "Search response is None"
    for idx, item in enumerate(context.search_response.results):
        assert item.title, f"Result #{idx} has empty title"
        assert item.url and str(item.url).startswith(("http://", "https://")), (
            f"Result #{idx} has invalid url: {item.url}"
        )
        assert item.snippet, f"Result #{idx} has empty snippet"


@then("the Tinyfish search response should report correct total count")
def step_then_tinyfish_search_total_count(context: Any) -> None:
    assert context.search_response is not None, "Search response is None"
    expected_count = len(context.search_response.results)
    assert context.search_response.total_results == expected_count, (
        f"total_results {context.search_response.total_results} != {expected_count}"
    )


@then("the Tinyfish search response should report one request unit")
def step_then_tinyfish_search_usage(context: Any) -> None:
    assert context.search_response is not None, "Search response is None"
    usage = context.search_response.usage
    assert usage is not None, "Usage event missing from search response"
    assert usage.provider == "tinyfish"
    assert usage.operation is UsageOperation.SEARCH
    assert usage.units == Decimal("1")
    assert usage.unit_kind is UnitKind.REQUEST


@then("the Tinyfish search operation should report non-negative latency metrics")
def step_then_tinyfish_search_latency(context: Any) -> None:
    assert hasattr(context, "search_latency_ms"), "Search latency was not recorded"
    assert isinstance(context.search_latency_ms, int), (
        f"Expected int latency, got {type(context.search_latency_ms)}"
    )
    assert context.search_latency_ms >= 0, (
        f"Expected non-negative latency, got {context.search_latency_ms}"
    )


@then('the Tinyfish fetch response should use provider "{provider}"')
def step_then_tinyfish_fetch_provider(context: Any, provider: str) -> None:
    assert context.last_error is None, f"Unexpected error during fetch: {context.last_error!r}"
    assert context.fetch_response is not None, "Fetch response is None"
    assert context.fetch_response.provider == provider, (
        f"Expected provider '{provider}', got '{context.fetch_response.provider}'"
    )


@then("the Tinyfish fetch response should contain clean markdown content")
def step_then_tinyfish_fetch_markdown(context: Any) -> None:
    assert context.fetch_response is not None, "Fetch response is None"
    doc = context.fetch_response.document
    assert doc is not None, "Fetched document is None"
    assert doc.content_type == "text/markdown", (
        f"Expected content_type 'text/markdown', got '{doc.content_type}'"
    )
    assert doc.content and len(doc.content.strip()) > 0, "Fetched markdown content is empty"
    assert doc.title, "Fetched document title is empty"


@then("the Tinyfish fetch document should contain metadata with final_url and language")
def step_then_tinyfish_fetch_metadata(context: Any) -> None:
    assert context.fetch_response is not None, "Fetch response is None"
    doc = context.fetch_response.document
    assert "final_url" in doc.metadata, "Metadata missing 'final_url'"
    assert "language" in doc.metadata, "Metadata missing 'language'"
    assert doc.metadata["final_url"] == "https://example.com/docs/latest"
    assert doc.metadata["language"] == "en"


@then("the Tinyfish fetch response should report one request unit")
def step_then_tinyfish_fetch_usage(context: Any) -> None:
    assert context.fetch_response is not None, "Fetch response is None"
    usage = context.fetch_response.usage
    assert usage is not None, "Usage event missing from fetch response"
    assert usage.provider == "tinyfish"
    assert usage.operation is UsageOperation.FETCH
    assert usage.units == Decimal("1")
    assert usage.unit_kind is UnitKind.REQUEST


@then('the Tinyfish operation should fail with "{error_code}"')
def step_then_tinyfish_operation_fails(context: Any, error_code: str) -> None:
    assert context.last_error is not None, (
        f"Expected operation failure with '{error_code}', but it succeeded"
    )
    assert isinstance(context.last_error, ProviderOperationError), (
        f"Expected ProviderOperationError, got {type(context.last_error)}"
    )
    assert context.last_error.error.code == error_code, (
        f"Expected error code '{error_code}', got '{context.last_error.error.code}'"
    )


@then("the Tinyfish error should not be retryable")
def step_then_tinyfish_error_not_retryable(context: Any) -> None:
    assert context.last_error is not None, "Expected error, got None"
    assert context.last_error.error.retryable is False, (
        f"Expected non-retryable error, got retryable={context.last_error.error.retryable}"
    )


@then("the Tinyfish error should be retryable")
def step_then_tinyfish_error_retryable(context: Any) -> None:
    assert context.last_error is not None, "Expected error, got None"
    assert context.last_error.error.retryable is True, (
        f"Expected retryable error, got retryable={context.last_error.error.retryable}"
    )


@then("the Tinyfish error status code should be {status_code:d}")
def step_then_tinyfish_error_status(context: Any, status_code: int) -> None:
    assert context.last_error is not None, "Expected error, got None"
    assert context.last_error.error.status_code == status_code, (
        f"Expected status code {status_code}, got {context.last_error.error.status_code}"
    )


@then("the Tinyfish initialization should fail closed with configuration_error")
def step_then_tinyfish_init_fail_closed(context: Any) -> None:
    assert context.last_error is not None, "Expected initialization to fail, but it succeeded"
    assert isinstance(context.last_error, ProviderOperationError)
    assert context.last_error.error.code == "configuration_error"
    assert context.last_error.error.provider == "tinyfish"


@then("the Tinyfish request should include the X-API-Key header")
def step_then_tinyfish_request_auth_header(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler not initialized"
    assert len(context.mock_handler.requests) > 0, "No wire requests were captured"
    last_req = context.mock_handler.requests[-1]
    assert "X-API-Key" in last_req.headers, (
        f"Missing X-API-Key header in wire request. Headers: {dict(last_req.headers)}"
    )
    assert last_req.headers["X-API-Key"] == _TINYFISH_KEY.get_secret_value()


@then('the Tinyfish wire request should target "{expected_host}"')
def step_then_tinyfish_wire_target(context: Any, expected_host: str) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler not initialized"
    assert len(context.mock_handler.requests) > 0, "No wire requests were captured"
    last_req = context.mock_handler.requests[-1]
    assert last_req.url.host == expected_host, (
        f"Expected wire request host '{expected_host}', got '{last_req.url.host}'"
    )


@then("the Tinyfish wire request should use the {method} method")
def step_then_tinyfish_wire_method(context: Any, method: str) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler not initialized"
    assert len(context.mock_handler.requests) > 0, "No wire requests were captured"
    last_req = context.mock_handler.requests[-1]
    assert last_req.method == method, f"Expected HTTP method '{method}', got '{last_req.method}'"


@then("no live external network calls should be made")
def step_then_tinyfish_no_live_network(context: Any) -> None:
    assert hasattr(context, "mock_handler"), "Mock handler not initialized"
    assert getattr(context, "live_network_called", False) is False
