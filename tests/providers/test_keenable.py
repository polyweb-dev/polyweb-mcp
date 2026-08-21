"""Mocked acceptance and boundary coverage for the Keenable adapter."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

import freesearch.adapters.keenable as keenable_module
from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.contracts import FetchRequest, SearchRequest, UsageOperation
from freesearch.resilience import ProviderOperationError
from freesearch.secrets import ProviderName


class _Resolver:
    def __init__(self, key: str | None = None) -> None:
        self._key = SecretStr(key) if key else None

    def get(self, provider: ProviderName) -> SecretStr | None:
        assert provider is ProviderName.KEENABLE
        return self._key


class _Runner:
    def __init__(self) -> None:
        self.providers: list[str] = []

    async def run(self, provider: str, operation):
        self.providers.append(provider)
        return await operation()


class _Transport:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("search/public") or request.url.path.endswith("search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com/result",
                            "description": "Description",
                            "snippet": "A snippet.",
                            "published_at": "2026-01-15T10:30:00Z",
                            "acquired_at": "2026-01-16T08:12:34Z",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "url": "https://example.com/document",
                "title": "Document",
                "content": "abcdef",
                "description": "Description",
                "published_at": 1_767_246_162,
            },
        )


def _adapter(transport: _Transport, runner: _Runner | None = None) -> KeenableAdapter:
    return KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(transport)), runner=runner
    )


def test_adapter_implements_contract_and_has_free_costs() -> None:
    adapter = _adapter(_Transport())

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "keenable"
    assert adapter.capabilities.search and adapter.capabilities.fetch
    assert adapter.capabilities.cost_estimate and not adapter.capabilities.quota


@pytest.mark.asyncio
async def test_keyless_search_and_fetch_use_public_paths_and_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport()
    runner = _Runner()
    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = _adapter(transport, runner)

    search = await adapter.search(SearchRequest(query="keenable", limit=2))
    fetch = await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    assert all(request.headers.get("X-Keenable-Title") for request in transport.requests)
    assert all("X-API-Key" not in request.headers for request in transport.requests)
    assert json.loads(transport.requests[0].content) == {"query": "keenable", "max_results": 2}
    assert dict(transport.requests[1].url.params) == {
        "url": "https://example.com/document",
        "max_chars": "3",
    }
    assert runner.providers == ["keenable", "keenable"]
    assert search.results[0].snippet == "A snippet."
    assert search.results[0].metadata == {
        "description": "Description",
        "acquired_at": "2026-01-16T08:12:34Z",
    }
    assert search.usage is not None and search.usage.units == Decimal("0")
    assert fetch.document.content == "abc"
    assert fetch.document.metadata["truncated"] is True
    assert fetch.usage is not None and fetch.usage.units == Decimal("0")


@pytest.mark.asyncio
async def test_keyed_requests_use_private_paths_and_only_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport()
    monkeypatch.setattr(
        keenable_module, "get_provider_secret_resolver", lambda: _Resolver("keen_secret")
    )

    await _adapter(transport).search(SearchRequest(query="keenable"))

    request = transport.requests[0]
    assert request.url.path == "/v1/search"
    assert request.headers["X-API-Key"] == "keen_secret"
    assert "X-Keenable-Title" not in request.headers


@pytest.mark.asyncio
async def test_estimates_are_zero_without_network() -> None:
    adapter = _adapter(_Transport())

    estimate = await adapter.estimate_cost(SearchRequest(query="keenable"))

    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("0")


@pytest.mark.asyncio
async def test_fetch_cost_estimate_uses_fetch_operation() -> None:
    adapter = _adapter(_Transport())

    estimate = await adapter.estimate_cost(FetchRequest(url="https://example.com/document"))

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0")


@pytest.mark.asyncio
async def test_invalid_response_and_vendor_errors_are_normalized_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key keen_secret"})

    monkeypatch.setattr(
        keenable_module, "get_provider_secret_resolver", lambda: _Resolver("keen_secret")
    )
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.status_code == 401
    assert not raised.value.error.retryable
    assert "keen_secret" not in raised.value.error.message


# Mirrors the shared runner's HTTP retry policy (resilience._RETRYABLE_STATUS_CODES).
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "expected_max_results"),
    [(10, 10), (50, 50), (51, 50), (100, 50)],
)
async def test_search_limit_is_capped_at_50_without_clamping_at_boundary(
    monkeypatch: pytest.MonkeyPatch, limit: int, expected_max_results: int
) -> None:
    transport = _Transport()
    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())

    await _adapter(transport).search(SearchRequest(query="keenable", limit=limit))

    assert json.loads(transport.requests[0].content)["max_results"] == expected_max_results


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_chars", "expected_content", "truncated"),
    [(None, "abcdef", False), (6, "abcdef", False), (5, "abcde", True)],
)
async def test_fetch_truncates_only_when_content_exceeds_max_chars(
    monkeypatch: pytest.MonkeyPatch, max_chars: int | None, expected_content: str, truncated: bool
) -> None:
    transport = _Transport()
    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())

    fetch = await _adapter(transport).fetch(
        FetchRequest(url="https://example.com/document", max_chars=max_chars)
    )

    assert fetch.document.content == expected_content
    assert ("truncated" in fetch.document.metadata) is truncated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": []},
        {"results": [{"title": "Missing URL"}]},
        {"results": {"not": "a list"}},
        {"results": "nope"},
        {"results": [{"url": "not-a-url"}]},
    ],
)
async def test_malformed_search_payloads_raise_normalized_invalid_response(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed search response"
    assert not raised.value.error.retryable
    assert raised.value.error.status_code is None


@pytest.mark.asyncio
async def test_non_json_success_body_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>proxy error</html>")

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed search response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"content": 123}, {"content": None}, {"content": ["a", "b"]}],
)
async def test_malformed_fetch_payloads_raise_normalized_invalid_response(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(FetchRequest(url="https://example.com/document"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed fetch response"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
async def test_http_error_retryable_flag_matches_status_policy(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "vendor detail"})

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)), runner=_Runner()
    )

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    error = raised.value.error
    assert error.code == "http_error"
    assert error.message == f"HTTP {status}"
    assert error.status_code == status
    assert error.retryable is (status in _RETRYABLE_STATUS_CODES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-15T10:30:00Z", datetime(2026, 1, 15, 10, 30, tzinfo=UTC)),
        ("2026-01-15", datetime(2026, 1, 15)),
        ("garbage", None),
        (1_767_246_162, None),
        (None, None),
    ],
)
async def test_published_at_is_parsed_or_dropped(
    monkeypatch: pytest.MonkeyPatch, raw: object, expected: datetime | None
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"url": "https://example.com/r", "published_at": raw}]}
        )

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    response = await adapter.search(SearchRequest(query="keenable"))

    assert response.results[0].published_at == expected


@pytest.mark.asyncio
async def test_minimal_search_result_uses_defaults_and_drops_none_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"url": "https://example.com/r", "description": None}]},
        )

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    response = await adapter.search(SearchRequest(query="keenable"))

    result = response.results[0]
    assert result.title == ""
    assert result.snippet == ""
    assert result.published_at is None
    assert result.metadata == {}


@pytest.mark.asyncio
async def test_fetch_uses_request_url_and_tolerates_non_string_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"url": "https://unused.example/other", "title": 123, "content": "body"},
        )

    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    fetch = await adapter.fetch(FetchRequest(url="https://example.com/document"))

    assert str(fetch.document.url) == "https://example.com/document"
    assert fetch.document.title is None
    assert fetch.document.content == "body"


@pytest.mark.asyncio
async def test_caller_client_default_api_key_does_not_leak_into_keyless_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller client default ``X-API-Key`` must not reach keyless /public calls."""
    transport = _Transport()
    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), headers={"X-API-Key": "unrelated-secret"}
    )
    adapter = KeenableAdapter(client, runner=_Runner())

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    for request in transport.requests:
        assert "X-API-Key" not in request.headers
        assert request.headers["X-Keenable-Title"] == "freesearch"


