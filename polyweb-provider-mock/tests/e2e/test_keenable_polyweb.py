"""End to end: the real Polyweb Keenable adapter against a live mock server.

The mock runs under uvicorn on a free loopback port and Polyweb's startup
interception (``install_provider_mock`` through ``create_async_client``)
reroutes ``https://api.keenable.ai`` to it. Each fault must surface with the
classification that ``tests/unit/adapters/test_keenable*.py`` in Polyweb
asserts for real payloads: the adapter maps by HTTP status only (402
``quota_exhausted``, everything else ``http_error``, retryable for
429/500/502/503/504 and *not* for Keenable's retryable 529).
"""

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import uvicorn
from polyweb.adapters.keenable import KeenableAdapter
from polyweb.configuration.config import Settings
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.provider_mock import install_provider_mock, provider_mock_origin
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, SearchRequest
from pydantic import SecretStr

from polyweb_provider_mock.app import create_app
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers._rate_windows import WindowSpec, add
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore

_PROJECT = UUID("00000000-0000-4000-8000-0000000000aa")
_URL = "https://docs.python.org/3/library/json.html"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _settings(origin: str) -> Settings:
    return Settings(
        _env_file=None,
        provider_mock_url=origin,
        http_timeout_seconds=1.5,
        http_connect_timeout_seconds=1.5,
    )


@pytest.fixture(scope="module")
def mock_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, MockStore]]:
    """Serve the mock on a free port and route Polyweb's HTTPX transports to it."""

    db = Path(tmp_path_factory.mktemp("mock")) / "mock.db"
    port = _free_port()
    app = create_app(MockSettings(port=port, db_path=db, random_seed=11))
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            proxy_headers=False,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the mock server did not start"
        time.sleep(0.02)
    origin = f"http://127.0.0.1:{port}"
    with pytest.MonkeyPatch.context() as patch:
        # The context restores both HTTPX handlers, which removes the routing.
        patch.setattr(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            httpx.AsyncHTTPTransport.handle_async_request,
        )
        patch.setattr(httpx.HTTPTransport, "handle_request", httpx.HTTPTransport.handle_request)
        assert install_provider_mock(_settings(origin)) is True
        yield origin, app.store
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def store(mock_server: tuple[str, MockStore]) -> MockStore:
    origin, state = mock_server
    assert provider_mock_origin() == origin
    state.seed(discover().values(), reset=True)
    return state


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("keenable") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.clients: list[httpx.AsyncClient] = []
        self.delays: list[float] = []

    async def _sleep(self, delay: float) -> None:
        self.delays.append(delay)

    def __call__(self, key: str | None, *, attempts: int = 1) -> KeenableAdapter:
        client = create_async_client(_settings(self.origin))
        self.clients.append(client)
        runner = ResilientRunner(client, max_attempts=attempts, sleeper=self._sleep)
        return KeenableAdapter(
            client, api_key=None if key is None else SecretStr(key), runner=runner
        )


@pytest.fixture
async def adapters(mock_server: tuple[str, MockStore]) -> AsyncIterator[_Adapters]:
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


