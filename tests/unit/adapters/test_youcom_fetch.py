"""You.com fetch document normalization - no network.

Covers AC-6's happy paths (target page matched with scheme/host
case-insensitivity and retained path/query case, bare-origin trailing-slash
normalization, empty markdown accepted, truncation at exact ``max_chars``
boundaries with ``metadata={"truncated": True}`` only when cut) and R5's
fetch half (contents ``metadata`` normalizes into document metadata). The
``_same_url`` unit behavior (AC-11/R3) lives in ``test_youcom_fetch_errors.py``.
"""

import json
from datetime import timedelta

from freesearch.models.contracts import FetchRequest
from tests.unit.adapters._youcom_test_support import (
    _fetch_payload,
    _wired,
    _WireRecorder,
)


async def test_fetch_matches_target_page_and_normalizes_document() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "https://example.com/doc", "markdown": "body text", "title": "Title"}
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.provider == "you"
    assert str(response.document.url) == "https://example.com/doc"
    assert response.document.content == "body text"
    assert response.document.title == "Title"
    assert response.document.content_type == "text/markdown"
    assert response.document.metadata == {}
    assert response.document.fetched_at.utcoffset() == timedelta(0)


async def test_fetch_matches_scheme_and_host_case_insensitively_and_retains_path_case() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "HTTPS://EXAMPLE.COM/Docs?Query=Alpha", "markdown": "kept", "title": "T"}
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/Docs?Query=Alpha"))

    assert response.document.content == "kept"
    assert str(response.document.url) == "https://example.com/Docs?Query=Alpha"


async def test_fetch_bare_origin_trailing_slash_normalization_matches() -> None:
    """You.com normalizes a bare origin to a trailing slash (the live BDD
    contract: ``https://example.com`` matches a returned ``.../`` page)."""
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "https://example.com/", "markdown": "landing", "title": "Home"}
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com"))

    assert response.document.content == "landing"
    assert str(response.document.url) == "https://example.com/"


async def test_fetch_normalizes_contents_metadata_site_name_and_favicon() -> None:
    """Contents ``metadata`` (OpenGraph) fields normalize into
    ``document.metadata`` with the wire field names (R5)."""
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {
                "url": "https://example.com/doc",
                "markdown": "body",
                "title": "T",
                "metadata": {
                    "site_name": "Example",
                    "favicon_url": "https://example.com/favicon.ico",
                },
            }
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.metadata == {
        "site_name": "Example",
        "favicon_url": "https://example.com/favicon.ico",
    }


async def test_fetch_truncation_merges_with_contents_metadata() -> None:
    """Truncation flag and contents metadata coexist in ``document.metadata``."""
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {
                "url": "https://example.com/doc",
                "markdown": "x" * 500,
                "title": "T",
                "metadata": {
                    "site_name": "Example",
                    "favicon_url": "https://example.com/favicon.ico",
                },
            }
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=100))

    assert response.document.content == "x" * 100
    assert response.document.metadata == {
        "truncated": True,
        "site_name": "Example",
        "favicon_url": "https://example.com/favicon.ico",
    }


async def test_fetch_non_dict_contents_metadata_is_ignored() -> None:
    """A non-dict ``metadata`` value (or one with null fields) is ignored;
    ``document.metadata`` stays ``{}`` (R5 safety)."""
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {
                "url": "https://example.com/doc",
                "markdown": "body",
                "title": "T",
                "metadata": {"site_name": None, "favicon_url": None},
            }
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.metadata == {}


async def test_fetch_empty_markdown_is_accepted() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload({"url": "https://example.com/doc", "markdown": "", "title": "T"})
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.content == ""
    assert response.document.metadata == {}


async def test_fetch_truncates_content_at_max_chars() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload(
            {"url": "https://example.com/doc", "markdown": "x" * 500, "title": "T"}
        )
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=100))

    assert response.document.content == "x" * 100
    assert response.document.metadata == {"truncated": True}


async def test_fetch_exact_boundary_length_is_not_truncated() -> None:
    recorder = _WireRecorder(
        fetch=_fetch_payload({"url": "https://example.com/doc", "markdown": "abcde", "title": "T"})
    )
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=5))

    assert response.document.content == "abcde"
    assert response.document.metadata == {}


async def test_fetch_forwards_you_contents_options_and_normalizes_html() -> None:
    page = {
        "url": "https://example.com/page",
        "title": "HTML page",
        "html": "<main>Page body</main>",
        "metadata": {
            "site_name": "Example",
            "favicon_url": "https://example.com/favicon.ico",
        },
    }
    recorder = _WireRecorder(fetch=_fetch_payload(page))
    async with _wired(recorder) as adapter:
        response = await adapter.fetch(
            FetchRequest(
                url="https://example.com/page",
                provider_options={
                    "you": {
                        "formats": ["html", "metadata"],
                        "crawl_timeout": 25,
                        "max_age": 0,
                    }
                },
            )
        )

    body = json.loads(recorder.requests[0].content)
    assert body == {
        "urls": ["https://example.com/page"],
        "formats": ["html", "metadata"],
        "crawl_timeout": 25,
        "max_age": 0,
    }
    assert response.document.content == "<main>Page body</main>"
    assert response.document.content_type == "text/html"
    assert response.document.metadata == {
        "site_name": "Example",
        "favicon_url": "https://example.com/favicon.ico",
    }
