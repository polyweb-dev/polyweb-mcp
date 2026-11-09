"""Shared Brave adapter builders for the ``test_brave*.py`` modules (never collected).

The client deliberately carries *contaminated* caller credentials
(``Authorization`` and ``X-API-Key``) so every suite built on it can keep
asserting transport isolation: the adapter must send only its own
``X-Subscription-Token`` and never forward the caller's headers.  Keys are
injected explicitly through the constructor; there is no ambient secret seam.
"""

from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter

# Caller headers that must never reach Brave; kept on every helper-built client.
CALLER_HEADERS: dict[str, str] = {"Authorization": "Bearer caller", "X-API-Key": "caller-key"}


def brave_payload(**overrides: object) -> dict[str, object]:
    """Return one representative well-formed Brave web-search payload."""
    payload: dict[str, object] = {
        "web": {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com/article",
                    "description": "A result snippet.",
                    "page_age": "2024-01-02T03:04:05Z",
                    "language": "en",
                }
            ]
        }
    }
    payload.update(overrides)
    return payload


def brave_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    key: str,
    runner: Any = None,
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    """Build a keyed adapter over a mock transport with contaminated caller headers."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers=dict(CALLER_HEADERS),
    )
    return BraveAdapter(client, runner=runner, api_key=SecretStr(key)), client