@pytest.mark.asyncio
async def test_caller_client_basic_auth_does_not_leak_into_keyless_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller client ``auth=`` must not reach keyless /public calls."""
    transport = _Transport()
    monkeypatch.setattr(keenable_module, "get_provider_secret_resolver", lambda: _Resolver())
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), auth=httpx.BasicAuth("user", "caller-secret")
    )
    adapter = KeenableAdapter(client, runner=_Runner())

    # Control: the same caller auth would reach a raw request on this transport,
    # proving the absence assertions below are not vacuous.
    control = _Transport()
    control_client = httpx.AsyncClient(
        transport=httpx.MockTransport(control), auth=httpx.BasicAuth("user", "caller-secret")
    )
    await control_client.get("https://example.com/control")
    assert control.requests[0].headers.get("Authorization") is not None

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    for request in transport.requests:
        assert "Authorization" not in request.headers
        assert "X-API-Key" not in request.headers
        assert request.headers["X-Keenable-Title"] == "freesearch"


@pytest.mark.asyncio
async def test_keyed_requests_send_resolver_key_only_without_caller_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller client ``auth=`` must not reach keyed calls; resolver key only."""
    transport = _Transport()
    monkeypatch.setattr(
        keenable_module, "get_provider_secret_resolver", lambda: _Resolver("keen_secret")
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), auth=httpx.BasicAuth("user", "caller-secret")
    )
    adapter = KeenableAdapter(client, runner=_Runner())

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search",
        "/v1/fetch",
    ]
    for request in transport.requests:
        assert request.headers["X-API-Key"] == "keen_secret"
        assert "Authorization" not in request.headers
        assert "X-Keenable-Title" not in request.headers


@pytest.mark.asyncio
async def test_keyed_fetch_uses_private_path_and_api_key_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport()
    monkeypatch.setattr(
        keenable_module, "get_provider_secret_resolver", lambda: _Resolver("keen_secret")
    )

    await _adapter(transport).fetch(FetchRequest(url="https://example.com/document"))

    request = transport.requests[0]
    assert request.url.path == "/v1/fetch"
    assert request.headers["X-API-Key"] == "keen_secret"
    assert "X-Keenable-Title" not in request.headers
