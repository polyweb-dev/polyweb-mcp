"""Contract: each recorded live Keenable exchange, replayed against the mock.

The eight recordings (2026-11-17, raw HTTPX 0.28.1, no SDK) are keyless: four
successes and four 400s. No keyed request was recorded, so the keyed shapes
are checked against the documented ``usage`` object in the unit tests. Each
replay sends the recorded method, path, query, headers, and body and checks
the status, the important headers, ``request_id`` equal to ``X-Request-Id``,
and the JSON shape (same keys and value types, recursively).
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "keenable").glob("*.json"))
_FORWARDED = {"content-type", "x-keenable-title", "user-agent", "accept"}
_RATE_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked)


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 8
    for path in _RECORDINGS:
        recording = json.loads(path.read_text(encoding="utf-8"))
        assert "x-api-key" not in recording["request_headers"]
        assert "authorization" not in recording["request_headers"]
        assert "keen_" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(path: Path, client: httpx.AsyncClient) -> None:
    recording: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    url = urlsplit(recording["url"])
    headers = {k: v for k, v in recording["request_headers"].items() if k in _FORWARDED}
    headers["host"] = url.hostname or ""
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        f"{url.path}?{url.query}" if url.query else url.path,
        headers=headers,
        content=None if body is None else json.dumps(body).encode(),
    )

    recorded_headers = recording["response_headers"]
    assert response.status_code == recording["status"]
    assert response.headers["content-type"] == recorded_headers["content-type"]
    for name in ("vary", "access-control-expose-headers", "access-control-allow-credentials"):
        assert response.headers[name] == recorded_headers[name]
    for name in _RATE_HEADERS:
        assert (name in response.headers) == (name in recorded_headers), name
    if "x-ratelimit-limit" in recorded_headers:
        assert response.headers["x-ratelimit-limit"] == recorded_headers["x-ratelimit-limit"]
        assert response.headers["x-ratelimit-reset"].endswith("Z")
    mocked = response.json()
    if "request_id" in recording["response_body"]:
        assert mocked["request_id"] == response.headers["x-request-id"]
    _same_shape(recording["response_body"], mocked)
    if recording["status"] != 200:
        recorded = recording["response_body"]
        assert (mocked["code"], mocked["type"], mocked["param"]) == (
            recorded["code"],
            recorded["type"],
            recorded["param"],
        )
        assert (mocked["error"], mocked["message"], mocked["fix"]) == (
            recorded["error"],
            recorded["message"],
            recorded["fix"],
        )
