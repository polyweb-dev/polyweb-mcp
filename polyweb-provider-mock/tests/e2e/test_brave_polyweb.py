"""End to end: the real Polyweb Brave adapter against a live mock server.

The mock runs under uvicorn on a free loopback port. Polyweb's own startup
interception (``install_provider_mock`` through ``create_async_client``)
reroutes ``api.search.brave.com`` to it, and
:class:`~polyweb.adapters.brave.BraveAdapter` makes the calls on the shared
client. Every fault must surface with the normalized error that the
adapter's unit tests assert for the matching real Brave payload, and the
ledger-derived ``X-RateLimit-*`` pairs must drive the adapter's quota state.
"""

import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import uvicorn
from polyweb.adapters.brave import BraveAdapter
from polyweb.configuration.config import Settings
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.provider_mock import install_provider_mock, provider_mock_origin
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import SearchRequest
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from pydantic import SecretStr

from polyweb_provider_mock.app import create_app
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore

_PROJECT = UUID("00000000-0000-4000-8000-0000000000cc")


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
    app = create_app(MockSettings(port=port, db_path=db, random_seed=17))
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
def keys(store: MockStore) -> dict[str, str]:
    return {item.label: item.key for item in store.keys("brave")}


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.clients: list[httpx.AsyncClient] = []

    def __call__(self, key: str) -> BraveAdapter:
        client = create_async_client(_settings(self.origin))
        self.clients.append(client)
        return BraveAdapter(
            client, api_key=SecretStr(key), runner=ResilientRunner(client, max_attempts=1)
        )


@pytest.fixture
async def adapters(mock_server: tuple[str, MockStore]) -> AsyncIterator[_Adapters]:
    factory = _Adapters(mock_server[0])
    yield factory
    for client in factory.clients:
        await client.aclose()


def _search(query: str = "polyweb mock", limit: int = 3, **brave: Any) -> SearchRequest:
    options = {"brave": brave} if brave else None
    return SearchRequest(project_id=_PROJECT, query=query, limit=limit, provider_options=options)


def _sync() -> UsageSyncRequest:
    return UsageSyncRequest(
        provider="brave", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
    )


async def _error(call: object) -> ProviderOperationError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value


