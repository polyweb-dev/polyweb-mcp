"""End to end: the real Polyweb Exa adapter against a live mock server.

The official ``exa-py`` SDK inside :class:`~polyweb.adapters.exa.ExaAdapter`
owns its HTTPX client; Polyweb's startup routing reroutes ``api.exa.ai`` from
that client to the mock. Every fault must surface with the same normalized
error that the adapter's unit tests assert for real Exa payloads.
"""

import time
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from polyweb.adapters.exa import ExaAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, ProviderError, SearchRequest
from pydantic import SecretStr

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.store import MockStore
from tests._support.live_server import LiveMock, polyweb_settings

MOCK_RANDOM_SEED = 11
MOCK_UNSET_ENV = ("EXA_API_KEY",)
_PROJECT = UUID("00000000-0000-4000-8000-0000000000ee")


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("exa") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.opened: list[tuple[ExaAdapter, httpx.AsyncClient]] = []

    def __call__(self, key: str) -> ExaAdapter:
        client = create_async_client(polyweb_settings(self.origin))
        adapter = ExaAdapter(
            client, api_key=SecretStr(key), runner=ResilientRunner(client, max_attempts=1)
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


def _fetch(url: str = "https://example.com") -> FetchRequest:
    return FetchRequest(project_id=_PROJECT, url=url)


async def _error(call: object) -> ProviderError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value.error


async def test_search_and_fetch_succeed_with_measured_cost(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(_fetch("https://docs.python.org/3/library/json.html"))

    assert len(search.results) == 3 and search.results[0].snippet
    assert str(search.results[0].url).startswith("https://")
    assert search.usage is not None and search.usage.units == Decimal("0.007")
    assert "provenance" not in search.usage.metadata
    assert fetch.document.title == "Library Json"
    assert fetch.document.content.startswith("Library Json\n\n## ")
    assert fetch.usage is not None and fetch.usage.units == Decimal("0.001")
    assert store.account("exa").credits_used == Decimal("0.008")
    logged = store.log_tail("exa")
    assert [(entry.operation, entry.status, entry.key_label) for entry in logged] == [
        ("search", 200, "default"),
        ("contents", 200, "default"),
    ]
    assert logged[0].request_summary["headers"]["host"] == "api.exa.ai"
    assert logged[0].request_summary["headers"]["x-api-key"] == "<redacted>"
    assert logged[0].request_summary["body"]["contents"] == {"highlights": True}


async def test_url_level_crawl_failure_is_fetch_failed(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    error = await _error(adapters(key).fetch(_fetch("https://blocked.example.org/page")))
    assert (error.code, error.retryable) == ("fetch_failed", False)
    assert store.account("exa").credits_used == 0


async def test_invalid_and_revoked_keys(store: MockStore, key: str, adapters: _Adapters) -> None:
    wrong = await _error(adapters("00000000-0000-4000-8000-000000000000").search(_search()))
    store.set_key_status("exa", "default", "revoked")
    revoked = await _error(adapters(key).fetch(_fetch()))

    for error in (wrong, revoked):
        assert (error.code, error.status_code, error.retryable) == ("invalid_api_key", 401, False)


@pytest.mark.parametrize(
    ("fault", "balance", "vendor_code"),
    [
        (None, Decimal(0), "NO_MORE_CREDITS"),
        (FaultSpec(provider="exa", kind=FaultKind.QUOTA_EXHAUSTED), None, "NO_MORE_CREDITS"),
        (
            FaultSpec(
                provider="exa", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(scope="key")
            ),
            None,
            "API_KEY_BUDGET_EXCEEDED",
        ),
        (
            FaultSpec(
                provider="exa", kind=FaultKind.QUOTA_EXHAUSTED, params=FaultParams(scope="team")
            ),
            None,
            "TEAM_BUDGET_EXCEEDED",
        ),
    ],
)
async def test_credit_exhaustion_is_terminal_quota_exhausted(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    fault: FaultSpec | None,
    balance: Decimal | None,
    vendor_code: str,
) -> None:
    if balance is not None:
        store.set_credits("exa", balance)
    if fault is not None:
        store.add_fault(fault)
    adapter = adapters(key)
    error = await _error(adapter.search(_search()))

    assert (error.code, error.status_code, error.retryable) == ("quota_exhausted", 402, False)
    assert error.details == {"error_code": vendor_code}
    snapshot = adapter.quota_after_error(402)
    assert snapshot is not None and snapshot.remaining == 0


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (FaultSpec(provider="exa", kind=FaultKind.RATE_LIMIT), ("rate_limited", 429, True)),
        (FaultSpec(provider="exa", kind=FaultKind.OUTAGE), ("http_error", 503, True)),
        (
            FaultSpec(provider="exa", kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            ("http_error", 502, True),
        ),
        (
            FaultSpec(provider="exa", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=403)),
            ("forbidden", 403, False),
        ),
        (
            FaultSpec(provider="exa", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=400)),
            ("bad_request", 400, False),
        ),
        (
            FaultSpec(provider="exa", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=501)),
            ("http_error", 501, False),
        ),
        (FaultSpec(provider="exa", kind=FaultKind.AUTH_INVALID), ("invalid_api_key", 401, False)),
        (
            FaultSpec(
                provider="exa", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=0.5, status=504)
            ),
            ("http_error", 504, True),
        ),
        (
            FaultSpec(provider="exa", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=0.5)),
            ("transport_error", None, True),
        ),
    ],
)
async def test_http_faults_map_like_real_exa_payloads(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    spec: FaultSpec,
    expected: tuple[str, int, bool],
) -> None:
    store.add_fault(spec)
    error = await _error(adapters(key).search(_search()))

    assert (error.code, error.status_code, error.retryable) == expected
    assert "Exa" not in error.message or error.code == "quota_exhausted"
    assert store.account("exa").credits_used == 0


async def test_connection_drop_is_a_transport_error(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(FaultSpec(provider="exa", kind=FaultKind.CONNECTION_DROP))
    error = await _error(adapters(key).fetch(_fetch()))

    assert (error.code, error.retryable) == ("transport_error", True)
    assert store.log_tail("exa")[-1].status is None


@pytest.mark.parametrize("variant", ["invalid_json", "missing_field"])
async def test_malformed_body_is_a_non_retryable_sdk_failure(
    store: MockStore, key: str, adapters: _Adapters, variant: str
) -> None:
    store.add_fault(
        FaultSpec(
            provider="exa",
            kind=FaultKind.MALFORMED,
            params=FaultParams.model_validate({"variant": variant}),
        )
    )
    error = await _error(adapters(key).search(_search()))
    assert (error.code, error.retryable) == ("exa_error", False)


async def test_latency_fault_delays_the_call(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)
    await adapter.search(_search())
    store.set_latency("exa", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4
