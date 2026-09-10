"""Step definitions for Brave BDD live scenarios.

Step text is Brave-specific to avoid collisions with the Tavily suite. No
secrets are asserted or logged; the ``given`` step only reports whether the
FREESEARCH_BRAVE_SEARCH_API_KEY is resolvable.
"""

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from pydantic import HttpUrl

from freesearch.contracts import FetchRequest, SearchRequest, UsageOperation, UsageStatus
from freesearch.monitoring import tracked_call
from freesearch.resilience import ProviderOperationError
from freesearch.storage import SQLiteRepository


@given("a configured Brave search adapter")
def step_given_brave_adapter(context: Any) -> None:
    """Verify that a Brave API key is resolved and the adapter is ready."""
    assert getattr(context, "has_brave_key", False), (
        "FREESEARCH_BRAVE_SEARCH_API_KEY is not configured in .env or environment. "
        "Please provide a valid Brave Search API key to run live Brave BDD tests."
    )
    assert context.adapter is not None, "Brave adapter was not initialized."


@when('I perform a live Brave search for "{query}" with limit {limit:d}')
def step_when_live_brave_search(context: Any, query: str, limit: int) -> None:
    """Execute a live search request through the Brave adapter."""
    request = SearchRequest(query=query, limit=limit)
    context.search_limit = limit
    context.search_response = context.loop.run_until_complete(context.adapter.search(request))


@then("the Brave search response should contain normalized results")
def step_then_brave_search_contains_results(context: Any) -> None:
    """Verify Brave results are normalized and bounded by the requested limit."""
    response = context.search_response
    assert response is not None, "Search response is None"
    assert response.provider == "brave", f"Expected provider 'brave', got '{response.provider}'"
    results = response.results
    limit = getattr(context, "search_limit", 3)
    assert 1 <= len(results) <= limit, f"Expected 1..{limit} Brave results, got {len(results)}"
    assert response.total_results == len(results), (
        f"total_results {response.total_results} != len(results) {len(results)}"
    )


@then("each Brave result should have a non-empty title, snippet, and http(s) URL")
def step_then_brave_results_valid(context: Any) -> None:
    """Verify each Brave result has a non-empty title and snippet plus http(s) URL."""
    for idx, result in enumerate(context.search_response.results):
        assert result.title, f"Result #{idx} has empty title"
        assert result.snippet, f"Result #{idx} has empty snippet"
        assert str(result.url).startswith(("http://", "https://")), (
            f"Result #{idx} url is invalid: {result.url}"
        )


@then("the Brave usage event should show one search unit")
def step_then_brave_reports_one_search_unit(context: Any) -> None:
    """Verify Brave reports exactly one search unit with optional rate-limit info.

    Brave does not promise a rate-limit header in every environment, so
    ``rate_limit_remaining`` is optional; when present it must be a
    non-negative int. No other usage/quota fields are asserted.
    """
    usage = context.search_response.usage
    assert usage is not None, "Search response missing usage telemetry"
    assert usage.provider == "brave", f"Expected usage.provider 'brave', got '{usage.provider}'"
    assert usage.operation == UsageOperation.SEARCH, (
        f"Expected usage.operation 'search', got '{usage.operation}'"
    )
    assert usage.units == Decimal("1"), f"Expected exactly one search unit, got {usage.units}"
    remaining = usage.metadata.get("rate_limit_remaining")
    if remaining is not None:
        assert type(remaining) is int and remaining >= 0, (
            f"rate_limit_remaining must be an int >= 0, got {remaining!r}"
        )


@when("I check the Brave adapter capabilities and search cost estimate")
def step_when_brave_capabilities(context: Any) -> None:
    """Query the adapter capabilities and search cost estimate (no network)."""
    context.brave_capabilities = context.adapter.capabilities
    context.brave_cost_estimate = context.loop.run_until_complete(
        context.adapter.estimate_cost(SearchRequest(query="cost check", limit=1))
    )


