"""End to end: the real Polyweb Firecrawl adapter against a live mock server.

Search and scrape go through the official ``firecrawl-py`` SDK, whose
private HTTPX client Polyweb's startup routing reroutes; the credit-usage
poll goes through Polyweb's shared client. Every fault must surface with the
same normalized error that the adapter's unit tests assert for real
Firecrawl payloads.
"""

import time
import types
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from firecrawl.v2.methods.aio import scrape as sdk_scrape
from polyweb.adapters.firecrawl import FirecrawlAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.provider_mock import provider_mock_origin
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, ProviderError, SearchRequest
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from pydantic import SecretStr

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore
from tests.e2e._exa_firecrawl_server import polyweb_settings, serve_mock

_PROJECT = UUID("00000000-0000-4000-8000-0000000000fc")
_DOC = "https://docs.python.org/3/library/json.html"


@pytest.fixture(scope="module")
def mock_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, MockStore]]:
    folder = Path(tmp_path_factory.mktemp("firecrawl"))
    with serve_mock(folder, "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL") as served:
        yield served


@pytest.fixture
def store(mock_server: tuple[str, MockStore]) -> MockStore:
    origin, state = mock_server
    assert provider_mock_origin() == origin
    state.seed(discover().values(), reset=True)
    return state


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("firecrawl") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.opened: list[tuple[FirecrawlAdapter, httpx.AsyncClient]] = []

    def __call__(self, key: str) -> FirecrawlAdapter:
        client = create_async_client(polyweb_settings(self.origin))
        adapter = FirecrawlAdapter(
            client, api_key=SecretStr(key), runner=ResilientRunner(client, max_attempts=1)
        )
        self.opened.append((adapter, client))
        return adapter


@pytest.fixture
async def adapters(mock_server: tuple[str, MockStore]) -> AsyncIterator[_Adapters]:
    factory = _Adapters(mock_server[0])
    yield factory
    for adapter, client in factory.opened:
        await adapter.aclose()
        await client.aclose()


def _search(query: str = "polyweb mock", limit: int = 3) -> SearchRequest:
    return SearchRequest(project_id=_PROJECT, query=query, limit=limit)


def _fetch(url: str = _DOC) -> FetchRequest:
    return FetchRequest(project_id=_PROJECT, url=url)


def _sync() -> UsageSyncRequest:
    return UsageSyncRequest(
        provider="firecrawl", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
    )


async def _error(call: object) -> ProviderError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value.error


