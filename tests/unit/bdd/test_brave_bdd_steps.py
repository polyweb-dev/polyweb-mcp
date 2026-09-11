"""Brave BDD step-contract tests for the usage and normalized-results steps.

These tests drive the real Behave step definitions (``features.steps.brave_steps``)
with a fake Behave context.  No live network calls or API keys are used.

Contract under test (locked Brave BDD contract):
  AC-L2  ``Then the Brave usage event should show one search unit`` must accept a
         ``UsageEvent`` with provider ``brave``, operation ``search``,
         ``units == Decimal('1')`` and optional ``rate_limit_remaining``; when
         present that field must be an ``int >= 0``.  Missing usage, wrong
         provider/operation/units, or a negative/non-int rate-limit value must
         all be rejected.
  AC-L1  ``Then the Brave search response should contain normalized results`` and
         ``each Brave result should have a non-empty title, snippet, and http(s)
         URL`` must enforce the provider, result-count, total_results, and
         per-result validity contract (and guard the tagged live scenario).

The environment lifecycle tests live in ``tests/test_brave_bdd_environment.py``.
"""

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from freesearch.models.contracts import (
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features.steps import brave_steps  # noqa: E402


def _usage(
    *,
    provider: str = "brave",
    operation: UsageOperation = UsageOperation.SEARCH,
    units: str = "1",
    metadata: dict[str, object] | None = None,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=Decimal(units),
        observed_at=datetime.now(UTC),
        metadata=metadata or {},
    )


def _brave_response(
    usage: UsageEvent | None,
    *,
    count: int = 1,
    provider: str = "brave",
    total_results: int | None = None,
) -> SearchResponse:
    results = [
        SearchResult(
            title=f"Result {idx}",
            url=f"https://example.com/result/{idx}",
            snippet=f"Snippet {idx}",
        )
        for idx in range(count)
    ]
    return SearchResponse(
        query="python asyncio documentation",
        provider=provider,
        results=results,
        total_results=len(results) if total_results is None else total_results,
        usage=usage,
    )


# --- AC-L2: Brave usage step acceptance / rejection ---------------------------


def test_usage_step_accepts_rate_limit_remaining_int() -> None:
    """A usage event with a non-negative int rate_limit_remaining must pass."""
    usage = _usage(metadata={"rate_limit_remaining": 250})
    context = SimpleNamespace(search_response=_brave_response(usage))

    brave_steps.step_then_brave_reports_one_search_unit(context)


def test_usage_step_accepts_missing_rate_limit_remaining() -> None:
    """Rate-limit metadata is optional; an event without it must pass."""
    context = SimpleNamespace(search_response=_brave_response(_usage()))

    brave_steps.step_then_brave_reports_one_search_unit(context)


def test_usage_step_rejects_missing_usage() -> None:
    """A search response without usage telemetry must still fail."""
    context = SimpleNamespace(search_response=_brave_response(None))

    with pytest.raises(AssertionError, match="missing usage"):
        brave_steps.step_then_brave_reports_one_search_unit(context)


def test_usage_step_rejects_wrong_provider() -> None:
    """Usage from another provider must not satisfy the Brave step."""
    context = SimpleNamespace(search_response=_brave_response(_usage(provider="tavily")))

    with pytest.raises(AssertionError, match="provider"):
        brave_steps.step_then_brave_reports_one_search_unit(context)


def test_usage_step_rejects_non_search_operation() -> None:
    """A non-search operation must not satisfy the Brave step."""
    context = SimpleNamespace(
        search_response=_brave_response(_usage(operation=UsageOperation.FETCH))
    )

    with pytest.raises(AssertionError, match="operation"):
        brave_steps.step_then_brave_reports_one_search_unit(context)


def test_usage_step_rejects_wrong_units() -> None:
    """Any unit count other than exactly one must be rejected."""
    context = SimpleNamespace(search_response=_brave_response(_usage(units="2")))

    with pytest.raises(AssertionError, match="search unit"):
        brave_steps.step_then_brave_reports_one_search_unit(context)


@pytest.mark.parametrize(
    "bad_value",
    [-1, "250", 250.0, True],
    ids=["negative", "string", "float", "bool"],
)
def test_usage_step_rejects_invalid_rate_limit_remaining(bad_value: object) -> None:
    """A present rate_limit_remaining that is not an int >= 0 must be rejected."""
    usage = _usage(metadata={"rate_limit_remaining": bad_value})
    context = SimpleNamespace(search_response=_brave_response(usage))

    with pytest.raises(AssertionError, match="rate_limit_remaining"):
        brave_steps.step_then_brave_reports_one_search_unit(context)


# --- AC-L1: normalized results step (guards the tagged live scenario) ---------


def test_search_results_step_accepts_bounded_results() -> None:
    """A Brave response with results within the requested limit must pass."""
    context = SimpleNamespace(search_limit=3, search_response=_brave_response(_usage(), count=2))

    brave_steps.step_then_brave_search_contains_results(context)


def test_search_results_step_accepts_results_at_limit_boundary() -> None:
    """Exactly ``limit`` results must still pass (1 <= len <= limit)."""
    context = SimpleNamespace(search_limit=3, search_response=_brave_response(_usage(), count=3))

    brave_steps.step_then_brave_search_contains_results(context)


def test_search_results_step_rejects_empty_results() -> None:
    """A live Brave search returning zero results must fail per AC-L1."""
    context = SimpleNamespace(search_limit=3, search_response=_brave_response(_usage(), count=0))

    with pytest.raises(AssertionError, match="Brave results"):
        brave_steps.step_then_brave_search_contains_results(context)


def test_search_results_step_rejects_over_limit_results() -> None:
    """Results exceeding the requested limit must be rejected."""
    context = SimpleNamespace(search_limit=3, search_response=_brave_response(_usage(), count=4))

    with pytest.raises(AssertionError, match="Brave results"):
        brave_steps.step_then_brave_search_contains_results(context)


def test_search_results_step_rejects_wrong_provider() -> None:
    """A non-brave response must not satisfy the Brave results step."""
    context = SimpleNamespace(
        search_limit=3,
        search_response=_brave_response(_usage(), count=2, provider="tavily"),
    )

    with pytest.raises(AssertionError, match="provider"):
        brave_steps.step_then_brave_search_contains_results(context)


def test_search_results_step_rejects_total_mismatch() -> None:
    """total_results must equal len(results) per AC-L1."""
    context = SimpleNamespace(
        search_limit=3,
        search_response=_brave_response(_usage(), count=2, total_results=99),
    )

    with pytest.raises(AssertionError, match="total_results"):
        brave_steps.step_then_brave_search_contains_results(context)


def test_result_validity_step_accepts_http_url() -> None:
    """A populated result with an http(s) URL must pass."""
    context = SimpleNamespace(search_response=_brave_response(_usage(), count=1))

    brave_steps.step_then_brave_results_valid(context)


def test_result_validity_step_rejects_empty_title() -> None:
    results = [SearchResult(title="", url="https://example.com/r", snippet="snippet")]
    context = SimpleNamespace(
        search_response=SearchResponse(
            query="q", provider="brave", results=results, total_results=1
        )
    )

    with pytest.raises(AssertionError, match="title"):
        brave_steps.step_then_brave_results_valid(context)


def test_result_validity_step_rejects_empty_snippet() -> None:
    results = [SearchResult(title="title", url="https://example.com/r", snippet="")]
    context = SimpleNamespace(
        search_response=SearchResponse(
            query="q", provider="brave", results=results, total_results=1
        )
    )

    with pytest.raises(AssertionError, match="snippet"):
        brave_steps.step_then_brave_results_valid(context)


def test_result_validity_step_rejects_non_http_url() -> None:
    """The step's http(s) guard must reject a non-http URL (via model_construct)."""
    result = SearchResult.model_construct(
        title="title", url="ftp://example.com/r", snippet="snippet"
    )
    context = SimpleNamespace(
        search_response=SearchResponse(
            query="q", provider="brave", results=[result], total_results=1
        )
    )

    with pytest.raises(AssertionError, match="url"):
        brave_steps.step_then_brave_results_valid(context)
