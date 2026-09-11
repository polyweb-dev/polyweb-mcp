"""You.com adapter lifecycle: construction and borrowed-transport wire tests.

Covers AC-2 (fail-closed construction, no ambient fallback), AC-3 (scoped
client never mutates the caller's client, no auth leak, ``aclose`` closes
only the owned client), the AC-4 wire contract for the search/fetch POSTs
(exact paths, resolver-only ``X-API-Key``, forwarded User-Agent, and the
shared client's full timeout phase policy reasserted per request), and the
cross-origin redirect regression (the owned client never follows a 3xx
``Location``, so the resolver key never reaches another origin).
"""

import json

import httpx
import pytest

import freesearch.adapters.youcom as youcom_module
from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest
from tests.unit.adapters._youcom_test_support import (
    _WIRE_TIMEOUT,
    _assert_wire_auth_and_timeout,
    _FakeClient,
    _KeyResolver,
    _NoKeyResolver,
    _search_payload,
    _wired,
    _WireRecorder,
    fake_resolver,  # noqa: F401  (autouse fixture registered via import)
)


async def _scoped_adapter(client: httpx.AsyncClient) -> tuple[YoucomAdapter, httpx.AsyncClient]:
    """Build an adapter over a caller client and close both, always."""
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(client)
    finally:
        await client.aclose()
        if adapter is not None:
            await adapter.aclose()
    assert adapter is not None
    return adapter, client


def test_adapter_implements_provider_adapter_interface() -> None:
    adapter = YoucomAdapter(_FakeClient())

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "you"
    assert adapter.capabilities.search is True
    assert adapter.capabilities.fetch is True
    assert adapter.capabilities.cost_estimate is True
    assert adapter.capabilities.quota is True  # AC-1: USD-balance quota enabled
    assert adapter.capabilities.health is False


def test_init_wraps_caller_client_in_shared_runner() -> None:
    client = _FakeClient()

    adapter = YoucomAdapter(client)

    assert adapter._runner.client is client


