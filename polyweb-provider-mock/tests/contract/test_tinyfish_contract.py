"""Contract: the recorded Tinyfish exchanges, replayed against the mock.

Two captures with raw HTTPX 0.28.1: the four 401s (2026-11-17, missing and
bogus key on both hosts) and an authenticated run (2026-11-19) of search on
every domain type, fetch in every format with options and per-URL failures,
each validation error, and the 405 routes. Success bodies are scrubbed
(``tests/_support/scrub.py``); request ids, CloudFront ids and the account's
``X-TF-User-ID`` are reduced to character-class patterns.

Errors replay exactly (code, message, details) with the recorded headers;
successes replay by shape, field order, and the per-URL error codes. The
capture's ``/usage`` responses held the account's earlier history, so they
are not stored; ``test_usage_items_have_the_recorded_fields`` pins their
fields instead. The success bodies are also checked against the required
fields of the public Search and Fetch references.
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
_SEARCH_HOST = {"host": "api.search.tinyfish.ai"}
_FETCH_HOST = {"host": "api.fetch.tinyfish.ai"}

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
#: ``/usage`` item fields in the recorded order (2026-11-19).
_USAGE_SEARCH = [
    "id", "request_id", "query", "status_code", "result_count", "results", "cached",
    "response_size_bytes", "created_at",
]  # fmt: skip
_USAGE_FETCH = [
    "id", "url", "final_url", "title", "description", "language", "author", "published_date",
    "format", "status", "request_origin", "request_id", "text_length", "links_count",
    "image_links_count", "latency_ms", "created_at", "error",
]  # fmt: skip


def _assert_documented(body: dict[str, Any], fields: dict[str, str]) -> None:
    for name, kinds in fields.items():
        assert name in body, name
        assert type(body[name]).__name__ in kinds.split("|"), (name, body[name])


def _load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) >= 40
    for path in _RECORDINGS:
        recording = _load(path)
        assert recording["request_headers"].get("x-api-key", "<REDACTED>") == "<REDACTED>"
        assert recording["response_headers"]["set-cookie"] == "<REDACTED>"
        user = recording["response_headers"].get("x-tf-user-id", "aaaa_")
        assert set(user) <= set("aA0_"), path.stem


async def _replay(
    recording: dict[str, Any], stem: str, client: httpx.AsyncClient, store: MockStore
) -> httpx.Response:
    url = urlsplit(recording["url"])
    headers = {k: v for k, v in recording["request_headers"].items() if k in _FORWARDED}
    headers["host"] = url.hostname or ""
    if "x-api-key" in recording["request_headers"]:
        default = next(item.key for item in store.keys("tinyfish") if item.label == "default")
        headers["x-api-key"] = _WRONG_KEY if stem.endswith("__bogus_key") else default
    if stem == "fetch__highlights":
        # The recorded account has no highlights access; the seeded one does.
        with store.db.transaction() as conn:
            conn.execute("UPDATE accounts SET attributes = '{}' WHERE provider = 'tinyfish'")
    body = recording["request_body"]
    content = body.encode() if isinstance(body, str) else None
    if body is not None and content is None:
        content = json.dumps(body).encode()
    target = f"{url.path or '/'}?{url.query}" if url.query else url.path or "/"
    return await client.request(recording["method"], target, headers=headers, content=content)


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = _load(path)
    response = await _replay(recording, path.stem, client, store)
    recorded_headers = recording["response_headers"]
    status = recording["status"]

    assert response.status_code == status
    for name in ("content-type", "cache-control", "www-authenticate", "x-cache"):
        assert response.headers.get(name) == recorded_headers.get(name), name
    assert response.headers["via"].endswith(".cloudfront.net (CloudFront)")
    assert {"x-amz-cf-pop", "x-amz-cf-id", "x-request-id"} <= set(response.headers)
    assert "retry-after" not in response.headers
    # The mock routes before it authenticates, so its 405 cannot name the account.
    account_header = () if status == 405 else ("x-tf-user-id",)
    for name in ("x-ratelimit-limit", "x-frame-options", *account_header):
        assert (name in response.headers) == (name in recorded_headers), name
    if status == 405:
        assert response.content == b""
        return
    mocked = response.json()
    recorded = recording["response_body"]
    if status != 200:
        assert mocked == {**recorded, "request_id": response.headers["x-request-id"]}
        return
    assert_same_shape(recorded, mocked, lists="any")
    assert list(mocked) == list(recorded)
    if "errors" in recorded:
        assert [e["error"] for e in mocked["errors"]] == [e["error"] for e in recorded["errors"]]
        assert (
            mocked.get("request_id", response.headers["x-request-id"])
            == (response.headers["x-request-id"])
        )
    for got, want in zip(mocked["results"], recorded["results"], strict=False):
        if "format" in want:
            assert list(got) == list(want)
        else:
            assert list(got) == sorted(got)
    if recording["request_body"] and recording["request_body"].get("format") == "json":
        assert recorded["results"][0]["text"]["type"] == mocked["results"][0]["text"]["type"]


async def test_usage_items_have_the_recorded_fields(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    key = next(item.key for item in store.keys("tinyfish") if item.label == "default")
    await client.get(
        "/", params={"query": "polyweb test"}, headers={**_SEARCH_HOST, "x-api-key": key}
    )
    await client.get("/", params={"page": "0"}, headers={**_SEARCH_HOST, "x-api-key": key})
    urls = ["https://example.com", "https://site.invalid/"]
    await client.post("/", json={"urls": urls}, headers={**_FETCH_HOST, "x-api-key": key})

    search = (await client.get("/usage", headers={**_SEARCH_HOST, "x-api-key": key})).json()
    fetch = (await client.get("/usage", headers={**_FETCH_HOST, "x-api-key": key})).json()

    assert list(search) == ["items", "total", "limit", "page", "total_pages", "has_more"]
    failed, done = search["items"]
    assert [list(failed), list(done)] == [_USAGE_SEARCH, _USAGE_SEARCH]
    assert (failed["status_code"], failed["result_count"], failed["results"]) == (400, None, [])
    assert failed["response_size_bytes"] is None and done["cached"] is None
    assert done["created_at"][10] == " " and len(done["created_at"]) == 19
    assert all(list(item) == _USAGE_FETCH for item in fetch["items"])
    assert {item["status"] for item in fetch["items"]} == {"completed", "failed"}


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
