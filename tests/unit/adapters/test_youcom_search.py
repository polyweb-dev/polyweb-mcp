"""You.com search normalization over ``MockTransport`` - no network.

Covers AC-5 (web + news sections flattened into normalized results with
title/snippet/date/metadata, ``count`` capped at 100) plus remediation
contracts: R1 (flattened ``total_results`` never exceeds the requested
limit), R2 (missing/null ``results`` is an empty successful search), and R4
(``page_age`` parses into ``published_at``).
"""

import json
from datetime import timedelta

import pytest
from pydantic import SecretStr

from freesearch.adapters.youcom import YoucomAdapter
from freesearch.models.contracts import SearchRequest
from tests.unit.adapters._youcom_test_support import (
    _TEST_KEY,
    _default_runner,
    _wire_caller,
    _wired,
    _WireRecorder,
)


@pytest.mark.parametrize(
    "limit,expected",
    [
        (5, 5),
        (100, 100),
        (500, 100),  # contract caps at 100; defensive cap via construct
    ],
)
async def test_search_caps_count_at_one_hundred(limit: int, expected: int) -> None:
    recorder = _WireRecorder(search={"results": {}})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        request = (
            SearchRequest(query="cap", limit=limit)
            if limit <= 100
            else SearchRequest.model_construct(query="cap", limit=limit)
        )
        await adapter.search(request)
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    body = json.loads(recorder.requests[0].content)
    assert body == {"query": "cap", "count": expected}


