"""Shared fakes and helpers for the You.com adapter test modules.

No test code lives here (never collected): only the injected fakes and
payload builders shared by ``test_youcom_*.py``. Fakes follow the conventions
in ``tests/test_resilience.py``: plain injected objects, no sleeping, no HTTP.

The adapter takes its credential by explicit constructor injection
(``YoucomAdapter(..., api_key=SecretStr(_TEST_KEY))``); tests build keyed
adapters with the ``_TEST_KEY`` fake and never reach for an ambient one, since
the retired ``get_provider_secret_resolver()`` seam no longer exists.
``_wired`` removes the per-test client construction/close boilerplate.
"""

import traceback
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from pydantic import SecretStr

from polyweb.adapters.youcom import YoucomAdapter
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner

_UNSET = object()

# Fake credential injected into every keyed adapter; wire assertions in the
# ``test_youcom_*.py`` modules compare ``X-API-Key`` against this value.
_TEST_KEY = "sk-you-test-secret-1"


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` carrying the shared timeout policy.

    Only used where no HTTP occurs (cost estimates), so only the attributes
    the adapter reads at construction are present.
    """

    timeout: httpx.Timeout = httpx.Timeout(20.0)
    follow_redirects = True
    max_redirects = 20
    headers = httpx.Headers({"user-agent": "polyweb-test/1.0"})


class _FakeClock:
    """Injectable monotonic clock that starts at zero."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now


class _FakeSleeper:
    """Injectable sleeper that records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.sleeps.append(delay)


class _RecordingRunner:
    """Records every shared-runner entry and executes the operation as-is."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await operation()


class _CountingRunner:
    """Wraps a real ``ResilientRunner`` while recording every entry."""

    def __init__(self, inner: ResilientRunner) -> None:
        self.inner = inner
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await self.inner.run(provider, operation)


class _WireRecorder:
    """Shared ``httpx.MockTransport`` handler recording wire requests.

    Serves the configured search/fetch payloads per path (or a canned
    response queue), recording every request so tests can assert method,
    URL, headers, body, and the timeout extension on the wire.
    """

    def __init__(
        self,
        *,
        search: object = _UNSET,
        fetch: object = _UNSET,
        balance: object = 0,
        responses: list[httpx.Response] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._search = _search_payload() if search is _UNSET else search
        self._fetch = _fetch_payload() if fetch is _UNSET else fetch
        self._balance = balance
        self._responses = list(responses) if responses is not None else []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        if request.url.path == "/v1/billing/account_balance":
            return httpx.Response(200, json=_balance_payload(self._balance))
        if request.url.path == "/v1/search":
            return httpx.Response(200, json=self._search)
        if request.url.path == "/v1/contents":
            return httpx.Response(200, json=self._fetch)
        return httpx.Response(404)


def _search_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "results": {
            "web": [
                {"title": "Example", "url": "https://example.com/doc", "snippets": ["A snippet."]}
            ],
        }
    }
    payload.update(overrides)
    return payload


def _fetch_payload(*pages: dict[str, object]) -> list[dict[str, object]]:
    return (
        list(pages)
        if pages
        else [{"url": "https://example.com/doc", "markdown": "body", "title": "Example"}]
    )


def _balance_payload(balance: object) -> dict[str, object]:
    """You.com account-balance payload carrying ``balance`` in USD cents."""
    return {"data": {"attributes": {"balance": balance}}}


def _default_runner(
    caller: httpx.AsyncClient, *, sleeper: _FakeSleeper | None = None
) -> ResilientRunner:
    """Deterministic runner: fake clock/sleeper, no jitter, three attempts."""
    return ResilientRunner(
        caller,
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        clock=_FakeClock(),
        sleeper=sleeper or _FakeSleeper(),
        random_source=lambda: 1.0,
    )


def _assert_no_secret_leak(error: ProviderOperationError, secret: str) -> None:
    """Assert the public error surfaces nothing containing the secret value."""
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert secret not in text


_WIRE_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0)


def _wire_caller(recorder: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(recorder),
        timeout=_WIRE_TIMEOUT,
        headers={
            "Authorization": "Bearer caller-token-1",
            "X-API-Key": "caller-xkey-2",
            "User-Agent": "youcom-test-ua/1.0",
        },
    )


@asynccontextmanager
async def _wired(
    recorder: Callable[[httpx.Request], httpx.Response],
    *,
    caller: httpx.AsyncClient | None = None,
    sleeper: _FakeSleeper | None = None,
) -> AsyncIterator[YoucomAdapter]:
    """Adapter over a ``MockTransport`` handler; owned clients always closed.

    Builds the caller client (or reuses the supplied one) and the adapter
    with the deterministic default runner and the fake injected key,
    guaranteeing both are closed on exit; wire assertions stay on
    ``recorder.requests``.
    """
    if caller is None:
        caller = _wire_caller(recorder)
    adapter = YoucomAdapter(
        caller, runner=_default_runner(caller, sleeper=sleeper), api_key=SecretStr(_TEST_KEY)
    )
    try:
        yield adapter
    finally:
        await adapter.aclose()
        await caller.aclose()


def _assert_wire_auth_and_timeout(
    requests: list[httpx.Request], secret: str, timeout: httpx.Timeout
) -> None:
    for request in requests:
        # Only the adapter's injected You.com key is auth on the wire.
        assert request.headers.get("X-API-Key") == secret
        assert request.headers.get("authorization") is None
        assert "caller-token-1" not in request.headers.values()
        assert "caller-xkey-2" not in request.headers.values()
        assert request.headers.get("user-agent") == "youcom-test-ua/1.0"
        # The borrowed transport reasserts the shared client's full phase
        # policy per request; the caller's phases never collapse.
        assert request.extensions["timeout"] == timeout.as_dict()
