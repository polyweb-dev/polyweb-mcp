"""Step definitions for Parallel BDD live scenarios."""

from decimal import Decimal
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.models.contracts import FetchRequest, SearchRequest, UsageEvent


def _assert_usage_event(usage: UsageEvent | None) -> None:
    """Verify an observed, non-negative usage event with a nonempty request id."""
    assert usage is not None, "Response missing usage telemetry"
    assert usage.provider == "parallel"
    assert usage.units is not None and usage.units >= Decimal(0), (
        f"Expected non-negative usage units, got {usage.units}"
    )
    assert usage.request_id, "Usage event missing non-empty request id"


@given("a configured Parallel adapter")
def step_given_parallel_adapter(context: Any) -> None:
    """Verify that a Parallel API key is resolved and the adapter is ready."""
    assert context.has_parallel_key, (
        "FREESEARCH_PARALLEL_API_KEY is not configured in .env or environment. "
        "Please provide a valid Parallel API key to run live BDD tests."
    )
    assert context.adapter is not None, "Parallel adapter was not initialized."


@when('I perform a live Parallel search for "{query}" with limit {limit:d}')
def step_when_parallel_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the Parallel adapter."""
    request = SearchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", query=query, limit=limit
    )
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then("the Parallel search response should contain structured results")
def step_then_parallel_search_results(context: Any) -> None:
    """Verify that search results are returned and structured properly."""
    response = context.search_response
    assert response is not None, "Search response is None"
    assert response.provider == "parallel", (
        f"Expected provider 'parallel', got '{response.provider}'"
    )
    assert len(response.results) > 0, "No search results returned from Parallel"
    for result in response.results:
        assert result.title, "Result has empty title"
        assert result.url, "Result has empty url"
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result url is invalid: {result.url}"
        )
        assert result.snippet, "Result has empty snippet"


@then("the Parallel search response should report a non-negative usage event with a request id")
def step_then_parallel_search_usage(context: Any) -> None:
    """Verify that search reports an observed usage event."""
    _assert_usage_event(context.search_response.usage)


@when('I perform a live Parallel fetch for "{url}" with max {max_chars:d} chars')
def step_when_parallel_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a live content extraction request through the Parallel adapter."""
    request = FetchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", url=HttpUrl(url), max_chars=max_chars
    )
    context.fetch_url = str(request.url)
    context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))


@then("the Parallel fetch response should contain the target document")
def step_then_parallel_fetch_document(context: Any) -> None:
    """Verify the fetch response targets the requested URL."""
    response = context.fetch_response
    assert response is not None, "Fetch response is None"
    assert response.provider == "parallel", (
        f"Expected provider 'parallel', got '{response.provider}'"
    )
    assert response.document is not None, "Document missing from fetch response"
    assert str(response.document.url) == context.fetch_url, (
        f"Document url '{response.document.url}' does not match target '{context.fetch_url}'"
    )


@then("the document content should be non-empty and obey the max char limit")
def step_then_parallel_fetch_content(context: Any) -> None:
    """Verify extracted content is non-empty and respects max_chars."""
    content = context.fetch_response.document.content
    assert isinstance(content, str) and len(content.strip()) > 0, (
        "Extracted document content is empty"
    )
    assert len(content) <= 1000, f"Content exceeds max 1000 chars: {len(content)}"


@then("the Parallel fetch response should report a non-negative usage event with a request id")
def step_then_parallel_fetch_usage(context: Any) -> None:
    """Verify that fetch reports an observed usage event."""
    _assert_usage_event(context.fetch_response.usage)
