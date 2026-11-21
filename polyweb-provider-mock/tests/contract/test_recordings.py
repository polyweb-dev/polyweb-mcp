"""Checks across every provider's recordings: no stored result content, real ``Server`` headers.

Brave's terms forbid storing its results, so every success recording must be
scrubbed (``tests/_support/scrub.py``). The missing-key recordings, replayed
without a key, prove that each plugin sends the provider's real ``Server``
header, or none where the provider sends none.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from tests._support.scrub import scrub_recording, unscrubbed

_ROOT = Path(__file__).parent / "recordings"
_ALL = sorted(_ROOT.glob("*/*.json"))
_MISSING_KEY = [
    path for path in _ALL if "__missing_key" in path.stem or "__missing_bearer" in path.stem
]


def _load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def test_every_success_recording_is_scrubbed() -> None:
    successes = [path for path in _ALL if 200 <= _load(path)["status"] < 300]
    problems = {_id(path): unscrubbed(_load(path)) for path in successes}

    assert len(successes) >= 30
    assert {name: found for name, found in problems.items() if found} == {}


def test_the_scrub_check_flags_raw_content_and_scrubbing_fixes_it() -> None:
    raw = {
        "status": 200,
        "response_body": {
            "query": "kept",
            "sources": {"https://news.site.test/a": {"title": "A headline"}},
            "results": [{"url": "https://example.com/", "snippet": "Third-party text"}],
        },
    }
    failed = {**raw, "status": 422}

    assert len(unscrubbed(raw)) == 3
    scrubbed = scrub_recording(raw)
    assert unscrubbed(scrubbed) == []
    assert scrubbed["response_body"]["query"] == "kept"
    assert scrubbed["response_body"]["results"][0]["url"] == "https://example.com/"
    assert unscrubbed(failed) == [] and scrub_recording(failed) is failed


@pytest.mark.parametrize("path", _MISSING_KEY, ids=[_id(path) for path in _MISSING_KEY])
async def test_missing_key_replay_sends_the_recorded_server_header(
    path: Path, client: httpx.AsyncClient
) -> None:
    recording = _load(path)
    url = urlsplit(recording["url"])
    headers = {"host": url.hostname or ""}
    if "content-type" in recording["request_headers"]:
        headers["content-type"] = recording["request_headers"]["content-type"]
    body = recording["request_body"]

    response = await client.request(
        recording["method"],
        f"{url.path}?{url.query}" if url.query else url.path,
        headers=headers,
        content=None if body is None else json.dumps(body).encode(),
    )

    recorded = {name.lower(): value for name, value in recording["response_headers"].items()}
    assert response.status_code == recording["status"]
    assert response.headers.get("server") == recorded.get("server")
