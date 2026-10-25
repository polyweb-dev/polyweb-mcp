"""Step definitions for Exa BDD live scenarios."""

from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.adapters.exa import ExaAdapter
from freesearch.models.contracts import FetchRequest, SearchRequest


@given("a configured and authenticated Exa adapter")
def step_given_exa_adapter(context: Any) -> None:
    """Verify that an Exa API key is resolved and the adapter is ready."""
    assert context.has_exa_key, "FREESEARCH_EXA_API_KEY is not configured."
    assert isinstance(context.adapter, ExaAdapter), "Exa adapter was not initialized."


@when('I perform an Exa live search for "{query}" with limit {limit:d}')
def step_when_live_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the Exa adapter."""
    context.search_response = context.loop.run_until_complete(
        context.adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query=query, limit=limit
            )
        )
    )


@then("the Exa search response should contain results")
def step_then_search_contains_results(context: Any) -> None:
    """Verify normalized search results are returned."""
    assert context.search_response.provider == "exa"
    assert context.search_response.results
    assert context.search_response.total_results == len(context.search_response.results)


@then("each Exa search result should have a valid title, url, and snippet")
def step_then_search_results_valid(context: Any) -> None:
    """Verify every result contains consumer-visible content."""
    for result in context.search_response.results:
        assert result.title
        assert str(result.url).startswith(("http://", "https://"))
        assert result.snippet


@when('I perform an Exa live fetch for "{url}" with max {max_chars:d} chars')
def step_when_live_fetch(context: Any, url: str, max_chars: int) -> None:
    """Execute a live content request through the Exa adapter."""
    context.fetch_response = context.loop.run_until_complete(
        context.adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url=HttpUrl(url),
                max_chars=max_chars,
            )
        )
    )


@then("the Exa fetch response should contain the target document")
def step_then_fetch_contains_document(context: Any) -> None:
    """Verify a normalized fetched document is returned."""
    assert context.fetch_response.provider == "exa"
    assert context.fetch_response.document is not None


@then("the Exa document content should be non-empty")
def step_then_document_content_non_empty(context: Any) -> None:
    """Verify fetched content is usable."""
    assert context.fetch_response.document.content.strip()
