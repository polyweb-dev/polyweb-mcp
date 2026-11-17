"""Contract: each recorded live Tavily exchange, replayed against the mock.

The recordings (2026-11-17, ``tavily-python`` 0.7.27) are sanitized: keys are
``<REDACTED>``. Each replay sends the recorded method, path, and body with a
seeded mock key (or a wrong key for the ``invalid_key`` cases, or none when
the recording had none) and checks the status, the important headers, and
the JSON shape: the same keys and value types, recursively. Values may differ.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from polyweb_provider_mock.store import MockStore

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "tavily").glob("*.json"))
_FORWARDED = {"content-type", "x-client-source", "x-tavily-access-mode", "user-agent"}
_IMPORTANT = ("content-type", "content-security-policy")
_WRONG_KEY = "tvly-dev-0000000000000000000000000000000"

#: State that a recording needs before replay (the live keyless cap was spent).
_SETUP: dict[str, Callable[[MockStore], object]] = {
    "search__keyless": lambda store: store.set_keyless("tavily", per_day=0),
    "extract__keyless": lambda store: store.set_keyless("tavily", per_day=0),
}


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def assert_same_shape(recorded: Any, mocked: Any, path: str = "$") -> None:
    """Assert equal keys and value types recursively; list items match the first item."""

    assert _kind(mocked) == _kind(recorded), f"{path}: {_kind(mocked)} != {_kind(recorded)}"
    if isinstance(recorded, dict):
        assert set(mocked) == set(recorded), f"{path}: keys {sorted(mocked)} != {sorted(recorded)}"
        for key, value in recorded.items():
            assert_same_shape(value, mocked[key], f"{path}.{key}")
    elif isinstance(recorded, list) and recorded:
        assert mocked, f"{path}: the mock returned an empty list"
        for index, item in enumerate(mocked):
            assert_same_shape(recorded[0], item, f"{path}[{index}]")


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {name: value for name, value in recorded.items() if name in _FORWARDED}
    headers["host"] = urlsplit(recording["url"]).hostname or ""
    if "authorization" in recorded:
        headers["authorization"] = f"Bearer {_WRONG_KEY if 'invalid_key' in name else key}"
    return headers


@pytest.mark.parametrize(
    ("recorded", "mocked"),
    [
        ({"a": 1, "b": None}, {"a": 1}),
        ({"a": 1}, {"a": "1"}),
        ({"a": None}, {"a": "x"}),
        ({"a": [{"x": 1}]}, {"a": [{"y": 1}]}),
        ({"a": [{"x": 1}]}, {"a": []}),
        ({"a": True}, {"a": 1}),
    ],
)
def test_shape_comparison_rejects_mismatches(recorded: Any, mocked: Any) -> None:
    with pytest.raises(AssertionError):
        assert_same_shape(recorded, mocked)


def test_every_recording_is_sanitized() -> None:
    assert len(_RECORDINGS) == 15
    for path in _RECORDINGS:
        text = path.read_text(encoding="utf-8")
        recording = json.loads(text)
        assert recording["request_headers"].get("authorization", "Bearer <REDACTED>") == (
            "Bearer <REDACTED>"
        )
        assert "tvly-" not in text


@pytest.mark.parametrize("path", _RECORDINGS, ids=[path.stem for path in _RECORDINGS])
async def test_mock_matches_recorded_exchange(
    path: Path, client: httpx.AsyncClient, store: MockStore, tavily_key: str
) -> None:
    recording = json.loads(path.read_text(encoding="utf-8"))
    _SETUP.get(path.stem, lambda _store: None)(store)
    url = urlsplit(recording["url"])
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        url.path,
        headers=_headers(path.stem, recording, tavily_key),
        content=None if body is None else json.dumps(body).encode(),
    )

    assert response.status_code == recording["status"]
    for header in _IMPORTANT:
        if header in recording["response_headers"]:
            assert response.headers.get(header) == recording["response_headers"][header], header
    assert ("retry-after" in response.headers) == ("retry-after" in recording["response_headers"])
    if "retry-after" in response.headers:
        assert int(response.headers["retry-after"]) >= 0
    assert_same_shape(recording["response_body"], response.json())
