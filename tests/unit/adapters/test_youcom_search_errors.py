"""You.com search failure modes and search-specific normalization helpers.

Covers AC-7 (malformed search payloads and non-JSON bodies fail closed as
the fixed, non-retryable, redaction-safe ``invalid_response`` with the cause
suppressed), R6 (a valid-JSON non-object body - list, scalar, or null - is
``invalid_response``, never an empty success), R5's search half
(``thumbnail_url``/``favicon_url`` normalize into result metadata only when
safe http(s) strings), and the AC-11 ``_parse_published_at`` unit behavior.
"""

import json
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.youcom import YoucomAdapter, _parse_published_at
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import SearchRequest
from tests.unit.adapters._youcom_test_support import (
    _TEST_KEY,
    _assert_no_secret_leak,
    _default_runner,
    _wire_caller,
    _wired,
    _WireRecorder,
)


@pytest.mark.parametrize("results", [[], "junk"])
async def test_search_malformed_results_is_invalid_response(results: object) -> None:
    recorder = _WireRecorder(search={"results": results})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert excinfo.value.error.provider == "you"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed search response" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        [{"title": "List Hit", "url": "https://example.com/list"}],  # top-level array
        ["just", "strings"],
        "plain scalar text",
        42,
        True,
        None,  # JSON null
    ],
)
async def test_search_top_level_list_or_scalar_body_is_invalid_response(
    payload: object,
) -> None:
    """A successful 200 with valid JSON that is not an object (top-level list
    or scalar, including null) is a malformed search response, never an empty
    success (R6)."""
    recorder = _WireRecorder(responses=[httpx.Response(200, content=json.dumps(payload).encode())])
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "you"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.error.status_code is None
    assert error.error.message == "malformed search response"
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


@pytest.mark.parametrize(
    "payload",
    [
        [{"api_key": "sk-r2-leak-1", "title": "leak", "url": "https://example.com/leak"}],
        "sk-r2-leak-1",
    ],
)
async def test_search_top_level_non_object_payload_redacts_secret_echo(
    payload: object,
) -> None:
    """A list/scalar body echoing a secret surfaces only the fixed message;
    the secret never reaches the message, serialized error, or traceback (R6)."""
    recorder = _WireRecorder(responses=[httpx.Response(200, content=json.dumps(payload).encode())])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "sk-r2-leak-1")


async def test_search_normalizes_thumbnail_and_favicon_url_metadata() -> None:
    """Safe http(s) ``thumbnail_url``/``favicon_url`` fields (the real WebResult
    field names) land in result metadata; junk and absent values leave
    ``metadata == {}`` (R5)."""
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    {
                        "title": "A",
                        "url": "https://example.com/a",
                        "snippets": ["s"],
                        "thumbnail_url": "https://img.example.com/a.png",
                        "favicon_url": "https://example.com/favicon.ico",
                    },
                    {
                        "title": "B",
                        "url": "https://example.com/b",
                        "snippets": ["s"],
                        "thumbnail_url": "javascript:alert(1)",
                        "favicon_url": 42,
                    },
                    {"title": "C", "url": "https://example.com/c", "snippets": ["s"]},
                ]
            }
        }
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="meta")
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.results[0].metadata == {
        "thumbnail_url": "https://img.example.com/a.png",
        "favicon_url": "https://example.com/favicon.ico",
    }
    assert response.results[1].metadata == {}
    assert response.results[2].metadata == {}


async def test_search_result_item_missing_url_returns_empty_success() -> None:
    recorder = _WireRecorder(search={"results": {"web": [{"title": "missing url"}]}})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage_gap is not None
    assert response.usage_gap.get("parse_errors") == [
        {"index": 0, "code": "invalid_response", "message": "malformed search result item"}
    ]


async def test_search_non_json_body_is_invalid_response() -> None:
    recorder = _WireRecorder(responses=[httpx.Response(200, content=b"not json")])
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed search response" in excinfo.value.error.message


async def test_search_malformed_item_records_redacted_error() -> None:
    """A structurally malformed item next to an ``api_key`` field records a
    redaction-safe parse error instead of failing the search."""
    recorder = _WireRecorder(
        search={"results": {"web": [{"api_key": "super-secret", "title": "missing url"}]}}
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage_gap is not None
    errors = response.usage_gap.get("parse_errors")
    assert errors == [
        {"index": 0, "code": "invalid_response", "message": "malformed search result item"}
    ]
    assert "super-secret" not in repr(errors)
    assert "super-secret" not in repr(response.results)


_GOOD_WEB_ITEM = {
    "title": "Web Hit",
    "url": "https://example.com/web",
    "snippets": ["web snippet"],
}

_GOOD_NEWS_ITEM = {
    "title": "News Hit",
    "url": "https://news.example.com/x",
    "snippets": ["news snippet"],
}

_BAD_URL_ITEM = {"title": "Bad address", "url": "not-a-url", "snippets": ["s"]}

_MISSING_URL_ITEM = {"title": "No address here"}

_EMPTY_URL_ITEM = {"title": "Empty address", "url": ""}

_EXPECTED_RECORD = {
    "code": "invalid_response",
    "message": "malformed search result item",
}


async def _search_with(search: object) -> object:
    recorder = _WireRecorder(search=search)
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        return await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="mixed", limit=10
            )
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()


