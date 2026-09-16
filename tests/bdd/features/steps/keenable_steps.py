"""Step definitions for Keenable BDD live scenarios."""

import os
from decimal import Decimal
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest, UsageOperation


@given("the Keenable adapter is ready for keyless search")
def step_given_keenable_adapter(context: Any) -> None:
    """Verify the Keenable adapter was selected by the environment hooks."""
    assert context.adapter is not None, "Keenable adapter was not initialized."
    assert context.adapter.name == "keenable", (
        f"Expected Keenable adapter, got '{context.adapter.name}'"
    )
    assert os.environ.get(PROVIDER_ENV_VARS[ProviderName.KEENABLE]) is None, (
        "Keyless live scenario requires FREESEARCH_KEENABLE_API_KEY to be absent."
    )


@when('I perform a live Keenable search for "{query}" with limit {limit:d}')
def step_when_live_keenable_search(context: Any, query: str, limit: int) -> None:
    """Execute a single low-cost search request through the Keenable adapter."""

    async def capture(request: Any) -> None:
        context.live_request = request

    context.http_client.event_hooks["request"].append(capture)
    request = SearchRequest(query=query, limit=limit)
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then('the Keenable search response should use provider "{provider}"')
def step_then_keenable_provider(context: Any, provider: str) -> None:
    """Verify the response originates from the Keenable provider."""
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == provider, (
        f"Expected provider '{provider}', got '{context.search_response.provider}'"
    )


@then("the Keenable search response should contain at least one valid result")
def step_then_keenable_has_valid_result(context: Any) -> None:
    """Verify at least one result with a nonempty title, http URL, and snippet."""
    results = context.search_response.results
    assert len(results) >= 1, "No search results returned from Keenable"
    for idx, result in enumerate(results):
        assert result.title, f"Result #{idx} has empty title"
        assert result.url, f"Result #{idx} has empty url"
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )
        assert result.snippet, f"Result #{idx} has empty snippet"


@then("the Keenable search response should report correct total count")
def step_then_keenable_total_count(context: Any) -> None:
    """Verify the reported total count matches the returned result count."""
    response = context.search_response
    assert response.total_results == len(response.results), (
        f"total_results={response.total_results} != len(results)={len(response.results)}"
    )


@then("the Keenable search response should report one request unit")
def step_then_keenable_zero_usage(context: Any) -> None:
    """Verify one hourly-limit request unit (the public tier is dollar-free)."""
    usage = context.search_response.usage
    assert usage is not None, "Search response missing usage telemetry"
    assert usage.provider == "keenable", (
        f"Expected usage provider 'keenable', got '{usage.provider}'"
    )
    assert usage.operation is UsageOperation.SEARCH, (
        f"Expected SEARCH operation, got {usage.operation}"
    )
    assert usage.units == Decimal("1"), f"Expected one request unit, got {usage.units}"
    assert str(usage.unit_kind).upper().endswith("REQUEST"), (
        f"Expected REQUEST usage kind, got {usage.unit_kind}"
    )


@then("the live Keenable request should use the keyless public endpoint")
def step_then_keenable_public_request(context: Any) -> None:
    """Verify the live wire request used Keenable's unauthenticated endpoint."""
    request = context.live_request
    assert request.url.path == "/v1/search/public"
    assert request.headers["X-Keenable-Title"] == "freesearch"
    assert "X-API-Key" not in request.headers
    assert "Authorization" not in request.headers


@given("the Keenable adapter is ready for keyed search")
def step_given_keenable_keyed_adapter(context: Any) -> None:
    """Verify the Keenable adapter is configured with an API key for keyed use."""
    assert context.adapter is not None, "Keenable adapter was not initialized."
    assert context.adapter.name == "keenable", (
        f"Expected Keenable adapter, got '{context.adapter.name}'"
    )
    assert os.environ.get(PROVIDER_ENV_VARS[ProviderName.KEENABLE]) is not None, (
        "Keyed live scenario requires FREESEARCH_KEENABLE_API_KEY to be configured."
    )


@when('I perform a live Keenable fetch for "{url}" with max {max_chars:d} chars')
def step_when_live_keenable_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a single low-cost fetch request through the Keenable adapter."""

    async def capture(request: Any) -> None:
        context.live_fetch_request = request

    context.http_client.event_hooks["request"].append(capture)
    request = FetchRequest(url=HttpUrl(url), max_chars=max_chars)
    context.fetch_url = str(request.url)
    context.fetch_max_chars = max_chars
    context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))


@then("the Keenable fetch response should contain non-empty content within {limit:d} chars")
def step_then_keenable_fetch_content(context: Any, limit: int) -> None:
    """Verify fetched content is non-empty and respects the max char bound."""
    response = getattr(context, "fetch_response", None)
    assert response is not None, "Fetch response is None"
    assert response.provider == "keenable", (
        f"Expected provider 'keenable', got '{response.provider}'"
    )
    assert response.document is not None, "Document missing from fetch response"
    content = response.document.content
    assert isinstance(content, str) and len(content.strip()) > 0, (
        "Extracted document content is empty"
    )
    assert len(content) <= limit, f"Content exceeds max {limit} chars: {len(content)}"
    assert len(content) <= context.fetch_max_chars, (
        f"Content exceeds requested max {context.fetch_max_chars} chars: {len(content)}"
    )


@then("the Keenable fetch response should report one request unit")
def step_then_keenable_fetch_zero_usage(context: Any) -> None:
    """Verify one hourly-limit request unit for a keyless fetch."""
    usage = context.fetch_response.usage
    assert usage is not None, "Fetch response missing usage telemetry"
    assert usage.provider == "keenable", (
        f"Expected usage provider 'keenable', got '{usage.provider}'"
    )
    assert usage.operation is UsageOperation.FETCH, (
        f"Expected FETCH operation, got {usage.operation}"
    )
    assert usage.units == Decimal("1"), f"Expected one request unit, got {usage.units}"
    assert str(usage.unit_kind).upper().endswith("REQUEST"), (
        f"Expected REQUEST usage kind, got {usage.unit_kind}"
    )


@then("the live Keenable fetch should use the keyless public endpoint")
def step_then_keenable_fetch_public_request(context: Any) -> None:
    """Verify the live fetch wire request used Keenable's unauthenticated endpoint."""
    request = context.live_fetch_request
    assert request.url.path == "/v1/fetch/public"
    assert request.headers["X-Keenable-Title"] == "freesearch"
    assert "X-API-Key" not in request.headers
    assert "Authorization" not in request.headers
