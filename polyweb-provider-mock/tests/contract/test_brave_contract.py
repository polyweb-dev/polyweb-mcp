"""Contract: each recorded live Brave exchange, replayed against the mock.

The recordings (2026-11-17, direct HTTPX 0.28.1, no SDK) are sanitized: the
subscription tokens are ``<REDACTED>`` and error UUIDs are replaced. Each
replay sends the recorded path and query with the seeded Search key (the
Answers key for the cross-product case, a wrong key for ``bogus_key``, none
for ``missing_key``) and checks the status, the ``X-RateLimit-*`` headers,
and the JSON shape: the same keys and value types, recursively. Values may
differ, except the rate-limit pairs of a fresh Search plan (its $5 free
credit does not show in them), which must equal the live ``50, 0`` / ``49, 0``.
"""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "brave").glob("*.json"))
_WRONG_KEY = "BSA0000000000000000000000000000"
_RATE_HEADERS = ("x-ratelimit-limit", "x-ratelimit-policy", "x-ratelimit-remaining")
_PRESENCE = (*_RATE_HEADERS, "x-ratelimit-reset", "retry-after", "server-timing", "vary")


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked, lists="any")


def _headers(name: str, recording: dict[str, Any], keys: dict[str, str]) -> dict[str, str]:
    headers = {"host": urlsplit(recording["url"]).hostname or ""}
    if "x-subscription-token" in recording["request_headers"]:
        if "bogus_key" in name:
            headers["x-subscription-token"] = _WRONG_KEY
        else:
            headers["x-subscription-token"] = keys["answers" if "answers_key" in name else "search"]
    return headers


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 10
    for path in _RECORDINGS:
        text = path.read_text(encoding="utf-8")
        recording = json.loads(text)
        token = recording["request_headers"].get("x-subscription-token", "<REDACTED>")
        assert token == "<REDACTED>"
        assert re.search(r"BSA[A-Za-z0-9_]{20,}", text) is None


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    keys = {item.label: item.key for item in store.keys("brave")}
    url = urlsplit(recording["url"])

    response = await client.get(
        f"{url.path}?{url.query}" if url.query else url.path,
        headers=_headers(path.stem, recording, keys),
    )

    assert response.status_code == recording["status"]
    recorded_headers = recording["response_headers"]
    assert response.headers["content-type"] == recorded_headers["content-type"]
    for header in _PRESENCE:
        assert (header in response.headers) == (header in recorded_headers), header
    for header in _RATE_HEADERS:
        if header in recorded_headers:
            assert response.headers[header] == recorded_headers[header], header
    if "x-ratelimit-reset" in recorded_headers:
        assert re.fullmatch(r"1, \d+", response.headers["x-ratelimit-reset"])
    _same_shape(_by_url(recording["response_body"]), _by_url(response.json()))


def _by_url(body: Any) -> Any:
    """Turn the URL-keyed Context ``sources`` map into a list, after checking its keys."""

    if not isinstance(body, dict) or not isinstance(body.get("sources"), dict):
        return body
    grounding = body.get("grounding", {})
    urls = {item["url"] for item in grounding.get("generic", [])}
    assert set(body["sources"]) == urls
    return {**body, "sources": list(body["sources"].values())}
