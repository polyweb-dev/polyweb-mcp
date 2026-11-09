"""Step definitions for live Tinyfish BDD scenarios.

Step phrases say "live Tinyfish" so they never collide with the offline
Tinyfish steps in ``features/steps/tinyfish_steps.py``.
"""

from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from polyweb.models.contracts import FetchRequest, SearchRequest

_TINYFISH_PROVIDER = "tinyfish"


@given("a live Tinyfish adapter with a harness key")
def step_given_live_tinyfish(context: Any) -> None:
    """Verify the hooks built the Tinyfish adapter from the harness env key."""
    assert getattr(context, "has_tinyfish_key", False), (
        "POLYWEB_TINYFISH_API_KEY is not configured in the harness env."
    )
    assert context.adapter is not None, "Tinyfish adapter was not initialized."
    assert getattr(context.adapter, "name", None) == _TINYFISH_PROVIDER, (
        f"Expected TinyfishAdapter, got '{getattr(context.adapter, 'name', None)}'"
    )


@when('a live Tinyfish search runs for "{query}" with limit {limit:d}')
def step_when_live_tinyfish_search(context: Any, query: str, limit: int) -> None:
    """Execute one live search request through the Tinyfish adapter."""
    request = SearchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", query=query, limit=limit
    )
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then("the live Tinyfish search response should be provider tinyfish")
def step_then_live_tinyfish_search_provider(context: Any) -> None:
    """Verify the search response is a normalized Tinyfish response."""
    assert context.search_response is not None, "Search response is None"
    assert context.search_response.provider == _TINYFISH_PROVIDER, (
        f"Expected provider '{_TINYFISH_PROVIDER}', got '{context.search_response.provider}'"
    )


@then("each live Tinyfish result should have a valid URL")
def step_then_live_tinyfish_results_valid_url(context: Any) -> None:
    """Verify at least one result exists and every result URL is http(s)."""
    results = context.search_response.results
    assert len(results) >= 1, "No search results returned from Tinyfish"
    for idx, result in enumerate(results):
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )


@then("the live Tinyfish search total should cover the result count")
def step_then_live_tinyfish_total(context: Any) -> None:
    """Verify the vendor total (passed through by the adapter) covers the page."""
    response = context.search_response
    assert response.total_results >= len(response.results), (
        f"Total {response.total_results} is below {len(response.results)} results"
    )


@when('a live Tinyfish fetch runs for "{url}" with max {max_chars:d} chars')
def step_when_live_tinyfish_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute one live fetch request through the Tinyfish adapter."""
    request = FetchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa", url=HttpUrl(url), max_chars=max_chars
    )
    context.fetch_response = context.loop.run_until_complete(context.adapter.fetch(request))


@then("the live Tinyfish fetch response should contain non-empty content")
def step_then_live_tinyfish_fetch_non_empty(context: Any) -> None:
    """Verify the fetch response is a Tinyfish response with non-empty content."""
    response = context.fetch_response
    assert response is not None, "Fetch response is None"
    assert response.provider == _TINYFISH_PROVIDER, (
        f"Expected provider '{_TINYFISH_PROVIDER}', got '{response.provider}'"
    )
    content = response.document.content
    assert isinstance(content, str) and content.strip(), "Extracted Tinyfish content is empty"


@then("the live Tinyfish content should be at most {max_chars:d} chars")
def step_then_live_tinyfish_fetch_bounded(context: Any, max_chars: int) -> None:
    """Verify the extracted content does not exceed the requested bound."""
    content = context.fetch_response.document.content
    assert len(content) <= max_chars, (
        f"Tinyfish content length {len(content)} exceeds {max_chars} chars"
    )
