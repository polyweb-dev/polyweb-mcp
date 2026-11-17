"""Contract: each recorded live Exa exchange, replayed against the mock.

The recordings (2026-11-17, ``exa-py`` 2.18.1) are sanitized: keys are
``<REDACTED>``. Each replay sends the recorded method, path, and body with a
seeded mock key (a wrong key for ``bogus_key``, the regular search key for
``regular_key``, none when the recording had none) and checks the status, the
important headers, and the recursive JSON shape. Values may differ.
"""

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "exa").glob("*.json"))
_WRONG_KEY = "00000000-0000-4000-8000-000000000000"
#: Headers whose presence must match the recording; values are per request.
_PRESENCE = (
    "x-request-id",
    "x-exa-queued",
    "x-exa-region",
    "payment-required",
    "www-authenticate",
    "access-control-expose-headers",
)


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked, lists="pairwise")


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {"host": urlsplit(recording["url"]).hostname or "", "user-agent": "exa-py/unknown"}
    if "content-type" in recorded:
        headers["content-type"] = recorded["content-type"]
    if "x-api-key" in recorded:
        headers["x-api-key"] = _WRONG_KEY if "bogus_key" in name else key
    return headers


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 14
    for path in _RECORDINGS:
        recording = json.loads(path.read_text(encoding="utf-8"))
        assert recording["request_headers"].get("x-api-key", "<REDACTED>") == "<REDACTED>"
        assert "authorization" not in recording["request_headers"]


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    key = next(item.key for item in store.keys("exa") if item.label == "default")
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
    mocked = response.json()
    _same_shape(recording["response_body"], mocked)
    if "requestId" in mocked:
        assert response.headers["x-request-id"] == mocked["requestId"]
        assert len(mocked["requestId"]) == 32 and int(mocked["requestId"], 16) >= 0


async def test_payment_challenge_header_encodes_the_body(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/search", json={"query": "x", "numResults": 1}, headers={"host": "api.exa.ai"}
    )

    challenge = json.loads(base64.b64decode(response.headers["payment-required"]))
    body = response.json()
    assert (
        challenge["resource"]
        == body["resource"]
        == {
            "url": "https://api.exa.ai/search",
            "description": "Exa /search endpoint",
            "mimeType": "application/json",
        }
    )
    assert {item["amount"] for item in body["accepts"]} == {"7000"}
    assert body["extensions"]["agentkit"]["info"]["uri"] == "https://api.exa.ai/search"
    assert response.headers["www-authenticate"].startswith('Payment id="')
