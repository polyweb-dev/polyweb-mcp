"""Step definitions for You.com BDD live scenarios."""

from decimal import Decimal
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.models.contracts import FetchRequest, QuotaSource, SearchRequest


@given("a configured and authenticated You.com adapter")
def step_given_youcom_adapter(context: Any) -> None:
    """Verify that the You.com adapter was initialized for this scenario."""
    assert context.youcom_adapter is not None, (
        "You.com adapter was not initialized; FREESEARCH_YOU_API_KEY must be configured."
    )


@when('I perform a live You.com search for "{query}" with limit {limit:d}')
def step_when_youcom_live_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the You.com adapter."""
    request = SearchRequest(query=query, limit=limit)
    context.youcom_query = query
    context.search_response = context.loop.run_until_complete(
        context.youcom_adapter.search(request)
    )


@then("the You.com search response should contain results")
def step_then_youcom_search_contains_results(context: Any) -> None:
    """Verify that search results are returned and structured properly."""
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == "you", (
        f"Expected provider 'you', got '{context.search_response.provider}'"
    )
    assert context.search_response.query == context.youcom_query, (
        f"Expected query '{context.youcom_query}', got '{context.search_response.query}'"
    )
    assert len(context.search_response.results) > 0, "No search results returned from You.com"
    assert context.search_response.total_results == len(context.search_response.results)


@then("each You.com search result should have a valid title, url, and snippet")
def step_then_youcom_search_results_valid(context: Any) -> None:
    """Verify each result item has populated fields."""
    for idx, result in enumerate(context.search_response.results):
        assert result.title, f"Result #{idx} has empty title"
        assert result.url, f"Result #{idx} has empty url"
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )
        assert result.snippet, f"Result #{idx} has empty snippet"


@when('I perform a live You.com fetch for "{url}" with max {max_chars:d} chars')
def step_when_youcom_live_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a live content extraction request through the You.com adapter."""
    request = FetchRequest(url=HttpUrl(url), max_chars=max_chars)
    context.fetch_url = url
    context.fetch_response = context.loop.run_until_complete(context.youcom_adapter.fetch(request))


@then("the You.com fetch response should contain the target document")
def step_then_youcom_fetch_contains_document(context: Any) -> None:
    """Verify the fetch response contains the extracted document."""
    assert context.fetch_response is not None, "Fetch response is None"
    assert context.fetch_response.provider == "you", (
        f"Expected provider 'you', got '{context.fetch_response.provider}'"
    )
    assert context.fetch_response.document is not None, "Document missing from fetch response"
    # Pydantic normalizes a bare origin to a trailing slash (``example.com`` ->
    # ``example.com/``); comparing the normalized forms asserts equivalence
    # while accepting that normalization on both sides.
    assert str(context.fetch_response.document.url) == str(HttpUrl(context.fetch_url)), (
        f"Expected document URL '{context.fetch_url}', got '{context.fetch_response.document.url}'"
    )


@then("the You.com document content should be non-empty")
def step_then_youcom_document_content_non_empty(context: Any) -> None:
    """Verify the extracted content is markdown/text and non-empty."""
    content = context.fetch_response.document.content
    assert isinstance(content, str) and len(content.strip()) > 0, (
        "Extracted document content is empty"
    )


@when("I query the live You.com quota")
def step_when_youcom_live_quota(context: Any) -> None:
    """Query the live You.com quota through the adapter."""
    context.quota_snapshot = context.loop.run_until_complete(context.youcom_adapter.quota())


@then("the You.com quota snapshot should be an estimate")
def step_then_youcom_quota_estimated(context: Any) -> None:
    """Verify quota is an explicit estimate derived from the USD balance."""
    snapshot = context.quota_snapshot
    assert snapshot is not None, "You.com quota snapshot is None"
    assert snapshot.provider == "you", f"Expected provider 'you', got '{snapshot.provider}'"
    assert snapshot.source == QuotaSource.ESTIMATED, (
        f"Expected ESTIMATED source, got {snapshot.source}"
    )


@then("the You.com quota remaining should be a non-negative number")
def step_then_youcom_quota_remaining_non_negative(context: Any) -> None:
    """Verify remaining balance-derived search-call equivalents are non-negative."""
    snapshot = context.quota_snapshot
    assert snapshot.remaining is not None, "Remaining quota is None"
    assert snapshot.remaining >= Decimal(0), (
        f"Remaining quota must be non-negative, got {snapshot.remaining}"
    )


@then("the You.com quota should expose no limit or reset")
def step_then_youcom_quota_no_limit_reset(context: Any) -> None:
    """Verify no vendor-authoritative limit or reset schedule is claimed."""
    snapshot = context.quota_snapshot
    assert snapshot.limit is None, f"Expected limit None, got {snapshot.limit}"
    assert snapshot.reset_at is None, f"Expected reset_at None, got {snapshot.reset_at}"
