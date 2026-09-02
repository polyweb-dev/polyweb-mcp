"""You.com USD-balance quota - deterministic, no network.

Locks the quota contract: a GET on the exact balance URL over the borrowed
transport with resolver-only auth (never caller credentials, never followed
redirects, shared timeout) and exactly one shared-runner entry; an ESTIMATED
snapshot with no limit/reset and a UTC timestamp whose remaining is the floor
of balance-in-cents to Web Search call equivalents at the shared 0.005
USD/call price (zero and sub-call balances map to zero); safe suppressed
``invalid_response`` for malformed or secret-bearing payloads; and the shared
runner's HTTP-status, Retry-After, and rate-limit cooldown behavior.
"""

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from _youcom_test_support import (
    _WIRE_TIMEOUT,
    _assert_no_secret_leak,
    _assert_wire_auth_and_timeout,
    _balance_payload,
    _CountingRunner,
    _default_runner,
    _FakeSleeper,
    _wire_caller,
    _wired,
    _WireRecorder,
    fake_resolver,  # noqa: F401  (autouse fixture registered via import)
)

from freesearch.adapters.youcom import YoucomAdapter
from freesearch.contracts import QuotaSource, SearchRequest
from freesearch.resilience import ProviderOperationError


async def test_capability_quota_enabled_and_price_matches_estimate() -> None:
    recorder = _WireRecorder(balance=50)
    caller = _wire_caller(recorder)
    runner = _CountingRunner(_default_runner(caller))
    adapter = YoucomAdapter(caller, runner=runner)
    try:
        assert adapter.capabilities.quota is True
        estimate = await adapter.estimate_cost(SearchRequest(query="price"))
        snapshot = await adapter.quota()
    finally:
        await adapter.aclose()
        await caller.aclose()

    assert estimate.units == Decimal("0.005")  # shared documented search price
    assert snapshot.remaining == Decimal("100")  # 50 cents at 0.005 USD/call
    assert runner.entries == ["you"]  # estimate is free; only quota hits the network


async def test_quota_get_uses_balance_url_resolver_auth_and_shared_timeout() -> None:
    recorder = _WireRecorder(balance=50)
    caller = _wire_caller(recorder)
    runner = _CountingRunner(_default_runner(caller))
    adapter = YoucomAdapter(caller, runner=runner)
    try:
        snapshot = await adapter.quota()
    finally:
        await adapter.aclose()
        await caller.aclose()

    # One GET, resolver key only, shared timeout, redirects disabled, one entry.
    assert [(r.method, str(r.url)) for r in recorder.requests] == [
        ("GET", "https://api.you.com/v1/billing/account_balance")
    ]
    _assert_wire_auth_and_timeout(recorder.requests, "sk-you-test-secret-1", _WIRE_TIMEOUT)
    assert adapter._owned_http.follow_redirects is False
    assert runner.entries == ["you"]
    assert snapshot.remaining == Decimal("100")


async def test_quota_snapshot_is_estimated_utc_with_no_limit_or_reset() -> None:
    recorder = _WireRecorder(balance=100)
    async with _wired(recorder) as adapter:
        snapshot = await adapter.quota()

    assert snapshot.provider == "you"
    assert snapshot.source is QuotaSource.ESTIMATED
    assert snapshot.remaining == Decimal("200")
    assert snapshot.limit is None
    assert snapshot.reset_at is None
    assert snapshot.observed_at.utcoffset() == timedelta(0)
    assert snapshot.observed_at.tzinfo is not None


@pytest.mark.parametrize(
    ("balance_cents", "expected_calls"),
    [
        (0, Decimal("0")),
        (0.3, Decimal("0")),  # positive but below one call -> zero
        (1, Decimal("2")),
        (2.5, Decimal("5")),
        (50, Decimal("100")),
        (100, Decimal("200")),
        (123.75, Decimal("247")),  # 1.2375 USD / 0.005 -> floor 247
    ],
)
async def test_quota_balance_cents_floor_to_conservative_search_calls(
    balance_cents: object, expected_calls: Decimal
) -> None:
    recorder = _WireRecorder(balance=balance_cents)
    async with _wired(recorder) as adapter:
        snapshot = await adapter.quota()

    assert snapshot.remaining == expected_calls


