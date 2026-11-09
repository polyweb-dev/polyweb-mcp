"""Runner/retry and credential-redaction coverage for BraveAdapter; all HTTP is mocked.

Exercises retry-path behavior against the real :class:`ResilientRunner` and
transport-error normalization/secret redaction with an injected failing runner.
Keys are injected explicitly into the constructor (no resolver seam), then
proven absent from every surfaced error.  Response/operation edges live in
``test_brave_edges.py``; wire-request hygiene lives in ``test_brave_wire.py``.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from polyweb.adapters.brave import BraveAdapter
from polyweb.infrastructure.resilience import (
    CircuitOpenError,
    ProviderOperationError,
    ResilientRunner,
)
from polyweb.models.contracts import SearchRequest


class _RaisingRunner:
    """Injected runner that fails before the wrapped operation can run."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def run(self, provider: str, operation: Callable[[], Any]) -> Any:
        raise self.exc


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
    client: httpx.AsyncClient, *, runner: Any = None, key: str = "edge-secret"
) -> BraveAdapter:
    """Build a Brave adapter with an explicitly injected fake key."""
    return BraveAdapter(client, runner=runner, api_key=SecretStr(key))


def _zero_delay_runner(client: httpx.AsyncClient, sleeps: list[float]) -> ResilientRunner:
    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    return ResilientRunner(
        client,
        max_attempts=3,
        base_delay=0.0,
        max_delay=0.0,
        backoff_factor=1.0,
        clock=lambda: 0.0,
        sleeper=sleeper,
        random_source=lambda: 0.0,
    )


async def test_real_runner_retries_429_then_succeeds_with_zero_delay() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=_payload(), headers={"X-RateLimit-Remaining": "1999"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    adapter = _adapter(client, runner=_zero_delay_runner(client, sleeps))
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="retry me")
        )
    finally:
        await client.aclose()

    assert attempts == 2
    assert sleeps == [0.0]
    assert response.query == "retry me"
    assert response.results[0].title == "Example"
    assert response.usage is not None
    assert response.usage.metadata == {"rate_limit_remaining": 1999}


async def test_real_runner_retries_transport_error_and_redacts_key() -> None:
    secret = "top-secret"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(f"connection refused: token={secret}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    adapter = _adapter(client, runner=_zero_delay_runner(client, sleeps), key=secret)
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
            )
    finally:
        await client.aclose()

    assert attempts == 3  # every attempt hits the transport error
    assert sleeps == [0.0, 0.0]
    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None
    assert excinfo.value.error.message == "connection refused: token=[REDACTED]"
    assert secret not in str(excinfo.value)


async def test_injected_runner_transport_error_normalized_without_key_leak() -> None:
    secret = "top-secret"
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_payload())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = _adapter(
        client,
        runner=_RaisingRunner(httpx.ConnectError(f"raw failure exposing {secret}")),
        key=secret,
    )
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
            )
    finally:
        await client.aclose()

    assert calls == 0  # operation never reached the client
    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None
    assert excinfo.value.error.message == "transport error"
    assert secret not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_injected_runner_circuit_open_passes_through_unchanged() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    adapter = _adapter(client, runner=_RaisingRunner(CircuitOpenError("brave")))
    try:
        with pytest.raises(CircuitOpenError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
            )
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "circuit_open"
    assert excinfo.value.error.retryable is False
