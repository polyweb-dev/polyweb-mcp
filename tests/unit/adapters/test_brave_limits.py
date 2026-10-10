"""S1 Brave unit tests: headers, budget math, error split. Mock HTTP only.

Brave files only. No vendor I/O, no database, no provider keys on the wire.
Plan: monthly comma-pair headers as budget, search 5 CRDs, funds 402
against rate 429, QUOTA_LIMITED final against RATE_LIMITED retryable.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.brave import (
    BraveAdapter,
    monthly_header_value,
)
from freesearch.models.contracts import SearchRequest, UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    CRDState,
    LimitOperation,
    UsageSyncRequest,
)
from freesearch.services import credit_units as cu


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[object] | None = None,
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    def counting(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    return BraveAdapter(client, api_key=SecretStr("brave-test-secret")), client


def _payload() -> dict[str, object]:
    return {
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


def _ok_handler(
    remaining: str = "49, 900", limit: str = "50, 1000"
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"X-RateLimit-Remaining": remaining, "X-RateLimit-Limit": limit},
        )

    return handler


def test_monthly_pair_takes_second_element() -> None:
    assert monthly_header_value("49, 900") == 900
    assert monthly_header_value("50, 1000") == 1000
    assert monthly_header_value(" 49 ,  900 ") == 900


def test_monthly_bare_and_bad_values_stay_absent() -> None:
    assert monthly_header_value(None) is None
    assert monthly_header_value("50") is None
    assert monthly_header_value("49, ") is None
    assert monthly_header_value("49, -1") is None
    assert monthly_header_value("49, lots") is None


def test_burst_takes_first_element() -> None:
    assert BraveAdapter._rate_limit_remaining("49, 900") == 49
    assert BraveAdapter._rate_limit_remaining("50") == 50
    assert BraveAdapter._rate_limit_remaining(None) is None
    assert BraveAdapter._rate_limit_remaining("49, -1") == 49
    assert BraveAdapter._rate_limit_remaining("nope") is None


def test_brave_catalog_holds_two_keyed_records() -> None:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    records = [r for r in provider_limit_defaults() if r.provider == "brave"]
    assert len(records) == 2
    assert all(r.auth_mode is AuthMode.KEYED for r in records)
    search = next(r for r in records if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in records if r.operation is LimitOperation.FETCH)
    assert search.supported and search.transport_available
    assert search.budget is not None and search.native_unit is UnitKind.USD
    assert fetch.supported is False and fetch.transport_available is False
    assert fetch.rate is None and fetch.budget is None


def test_brave_search_costs_five_crds() -> None:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    search = next(
        r
        for r in provider_limit_defaults()
        if r.provider == "brave" and r.operation is LimitOperation.SEARCH
    )
    assert cu.request_cost_crd(search) == Decimal("5")


def test_usd_from_requests_rejects_partial_and_negative() -> None:
    assert BraveAdapter._usd_from_requests(None) is None
    assert BraveAdapter._usd_from_requests(Decimal("-1")) is None
    assert BraveAdapter._usd_from_requests(Decimal("1.5")) is None
    assert BraveAdapter._usd_from_requests(Decimal("900")) == Decimal("4.500")


async def test_usage_snapshot_monthly_pair_becomes_budget() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        await adapter.search(SearchRequest(query="q", limit=2))
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="brave",
                auth_mode=AuthMode.KEYED,
                observed_at=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
            )
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.remaining == Decimal("4.500")
    assert snapshot.allowance == Decimal("5.000")
    assert snapshot.source == "vendor_headers"
    assert snapshot.native_unit is UnitKind.USD
    assert len(snapshot.rate_observations) == 1
    assert snapshot.rate_observations[0].window.value == "1s"
    assert snapshot.rate_observations[0].remaining == Decimal("49")


async def test_usage_snapshot_without_headers_is_local_ledger() -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=_payload()))
    try:
        await adapter.search(SearchRequest(query="q", limit=2))
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="brave",
                auth_mode=AuthMode.KEYED,
                observed_at=datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
            )
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.source == "local_ledger"
    assert snapshot.rate_observations == []


def _error(status: int, code: str | None) -> httpx.Response:
    if code is None:
        return httpx.Response(status, text="boom")
    return httpx.Response(status, json={"code": code})


@pytest.mark.parametrize("code", ["CREDIT_EXHAUSTED", "QUOTA_LIMITED", "USAGE_LIMIT_EXCEEDED"])
def test_http_error_body_markers_are_final(code: str) -> None:
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=_payload()))
    error = adapter._http_error(_error(402, code))
    assert error.error.code == "quota_exhausted"
    assert error.error.retryable is False
    assert error.error.status_code == 402


def test_http_error_429_quota_keeps_vendor_status_without_retry() -> None:
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=_payload()))
    error = adapter._http_error(_error(429, "QUOTA_LIMITED"))
    assert error.error.code == "quota_exhausted"
    assert error.error.retryable is False
    assert error.error.status_code == 429


def test_http_error_429_rate_stays_retryable() -> None:
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=_payload()))
    error = adapter._http_error(_error(429, "RATE_LIMITED"))
    assert error.error.code == "http_error"
    assert error.error.retryable is True


def test_brave_fetch_view_is_unavailable() -> None:
    from freesearch.configuration.provider_limits import provider_limit_defaults

    fetch = next(
        r
        for r in provider_limit_defaults()
        if r.provider == "brave" and r.operation is LimitOperation.FETCH
    )
    view = cu.crd_view(fetch, None)
    assert view.state is CRDState.UNAVAILABLE
    assert view.remaining_crd is None
