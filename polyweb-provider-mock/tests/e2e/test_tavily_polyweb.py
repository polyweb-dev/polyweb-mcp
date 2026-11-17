"""End to end: the real Polyweb Tavily adapter against a live mock server.

The mock runs under uvicorn on a free loopback port. Polyweb's own startup
interception (``install_provider_mock`` through ``create_async_client``)
reroutes ``https://api.tavily.com`` to it, and the official ``tavily-python``
SDK inside :class:`~polyweb.adapters.tavily.TavilyAdapter` makes the calls.
Every fault must surface with the same normalized error that the adapter's
unit tests assert for real Tavily payloads.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from polyweb.adapters.tavily import TavilyAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from pydantic import SecretStr

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore
from tests._support.live_server import LiveMock, polyweb_settings

MOCK_RANDOM_SEED = 11
MOCK_UNSET_ENV = ("TAVILY_API_KEY", "TAVILY_PROJECT", "TAVILY_ORG_ID")
_PROJECT = UUID("00000000-0000-4000-8000-0000000000aa")


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("tavily") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.opened: list[tuple[TavilyAdapter, httpx.AsyncClient]] = []

    def __call__(self, key: str | None) -> TavilyAdapter:
        # The real factory installs the routing too; the install is idempotent.
        client = create_async_client(polyweb_settings(self.origin))
        adapter = TavilyAdapter(
            client,
            api_key=None if key is None else SecretStr(key),
            runner=ResilientRunner(client, max_attempts=1),
        )
        self.opened.append((adapter, client))
        return adapter


@pytest.fixture
async def adapters(mock_server: LiveMock) -> AsyncIterator[_Adapters]:
    factory = _Adapters(mock_server[0])
    yield factory
    for adapter, client in factory.opened:
        await adapter.aclose()
        await client.aclose()


def _search(query: str = "polyweb mock", limit: int = 3) -> SearchRequest:
    return SearchRequest(project_id=_PROJECT, query=query, limit=limit)


async def _error(call: object) -> ProviderOperationError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value


async def test_search_fetch_and_usage_succeed_and_debit(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(
        FetchRequest(project_id=_PROJECT, url="https://docs.python.org/3/library/json.html")
    )
    snapshot = await adapter.usage_snapshot(
        UsageSyncRequest(provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC))
    )

    assert len(search.results) == 3 and str(search.results[0].url).startswith("https://")
    assert search.usage is not None and search.usage.units == 1
    assert fetch.document.content.startswith("# ")
    assert fetch.usage is not None and fetch.usage.units == 0
    assert snapshot is not None
    assert (snapshot.remaining, snapshot.allowance, snapshot.plan_name) == (
        Decimal(999),
        Decimal(1000),
        "Researcher",
    )
    assert store.account("tavily").credits_used == 1
    logged = store.log_tail("tavily")
    assert [(entry.operation, entry.status, entry.key_label) for entry in logged] == [
        ("search", 200, "default"),
        ("extract", 200, "default"),
        ("usage", 200, "default"),
    ]
    assert logged[0].request_summary["headers"]["host"] == "api.tavily.com"
    assert logged[0].request_summary["headers"]["authorization"] == "<redacted>"


@pytest.mark.parametrize(
    ("host", "server"), [("api.tavily.com", None), ("api.exa.ai", "cloudflare")]
)
async def test_the_server_sends_only_the_provider_server_header(
    store: MockStore, mock_server: LiveMock, host: str, server: str | None
) -> None:
    async with httpx.AsyncClient(base_url=mock_server.origin) as http:
        response = await http.post("/search", json={"query": "q"}, headers={"host": host})

    assert response.status_code in {401, 402}
    assert response.headers.get_list("server") == ([] if server is None else [server])


async def test_keyless_rail_and_its_daily_cap(store: MockStore, adapters: _Adapters) -> None:
    adapter = adapters(None)
    assert len((await adapter.search(_search(limit=2))).results) == 2
    assert store.log_tail("tavily")[-1].key_label == "keyless"

    store.set_keyless("tavily", per_day=1)
    error = (await _error(adapter.search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("rate_limited", 429, True)
    assert error.details["retry_after_seconds"] > 0


async def test_rate_limit_fault_keeps_retry_after(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="tavily",
            operation="search",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=7),
        )
    )
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("rate_limited", 429, True)
    assert error.details == {"retry_after_seconds": 7}


@pytest.mark.parametrize("status", [503, 502])
async def test_outage_is_a_retryable_http_error(
    store: MockStore, key: str, adapters: _Adapters, status: int
) -> None:
    store.add_fault(
        FaultSpec(provider="tavily", kind=FaultKind.OUTAGE, params=FaultParams(status=status))
    )
    error = (await _error(adapters(key).fetch(FetchRequest(url="https://example.com/")))).error

    assert (error.code, error.status_code, error.retryable) == ("http_error", status, True)


@pytest.mark.parametrize(
    ("fault", "balance"),
    [
        (None, Decimal(0)),
        (FaultSpec(provider="tavily", kind=FaultKind.QUOTA_EXHAUSTED), None),
        (
            FaultSpec(
                provider="tavily", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(scope="paygo")
            ),
            None,
        ),
    ],
)
async def test_credit_exhaustion_is_terminal_quota_exhausted(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    fault: FaultSpec | None,
    balance: Decimal | None,
) -> None:
    if balance is not None:
        store.set_credits("tavily", balance)
    if fault is not None:
        store.add_fault(fault)
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 402, False)


async def test_invalid_and_revoked_keys(store: MockStore, key: str, adapters: _Adapters) -> None:
    wrong = await _error(adapters("tvly-dev-notarealkey000000000000000000").search(_search()))
    assert (wrong.error.code, wrong.error.status_code) == ("invalid_api_key", 401)

    store.set_key_status("tavily", "default", "revoked")
    revoked = (await _error(adapters(key).search(_search()))).error
    assert (revoked.code, revoked.status_code, revoked.retryable) == ("invalid_api_key", 401, False)

    usage = await _error(
        adapters(key).usage_snapshot(
            UsageSyncRequest(
                provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
            )
        )
    )
    assert (usage.error.code, usage.error.status_code) == ("http_error", 401)


async def test_auth_invalid_fault(store: MockStore, key: str, adapters: _Adapters) -> None:
    store.add_fault(FaultSpec(provider="tavily", kind=FaultKind.AUTH_INVALID))
    error = (await _error(adapters(key).search(_search()))).error
    assert error.code == "invalid_api_key"


async def test_latency_fault_delays_the_call(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)
    await adapter.search(_search())
    store.set_latency("tavily", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4


async def test_timeout_fault_times_out_in_the_client(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(provider="tavily", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=4))
    )
    error = (await _error(adapters(key).search(_search()))).error
    assert (error.code, error.retryable) == ("timeout_error", True)


async def test_connection_drop_is_a_transport_error(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(FaultSpec(provider="tavily", kind=FaultKind.CONNECTION_DROP))
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.retryable) == ("transport_error", True)
    assert store.log_tail("tavily")[-1].status is None


async def test_malformed_body_is_not_accepted(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="tavily",
            operation="extract",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    store.add_fault(
        FaultSpec(
            provider="tavily",
            operation="search",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="invalid_json"),
        )
    )
    adapter = adapters(key)

    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(FetchRequest(url="https://example.com/")))).error

    assert (search.code, search.retryable) == ("tavily_error", False)
    assert fetch.code == "fetch_failed"
