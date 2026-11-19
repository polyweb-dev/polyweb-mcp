"""End to end: the real Polyweb Tinyfish adapter against a live mock server.

The mock runs under uvicorn on a free loopback port and Polyweb's startup
interception reroutes both ``https://api.search.tinyfish.ai`` and
``https://api.fetch.tinyfish.ai`` to it; the mock tells them apart by the
preserved ``Host``. Each fault must surface with the classification that
Polyweb's ``tests/unit/adapters/test_tinyfish.py`` asserts for real payloads:
401 ``invalid_api_key``, 402 ``quota_exhausted``, 429 ``rate_limited``,
other statuses ``http_error`` (retryable only for 500/502/503/504), and
per-URL fetch errors inside an HTTP 200 mapped by their ``error`` code.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from polyweb.adapters.tinyfish import TinyfishAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, SearchRequest
from pydantic import SecretStr

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore
from polyweb_provider_mock.windows import WindowSpec
from tests._support.live_server import LiveMock, polyweb_settings

MOCK_RANDOM_SEED = 11
_PROJECT = UUID("00000000-0000-4000-8000-0000000000aa")
_URL = "https://docs.python.org/3/library/json.html"


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("tinyfish") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.clients: list[httpx.AsyncClient] = []
        self.delays: list[float] = []

    async def _sleep(self, delay: float) -> None:
        self.delays.append(delay)

    def __call__(self, key: str, *, attempts: int = 1) -> TinyfishAdapter:
        client = create_async_client(polyweb_settings(self.origin))
        self.clients.append(client)
        runner = ResilientRunner(client, max_attempts=attempts, sleeper=self._sleep)
        return TinyfishAdapter(client, api_key=SecretStr(key), runner=runner)


@pytest.fixture
async def adapters(mock_server: LiveMock) -> AsyncIterator[_Adapters]:
    factory = _Adapters(mock_server[0])
    yield factory
    for client in factory.clients:
        await client.aclose()


def _search(query: str = "polyweb mock", limit: int = 3) -> SearchRequest:
    return SearchRequest(project_id=_PROJECT, query=query, limit=limit)


async def _error(call: object) -> ProviderOperationError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value


async def test_search_and_fetch_succeed_on_their_hosts(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(FetchRequest(project_id=_PROJECT, url=_URL))

    assert len(search.results) == 3
    assert search.results[0].metadata["position"] == 1
    assert search.usage is not None and search.usage.units == 1
    assert fetch.document.content.startswith("# ")
    assert fetch.document.metadata["format"] == "markdown"
    logged = store.log_tail("tinyfish")
    assert [(e.operation, e.method, e.path, e.status) for e in logged] == [
        ("search", "GET", "/", 200),
        ("fetch", "POST", "/", 200),
    ]
    assert [e.request_summary["headers"]["host"] for e in logged] == [
        "api.search.tinyfish.ai",
        "api.fetch.tinyfish.ai",
    ]
    assert logged[0].request_summary["headers"]["x-api-key"] == "<redacted>"
    assert [entry.units for entry in store.ledger("tinyfish")] == [1, 1]


@pytest.mark.parametrize(
    ("url", "code", "status", "retryable"),
    [
        ("https://timeout.example.org/a", "timeout", 504, True),
        ("https://blocked.example.org/a", "bot_blocked", 403, False),
        ("https://login.example.org/a", "bot_blocked", 403, False),
        ("https://empty.example.org/a", "fetch_failed", 404, False),
        ("https://unreachable.example.org/a", "transport_error", 502, True),
        ("https://site.invalid/a", "not_found", 404, False),
        ("https://missing.example.org/a", "not_found", 404, False),
        ("https://status-503.example.org/a", "http_error", 503, True),
    ],
)
async def test_per_url_fetch_errors(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    url: str,
    code: str,
    status: int,
    retryable: bool,
) -> None:
    error = (await _error(adapters(key).fetch(FetchRequest(url=url)))).error

    assert (error.code, error.status_code, error.retryable) == (code, status, retryable)
    assert store.log_tail("tinyfish")[-1].status == 200


async def test_minute_limit_is_rate_limited_and_retried(
    store: MockStore, key: str, adapters: _Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = datetime(2026, 11, 17, 12, 0, 15, tzinfo=UTC)
    monkeypatch.setattr(store, "now", lambda: frozen)
    account = store.account("tinyfish").id
    store.count_window(WindowSpec(f"tinyfish:{account}:search:minute", 30, 60, aligned=True), 30)

    error = (await _error(adapters(key, attempts=2).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("rate_limited", 429, True)
    assert [e.status for e in store.log_tail("tinyfish")] == [429, 429]
    assert adapters.delays[0] == 45.0


async def test_rate_limit_fault_is_retried_with_retry_after(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="tinyfish",
            operation="fetch",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=2),
            count=1,
        )
    )

    fetch = await adapters(key, attempts=3).fetch(FetchRequest(url=_URL))

    assert fetch.document.content
    assert adapters.delays[:1] == [2.0]
    assert [e.status for e in store.log_tail("tinyfish")] == [429, 200]


@pytest.mark.parametrize(
    ("status", "retryable"), [(500, True), (502, True), (503, True), (504, True), (501, False)]
)
async def test_server_errors(
    store: MockStore, key: str, adapters: _Adapters, status: int, retryable: bool
) -> None:
    store.add_fault(
        FaultSpec(provider="tinyfish", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=status))
    )
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("http_error", status, retryable)


@pytest.mark.parametrize("how", ["credits", "allowance", "fault"])
async def test_exhaustion_is_terminal_quota_exhausted(
    store: MockStore, key: str, adapters: _Adapters, how: str
) -> None:
    if how == "credits":
        store.set_credits("tinyfish", Decimal(0))
    elif how == "allowance":
        account = store.account("tinyfish").id
        store.count_window(
            WindowSpec(f"tinyfish:{account}:fetch:day", 1000, 86400, aligned=True), 1000
        )
    else:
        store.add_fault(FaultSpec(provider="tinyfish", kind=FaultKind.QUOTA_EXHAUSTED))

    error = (await _error(adapters(key, attempts=3).fetch(FetchRequest(url=_URL)))).error

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 402, False)
    assert len(store.log_tail("tinyfish")) == 1


async def test_invalid_and_revoked_keys(store: MockStore, key: str, adapters: _Adapters) -> None:
    unknown = (await _error(adapters("not-a-tinyfish-key").search(_search()))).error
    assert (unknown.code, unknown.status_code, unknown.retryable) == ("invalid_api_key", 401, False)

    store.set_key_status("tinyfish", "default", "revoked")
    revoked = (await _error(adapters(key).fetch(FetchRequest(url=_URL)))).error
    assert (revoked.code, revoked.status_code, revoked.retryable) == ("invalid_api_key", 401, False)


async def test_auth_invalid_fault(store: MockStore, key: str, adapters: _Adapters) -> None:
    store.add_fault(FaultSpec(provider="tinyfish", kind=FaultKind.AUTH_INVALID))
    error = (await _error(adapters(key).fetch(FetchRequest(url=_URL)))).error
    assert (error.code, error.status_code) == ("invalid_api_key", 401)


async def test_latency_fault_delays_the_call(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)
    await adapter.search(_search())
    store.set_latency("tinyfish", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4


@pytest.mark.parametrize(
    "fault",
    [
        FaultSpec(provider="tinyfish", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=4)),
        FaultSpec(provider="tinyfish", kind=FaultKind.CONNECTION_DROP),
    ],
)
async def test_timeout_and_drop_are_transport_errors(
    store: MockStore, key: str, adapters: _Adapters, fault: FaultSpec
) -> None:
    store.add_fault(fault)
    error = (await _error(adapters(key).search(_search()))).error
    assert (error.code, error.retryable, error.status_code) == ("transport_error", True, None)


@pytest.mark.parametrize("variant", ["invalid_json", "missing_field", "wrong_content_type"])
async def test_malformed_bodies(
    store: MockStore, key: str, adapters: _Adapters, variant: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="tinyfish",
            kind=FaultKind.MALFORMED,
            params=FaultParams.model_validate({"variant": variant}),
        )
    )
    adapter = adapters(key)

    if variant == "wrong_content_type":
        # The adapter parses JSON regardless of the content type, as real code would.
        assert len((await adapter.search(_search())).results) == 3
        return
    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(FetchRequest(url=_URL)))).error

    assert (search.code, search.retryable) == ("invalid_response", False)
    assert (fetch.code, fetch.retryable) == ("invalid_response", False)