async def test_search_flattens_web_and_news_sections() -> None:
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    {
                        "title": "Web Hit",
                        "url": "https://example.com/web",
                        "snippets": ["web snippet"],
                        "publish_date": "2025-01-02T03:04:05Z",
                        "extra_field": "ignored",
                    },
                    {
                        "url": "https://example.com/odd",
                        "snippets": [],
                        "description": "desc fallback",
                        "publish_date": "not-a-date",
                    },
                    {
                        "title": "Empty Snippet",
                        "url": "https://example.com/none",
                        "snippets": [""],
                        "publish_date": "2025-06-07T08:09:10+02:00",
                    },
                ],
                "news": [
                    {
                        "title": "News Hit",
                        "url": "https://news.example.com/x",
                        "snippets": ["news snippet"],
                        "published_date": "2024-11-30T23:59:59Z",
                    }
                ],
            }
        }
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(SearchRequest(query="norm"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.provider == "you"
    assert response.total_results == 4
    # web section first, then news; every item normalized with metadata {}
    assert [str(result.url) for result in response.results] == [
        "https://example.com/web",
        "https://example.com/odd",
        "https://example.com/none",
        "https://news.example.com/x",
    ]
    first = response.results[0]
    assert first.title == "Web Hit"
    assert first.snippet == "web snippet"
    assert first.published_at is not None
    assert first.published_at.year == 2025
    assert first.published_at.utcoffset() == timedelta(0)
    assert first.score is None
    assert first.metadata == {}

    second = response.results[1]
    assert second.title == ""
    assert second.snippet == "desc fallback"
    assert second.published_at is None
    assert second.metadata == {}

    third = response.results[2]
    assert third.snippet == ""  # first snippet is a string, even empty
    assert third.published_at is not None
    assert third.published_at.utcoffset() == timedelta(hours=2)

    news = response.results[3]
    assert news.title == "News Hit"
    assert news.snippet == "news snippet"
    assert news.published_at is not None  # published_date alias accepted
    assert news.published_at.year == 2024


@pytest.mark.parametrize("results", [{}, {"web": "not-a-list"}, {"news": None}])
async def test_search_missing_or_typo_sections_yield_empty_response(results: object) -> None:
    recorder = _WireRecorder(search={"results": results})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(SearchRequest(query="empty"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0


@pytest.mark.parametrize("payload", [{}, {"results": None}])
async def test_search_missing_or_null_results_yield_empty_success(
    payload: dict[str, object],
) -> None:
    """A missing or null ``results`` key is an empty, successful search (R2)."""
    recorder = _WireRecorder(search=payload)
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(SearchRequest(query="empty"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.provider == "you"
    assert response.query == "empty"
    assert response.results == []
    assert response.total_results == 0


async def test_search_flattened_total_never_exceeds_requested_limit() -> None:
    """Web + news flattening must never exceed the requested limit (R1)."""
    web = [
        {"title": f"web {i}", "url": f"https://example.com/w{i}", "snippets": ["s"]}
        for i in range(8)
    ]
    news = [
        {"title": f"news {i}", "url": f"https://news.example.com/n{i}", "snippets": ["s"]}
        for i in range(5)
    ]
    recorder = _WireRecorder(search={"results": {"web": web, "news": news}})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(SearchRequest(query="cap", limit=10))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.total_results == 10
    assert len(response.results) == 10
    # Web section stays first, truncated after it, then news fills the remainder.
    assert [str(result.url) for result in response.results] == [
        f"https://example.com/w{i}" for i in range(8)
    ] + [f"https://news.example.com/n{i}" for i in range(2)]


async def test_search_parses_page_age_into_published_at() -> None:
    """``page_age`` - the real WebResult/NewsResult date field - parses into
    ``published_at`` for both sections (R4)."""
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    {
                        "title": "A",
                        "url": "https://example.com/a",
                        "snippets": ["s"],
                        "page_age": "2024-03-15T10:30:00Z",
                    }
                ],
                "news": [
                    {
                        "title": "N",
                        "url": "https://news.example.com/n",
                        "snippets": ["s"],
                        "page_age": "2024-01-02T03:04:05Z",
                    }
                ],
            }
        }
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(SearchRequest(query="age"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    web = response.results[0]
    assert web.published_at is not None
    assert web.published_at.year == 2024
    assert web.published_at.utcoffset() == timedelta(0)
    news = response.results[1]
    assert news.published_at is not None
    assert news.published_at.year == 2024


async def test_search_forwards_you_options_and_preserves_extraction_contents() -> None:
    contents = {
        "markdown": "# Extracted report",
        "html": "<main>Extracted report</main>",
    }
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    {
                        "title": "Extracted report",
                        "url": "https://example.com/report",
                        "description": "Report summary",
                        "snippets": ["A useful snippet"],
                        "page_age": "2026-07-08T09:10:11Z",
                        "thumbnail_url": "https://example.com/thumbnail.png",
                        "favicon_url": "https://example.com/favicon.ico",
                        "contents": contents,
                    }
                ]
            },
            "metadata": {
                "search_uuid": "a442f19a-5ad7-44bb-a1d0-262b2a563657",
                "query": "report",
                "latency": 0.41,
            },
        }
    )
    async with _wired(recorder) as adapter:
        response = await adapter.search(
            SearchRequest(
                query="report",
                limit=3,
                country_code="US",
                language="EN",
                domains=("common.example",),
                provider_options={
                    "you": {
                        "country": "CA",
                        "language": "FR",
                        "freshness": "2026-01-01to2026-08-01",
                        "offset": 2,
                        "safesearch": "strict",
                        "knowledge": "core",
                        "include_domains": ["override.example"],
                        "strict_operators": True,
                        "extraction": {
                            "mode": "full_page",
                            "source": "cache",
                            "full_page": {"extraction_formats": ["html", "markdown"]},
                        },
                        "crawl_timeout": 25,
                    }
                },
            )
        )

    body = json.loads(recorder.requests[0].content)
    assert body == {
        "query": "report",
        "count": 3,
        "include_domains": ["override.example"],
        "country": "CA",
        "language": "FR",
        "freshness": "2026-01-01to2026-08-01",
        "offset": 2,
        "safesearch": "strict",
        "knowledge": "core",
        "strict_operators": True,
        "crawl_timeout": 25,
        "extraction": {
            "extraction_mode": "full_page",
            "extraction_source": "cache",
            "full_page": {"extraction_formats": ["html", "markdown"]},
        },
    }
    assert response.provider_metadata == {
        "search_uuid": "a442f19a-5ad7-44bb-a1d0-262b2a563657",
        "query": "report",
        "latency": 0.41,
    }
    result = response.results[0]
    assert result.metadata == {
        "thumbnail_url": "https://example.com/thumbnail.png",
        "favicon_url": "https://example.com/favicon.ico",
        "contents": contents,
    }


async def test_search_forwards_exclude_boost_and_legacy_crawl_options() -> None:
    recorder = _WireRecorder(search={"results": {}})
    async with _wired(recorder) as adapter:
        await adapter.search(
            SearchRequest(
                query="vendors",
                domains=("common.example",),
                provider_options={
                    "you": {
                        "exclude_domains": ["blocked.example"],
                        "boost_domains": ["preferred.example"],
                        "livecrawl": "news",
                        "livecrawl_formats": ["html", "markdown"],
                    }
                },
            )
        )

    assert json.loads(recorder.requests[0].content) == {
        "query": "vendors",
        "count": 10,
        "include_domains": ["common.example"],
        "exclude_domains": ["blocked.example"],
        "boost_domains": ["preferred.example"],
        "livecrawl": "news",
        "livecrawl_formats": ["html", "markdown"],
    }


async def test_search_highlight_extraction_is_forwarded_and_retained_in_metadata() -> None:
    highlights = ["The passage most relevant to the query."]
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    {
                        "title": "Highlighted page",
                        "url": "https://example.com/highlighted",
                        "contents": {"highlights": highlights},
                    }
                ]
            }
        }
    )
    async with _wired(recorder) as adapter:
        response = await adapter.search(
            SearchRequest(
                query="highlight query",
                provider_options={
                    "you": {
                        "extraction": {
                            "mode": "highlights",
                            "highlights": {"total_max_tokens": 1024},
                        },
                    }
                },
            )
        )

    body = json.loads(recorder.requests[0].content)
    assert body["extraction"] == {
        "extraction_mode": "highlights",
        "highlights": {"total_max_tokens": 1024},
    }
    assert response.results[0].metadata["contents"] == {"highlights": highlights}
