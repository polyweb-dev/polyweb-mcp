"""Contract: the recorded Tinyfish exchanges, and the documented success shapes.

The four recordings (2026-11-17, raw HTTPX 0.28.1) are the only live
evidence: missing and bogus keys on the search and fetch hosts. They are
replayed exactly. No authenticated call was recorded, so the success bodies
are checked against the required fields of the public Search and Fetch
references (``docs__search-api__reference.md``, ``docs__fetch-api__reference.md``
in the research folder), not against a capture.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "tinyfish").glob("*.json"))
_FORWARDED = {"content-type", "user-agent", "accept"}
_WRONG_KEY = "mockbogus0000000000000000000000000000000"

#: Documented required fields and their JSON types (``|`` separates choices).
_SEARCH_TOP = {"query": "str", "results": "list", "total_results": "int", "page": "int"}
_SEARCH_ITEM = {
    "position": "int",
    "site_name": "str",
    "title": "str",
    "snippet": "str",
    "url": "str",
}
_FETCH_TOP = {"results": "list", "errors": "list"}
_FETCH_ITEM = {
    "url": "str",
    "final_url": "str",
    "title": "str|NoneType",
    "description": "str|NoneType",
    "language": "str|NoneType",
    "author": "str|NoneType",
    "published_date": "str|NoneType",
    "text": "str|dict|NoneType",
    "latency_ms": "int|float|NoneType",
    "format": "str",
}


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked)


def _assert_documented(body: dict[str, Any], fields: dict[str, str]) -> None:
    for name, kinds in fields.items():
        assert name in body, name
        assert type(body[name]).__name__ in kinds.split("|"), (name, body[name])


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 4
    for path in _RECORDINGS:
        recording = json.loads(path.read_text(encoding="utf-8"))
        assert recording["request_headers"].get("x-api-key", "<REDACTED>") == "<REDACTED>"
        assert recording["response_headers"]["set-cookie"] == "<REDACTED>"


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(path: Path, client: httpx.AsyncClient) -> None:
    recording: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    url = urlsplit(recording["url"])
    headers = {k: v for k, v in recording["request_headers"].items() if k in _FORWARDED}
    headers["host"] = url.hostname or ""
    if "x-api-key" in recording["request_headers"]:
        headers["x-api-key"] = _WRONG_KEY
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        f"{url.path or '/'}?{url.query}" if url.query else url.path or "/",
        headers=headers,
        content=None if body is None else json.dumps(body).encode(),
    )

    recorded_headers = recording["response_headers"]
    assert response.status_code == recording["status"]
    for name in ("content-type", "cache-control", "www-authenticate", "x-cache"):
        assert response.headers[name] == recorded_headers[name], name
    assert response.headers["via"].endswith(".cloudfront.net (CloudFront)")
    assert {"x-amz-cf-pop", "x-amz-cf-id"} <= set(response.headers)
    assert "retry-after" not in response.headers
    mocked = response.json()
    assert mocked == {**recording["response_body"], "request_id": response.headers["x-request-id"]}
    _same_shape(recording["response_body"], mocked)


async def test_search_success_has_the_documented_fields(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    key = next(item.key for item in store.keys("tinyfish") if item.label == "default")
    response = await client.get(
        "/",
        params={"query": "polyweb test", "page": "0"},
        headers={"host": "api.search.tinyfish.ai", "x-api-key": key},
    )

    body = response.json()
    assert response.headers["content-type"] == "application/json"
    assert {"x-request-id", "x-ratelimit-limit", "x-ratelimit-remaining"} <= set(response.headers)
    _assert_documented(body, _SEARCH_TOP)
    for item in body["results"]:
        _assert_documented(item, _SEARCH_ITEM)


async def test_fetch_success_has_the_documented_fields(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    key = next(item.key for item in store.keys("tinyfish") if item.label == "default")
    response = await client.post(
        "/",
        json={"urls": ["https://example.com"], "format": "markdown"},
        headers={"host": "api.fetch.tinyfish.ai", "x-api-key": key},
    )

    body = response.json()
    _assert_documented(body, _FETCH_TOP)
    _assert_documented(body["results"][0], _FETCH_ITEM)
    assert body["results"][0]["final_url"] == "https://example.com/"
    assert set(body["results"][0]) == set(_FETCH_ITEM)