@then("the Brave capabilities should report search and cost estimation without fetch")
def step_then_brave_capabilities(context: Any) -> None:
    """Verify Brave supports search and cost estimation but not fetch."""
    capabilities = context.brave_capabilities
    assert capabilities is not None, "Capabilities were not captured"
    assert capabilities.search is True, "Brave must support search"
    assert capabilities.fetch is False, "Brave must not support fetch"
    assert capabilities.cost_estimate is True, "Brave must support cost estimation"


@then("the Brave search cost estimate should be one unit in query currency")
def step_then_brave_cost_estimate(context: Any) -> None:
    """Verify the SearchRequest cost estimate is exactly one query."""
    estimate = context.brave_cost_estimate
    assert estimate is not None, "Cost estimate was not captured"
    assert estimate.provider == "brave", (
        f"Expected estimate.provider 'brave', got '{estimate.provider}'"
    )
    assert estimate.operation == UsageOperation.SEARCH, (
        f"Expected estimate.operation 'search', got '{estimate.operation}'"
    )
    assert estimate.units == Decimal("1"), f"Expected exactly one unit, got {estimate.units}"
    assert estimate.currency == "queries", f"Expected currency 'queries', got '{estimate.currency}'"


@when('I attempt a live Brave fetch for "{url}" with max {max_chars:d} chars')
def step_when_live_brave_fetch(context: Any, url: str, max_chars: int) -> None:
    """Attempt a Brave fetch that must fail as unsupported, recording telemetry."""
    if getattr(context, "repository", None) is None:
        context.temp_directory = tempfile.TemporaryDirectory(prefix="brave-fetch-bdd-")
        db_path = Path(context.temp_directory.name) / "brave-fetch-test.db"
        context.database_path = str(db_path)
        context.repository = context.loop.run_until_complete(SQLiteRepository.open(db_path))
    request = FetchRequest(url=HttpUrl(url), max_chars=max_chars)
    context.fetch_url = str(request.url)
    context.fetch_response = None
    context.fetch_error = None
    try:
        context.loop.run_until_complete(
            tracked_call(
                context.repository,
                context.adapter,
                lambda adapter: adapter.fetch(request),
                operation=UsageOperation.FETCH,
            )
        )
    except ProviderOperationError as exc:
        context.fetch_error = exc
    except Exception as exc:  # pragma: no cover - typed error expected
        context.fetch_error = exc


@then("the Brave fetch should raise unsupported_operation")
def step_then_brave_fetch_unsupported(context: Any) -> None:
    """Verify the fetch attempt raised the unsupported operation error."""
    error = getattr(context, "fetch_error", None)
    assert error is not None, "Expected Brave fetch to raise, but it succeeded"
    code = getattr(getattr(error, "error", None), "code", None)
    assert code == "unsupported_operation", (
        f"Expected Brave fetch error code 'unsupported_operation', got {code!r}"
    )


@then("no Brave quota snapshot should be recorded")
def step_then_brave_no_quota(context: Any) -> None:
    """Verify the unsupported fetch left no quota snapshot behind."""
    latest = context.loop.run_until_complete(context.repository.latest_quota("brave"))
    assert latest is None, (
        f"Expected no Brave quota snapshot after unsupported fetch, saw {latest!r}"
    )


@then("the zero-unit Brave FAILURE should be excluded from usage totals")
def step_then_brave_failure_excluded(context: Any) -> None:
    """Verify the zero-unit failure row exists for observability but not totals."""
    events = context.loop.run_until_complete(context.repository.list_usage(provider="brave"))
    failures = [
        event
        for event in events
        if event.status == UsageStatus.FAILURE and event.units == Decimal("0")
    ]
    assert len(failures) >= 1, (
        f"Expected at least one zero-unit Brave FAILURE event for observability, saw {events!r}"
    )
    totals = context.loop.run_until_complete(context.repository.usage_totals())
    brave_fetch = [
        total
        for total in totals
        if total.provider == "brave" and total.operation == UsageOperation.FETCH
    ]
    assert brave_fetch == [], (
        f"Zero-unit Brave FAILURE rows must not appear in usage totals, saw {brave_fetch!r}"
    )
