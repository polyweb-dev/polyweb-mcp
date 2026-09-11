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

from freesearch.adapters.youcom import YoucomAdapter, _parse_published_at
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import SearchRequest
from tests.unit.adapters._youcom_test_support import (
    _assert_no_secret_leak,
    _default_runner,
    _wire_caller,
    _wired,
    _WireRecorder,
    fake_resolver,  # noqa: F401  (autouse fixture registered via import)
)


@pytest.mark.parametrize("results", [[], "junk"])
async def test_search_malformed_results_is_invalid_response(results: object) -> None:
    recorder = _WireRecorder(search={"results": results})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
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
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
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
            await adapter.search(SearchRequest(query="bad"))

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
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        response = await adapter.search(SearchRequest(query="meta"))
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


async def test_search_result_item_missing_url_is_invalid_response() -> None:
    recorder = _WireRecorder(search={"results": {"web": [{"title": "missing url"}]}})
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_non_json_body_is_invalid_response() -> None:
    recorder = _WireRecorder(responses=[httpx.Response(200, content=b"not json")])
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed search response" in excinfo.value.error.message


async def test_search_malformed_payload_suppresses_cause_and_redacts() -> None:
    """A structurally malformed item next to an ``api_key`` field surfaces as
    the redaction-safe ``invalid_response`` with the cause suppressed."""
    recorder = _WireRecorder(
        search={"results": {"web": [{"api_key": "super-secret", "title": "missing url"}]}}
    )
    caller = _wire_caller(recorder)
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=_default_runner(caller))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "super-secret")


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
