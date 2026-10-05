"""You.com HTTP status and retry error normalization - no network.

Covers AC-8: 401/402/403/400/422 map to provider-neutral non-retryable
codes, other non-retryable 4xx map to ``http_error``, all with fixed
messages that never echo the response body; retryable 5xx/429 retried inside
the shared runner, 429 exhausting retries remapped to ``rate_limited``.
"""

import httpx
import pytest

from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import SearchRequest
from tests.unit.adapters._youcom_test_support import (
    _assert_no_secret_leak,
    _FakeSleeper,
    _search_payload,
    _wired,
    _WireRecorder,
)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_api_key"),
        (402, "insufficient_credits"),
        (403, "forbidden"),
        (400, "bad_request"),
        (422, "bad_request"),
        (418, "http_error"),
    ],
)
async def test_status_mapping_is_provider_neutral_and_nonretryable(status: int, code: str) -> None:
    recorder = _WireRecorder(responses=[httpx.Response(status, json={"error": "x"})])
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="status"))

    assert len(recorder.requests) == 1  # non-retryable: no runner retries
    assert excinfo.value.error.provider == "you"
    assert excinfo.value.error.code == code
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.status_code == status
    assert excinfo.value.error.message == f"HTTP {status}"


async def test_status_error_message_is_fixed_and_redacts_secret_payloads() -> None:
    """A 401 body echoing a secret must never surface it: the message is the
    fixed ``HTTP 401`` string and redaction covers any payload echo."""
    recorder = _WireRecorder(
        responses=[
            httpx.Response(401, json={"error": {"message": "invalid key: api_key=sk-leak-123"}})
        ]
    )
    async with _wired(recorder) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="leak"))

    error = excinfo.value
    assert error.error.code == "invalid_api_key"
    assert error.error.message == "HTTP 401"
    _assert_no_secret_leak(error, "sk-leak-123")


async def test_retryable_5xx_retried_inside_runner_then_http_error() -> None:
    recorder = _WireRecorder(responses=[httpx.Response(500, json={})] * 3)
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="retry"))

    # Three attempts happen inside one runner.run, then the retryable error
    # surfaces unchanged (only 429 is remapped to rate_limited).
    assert len(recorder.requests) == 3
    assert sleeper.sleeps == [1.0, 2.0]
    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == 500


async def test_429_retry_after_backoff_then_success() -> None:
    recorder = _WireRecorder(
        responses=[
            httpx.Response(429, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json=_search_payload()),
        ]
    )
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        response = await adapter.search(SearchRequest(query="retry"))

    assert response.query == "retry"
    assert len(recorder.requests) == 2
    assert sleeper.sleeps == [7.0]  # Retry-After overrides the calculated backoff


async def test_429_exhausting_retries_is_remapped_to_rate_limited() -> None:
    recorder = _WireRecorder(
        responses=[httpx.Response(429, headers={"Retry-After": "7"}, json={})] * 3
    )
    sleeper = _FakeSleeper()
    async with _wired(recorder, sleeper=sleeper) as adapter:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="retry"))

    assert len(recorder.requests) == 3
    assert sleeper.sleeps == [7.0, 7.0]
    # The runner surfaces retries exhausted on a 429 as http_error; the
    # adapter remaps it to the provider-neutral rate_limited code.
    assert excinfo.value.error.code == "rate_limited"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == 429
