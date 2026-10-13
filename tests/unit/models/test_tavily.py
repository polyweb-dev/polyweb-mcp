"""Tavily parameter models and pure depth/debit helpers. No I/O."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from freesearch.models.tavily import (
    TavilyExtractParams,
    TavilySearchParams,
    tavily_extract_credits,
    tavily_extract_depth,
    tavily_search_depth,
)


def test_search_params_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TavilySearchParams(urls=["https://example.com"])  # type: ignore[call-arg]


def test_extract_params_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TavilyExtractParams(urls=["https://example.com"])  # type: ignore[call-arg]


def test_search_params_reject_reserved_include_usage() -> None:
    with pytest.raises(ValidationError):
        TavilySearchParams(include_usage=True)  # type: ignore[call-arg]


def test_extract_params_reject_reserved_include_usage() -> None:
    with pytest.raises(ValidationError):
        TavilyExtractParams(include_usage=True)  # type: ignore[call-arg]


def test_search_params_reject_reserved_max_results() -> None:
    with pytest.raises(ValidationError):
        TavilySearchParams(max_results=5)  # type: ignore[call-arg]


def test_search_params_reject_reserved_auth_fields() -> None:
    with pytest.raises(ValidationError):
        TavilySearchParams(api_key="tvly-secret")  # type: ignore[call-arg]


def test_extract_params_reject_reserved_auth_and_timeout() -> None:
    with pytest.raises(ValidationError):
        TavilyExtractParams(timeout=5)  # type: ignore[call-arg]


def test_search_depth_explicit_wins_when_mode_absent() -> None:
    assert tavily_search_depth(None, TavilySearchParams(search_depth="advanced")) == "advanced"
    assert tavily_search_depth(None, TavilySearchParams(search_depth="basic")) == "basic"


def test_search_depth_mode_maps_without_params() -> None:
    assert tavily_search_depth("advanced", None) == "advanced"
    assert tavily_search_depth("basic", None) == "basic"
    assert tavily_search_depth(None, None) == "basic"
    assert tavily_search_depth("turbo", None) == "basic"


def test_search_depth_conflict_rejected_before_io() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        tavily_search_depth("basic", TavilySearchParams(search_depth="advanced"))
    with pytest.raises(ValueError, match="conflicts"):
        tavily_search_depth("advanced", TavilySearchParams(search_depth="basic"))


def test_search_depth_matching_mode_passes() -> None:
    assert (
        tavily_search_depth("advanced", TavilySearchParams(search_depth="advanced"))
        == "advanced"
    )
    assert tavily_search_depth("basic", TavilySearchParams(search_depth="basic")) == "basic"


def test_extract_depth_defaults_basic() -> None:
    assert tavily_extract_depth(None) == "basic"
    assert tavily_extract_depth(TavilyExtractParams()) == "basic"
    assert tavily_extract_depth(TavilyExtractParams(extract_depth="advanced")) == "advanced"


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0.0"), (1, "0.2"), (4, "0.8"), (5, "1.0"), (6, "1.2")],
)
def test_extract_basic_credits_proportional(count: int, expected: str) -> None:
    assert tavily_extract_credits(count, "basic") == Decimal(expected)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "0.0"), (1, "0.4"), (4, "1.6"), (5, "2.0"), (6, "2.4")],
)
def test_extract_advanced_credits_proportional(count: int, expected: str) -> None:
    assert tavily_extract_credits(count, "advanced") == Decimal(expected)


def test_extract_credits_reject_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        tavily_extract_credits(-1, "basic")
