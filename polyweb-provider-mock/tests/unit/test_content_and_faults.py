"""Deterministic content generation and fault duration parsing."""

import uuid

import pytest

from polyweb_provider_mock import content
from polyweb_provider_mock.faults import parse_duration


def test_search_hits_are_deterministic_ordered_and_counted() -> None:
    first = content.search_hits("Rust async runtimes", 7)
    assert first == content.search_hits("Rust async runtimes", 7)
    assert len(first) == 7
    assert [hit.score for hit in first] == sorted((hit.score for hit in first), reverse=True)
    assert all(0 < hit.score <= 1 for hit in first)
    assert len({hit.url for hit in first}) == 7
    assert content.search_hits("rust async runtimes", 0) == []


def test_search_hits_honour_domain_filters() -> None:
    only = content.search_hits("python", 4, include_domains=["docs.python.org"])
    assert {hit.domain for hit in only} == {"docs.python.org"}
    excluded = content.search_hits("python", 20, exclude_domains=["github.com"])
    assert "github.com" not in {hit.domain for hit in excluded}


def test_page_is_stable_and_example_domains_stay_plain() -> None:
    page = content.page("https://docs.python.org/3/library/asyncio-task.html")
    assert page == content.page("https://docs.python.org/3/library/asyncio-task.html")
    assert page.title == "Library Asyncio Task"
    assert page.markdown.startswith("# Library Asyncio Task")
    assert page.images and page.favicon == "https://docs.python.org/favicon.ico"
    plain = content.page("https://example.com")
    assert (plain.title, plain.images, plain.favicon) == ("Example Domain", (), None)


def test_identifiers_have_provider_shapes() -> None:
    value = content.stable_uuid("tavily", 1)
    assert uuid.UUID(value).version == 4
    assert value != content.stable_uuid("tavily", 2)
    assert len(content.hex_id(6, "x")) == 6
    assert content.normalize_url(" HTTPS://Example.COM/Path?q=A ") == "https://example.com/Path?q=A"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("30", 30.0), ("30s", 30.0), ("500ms", 0.5), ("10m", 600.0), ("2h", 7200.0), ("1d", 86400.0)],
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration("soon")
