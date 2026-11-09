"""You.com fetch failure modes - no network.

Covers AC-6's mismatch boundaries (path/query case differences do not match,
path trailing-slash differences do not match per R3, no matching page raises
the non-retryable ``fetch_failed``) and AC-7's fetch half (pages not a list,
non-JSON bodies, and a matching page without string markdown fail closed as
the fixed, non-retryable ``invalid_response`` with the cause suppressed).
Also locks ``without max_chars`` never truncating, non-string titles
becoming ``None``, and the AC-11/R3 ``_same_url`` unit behavior.
"""

import httpx
import pytest

from polyweb.adapters.youcom import _same_url
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models.contracts import FetchRequest
from tests.unit.adapters._youcom_test_support import (
    _fetch_payload,
    _wired,
    _WireRecorder,
)


async def test_fetch_path_and_query_case_differences_do_not_match() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "HTTPS://EXAMPLE.COM/DOCS?QUERY=ALPHA", "markdown": "wrong", "title": "T"}
        )
    )
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://example.com/docs?query=alpha",
                )
            )

    assert excinfo.value.error.code == "fetch_failed"


async def test_fetch_path_trailing_slash_difference_does_not_match() -> None:
    """``/docs`` and ``/docs/`` are distinct paths; only bare-origin slash forms
    are interchangeable (R3)."""
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "https://example.com/docs/", "markdown": "wrong", "title": "T"}
        )
    )
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://example.com/docs",
                )
            )

    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


async def test_fetch_no_matching_page_raises_nonretryable_error() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload({"url": "https://other.example/x", "markdown": "no", "title": "T"})
    )
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
                )
            )

    assert excinfo.value.error.provider == "you"
    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False
    assert "no successful extraction result" in excinfo.value.error.message


async def test_fetch_skips_non_dict_pages() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            "junk",
            42,
            {"url": "https://example.com/doc", "markdown": "kept", "title": "T"},
            None,
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert response.document.content == "kept"


async def test_fetch_pages_not_a_list_is_invalid_response() -> None:
    recorder = _WireRecorder(fetch={"results": [{"url": "https://example.com/doc"}]})
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
                )
            )

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed fetch response" in excinfo.value.error.message


async def test_fetch_non_json_body_is_invalid_response() -> None:
    recorder = _WireRecorder(responses=[httpx.Response(200, content=b"not json")])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
                )
            )

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed fetch response" in excinfo.value.error.message


@pytest.mark.parametrize(
    "page",
    [
        {"url": "https://example.com/doc", "title": "T"},  # markdown key absent
        {"url": "https://example.com/doc", "markdown": None, "title": "T"},
        {"url": "https://example.com/doc", "markdown": 123, "title": "T"},
    ],
)
async def test_fetch_matching_page_without_string_markdown_is_invalid_response(
    page: dict[str, object],
) -> None:
    recorder = _WireRecorder(fetch=[page])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
                )
            )

    assert excinfo.value.error.provider == "you"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


async def test_fetch_without_max_chars_never_truncates() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "https://example.com/doc", "markdown": "y" * 5000, "title": "T"}
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert response.document.content == "y" * 5000
    assert response.document.metadata == {}


async def test_fetch_non_string_title_becomes_none() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload({"url": "https://example.com/doc", "markdown": "body", "title": 42})
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert response.document.title is None


# --- normalization helpers --------------------------------------------------


def test_same_url_bare_origin_slash_forms_match_but_path_slash_is_significant() -> None:
    # Bare-origin trailing slash normalization (the live BDD contract).
    assert _same_url("https://example.com", "https://example.com/")
    # A non-bare path keeps its trailing slash: /a != /a/ (R3).
    assert not _same_url("https://example.com/a", "https://example.com/a/")
    assert _same_url("HTTPS://EXAMPLE.com/Path", "https://example.com/Path")
    # Path and query case are preserved, fragments are compared.
    assert not _same_url("https://example.com/Docs", "https://example.com/docs")
    assert not _same_url("https://example.com/?q=A", "https://example.com/?q=a")
    assert not _same_url("https://example.com/a#x", "https://example.com/a#y")
    assert _same_url("https://example.com/a#x", "https://example.com/a#x")
    # Unparseable URLs fall back to exact string equality.
    assert _same_url("https://example.com:abc", "https://example.com:abc")
    assert not _same_url("https://example.com:abc", "https://example.com")
