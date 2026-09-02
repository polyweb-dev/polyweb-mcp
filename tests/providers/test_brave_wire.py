"""Wire-request hygiene coverage for BraveAdapter; all HTTP is mocked.

Locks the outgoing request shape: query/count/country/search_lang parameters,
the count cap at twenty, suppression of caller-client auth and headers, no
redirect following, and single-request 3xx handling that never forwards the
Brave ``X-Subscription-Token`` off-host.  Response/operation edges live in
``test_brave_edges.py``; runner/retry behavior lives in ``test_brave_resilience.py``.
"""

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

import freesearch.adapters.brave as brave_module
from freesearch.adapters.brave import BraveAdapter
from freesearch.contracts import SearchRequest, SearchResponse
from freesearch.resilience import ProviderOperationError
from freesearch.secrets import ProviderName


class _Resolver:
    def __init__(self, key: str = "edge-secret") -> None:
        self.key = SecretStr(key)

    def get(self, provider: ProviderName) -> SecretStr:
        return self.key


def _payload(**overrides: object) -> dict[str, object]:
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


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer caller", "X-API-Key": "caller-key"},
    )
    return BraveAdapter(client), client


def _no_leak_client(
    handler: Callable[[httpx.Request], httpx.Response],
    requests: list[httpx.Request],
    sent_kwargs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    """Build a caller-credentialed client whose send kwargs are recorded."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        auth=httpx.BasicAuth("caller-user", "caller-pass"),
        headers={"Authorization": "Bearer caller-token", "X-API-Key": "caller-key"},
    )
    original_send = client.send

    async def recording_send(request: httpx.Request, **kwargs: object) -> httpx.Response:
        sent_kwargs.update(kwargs)
        return await original_send(request, **kwargs)

    monkeypatch.setattr(client, "send", recording_send)
    return BraveAdapter(client), client


async def test_wire_request_preserves_query_and_drops_domain_and_caller_auth(monkeypatch) -> None:
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload())

    adapter, client = _adapter(handler)
    try:
        response = await adapter.search(
            SearchRequest(
                query="café & python?",
                domains=("example.com", "example.org"),
                country_code="us",
                language="en",
            )
        )
    finally:
        await client.aclose()

    request = requests[0]
    assert set(request.url.params) == {"q", "count", "country", "search_lang"}
    assert request.url.params["q"] == "café & python?"
    assert request.url.params["count"] == "10"
    assert request.url.params["country"] == "US"
    assert "Authorization" not in request.headers
    assert "X-API-Key" not in request.headers
    assert client.headers["Authorization"] == "Bearer caller"
    assert response.query == "café & python?"


@pytest.mark.parametrize(
    "limit,expected",
    [(1, "1"), (10, "10"), (20, "20"), (21, "20"), (100, "20")],
)
async def test_wire_count_is_capped_to_twenty(monkeypatch, limit: int, expected: str) -> None:
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload())

    adapter, client = _adapter(handler)
    try:
        await adapter.search(SearchRequest(query="query", limit=limit))
    finally:
        await client.aclose()

    assert requests[0].url.params["count"] == expected


def _assert_no_leak_wire(
    sent_kwargs: dict[str, object],
    requests: list[httpx.Request],
    response: SearchResponse,
) -> None:
    assert sent_kwargs["auth"] is None  # caller BasicAuth must be suppressed
    assert sent_kwargs["follow_redirects"] is False  # never follow redirects
    assert len(requests) == 1  # single request; no redirect follow-up
    wire = requests[0]
    assert wire.url.host == "api.search.brave.com"
    assert wire.headers["X-Subscription-Token"] == "edge-secret"
    assert "Authorization" not in wire.headers
    assert "X-API-Key" not in wire.headers
    assert response.query == "query"


async def test_wire_request_never_sends_caller_client_auth_and_never_follows_redirects(
    monkeypatch,
) -> None:
    """The Brave wire request must not leak caller-client credentials.

    The shared client carries caller ``httpx.BasicAuth`` and default
    ``Authorization``/``X-API-Key`` headers; the adapter must override auth and
    drop them, leaving only the Brave ``X-Subscription-Token``.
    """
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    requests: list[httpx.Request] = []
    sent_kwargs: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload())

    adapter, client = _no_leak_client(handler, requests, sent_kwargs, monkeypatch)
    try:
        response = await adapter.search(SearchRequest(query="query"))
    finally:
        await client.aclose()

    _assert_no_leak_wire(sent_kwargs, requests, response)


async def test_cross_origin_302_is_single_request_without_forwarding_token(monkeypatch) -> None:
    """A 302 to a cross-origin host must not trigger a second request or forward
    the Brave ``X-Subscription-Token``; it is surfaced as one normalized,
    non-retryable error (regression lock for redirect-following/forwarding).
    """
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    requests: list[httpx.Request] = []
    sent_kwargs: dict[str, object] = {}
    location = "https://attacker.example.net/steal"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "attacker.example.net":
            return httpx.Response(200, json=_payload())
        return httpx.Response(302, headers={"Location": location})

    adapter, client = _no_leak_client(handler, requests, sent_kwargs, monkeypatch)
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="query"))
    finally:
        await client.aclose()

    assert len(requests) == 1
    assert sent_kwargs["follow_redirects"] is False
    assert requests[0].url.host == "api.search.brave.com"
    assert requests[0].headers["X-Subscription-Token"] == "edge-secret"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.status_code is None