async def test_unlimited_plan_search_and_context_succeed(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    adapter = adapters(keys["search"])

    web = await adapter.search(_search(extra_snippets=True))
    context = await adapter.search(
        _search(limit=2, search_type="llm_context", enable_source_metadata=True)
    )
    usage = await adapter.usage_snapshot(_sync())

    assert len(web.results) == 3 and web.results[0].metadata["subtype"] == "generic"
    assert web.usage is not None and web.usage.units == 1
    assert web.usage.metadata["rate_limit_remaining"] == 49
    snapshot = web.quota_snapshot
    assert snapshot is not None and (snapshot.remaining, snapshot.limit) == (None, None)
    assert len(context.results) == 2
    assert context.provider_metadata is not None
    sources = context.provider_metadata["sources"]
    assert set(sources) == {str(result.url) for result in context.results}
    assert context.results[0].metadata["source"]["site_name"]
    assert usage is not None and usage.source == "local_ledger" and usage.remaining is None
    assert store.account("brave").credits_used == 2
    logged = store.log_tail("brave")
    assert [(entry.operation, entry.status, entry.key_label) for entry in logged] == [
        ("web_search", 200, "search"),
        ("llm_context", 200, "search"),
    ]
    assert logged[0].request_summary["headers"]["x-subscription-token"] == "<redacted>"


async def test_finite_monthly_cap_reaches_the_quota_snapshot(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    store.set_credits("brave", Decimal(1000))
    adapter = adapters(keys["search"])

    response = await adapter.search(_search())
    usage = await adapter.usage_snapshot(_sync())

    snapshot = response.quota_snapshot
    assert snapshot is not None
    assert (snapshot.remaining, snapshot.limit) == (Decimal(999), Decimal(1000))
    reset = store.account("brave").period_reset
    assert snapshot.reset_at is not None and reset is not None
    assert abs(snapshot.reset_at - reset) < timedelta(seconds=5)
    assert usage is not None and usage.source == "vendor_headers"
    assert (usage.remaining, usage.allowance) == (Decimal("4.995"), Decimal("5.000"))


async def test_spent_monthly_cap_is_a_final_quota_error(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    store.set_credits("brave", Decimal(0))
    error = (await _error(adapters(keys["search"]).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 429, False)
    assert store.log_tail("brave")[-1].status == 429


@pytest.mark.parametrize(
    ("token", "status"),
    [("answers", 400), ("wrong", 422), ("missing", 422)],
)
async def test_auth_failures_are_non_retryable_http_errors(
    keys: dict[str, str], adapters: _Adapters, token: str, status: int
) -> None:
    value = {**keys, "wrong": "BSAnotarealkey000000000000000000", "missing": ""}[token]
    for request in (_search(), _search(search_type="llm_context")):
        error = (await _error(adapters(value).search(request))).error
        assert (error.code, error.status_code, error.retryable) == ("http_error", status, False)


async def test_revoked_search_key_fails_like_a_wrong_key(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    store.set_key_status("brave", "search", "revoked")
    error = (await _error(adapters(keys["search"]).search(_search()))).error
    assert (error.code, error.status_code) == ("http_error", 422)


@pytest.mark.parametrize(
    ("spec", "code", "status", "retryable"),
    [
        (FaultSpec(provider="brave", kind=FaultKind.RATE_LIMIT), "http_error", 429, True),
        (
            FaultSpec(provider="brave", kind=FaultKind.QUOTA_EXHAUSTED),
            "quota_exhausted",
            429,
            False,
        ),
        (
            FaultSpec(
                provider="brave", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(status=402)
            ),
            "quota_exhausted",
            402,
            False,
        ),
        (
            FaultSpec(
                provider="brave",
                kind=FaultKind.QUOTA_EXHAUSTED,
                params=FaultParams(scope="spend_cap"),
            ),
            "quota_exhausted",
            429,
            False,
        ),
        (FaultSpec(provider="brave", kind=FaultKind.OUTAGE), "http_error", 503, True),
        (
            FaultSpec(provider="brave", kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            "http_error",
            502,
            True,
        ),
        (FaultSpec(provider="brave", kind=FaultKind.AUTH_INVALID), "http_error", 422, False),
    ],
)
async def test_faults_map_like_real_payloads(
    store: MockStore,
    keys: dict[str, str],
    adapters: _Adapters,
    spec: FaultSpec,
    code: str,
    status: int,
    retryable: bool,
) -> None:
    store.add_fault(spec)
    error = (await _error(adapters(keys["search"]).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == (code, status, retryable)
    assert store.account("brave").credits_used == 0


async def test_402_records_a_zero_remaining_observation(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(provider="brave", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(status=402))
    )
    adapter = adapters(keys["search"])
    error = (await _error(adapter.search(_search()))).error

    snapshot = await adapter.quota_after_error(error.status_code)
    assert snapshot is not None and snapshot.remaining == 0


async def test_latency_fault_delays_the_call(
    store: MockStore, keys: dict[str, str], adapters: _Adapters
) -> None:
    adapter = adapters(keys["search"])
    await adapter.search(_search())
    store.set_latency("brave", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4


@pytest.mark.parametrize("kind", [FaultKind.TIMEOUT, FaultKind.CONNECTION_DROP])
async def test_timeout_and_dropped_connection_are_transport_errors(
    store: MockStore, keys: dict[str, str], adapters: _Adapters, kind: FaultKind
) -> None:
    store.add_fault(FaultSpec(provider="brave", kind=kind, params=FaultParams(seconds=4)))
    error = (await _error(adapters(keys["search"]).search(_search()))).error

    assert (error.code, error.retryable) == ("transport_error", True)


@pytest.mark.parametrize(
    ("variant", "search_type"),
    [
        ("invalid_json", "web"),
        ("missing_field", "web"),
        ("missing_field", "llm_context"),
        ("wrong_content_type", "web"),
    ],
)
async def test_malformed_bodies_are_invalid_responses(
    store: MockStore, keys: dict[str, str], adapters: _Adapters, variant: str, search_type: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="brave",
            kind=FaultKind.MALFORMED,
            params=FaultParams.model_validate({"variant": variant}),
        )
    )
    request = _search(search_type=search_type)
    if variant == "wrong_content_type":
        # The adapter parses JSON regardless of the content type, as against live Brave.
        assert len((await adapters(keys["search"]).search(request)).results) == 3
        return
    error = (await _error(adapters(keys["search"]).search(request))).error
    assert (error.code, error.retryable) == ("invalid_response", False)
