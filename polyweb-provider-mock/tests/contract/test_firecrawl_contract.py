"""Contract: each recorded live Firecrawl exchange, replayed against the mock.

The recordings (2026-11-17, ``firecrawl-py`` 4.41.0) are sanitized: keys and
the signup token are ``<REDACTED>``. Each replay sends the recorded method,
path, and body with a seeded mock key (a wrong key for ``invalid_key``, none
when the recording had none) and checks the status, the important headers,
and the recursive JSON shape. Values may differ.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "firecrawl").glob("*.json"))
_WRONG_KEY = "fc-00000000000000000000000000000000"
_PRESENCE = ("www-authenticate", "x-response-time", "access-control-allow-origin", "retry-after")


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked, lists="pairwise")


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {"host": urlsplit(recording["url"]).hostname or ""}
    if "content-type" in recorded:
        headers["content-type"] = recorded["content-type"]
    if "authorization" in recorded:
        headers["authorization"] = f"Bearer {_WRONG_KEY if 'invalid_key' in name else key}"
    return headers


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 12
    for path in _RECORDINGS:
        text = path.read_text(encoding="utf-8")
        recording = json.loads(text)
        assert recording["request_headers"].get("authorization", "Bearer <REDACTED>") == (
            "Bearer <REDACTED>"
        )
        assert "fc-" not in text


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    key = next(item.key for item in store.keys("firecrawl") if item.label == "default")
    url = urlsplit(recording["url"])
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        url.path,
        headers=_headers(path.stem, recording, key),
        content=None if body is None else json.dumps(body).encode(),
    )

    assert response.status_code == recording["status"]
    assert response.headers["content-type"] == recording["response_headers"]["content-type"]
    for header in _PRESENCE:
        assert (header in response.headers) == (header in recording["response_headers"]), header
    if "www-authenticate" in response.headers:
        assert (
            response.headers["www-authenticate"]
            == (recording["response_headers"]["www-authenticate"])
        )
    _same_shape(recording["response_body"], response.json())


async def test_bad_format_union_lists_every_format_branch(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    path = Path(__file__).parent / "recordings" / "firecrawl" / "scrape__bad_format.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))["response_body"]
    key = next(item.key for item in store.keys("firecrawl") if item.label == "default")

    response = await client.post(
        "/v2/scrape",
        json={"url": "https://example.com", "formats": ["not-a-real-format"]},
        headers={"host": "api.firecrawl.dev", "authorization": f"Bearer {key}"},
    )

    assert response.json() == recorded
