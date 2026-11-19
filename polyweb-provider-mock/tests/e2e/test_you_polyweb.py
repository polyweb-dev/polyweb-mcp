"""End to end: the real Polyweb You.com adapter against a live mock server.

The mock runs under uvicorn on a free loopback port. Polyweb's own startup
interception (``install_provider_mock`` through ``create_async_client``)
reroutes ``ydc-index.io`` and ``api.you.com`` to it, and
:class:`~polyweb.adapters.youcom.YoucomAdapter` makes the calls through its
borrowed transport. Every fault must surface with the normalized error that
the adapter's unit tests assert for the matching real You.com status.
"""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from polyweb.adapters.youcom import YoucomAdapter
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from pydantic import SecretStr

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import plugin
from polyweb_provider_mock.store import MockStore
from tests._support.live_server import LiveMock, polyweb_settings

MOCK_RANDOM_SEED = 13
_PROJECT = UUID("00000000-0000-4000-8000-0000000000bb")


@pytest.fixture
def key(store: MockStore) -> str:
    return next(item.key for item in store.keys("you") if item.label == "default")


class _Adapters:
    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.opened: list[tuple[YoucomAdapter, httpx.AsyncClient]] = []

    def __call__(self, key: str) -> YoucomAdapter:
        client = create_async_client(polyweb_settings(self.origin))
        adapter = YoucomAdapter(
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


def _fetch(url: str = "https://docs.python.org/3/library/json.html") -> FetchRequest:
    return FetchRequest(project_id=_PROJECT, url=url)


async def _error(call: object) -> ProviderOperationError:
    with pytest.raises(ProviderOperationError) as raised:
        await call  # type: ignore[misc]
    return raised.value


async def test_search_fetch_and_balance_succeed_and_debit(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(_fetch())
    origin = await adapter.fetch(_fetch("https://example.com"))
    snapshot = await adapter.usage_snapshot(
        UsageSyncRequest(provider="you", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC))
    )

    assert len(search.results) == 3 and search.results[0].snippet
    assert search.provider_metadata is not None and "search_uuid" in search.provider_metadata
    assert (
        fetch.document.content.startswith("# ") and fetch.document.content_type == "text/markdown"
    )
    assert fetch.document.metadata["site_name"] == "Python"
    assert origin.document.title == "Example Domain"
    assert snapshot is not None
    assert (snapshot.remaining, snapshot.allowance) == (Decimal("99.993"), None)
    assert store.account("you").credits_used == Decimal("0.7")
    logged = store.log_tail("you")
    assert [(entry.operation, entry.status, entry.key_label) for entry in logged] == [
        ("search", 200, "default"),
        ("contents", 200, "default"),
        ("contents", 200, "default"),
        ("balance", 200, "default"),
    ]
    assert logged[0].request_summary["headers"]["host"] == "ydc-index.io"
    assert logged[-1].request_summary["headers"]["host"] == "api.you.com"
    assert logged[0].request_summary["headers"]["x-api-key"] == "<redacted>"


async def test_full_page_extraction_reaches_result_metadata(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    request = SearchRequest(
        project_id=_PROJECT,
        query="polyweb mock",
        limit=2,
        provider_options={
            "you": {
                "extraction": {
                    "mode": "full_page",
                    "source": "fetch",
                    "full_page": {"extraction_formats": ["markdown"]},
                }
            }
        },
    )
    response = await adapters(key).search(request)

    assert all("markdown" in result.metadata["contents"] for result in response.results)
    assert store.account("you").credits_used == Decimal("0.7")


async def test_wrong_and_revoked_keys_follow_the_real_hosts(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    wrong = adapters(plugin("you").key_format.generate())
    assert (await _error(wrong.search(_search()))).error.code == "forbidden"
    assert (await _error(wrong.quota())).error.code == "invalid_api_key"

    store.set_key_status("you", "default", "revoked")
    revoked = adapters(key)
    search = (await _error(revoked.search(_search()))).error
    fetch = (await _error(revoked.fetch(_fetch()))).error
    quota = (await _error(revoked.quota())).error

    assert (search.code, search.status_code, search.retryable) == ("forbidden", 403, False)
    assert (fetch.code, fetch.status_code) == ("forbidden", 403)
    assert (quota.code, quota.status_code) == ("invalid_api_key", 401)


async def test_empty_wallet_is_insufficient_credits(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.set_credits("you", Decimal(0))
    adapter = adapters(key)

    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(_fetch()))).error
    quota = await adapter.quota()

    assert (search.code, search.status_code, search.retryable) == (
        "insufficient_credits",
        402,
        False,
    )
    assert fetch.code == "insufficient_credits"
    assert quota.remaining == Decimal(0)


async def test_key_spend_cap_surfaces_as_a_rate_limit(
    store: MockStore, adapters: _Adapters
) -> None:
    capped = next(item.key for item in store.keys("you") if item.label == "capped")
    principal = store.resolve("you", capped)
    assert principal is not None
    store.charge(principal, "search", Decimal(200))
    error = (await _error(adapters(capped).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == ("rate_limited", 429, True)


@pytest.mark.parametrize(
    ("spec", "code", "status", "retryable"),
    [
        (FaultSpec(provider="you", kind=FaultKind.RATE_LIMIT), "rate_limited", 429, True),
        (
            FaultSpec(provider="you", kind=FaultKind.QUOTA_EXHAUSTED),
            "insufficient_credits",
            402,
            False,
        ),
        (FaultSpec(provider="you", kind=FaultKind.AUTH_INVALID), "forbidden", 403, False),
        (
            FaultSpec(provider="you", kind=FaultKind.OUTAGE, params=FaultParams(status=503)),
            "http_error",
            503,
            True,
        ),
        (
            FaultSpec(provider="you", kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            "http_error",
            502,
            True,
        ),
        (
            FaultSpec(provider="you", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=400)),
            "bad_request",
            400,
            False,
        ),
        (
            FaultSpec(provider="you", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=404)),
            "http_error",
            404,
            False,
        ),
    ],
)
async def test_search_faults_map_like_real_statuses(
    store: MockStore,
    key: str,
    adapters: _Adapters,
    spec: FaultSpec,
    code: str,
    status: int,
    retryable: bool,
) -> None:
    store.add_fault(spec)
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.status_code, error.retryable) == (code, status, retryable)
    assert store.account("you").credits_used == 0


async def test_auth_invalid_fault_on_the_balance_host(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(FaultSpec(provider="you", operation="balance", kind=FaultKind.AUTH_INVALID))
    error = (await _error(adapters(key).quota())).error
    assert (error.code, error.status_code) == ("invalid_api_key", 401)


async def test_failed_page_is_fetch_failed(key: str, adapters: _Adapters) -> None:
    error = (await _error(adapters(key).fetch(_fetch("https://blocked.example.org/a")))).error
    assert (error.code, error.retryable) == ("fetch_failed", False)


async def test_latency_fault_delays_the_call(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    adapter = adapters(key)
    await adapter.search(_search())
    store.set_latency("you", 400, 0)

    started = time.perf_counter()
    await adapter.search(_search())

    assert time.perf_counter() - started >= 0.4


@pytest.mark.parametrize("kind", [FaultKind.TIMEOUT, FaultKind.CONNECTION_DROP])
async def test_timeout_and_dropped_connection_are_transport_errors(
    store: MockStore, key: str, adapters: _Adapters, kind: FaultKind
) -> None:
    store.add_fault(FaultSpec(provider="you", kind=kind, params=FaultParams(seconds=4)))
    error = (await _error(adapters(key).search(_search()))).error

    assert (error.code, error.retryable) == ("transport_error", True)


async def test_malformed_bodies_are_invalid_responses(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    for operation, variant in (
        ("search", "invalid_json"),
        ("contents", "missing_field"),
        ("balance", "missing_field"),
    ):
        store.add_fault(
            FaultSpec(
                provider="you",
                operation=operation,
                kind=FaultKind.MALFORMED,
                params=FaultParams.model_validate({"variant": variant}),
            )
        )
    adapter = adapters(key)

    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(_fetch()))).error
    quota = (await _error(adapter.quota())).error

    assert {search.code, fetch.code, quota.code} == {"invalid_response"}


async def test_missing_url_fault_keeps_parse_errors(
    store: MockStore, key: str, adapters: _Adapters
) -> None:
    store.add_fault(
        FaultSpec(
            provider="you",
            operation="search",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    response = await adapters(key).search(_search())

    assert response.results == []
    assert response.usage_gap is not None and len(response.usage_gap["parse_errors"]) == 3
