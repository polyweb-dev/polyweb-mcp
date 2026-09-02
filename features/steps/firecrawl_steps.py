"""Step definitions for Firecrawl BDD live scenarios.

Step phrases are deliberately Firecrawl-specific so they never collide with
the global Tavily step phrases in ``features/steps/tavily_steps.py``.
"""

from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.contracts import FetchRequest, SearchRequest

_FIRECRAWL_PROVIDER = "firecrawl"


@given("a configured Firecrawl key resolved through the shared resolver")
def step_given_firecrawl_key(context: Any) -> None:
    """Verify the shared resolver surfaced a Firecrawl key and the right adapter.

    ``has_firecrawl_key`` is populated by ``before_all`` via the shared
    provider secret resolver; the adapter must have been tag-selected by the
    environment hooks, never the default Tavily adapter.
    """
    assert getattr(context, "has_firecrawl_key", False), (
        "FREESEARCH_FIRECRAWL_API_KEY is not configured in .env or environment. "
        "Please provide a valid Firecrawl API key to run live BDD tests."
    )
    assert context.adapter is not None, "Firecrawl adapter was not initialized."
    assert getattr(context.adapter, "name", None) == _FIRECRAWL_PROVIDER, (
        f"Expected FirecrawlAdapter, got '{getattr(context.adapter, 'name', None)}'"
    )


@when('a live Firecrawl search runs for "{query}" with limit {limit:d}')
def step_when_live_firecrawl_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the Firecrawl adapter."""
    request = SearchRequest(query=query, limit=limit)
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then("the Firecrawl search response should be provider firecrawl")
def step_then_firecrawl_search_provider(context: Any) -> None:
    """Verify the search response is a normalized Firecrawl response."""
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == _FIRECRAWL_PROVIDER, (
        f"Expected provider '{_FIRECRAWL_PROVIDER}', got '{context.search_response.provider}'"
    )


@then("each Firecrawl result should have a valid URL")
def step_then_firecrawl_results_valid_url(context: Any) -> None:
    """Verify at least one result exists and every result URL is http(s)."""
    results = context.search_response.results
    assert len(results) >= 1, "No search results returned from Firecrawl"
    for idx, result in enumerate(results):
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )


@then("the Firecrawl search total should match the result count")
def step_then_firecrawl_search_total_matches(context: Any) -> None:
    """Verify the reported total equals the number of normalized results."""
    assert context.search_response.total_results == len(context.search_response.results), (
        f"Total {context.search_response.total_results} does not match "
        f"{len(context.search_response.results)} results"
    )


@when('a live Firecrawl scrape fetches "{url}" with max {max_chars:d} chars')
def step_when_live_firecrawl_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a live content extraction request through the Firecrawl adapter."""
    request = FetchRequest(url=HttpUrl(url), max_chars=max_chars)
    context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))


@then("the Firecrawl fetch response should contain non-empty markdown")
def step_then_firecrawl_fetch_non_empty(context: Any) -> None:
    """Verify the fetch response is a Firecrawl response with non-empty markdown."""
    assert context.fetch_response is not None, "Fetch response is None"
    assert context.fetch_response.provider == _FIRECRAWL_PROVIDER, (
        f"Expected provider '{_FIRECRAWL_PROVIDER}', got '{context.fetch_response.provider}'"
    )
    content = context.fetch_response.document.content
    assert isinstance(content, str) and len(content.strip()) > 0, (
        "Extracted Firecrawl markdown content is empty"
    )


@then("the Firecrawl markdown content should be at most {max_chars:d} chars")
def step_then_firecrawl_fetch_bounded(context: Any, max_chars: int) -> None:
    """Verify the extracted markdown does not exceed the requested bound."""
    content = context.fetch_response.document.content
    assert len(content) <= max_chars, (
        f"Firecrawl markdown length {len(content)} exceeds {max_chars} chars"
    )
