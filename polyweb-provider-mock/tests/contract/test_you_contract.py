"""Contract: each recorded live You.com exchange, replayed against the mock.

The recordings (2026-11-17, direct HTTPX 0.28.1, no SDK) are sanitized: keys,
cookies, and the account id are ``<REDACTED>``. Each replay sends the
recorded method, host, path, and body with a seeded mock key (a wrong key for
the ``invalid_key`` cases, none when the recording had none) and checks the
status, the host-specific gateway or edge headers, and the JSON shape: the
same keys and value types, recursively. Values may differ.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "you").glob("*.json"))
_WRONG_KEY = "ydc-sk-0000000000000000000000000000000000000000000000000000000000"
#: Headers whose presence must match the recording (their values are random IDs).
_PRESENCE = (
    "x-amzn-requestid",
    "x-amz-apigw-id",
    "x-amzn-trace-id",
    "x-amzn-remapped-server",
    "x-request-id",
    "x-correlation-id",
    "cf-ray",
    "retry-after",
    "x-ratelimit-limit",
)


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked, lists="any")


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {"host": urlsplit(recording["url"]).hostname or ""}
    if "content-type" in recorded:
        headers["content-type"] = recorded["content-type"]
    if "x-api-key" in recorded:
        headers["x-api-key"] = _WRONG_KEY if "invalid_key" in name else key
    return headers


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 14
    for path in _RECORDINGS:
        text = path.read_text(encoding="utf-8")
        recording = json.loads(text)
        for name in ("x-api-key", "cookie"):
            assert recording["request_headers"].get(name, "<REDACTED>") == "<REDACTED>"
        assert recording["response_headers"].get("set-cookie", "<REDACTED>") == "<REDACTED>"
        assert "ydc-sk-" not in text


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    key = next(item.key for item in store.keys("you") if item.label == "default")
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        urlsplit(recording["url"]).path,
        headers=_headers(path.stem, recording, key),
        content=None if body is None else json.dumps(body).encode(),
    )

    assert response.status_code == recording["status"]
    recorded_headers = recording["response_headers"]
    assert response.headers["content-type"] == recorded_headers["content-type"]
    assert response.headers.get("x-amzn-errortype") == recorded_headers.get("x-amzn-errortype")
    for header in _PRESENCE:
        assert (header in response.headers) == (header in recorded_headers), header
    assert "content-encoding" not in response.headers
    _same_shape(recording["response_body"], response.json())