async def test_keyed_search_and_fetch_debit_credits(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(FetchRequest(project_id=_PROJECT, url=_URL, enhanced=True))

    assert len(search.results) == 3 and search.results[0].snippet
    assert search.usage is not None
    assert (search.usage.units, search.usage.metadata["sku"]) == (1, "search.pro")
    assert search.usage.metadata["credits_remaining"] == "99999"
    assert fetch.document.content.startswith("# ")
    assert fetch.usage is not None and fetch.usage.metadata["sku"] == "fetch.live"
    assert store.account("keenable").credits_used == 2
    logged = store.log_tail("keenable")
    assert [(e.operation, e.path, e.status, e.key_label) for e in logged] == [
        ("search", "/v1/search", 200, "default"),
        ("fetch", "/v1/fetch", 200, "default"),
    ]
    assert logged[0].request_summary["headers"]["x-api-key"] == "<redacted>"


async def test_keyless_rail_is_free_and_counted(store: MockStore, adapters: _Adapters) -> None:
    adapter = adapters(None)

    search = await adapter.search(_search(limit=2))
    fetch = await adapter.fetch(FetchRequest(project_id=_PROJECT, url="https://example.com/"))

    assert len(search.results) == 2
    assert search.usage is not None and search.usage.metadata["mode"] == "keyless"
    assert fetch.document.title == "Example Domain"
    assert store.account("keenable").credits_used == 0
    logged = store.log_tail("keenable")
    assert [(e.path, e.key_label) for e in logged] == [
        ("/v1/search/public", "keyless"),
        ("/v1/fetch/public", "keyless"),
    ]
    assert logged[0].request_summary["headers"]["x-keenable-title"] == "polyweb"


async def test_keyless_hourly_pool_exhaustion_is_retryable(
    store: MockStore, adapters: _Adapters
) -> None:
    await adapters(None).search(_search())
    add(store, WindowSpec("keenable:public:search:hour", 1000, 3600), 1000)

    error = (await _error(adapters(None).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("http_error", 429, True)
    assert store.log_tail("keenable")[-1].status == 429


async def test_rate_limit_fault_is_retried_with_retry_after(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="keenable",
            operation="search",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=4),
            count=2,
        )
    )

    result = await adapters(key, attempts=3).search(_search())

    assert len(result.results) == 3
    assert adapters.delays[:2] == [4.0, 4.0]
    assert [e.status for e in store.log_tail("keenable")] == [429, 429, 200]


async def test_529_overload_is_not_retried(store: MockStore, key: str, adapters: _Adapters) -> None:
    store.add_fault(
        FaultSpec(provider="keenable", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=529))
    )

    error = (await _error(adapters(key, attempts=3).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("http_error", 529, False)
    assert len(store.log_tail("keenable")) == 1


@pytest.mark.parametrize("status", [503, 502, 500])
async def test_outage_is_a_retryable_http_error(
    store: MockStore, key: str, adapters: _Adapters, status: int
) -> None:
    store.add_fault(
        FaultSpec(provider="keenable", kind=FaultKind.OUTAGE, params=FaultParams(status=status))
    )
    error = (await _error(adapters(key).fetch(FetchRequest(url="https://example.com/")))).error

    assert (error.code, error.status_code, error.retryable) == ("http_error", status, True)


@pytest.mark.parametrize(
    "fault", [None, FaultSpec(provider="keenable", kind=FaultKind.QUOTA_EXHAUSTED)]
)
async def test_credit_exhaustion_is_terminal_quota_exhausted(
    store: MockStore, key: str, adapters: _Adapters, fault: FaultSpec | None
) -> None:
    if fault is None:
        store.set_credits("keenable", Decimal(0))
    else:
        store.add_fault(fault)
    adapter = adapters(key, attempts=3)

    error = (await _error(adapter.search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 402, False)
    assert len(store.log_tail("keenable")) == 1
    quota = await adapter.quota_after_error(402)
    assert quota is not None and quota.remaining == 0


async def test_invalid_and_revoked_keys(store: MockStore, key: str, adapters: _Adapters) -> None:
    unknown = (await _error(adapters("keen_notarealkey").search(_search()))).error
    assert (unknown.code, unknown.status_code, unknown.retryable) == ("http_error", 401, False)

    store.set_key_status("keenable", "default", "revoked")
    revoked = (await _error(adapters(key).fetch(FetchRequest(url=_URL)))).error
    assert (revoked.code, revoked.status_code, revoked.retryable) == ("http_error", 403, False)


async def test_auth_invalid_fault(store: MockStore, key: str, adapters: _Adapters) -> None:
    store.add_fault(FaultSpec(provider="keenable", kind=FaultKind.AUTH_INVALID))
    error = (await _error(adapters(key).search(_search()))).error
    assert (error.code, error.status_code) == ("http_error", 401)


async def test_latency_fault_delays_the_call(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)
    await adapter.search(_search())
    store.set_latency("keenable", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4


@pytest.mark.parametrize(
    "fault",
    [
        FaultSpec(provider="keenable", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=4)),
        FaultSpec(provider="keenable", kind=FaultKind.CONNECTION_DROP),
    ],
)
async def test_timeout_and_drop_are_transport_errors(
    store: MockStore, key: str, adapters: _Adapters, fault: FaultSpec
) -> None:
    store.add_fault(fault)
    error = (await _error(adapters(key).search(_search()))).error
    assert (error.code, error.retryable, error.status_code) == ("transport_error", True, None)


@pytest.mark.parametrize("variant", ["invalid_json", "missing_field", "truncated"])
async def test_malformed_bodies_are_invalid_responses(
    store: MockStore, key: str, adapters: _Adapters, variant: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="keenable",
            kind=FaultKind.MALFORMED,
            params=FaultParams.model_validate({"variant": variant}),
        )
    )
    adapter = adapters(key)

    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(FetchRequest(url=_URL)))).error

    assert (search.code, search.retryable) == ("invalid_response", False)
    assert (fetch.code, fetch.retryable) == ("invalid_response", False)