async def test_search_fetch_and_credit_usage_succeed_and_debit(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(_fetch())
    quota = await adapter.quota()
    snapshot = await adapter.usage_snapshot(_sync())

    assert len(search.results) == 3 and search.results[0].snippet
    # The SDK drops the search envelope's creditsUsed, as with the live API.
    assert search.usage is None
    assert fetch.document.content.startswith("# Library Json")
    assert fetch.document.title == "Library Json"
    assert fetch.usage is not None and fetch.usage.units == Decimal(1)
    account = store.account("firecrawl")
    assert account.credits_used == 3
    assert quota is not None and (quota.remaining, quota.limit) == (Decimal(997), Decimal(1000))
    assert quota.reset_at == account.period_reset
    assert snapshot is not None and snapshot.source == "vendor_api"
    assert (snapshot.remaining, snapshot.allowance) == (Decimal(997), Decimal(1000))
    assert snapshot.plan_name == "Free plan (1,000 monthly credits)"
    logged = store.log_tail("firecrawl")
    assert [(entry.operation, entry.status) for entry in logged] == [
        ("search", 200),
        ("scrape", 200),
        ("credit_usage", 200),
        ("credit_usage", 200),
    ]
    assert logged[1].request_summary["body"]["origin"].startswith("python-sdk@")
    assert logged[2].request_summary["headers"]["authorization"] == "<redacted>"


async def test_scrape_auto_resume_adopts_the_finished_document(
    store: MockStore, key: str, adapters: _Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def no_wait(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(sdk_scrape, "asyncio", types.SimpleNamespace(sleep=no_wait))
    fetch = await adapters(key).fetch(_fetch("https://processing.example.org/report.pdf"))

    assert slept == [5.0, 5.0]
    assert [entry.status for entry in store.log_tail("firecrawl")] == [408, 408, 200]
    assert fetch.usage is not None and fetch.usage.units == store.account("firecrawl").credits_used
    assert fetch.document.content_type == "application/pdf"


async def test_invalid_and_revoked_keys_are_non_retryable_401(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    wrong = await _error(adapters("fc-00000000000000000000000000000000").search(_search()))
    store.set_key_status("firecrawl", "default", "revoked")
    revoked = await _error(adapters(key).fetch(_fetch()))
    quota = await _error(adapters(key).quota())

    for error in (wrong, revoked, quota):
        assert (error.code, error.status_code, error.retryable) == ("http_error", 401, False)


async def test_credit_exhaustion_is_quota_exhausted_and_usage_reads_zero(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.set_credits("firecrawl", Decimal(0))
    adapter = adapters(key)

    error = await _error(adapter.fetch(_fetch()))
    snapshot = await adapter.quota_after_error(402)

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 402, False)
    assert snapshot is not None and snapshot.remaining == 0


async def test_402_on_credit_usage_is_a_vendor_zero_or_quota_exhausted(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="credit_usage",
            kind=FaultKind.HTTP_ERROR,
            params=FaultParams(status=402),
        )
    )
    adapter = adapters(key)

    snapshot = await adapter.usage_snapshot(_sync())
    error = await _error(adapter.quota())

    assert snapshot is not None and (snapshot.source, snapshot.remaining) == ("vendor_402", 0)
    assert (error.code, error.status_code) == ("quota_exhausted", 402)


@pytest.mark.parametrize(
    ("spec", "operation", "expected"),
    [
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.RATE_LIMIT),
            "fetch",
            ("http_error", 429, True),
        ),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.OUTAGE),
            "search",
            ("http_error", 503, True),
        ),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.HTTP_ERROR),
            "fetch",
            ("http_error", 500, True),
        ),
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=403)
            ),
            "fetch",
            ("forbidden", 403, False),
        ),
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=408)
            ),
            "fetch",
            ("scrape_timeout", 408, True),
        ),
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=408)
            ),
            "search",
            ("timeout_error", 408, True),
        ),
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=400)
            ),
            "search",
            ("http_error", 400, False),
        ),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.AUTH_INVALID),
            "search",
            ("http_error", 401, False),
        ),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.QUOTA_EXHAUSTED),
            "search",
            ("quota_exhausted", 402, False),
        ),
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=0.5)
            ),
            "fetch",
            ("http_error", 504, True),
        ),
    ],
)
async def test_http_faults_map_like_real_firecrawl_payloads(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    spec: FaultSpec,
    operation: str,
    expected: tuple[str, int, bool],
) -> None:
    store.add_fault(spec)
    adapter = adapters(key)
    call = adapter.search(_search()) if operation == "search" else adapter.fetch(_fetch())

    error = await _error(call)

    assert (error.code, error.status_code, error.retryable) == expected
    assert store.account("firecrawl").credits_used == 0


async def test_rate_limited_quota_poll_waits_for_retry_after(
    store: MockStore, key: str, adapters: _Adapters, mock_server: tuple[str, MockStore]
) -> None:
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="credit_usage",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=1),
            count=1,
        )
    )
    error = await _error(adapters(key).quota())
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="credit_usage",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=1),
            count=1,
        )
    )
    client = create_async_client(polyweb_settings(mock_server[0]))
    retrying = FirecrawlAdapter(
        client, api_key=SecretStr(key), runner=ResilientRunner(client, max_attempts=2)
    )
    started = time.perf_counter()
    try:
        quota = await retrying.quota()
    finally:
        await retrying.aclose()
        await client.aclose()

    assert (error.code, error.status_code, error.retryable) == ("http_error", 429, True)
    assert quota is not None and quota.remaining == 1000
    assert time.perf_counter() - started >= 1.0
    assert [entry.status for entry in store.log_tail("firecrawl")] == [429, 429, 200]


async def test_transport_faults_are_retryable_transport_errors(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(provider="firecrawl", operation="scrape", kind=FaultKind.CONNECTION_DROP)
    )
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="credit_usage",
            kind=FaultKind.TIMEOUT,
            params=FaultParams(seconds=3),
        )
    )
    adapter = adapters(key)

    dropped = await _error(adapter.fetch(_fetch()))
    timed_out = await _error(adapter.quota())

    assert (dropped.code, dropped.retryable) == ("transport_error", True)
    assert (timed_out.code, timed_out.retryable) == ("transport_error", True)


@pytest.mark.parametrize(
    ("variant", "operation", "code"),
    [
        ("invalid_json", "fetch", "firecrawl_error"),
        ("invalid_json", "search", "firecrawl_error"),
        ("missing_field", "fetch", "firecrawl_error"),
        ("missing_field", "search", "http_error"),
    ],
)
async def test_malformed_bodies_are_non_retryable(
    store: MockStore, key: str, adapters: _Adapters, variant: str, operation: str, code: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            kind=FaultKind.MALFORMED,
            params=FaultParams.model_validate({"variant": variant}),
        )
    )
    adapter = adapters(key)
    call = adapter.search(_search()) if operation == "search" else adapter.fetch(_fetch())

    error = await _error(call)

    assert (error.code, error.retryable) == (code, False)
