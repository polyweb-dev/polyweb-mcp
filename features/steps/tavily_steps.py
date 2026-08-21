"""Step definitions for Tavily BDD live scenarios."""

from decimal import Decimal
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.contracts import FetchRequest, QuotaSource, SearchRequest


@given("a configured and authenticated Tavily adapter")
def step_given_tavily_adapter(context: Any) -> None:
    """Verify that a Tavily API key is resolved and the adapter is ready."""
    assert context.has_tavily_key, (
        "FREESEARCH_TAVILY_API_KEY is not configured in .env or environment. "
        "Please provide a valid Tavily API key to run live BDD tests."
    )
    assert context.adapter is not None, "Tavily adapter was not initialized."


@when('I perform a live search for "{query}" with limit {limit:d}')
def step_when_live_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the Tavily adapter."""
    request = SearchRequest(query=query, limit=limit)
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then("the search response should contain results")
def step_then_search_contains_results(context: Any) -> None:
    """Verify that search results are returned and structured properly."""
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == "tavily", (
        f"Expected provider 'tavily', got '{context.search_response.provider}'"
    )
    assert len(context.search_response.results) > 0, "No search results returned from Tavily"
    assert context.search_response.total_results == len(context.search_response.results)


@then("each search result should have a valid title, url, and snippet")
def step_then_search_results_valid(context: Any) -> None:
    """Verify each result item has populated fields."""
    for idx, result in enumerate(context.search_response.results):
        assert result.title, f"Result #{idx} has empty title"
        assert result.url, f"Result #{idx} has empty url"
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )
        assert result.snippet, f"Result #{idx} has empty snippet"


@then("the search response should report observed usage credits")
def step_then_search_reports_usage(context: Any) -> None:
    """Verify that search reports observed credit usage."""
    usage = context.search_response.usage
    assert usage is not None, "Search response missing usage telemetry"
    assert usage.provider == "tavily"
    assert usage.units is not None and usage.units > Decimal(0), (
        f"Expected positive usage units, got {usage.units}"
    )


@when('I perform a live fetch for "{url}" with max {max_chars:d} chars')
def step_when_live_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a live content extraction request through the Tavily adapter."""
    request = FetchRequest(url=HttpUrl(url), max_chars=max_chars)
    context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))


@then("the fetch response should contain the target document")
def step_then_fetch_contains_document(context: Any) -> None:
    """Verify the fetch response contains the extracted document."""
    assert context.fetch_response is not None, "Fetch response is None"
    assert context.fetch_response.provider == "tavily"
    assert context.fetch_response.document is not None, "Document missing from fetch response"


@then("the document content should be non-empty")
def step_then_document_content_non_empty(context: Any) -> None:
    """Verify the extracted content is markdown/text and non-empty."""
    content = context.fetch_response.document.content
    assert isinstance(content, str) and len(content.strip()) > 0, (
        "Extracted document content is empty"
    )


@then("the fetch response should report observed usage credits")
def step_then_fetch_reports_usage(context: Any) -> None:
    """Verify that fetch reports observed credit usage."""
    usage = context.fetch_response.usage
    assert usage is not None, "Fetch response missing usage telemetry"
    assert usage.provider == "tavily"
    assert usage.units is not None and usage.units >= Decimal(0), (
        f"Expected non-negative usage units, got {usage.units}"
    )


@when("I request the current Tavily quota snapshot")
def step_when_request_quota(context: Any) -> None:
    """Query live Tavily /usage endpoint for account quota details."""
    context.quota_snapshot = context.loop.run_until_complete(context.adapter.quota())


@then("the quota snapshot should be authoritative")
def step_then_quota_authoritative(context: Any) -> None:
    """Verify quota source is authoritative from vendor API."""
    snapshot = context.quota_snapshot
    assert snapshot is not None, "Quota snapshot is None"
    assert snapshot.provider == "tavily"
    assert snapshot.source == QuotaSource.AUTHORITATIVE, (
        f"Expected AUTHORITATIVE source, got {snapshot.source}"
    )


@then("the remaining credits should be a non-negative number")
def step_then_remaining_credits_non_negative(context: Any) -> None:
    """Verify remaining credits are non-negative and present."""
    snapshot = context.quota_snapshot
    assert snapshot.remaining is not None, "Remaining credits is None"
    assert snapshot.remaining >= Decimal(0), (
        f"Remaining credits must be non-negative, got {snapshot.remaining}"
    )


@then("the quota limit should be greater than zero")
def step_then_quota_limit_positive(context: Any) -> None:
    """Verify account limit is positive and log the live quota details."""
    snapshot = context.quota_snapshot
    assert snapshot.limit is not None and snapshot.limit > Decimal(0), (
        f"Expected positive quota limit, got {snapshot.limit}"
    )
