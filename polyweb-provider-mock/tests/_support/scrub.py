"""Scrub third-party result content from success recordings, and check that it is gone.

Brave's terms forbid storing its results, so no in-repo success recording
keeps any provider's result content. Scrubbing keeps the status, headers,
structure, key sets, list lengths, numbers, and booleans, and replaces:

- every URL whose host is not ``example.com`` (or a subdomain) with a
  synthetic ``https://example.com/synthetic/<hash>`` URL, in values and in
  object keys, consistently (the same URL always maps to the same value);
- every bare domain name with ``site-<hash>.example.com``;
- every other string with ``Synthetic <field> <hash>.``, except structural
  fields (identifiers, enums, dates, the echoed query; see :data:`KEEP`).

Run ``uv run python -m tests._support.scrub tests/contract/recordings/*/*.json``
after adding recordings; ``tests/contract/test_recordings.py`` fails on any
success recording that still holds third-party content.
"""

import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

__all__ = ["KEEP", "scrub_file", "scrub_recording", "unscrubbed"]

#: Fields whose string values are structural (ids, enums, dates, our own query).
KEEP = frozenset(
    {
        "acquired_at",
        "age",
        "billingPeriodEnd",
        "billingPeriodStart",
        "cacheState",
        "cachedAt",
        "contentType",
        "currency",
        "current_plan",
        "date",
        "dateFrom",
        "dateTo",
        "description_source",
        "duration",
        "error",
        "extract_id",
        "format",
        "id",
        "language",
        "message",
        "mode",
        "page_age",
        "proxyUsed",
        "publishedDate",
        "query",
        "request_id",
        "requestId",
        "resolvedSearchType",
        "scheme",
        "score",
        "scrapeId",
        "search_id",
        "search_uuid",
        "session_id",
        "source",
        "status",
        "subtype",
        "type",
        "unit",
        "unmatched_selectors",
    }
)
#: Fields kept under a parent field: the echoed query object, usage SKU names.
_KEEP_UNDER = {"query": None, "usage": frozenset({"name"})}
_NOT_UNDER_QUERY = frozenset({"related_queries"})
_DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", re.IGNORECASE)
_SYNTHETIC = "Synthetic "


def _digest(value: str, size: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:size]


def _clean_host(host: str | None) -> bool:
    host = (host or "").lower()
    return host == "example.com" or host.endswith(".example.com")


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def _url(value: str) -> str:
    if _clean_host(urlsplit(value).hostname):
        return value
    return f"https://example.com/synthetic/{_digest(value)}"


def _kept(key: str | None, parent: str | None) -> bool:
    if key in KEEP:
        return True
    if parent == "query":
        return key not in _NOT_UNDER_QUERY
    allowed = _KEEP_UNDER.get(parent or "")
    return allowed is not None and key in allowed


def _text(value: str, key: str | None, parent: str | None) -> str:
    if not value or value == "data:,":
        return value
    if _is_url(value):
        return _url(value)
    if _DOMAIN.match(value):
        return value if _clean_host(value) else f"site-{_digest(value, 6)}.example.com"
    if _kept(key, parent):
        return value
    return f"{_SYNTHETIC}{key or 'text'} {_digest(value, 8)}."


def _scrub(value: Any, key: str | None, parent: str | None) -> Any:
    if isinstance(value, dict):
        return {
            (_url(name) if _is_url(name) else name): _scrub(item, name, key)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, key, parent) for item in value]
    if isinstance(value, str):
        return _text(value, key, parent)
    return value


def _success(recording: dict[str, Any]) -> bool:
    return 200 <= int(recording["status"]) < 300


def scrub_recording(recording: dict[str, Any]) -> dict[str, Any]:
    """Return the recording with third-party content of a success body replaced."""

    if not _success(recording):
        return recording
    return {**recording, "response_body": _scrub(recording["response_body"], None, None)}


def _problems(value: Any, key: str | None, parent: str | None, path: str) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for name, item in value.items():
            if _is_url(name) and not _clean_host(urlsplit(name).hostname):
                found.append(f"{path} key {name[:60]!r}")
            found += _problems(item, name, key, f"{path}.{name}")
        return found
    if isinstance(value, list):
        return [
            problem
            for index, item in enumerate(value)
            for problem in _problems(item, key, parent, f"{path}[{index}]")
        ]
    if not isinstance(value, str) or _text(value, key, parent) == value:
        return []
    if value.startswith(_SYNTHETIC):
        return []
    return [f"{path} = {value[:60]!r}"]


def unscrubbed(recording: dict[str, Any]) -> list[str]:
    """Return the paths of a success body that still hold third-party content."""

    if not _success(recording):
        return []
    return _problems(recording["response_body"], None, None, "$")


def scrub_file(path: Path) -> bool:
    """Scrub one recording file in place, keeping its JSON layout; return whether it changed."""

    text = path.read_text(encoding="utf-8")
    recording = json.loads(text)
    scrubbed = scrub_recording(recording)
    if scrubbed == recording:
        return False
    ascii_only = json.dumps(recording, indent=2, ensure_ascii=True) == text.rstrip("\n")
    output = json.dumps(scrubbed, indent=2, ensure_ascii=ascii_only)
    path.write_text(output + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(item) for item in (sys.argv[1:] if argv is None else argv)]
    changed = [path for path in paths if scrub_file(path)]
    for path in changed:
        print(f"scrubbed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
