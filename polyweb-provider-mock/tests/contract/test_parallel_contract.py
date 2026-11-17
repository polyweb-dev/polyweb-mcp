"""Contract: each recorded live Parallel exchange, replayed against the mock.

The recordings (2026-11-17, direct HTTPX 0.28.1, no SDK) are sanitized: keys,
bearer tokens, and cookies are ``<REDACTED>`` and IDs keep only their format.
Each replay sends the recorded method, host, path, and body with a seeded mock
key (a wrong key for ``invalid_*`` cases, none for ``missing_*``) and checks
the status, the important headers, and the JSON shape: the same keys and value
types, recursively. A recorded ``null`` also matches a string, because every
such field is documented as ``string | null``. Values may differ.
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

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "parallel").glob("*.json"))
_FORWARDED = {"content-type", "user-agent", "accept"}
_HEX_ID = re.compile(r"^[0-9a-f]{32}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked, null_accepts_str=True)


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {header: value for header, value in recorded.items() if header in _FORWARDED}
    headers["host"] = urlsplit(recording["url"]).hostname or ""
    wrong = name.endswith("__invalid_key") or name.endswith("__invalid_bearer")
    if "x-api-key" in recorded:
        headers["x-api-key"] = "not-a-real-parallel-key" if wrong else key
    if "authorization" in recorded:
        headers["authorization"] = "Bearer bogus"
    return headers


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 10
    for path in _RECORDINGS:
        recording = json.loads(path.read_text(encoding="utf-8"))
        for part in ("request_headers", "response_headers"):
            for header in ("x-api-key", "authorization", "cookie", "set-cookie"):
                value = recording[part].get(header)
                assert value in {None, "<REDACTED>", "Bearer <REDACTED>"}, (path.name, header)


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    key = next(item.key for item in store.keys("parallel") if item.label == "default")
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        urlsplit(recording["url"]).path,
        headers=_headers(path.stem, recording, key),
        content=None if body is None else json.dumps(body).encode(),
    )

    recorded_headers = recording["response_headers"]
    assert response.status_code == recording["status"]
    assert response.headers["content-type"] == recorded_headers["content-type"]
    assert ("x-request-id" in response.headers) == ("x-request-id" in recorded_headers)
    assert response.headers.get("www-authenticate") == recorded_headers.get("www-authenticate")
    request_id = response.headers.get("x-request-id")
    if request_id is not None:
        pattern = _UUID if path.stem.startswith("balance") else _HEX_ID
        assert pattern.match(request_id), request_id
    payload = response.json()
    _same_shape(recording["response_body"], payload)
    if isinstance(payload.get("error"), dict) and "ref_id" in payload["error"]:
        assert payload["error"]["ref_id"] == request_id
    for field, prefix in (("search_id", "search_"), ("extract_id", "extract_")):
        if field in payload:
            assert payload[field] == f"{prefix}{request_id}"
            assert payload["session_id"] == f"session_{request_id}"
    if not path.stem.endswith("__success"):
        # Auth and validation answers are deterministic apart from the request ID.
        expected = json.loads(json.dumps(recording["response_body"]))
        if "error" in expected and isinstance(expected["error"], dict):
            expected["error"]["ref_id"] = request_id
        assert payload == expected