def _gap_records(response: object) -> object:
    gap = response.usage_gap  # type: ignore[union-attr]
    assert gap is not None
    assert gap["reason"] == "metering-unavailable"
    assert gap["estimated"] is True
    assert gap["currency"] == "USD"
    return gap.get("parse_errors")


@pytest.mark.parametrize(
    ("sections", "expected_urls", "expected_indices"),
    [
        (
            {"web": [_GOOD_WEB_ITEM, _BAD_URL_ITEM]},
            ["https://example.com/web"],
            [1],
        ),
        (
            {"web": [_MISSING_URL_ITEM], "news": [_GOOD_NEWS_ITEM]},
            ["https://news.example.com/x"],
            [0],
        ),
        (
            {
                "web": [_GOOD_WEB_ITEM, _EMPTY_URL_ITEM],
                "news": [_BAD_URL_ITEM, _GOOD_NEWS_ITEM],
            },
            ["https://example.com/web", "https://news.example.com/x"],
            [1, 2],
        ),
    ],
)
async def test_search_skips_invalid_items_and_records_errors(
    sections: object, expected_urls: list[str], expected_indices: list[int]
) -> None:
    response = await _search_with({"results": sections})

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.query == "mixed"
    assert response.provider == "you"
    assert response.total_results == len(expected_urls)
    assert _gap_records(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


@pytest.mark.parametrize(
    ("sections", "expected_indices"),
    [
        ({"web": [{"title": "No address"}]}, [0]),
        ({"web": [{"title": "Bad", "url": "not-a-url"}]}, [0]),
        ({"news": [{"title": "Empty", "url": ""}]}, [0]),
    ],
)
async def test_search_all_invalid_items_returns_empty_success(
    sections: object, expected_indices: list[int]
) -> None:
    response = await _search_with({"results": sections})

    assert response.results == []
    assert response.total_results == 0
    assert response.query == "mixed"
    assert response.provider == "you"
    assert _gap_records(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


async def test_search_empty_list_has_no_parse_errors() -> None:
    response = await _search_with({"results": {"web": []}})

    assert response.results == []
    assert response.total_results == 0
    assert response.usage_gap is not None
    assert "parse_errors" not in response.usage_gap


@pytest.mark.parametrize(
    ("limit", "sections", "expected_urls", "expected_indices"),
    [
        (
            1,
            {"web": [_BAD_URL_ITEM, _GOOD_WEB_ITEM, _GOOD_NEWS_ITEM]},
            ["https://example.com/web"],
            [0],
        ),
        (
            2,
            {"web": [_GOOD_WEB_ITEM, _MISSING_URL_ITEM], "news": [_GOOD_NEWS_ITEM]},
            ["https://example.com/web", "https://news.example.com/x"],
            [1],
        ),
    ],
)
async def test_search_limit_applies_after_invalid_item_filter(
    limit: int, sections: object, expected_urls: list[str], expected_indices: list[int]
) -> None:
    recorder = _WireRecorder(search={"results": sections})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="capped", limit=limit
            )
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.total_results == len(expected_urls)
    gap = response.usage_gap
    assert gap is not None
    assert gap.get("parse_errors") == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


async def test_search_invalid_tail_item_does_not_fail_response() -> None:
    recorder = _WireRecorder(
        search={"results": {"web": [_GOOD_WEB_ITEM, _GOOD_NEWS_ITEM, _BAD_URL_ITEM]}}
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="tailed", limit=1
            )
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert [str(item.url) for item in response.results] == ["https://example.com/web"]
    assert response.total_results == 1
    gap = response.usage_gap
    assert gap is not None
    assert gap.get("parse_errors") == [{"index": 2, **_EXPECTED_RECORD}]


async def test_search_parse_errors_do_not_expose_payload_or_key() -> None:
    recorder = _WireRecorder(
        search={
            "results": {
                "web": [
                    _GOOD_WEB_ITEM,
                    {
                        "title": "leak sk-you-test-secret-1",
                        "url": "not-a-url",
                        "snippets": ["leak sk-you-test-secret-1"],
                    },
                ]
            }
        }
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(
            caller, runner=_default_runner(caller), api_key=SecretStr(_TEST_KEY)
        )
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="leak", limit=10)
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert [str(item.url) for item in response.results] == ["https://example.com/web"]
    gap = response.usage_gap
    assert gap is not None
    errors = gap.get("parse_errors")
    assert errors == [{"index": 1, **_EXPECTED_RECORD}]
    assert _TEST_KEY not in repr(errors)
    assert _TEST_KEY not in repr(response.results)
    for record in errors:
        assert set(record.keys()) == {"index", "code", "message"}


# --- normalization helpers --------------------------------------------------


def test_parse_published_at_accepts_iso_8601_and_rejects_garbage() -> None:
    parsed = _parse_published_at("2025-01-02T03:04:05Z")
    assert parsed is not None
    assert parsed.year == 2025
    assert parsed.utcoffset() == timedelta(0)

    offset = _parse_published_at("2025-06-07T08:09:10+02:00")
    assert offset is not None
    assert offset.utcoffset() == timedelta(hours=2)

    assert _parse_published_at("not-a-date") is None
    assert _parse_published_at(123) is None
    assert _parse_published_at(None) is None
