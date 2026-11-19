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
from tests._support.shape import assert_same_shape

_RECORDINGS = sorted((Path(__file__).parent / "recordings" / "tavily").glob("*.json"))
_FORWARDED = {"content-type", "x-client-source", "x-tavily-access-mode", "user-agent"}
_IMPORTANT = ("content-type", "content-security-policy")
_WRONG_KEY = "tvly-dev-0000000000000000000000000000000"

#: State that a recording needs before replay (the live keyless cap was spent).
_SETUP: dict[str, Callable[[MockStore], object]] = {
    "search__keyless": lambda store: store.set_keyless("tavily", per_day=0),
    "extract__keyless": lambda store: store.set_keyless("tavily", per_day=0),
}


def _same_shape(recorded: Any, mocked: Any) -> None:
    assert_same_shape(recorded, mocked)


def _headers(name: str, recording: dict[str, Any], key: str) -> dict[str, str]:
    recorded = recording["request_headers"]
    headers = {name: value for name, value in recorded.items() if name in _FORWARDED}
    headers["host"] = urlsplit(recording["url"]).hostname or ""
    if "authorization" in recorded:
        headers["authorization"] = f"Bearer {_WRONG_KEY if 'invalid_key' in name else key}"
    return headers


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
    _same_shape(recording["response_body"], response.json())


async def test_default_account_reports_the_recorded_free_plan_values(
    client: httpx.AsyncClient, tavily_key: str
) -> None:
    """The seeded Researcher account is prepaid with no PAYGO and no key limit, as recorded."""

    recording = json.loads((_RECORDINGS[0].parent / "usage__keyed.json").read_text("utf-8"))
    recorded = recording["response_body"]
    response = await client.get(
        "/usage", headers={"host": "api.tavily.com", "authorization": f"Bearer {tavily_key}"}
    )

    mocked = response.json()
    assert mocked["key"]["limit"] == recorded["key"]["limit"]
    for field in ("current_plan", "plan_limit", "paygo_usage", "paygo_limit"):
        assert mocked["account"][field] == recorded["account"][field], field


async def test_postpaid_usage_keeps_the_recorded_shape(
    client: httpx.AsyncClient, store: MockStore, tavily_key: str
) -> None:
    """PAYGO numbers replace the recorded nulls; every other field keeps its type."""

    recording = json.loads((_RECORDINGS[0].parent / "usage__keyed.json").read_text("utf-8"))
    store.set_funding("tavily", "postpaid", overage_limit=None)
    response = await client.get(
        "/usage", headers={"host": "api.tavily.com", "authorization": f"Bearer {tavily_key}"}
    )

    assert response.status_code == recording["status"]
    _same_shape(recording["response_body"], response.json())