async def test_init_missing_resolver_credential_fails_closed(monkeypatch) -> None:
    resolver = _NoKeyResolver()
    monkeypatch.setattr(youcom_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            YoucomAdapter(client)

        # The resolver must be asked for exactly the You.com credential.
        assert resolver.requested == [ProviderName.YOU]
        assert excinfo.value.error.provider == "you"
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        assert excinfo.value.error.status_code is None
        assert "no You.com API key configured" in excinfo.value.error.message
        # The failing path must leave the shared client untouched.
        assert "X-API-Key" not in client.headers
    finally:
        await client.aclose()


async def test_init_missing_credential_never_falls_back_to_ambient_key(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_YOU_API_KEY", "ambient-you-leak")
    resolver = _NoKeyResolver()
    monkeypatch.setattr(youcom_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            YoucomAdapter(client)
        assert resolver.requested == [ProviderName.YOU]
        assert excinfo.value.error.code == "configuration_error"
        assert "ambient-you-leak" not in str(excinfo.value)
        assert "ambient-you-leak" not in str(client.headers)
    finally:
        await client.aclose()


async def test_init_scopes_credential_to_adapter_owned_client(monkeypatch) -> None:
    resolver = _KeyResolver("sk-you-super-secret-abc")
    monkeypatch.setattr(youcom_module, "get_provider_secret_resolver", lambda: resolver)

    adapter, client = await _scoped_adapter(httpx.AsyncClient())

    assert resolver.requested == [ProviderName.YOU]
    assert adapter._owned_http is not None
    assert adapter._owned_http is not client
    assert adapter._owned_http.headers.get("X-API-Key") == "sk-you-super-secret-abc"
    assert "sk-you-super-secret-abc" not in repr(adapter)
    assert "sk-you-super-secret-abc" not in str(adapter)


async def test_init_does_not_mutate_caller_http_client() -> None:
    client = httpx.AsyncClient()
    headers_before = dict(client.headers)
    base_url_before = str(client.base_url)

    _adapter, client = await _scoped_adapter(client)

    assert dict(client.headers) == headers_before
    assert str(client.base_url) == base_url_before


async def test_caller_auth_headers_never_leak_into_scoped_client() -> None:
    client = httpx.AsyncClient(
        headers={
            "Authorization": "Bearer caller-token-1",
            "X-API-Key": "caller-xkey-2",
            "User-Agent": "youcom-test-ua/1.0",
        }
    )

    adapter, client = await _scoped_adapter(client)

    owned = adapter._owned_http.headers
    # The resolver's You.com key is the only auth header on the scoped client;
    # caller auth headers never leak into it, and the User-Agent is forwarded.
    assert owned.get("X-API-Key") == "sk-you-test-secret-1"
    assert "authorization" not in owned
    assert "caller-token-1" not in owned.values()
    assert "caller-xkey-2" not in owned.values()
    assert owned.get("User-Agent") == "youcom-test-ua/1.0"


async def test_aclose_closes_owned_client_and_leaves_shared_client_open() -> None:
    client = httpx.AsyncClient()
    try:
        adapter = YoucomAdapter(client)
        await adapter.aclose()

        assert adapter._owned_http is not None
        assert adapter._owned_http.is_closed is True
        assert client.is_closed is False
    finally:
        await client.aclose()


# --- end-to-end wire behavior over the borrowed transport ------------------


async def test_search_wire_post_path_body_headers_and_timeout() -> None:
    recorder = _WireRecorder()
    async with _wired(recorder) as adapter:
        response = await adapter.search(
            SearchRequest(
                query="python async",
                limit=7,
                domains=("example.com", "docs.org"),
                country_code="US",
                language="en",
            )
        )

    assert response.query == "python async"
    assert [request.method for request in recorder.requests] == ["POST"]
    assert [str(request.url) for request in recorder.requests] == ["https://ydc-index.io/v1/search"]
    assert json.loads(recorder.requests[0].content) == {
        "query": "python async",
        "count": 7,
        "include_domains": ["example.com", "docs.org"],
        "country": "US",
        "language": "en",
    }
    _assert_wire_auth_and_timeout(recorder.requests, "sk-you-test-secret-1", _WIRE_TIMEOUT)


async def test_fetch_wire_post_path_body_headers_and_timeout() -> None:
    recorder = _WireRecorder()
    async with _wired(recorder) as adapter:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert [request.method for request in recorder.requests] == ["POST"]
    assert [str(request.url) for request in recorder.requests] == [
        "https://ydc-index.io/v1/contents"
    ]
    assert json.loads(recorder.requests[0].content) == {
        "urls": ["https://example.com/doc"],
        "formats": ["markdown", "metadata"],
        "max_age": 0,
    }
    _assert_wire_auth_and_timeout(recorder.requests, "sk-you-test-secret-1", _WIRE_TIMEOUT)


async def test_search_omits_optionals_when_unset() -> None:
    recorder = _WireRecorder(search={"results": {}})
    async with _wired(recorder) as adapter:
        await adapter.search(SearchRequest(query="bare"))

    assert json.loads(recorder.requests[0].content) == {"query": "bare", "count": 10}


async def test_owned_client_never_follows_cross_origin_redirect() -> None:
    """A 3xx ``Location`` to another origin must never be followed by the
    adapter's owned client (``follow_redirects=False``): only the ydc request
    is recorded and the resolver key never reaches the evil destination."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "evil.example":
            return httpx.Response(200, json=_search_payload())
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    # Even a redirect-following caller cannot make the owned client follow.
    caller = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"User-Agent": "youcom-test-ua/1.0"},
    )
    async with _wired(handler, caller=caller) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="redirect"))

    # Only the ydc search POST was sent; the cross-origin Location was never
    # followed, so the resolver key never reached the evil destination.
    assert [str(request.url) for request in requests] == ["https://ydc-index.io/v1/search"]
    assert all("evil.example" not in str(request.url) for request in requests)
    assert excinfo.value.error.code == "invalid_response"  # bodyless 302 not followed
    assert excinfo.value.error.retryable is False