@pytest.mark.parametrize(
    ("response", "secret"),
    [
        (httpx.Response(200, json=["not", "an", "object"]), None),
        (httpx.Response(200, json={"no_data": {}}), None),
        (httpx.Response(200, json={"data": {}}), None),
        (httpx.Response(200, json={"data": {"attributes": {}}}), None),
        (httpx.Response(200, json={"data": {"attributes": {"balance": True}}}), None),
        (httpx.Response(200, json={"data": {"attributes": {"balance": "12.5"}}}), None),
        (httpx.Response(200, json={"data": {"attributes": {"balance": -1}}}), None),
        (httpx.Response(200, content=b"not json at all"), None),
        (httpx.Response(200, content=b'{"data":{"attributes":{"balance":NaN}}}'), None),
        (httpx.Response(200, content=b'{"data":{"attributes":{"balance":Infinity}}}'), None),
        (
            httpx.Response(
                200, json={"data": {"attributes": {"balance": {"api_key": "sk-leak-123"}}}}
            ),
            "sk-leak-123",
        ),
    ],
)
async def test_quota_malformed_body_is_suppressed_invalid_response(
    response: httpx.Response, secret: str | None
) -> None:
    recorder = _WireRecorder(responses=[response])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.quota()

    assert len(recorder.requests) == 1  # one runner entry, no retries
    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert error.status_code is None
    assert "malformed quota response" in error.message
    if secret:
        _assert_no_secret_leak(excinfo.value, secret)


async def test_quota_owned_client_never_follows_cross_origin_redirect() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "evil.example":
            return httpx.Response(200, json=_balance_payload(50))
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    caller = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"User-Agent": "youcom-test-ua/1.0"},
    )
    async with _wired(handler, caller=caller) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.quota()

    assert [str(request.url) for request in requests] == [
        "https://api.you.com/v1/billing/account_balance"
    ]
    assert all("evil.example" not in str(request.url) for request in requests)
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_api_key"),
        (402, "insufficient_credits"),
        (403, "forbidden"),
        (400, "bad_request"),
        (422, "bad_request"),
    ],
)
async def test_quota_http_status_maps_to_provider_neutral_nonretryable_code(
    status: int, code: str
) -> None:
    recorder = _WireRecorder(responses=[httpx.Response(status, json={})])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.quota()

    assert len(recorder.requests) == 1  # non-retryable: no runner retries
    assert excinfo.value.error.provider == "you"
    assert excinfo.value.error.code == code
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.status_code == status
    assert excinfo.value.error.message == f"HTTP {status}"


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_quota_retryable_5xx_retried_inside_runner_then_http_error(status: int) -> None:
    recorder = _WireRecorder(responses=[httpx.Response(status, json={})] * 3)
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.quota()

    assert len(recorder.requests) == 3
    assert sleeper.sleeps == [1.0, 2.0]
    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == status


async def test_quota_429_exhausting_retries_is_remapped_to_rate_limited() -> None:
    recorder = _WireRecorder(
        responses=[httpx.Response(429, headers={"Retry-After": "7"}, json={})] * 3
    )
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.quota()

    assert len(recorder.requests) == 3
    assert sleeper.sleeps == [7.0, 7.0]
    assert excinfo.value.error.code == "rate_limited"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == 429


async def test_quota_retry_after_and_rate_limit_cooldown_waited_out_by_later_call() -> None:
    recorder = _WireRecorder(
        responses=[
            httpx.Response(429, headers={"Retry-After": "5"}, json={}),
            httpx.Response(200, json=_balance_payload(50)),
            httpx.Response(200, json=_balance_payload(50)),
        ]
    )
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        first = await adapter.quota()  # 429 Retry-After 5 -> retry -> success
        second = await adapter.quota()  # shared cooldown must be waited out

    assert first.remaining == Decimal("100")
    assert second.remaining == Decimal("100")
    # Retry-After 5 overrides the 1.0 backoff; the cooldown is slept again.
    assert sleeper.sleeps == [5.0, 5.0]
