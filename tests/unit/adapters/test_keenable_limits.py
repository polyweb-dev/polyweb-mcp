"""Keenable adapter unit tests: catalog, usage, state, confidence. Mock HTTP only.

Keenable slice only. Real catalog records with mock-transport adapters.
No vendor I/O, no database, no live keys. Plan: four records share one
keyed pool, keyless has no budget, reported credits debit native units,
paid stays separate, 402 outranks paid unknown, success clears exhaustion.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from polyweb.adapters.keenable import KeenableAdapter
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import SearchRequest, UnitKind
from polyweb.models.provider_limits import (
    AuthMode,
    Confidence,
    LimitOperation,
    UsageSyncRequest,
)

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_KEY = SecretStr("keenable-test-secret")
_PROJECT = "00000000-0000-4000-8000-0000000000aa"


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[object] | None = None,
    *,
    keyless: bool = False,
    runner: ResilientRunner | None = None,
) -> tuple[KeenableAdapter, httpx.AsyncClient]:
    def counting(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    if runner is None:
        adapter = KeenableAdapter(client, api_key=None if keyless else _KEY, runner=None)
        # Swap the default runner for a no-sleep runner only when the caller
        # supplies one; the default path keeps production retry behavior.
        return adapter, client
    adapter = KeenableAdapter(client, api_key=None if keyless else _KEY, runner=runner)
    return adapter, client


def _search_payload(credits: object = 1, *, paid: bool = False) -> dict[str, object]:
    return {
        "results": [{"title": "k", "url": "https://example.com/k"}],
        "_meta": {"keenable/usage": {"credits": credits, "paid": paid, "sku": "search.pro"}},
    }


def _ok_handler(
    credits: object = 1, *, paid: bool = False
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_search_payload(credits, paid=paid))

    return handler


def test_keenable_catalog_shared_profiles() -> None:
    from polyweb.configuration.provider_limits import provider_limit_defaults
    from polyweb.services import credit_units as cu

    records = [r for r in provider_limit_defaults() if r.provider == "keenable"]
    assert len(records) == 4
    keyed = [r for r in records if r.auth_mode is AuthMode.KEYED]
    keyless = [r for r in records if r.auth_mode is AuthMode.KEYLESS]
    assert {r.operation for r in keyed} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    assert {r.operation for r in keyless} == {LimitOperation.SEARCH, LimitOperation.FETCH}
    for record in keyed:
        assert record.native_pool_id == "keenable:keyed:request"
        assert record.native_unit is UnitKind.REQUEST
        assert record.budget is not None
        assert record.budget.free_allowance == Decimal("100000")
        assert record.budget.standard_native_cost == Decimal("1")
        assert cu.request_cost_crd(record) == Decimal("4")
        assert record.conversion_profile.estimated is True
    for record in keyless:
        assert record.budget is None
        assert record.native_unit is None
        assert record.native_pool_id is None


async def test_keyless_snapshot_has_no_budget() -> None:
    adapter, client = _adapter(_ok_handler(), keyless=True)
    try:
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYLESS, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()
    assert snapshot is None
    assert await adapter.quota() is None


async def test_keyed_snapshot_preserves_generation() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="keenable",
                auth_mode=AuthMode.KEYED,
                observed_at=FIXED_AT,
                credential_generation=7,
            )
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.observed_at == FIXED_AT
    assert snapshot.credential_generation == 7
    assert snapshot.pool_id == "keenable:keyed:request"
    assert snapshot.native_unit is UnitKind.REQUEST
    assert snapshot.allowance == Decimal("100000")
    assert snapshot.remaining == Decimal("100000")
    assert snapshot.confidence is Confidence.ESTIMATED
    assert snapshot.source == "local_ledger"


def test_reported_sku_usage() -> None:
    credits, paid, metadata = KeenableAdapter._reported_usage(
        {"_meta": {"keenable/usage": {"credits": 3, "paid": False, "sku": "search.pro"}}}
    )
    assert credits == Decimal("3")
    assert paid is False
    assert metadata == {"sku": "search.pro", "paid": False}


@pytest.mark.parametrize(
    ("credits", "expected"),
    [(0, "0"), (1, "1"), ("0.5", "0.5"), (3, "3"), (2, "2")],
)
def test_reported_zero_fractional_multiple(credits: object, expected: str) -> None:
    got, paid, _ = KeenableAdapter._reported_usage(
        {"_meta": {"keenable/usage": {"credits": credits, "paid": False}}}
    )
    assert got == Decimal(expected)
    assert paid is False


def test_reported_fallback_without_metadata() -> None:
    assert KeenableAdapter._reported_usage(None) == (Decimal("1"), False, {})
    assert KeenableAdapter._reported_usage({}) == (Decimal("1"), False, {})
    assert KeenableAdapter._reported_usage({"results": []}) == (Decimal("1"), False, {})


@pytest.mark.parametrize(
    "credits",
    [-1, "-0.5", True, False, "lots", "49, 900", "", None, "NaN", "Infinity", "-Infinity"],
)
def test_reported_negative_bool_nonfinite_malformed(credits: object) -> None:
    payload: dict[str, object] = {"_meta": {"keenable/usage": {"credits": credits}}}
    if credits is None:
        payload = {"_meta": {"keenable/usage": {"paid": False}}}
        got, paid, _ = KeenableAdapter._reported_usage(payload)
        assert got == Decimal("1")
        assert paid is False
        return
    with pytest.raises(ValueError):
        KeenableAdapter._reported_usage(payload)


def test_reported_inf_float_rejected() -> None:
    with pytest.raises(ValueError):
        KeenableAdapter._reported_usage({"_meta": {"keenable/usage": {"credits": float("inf")}}})
    with pytest.raises(ValueError):
        KeenableAdapter._reported_usage({"_meta": {"keenable/usage": {"credits": float("nan")}}})


def test_reported_nonbool_paid_rejected() -> None:
    with pytest.raises(ValueError):
        KeenableAdapter._reported_usage(
            {"_meta": {"keenable/usage": {"credits": 1, "paid": "yes"}}}
        )


async def test_keyless_payload_without_usage_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"title": "k", "url": "https://example.com/k"}]}
        )

    adapter, client = _adapter(handler, keyless=True)
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
    finally:
        await client.aclose()
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert response.usage.unit_kind is UnitKind.REQUEST


async def test_malformed_numeric_usage_gives_invalid_response_without_counter_change() -> None:
    calls: list[object] = []
    adapter, client = _adapter(
        lambda request: httpx.Response(200, json=_search_payload("lots")), calls
    )
    try:
        with pytest.raises(ProviderOperationError) as exc_info:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            )
    finally:
        await client.aclose()
    assert exc_info.value.error.code == "invalid_response"
    assert len(calls) == 1
    quota = await adapter.quota()
    assert quota is not None
    assert quota.remaining == Decimal("100000")


async def test_apply_usage_rejects_negative_and_nonfinite_before_counter_change() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        with pytest.raises(ValueError):
            adapter.apply_usage(credits=Decimal("-1"))
        with pytest.raises(ValueError):
            adapter.apply_usage(credits=Decimal("NaN"))
        with pytest.raises(ValueError):
            adapter.apply_usage(credits=Decimal("Infinity"))
        quota = await adapter.quota()
    finally:
        await client.aclose()
    assert quota is not None
    assert quota.remaining == Decimal("100000")


async def test_paid_then_402_has_zero_remaining() -> None:
    adapter, client = _adapter(_ok_handler(2, paid=True))
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="paid", limit=2)
        )
        assert response.usage is not None
        assert response.usage.units == Decimal("2")
        assert adapter._paid_usage_seen is True
        assert adapter._paid_spend == Decimal("2")
        assert adapter._allowance_spend == Decimal("0")
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
        assert snapshot is not None
        assert snapshot.remaining is None
        assert snapshot.confidence is Confidence.UNKNOWN
        await adapter.quota_after_error(402)
        exhausted = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()
    assert exhausted is not None
    assert exhausted.remaining == Decimal("0")
    assert exhausted.confidence is Confidence.OBSERVED


async def test_success_clears_hard_exhaustion() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        await adapter.quota_after_error(402)
        assert (await adapter.quota()).remaining == Decimal("0")  # type: ignore[union-attr]
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
        quota = await adapter.quota()
    finally:
        await client.aclose()
    assert quota is not None
    assert quota.remaining == Decimal("99999")


async def test_success_after_previous_402_debits_once() -> None:
    adapter, client = _adapter(_ok_handler(3))
    try:
        await adapter.quota_after_error(402)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
        )
        quota = await adapter.quota()
    finally:
        await client.aclose()
    assert response.usage is not None
    assert response.usage.units == Decimal("3")
    assert quota is not None
    assert quota.remaining == Decimal("99997")


async def test_free_and_paid_spend_stay_separate() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        adapter.apply_usage(credits=Decimal("3"), paid=False)
        adapter.apply_usage(credits=Decimal("2"), paid=True)
        assert adapter._allowance_spend == Decimal("3")
        assert adapter._paid_spend == Decimal("2")
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.remaining is None
    assert snapshot.confidence is Confidence.UNKNOWN


async def test_monthly_rollover_resets_spend() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        adapter.apply_usage(credits=Decimal("5"), paid=False)
        assert (await adapter.quota()).remaining == Decimal("99995")  # type: ignore[union-attr]
        adapter._rollover_if_needed(datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC))
        quota = await adapter.quota()
    finally:
        await client.aclose()
    assert quota is not None
    assert quota.remaining == Decimal("100000")


async def test_quota_after_error_429_preserves_budget() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        adapter.apply_usage(credits=Decimal("5"), paid=False)
        result = await adapter.quota_after_error(429)
        quota = await adapter.quota()
    finally:
        await client.aclose()
    assert result is None
    assert quota is not None
    assert quota.remaining == Decimal("99995")


async def test_quota_after_error_402_without_paid_is_zero_observed() -> None:
    adapter, client = _adapter(_ok_handler())
    try:
        await adapter.quota_after_error(402)
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.remaining == Decimal("0")
    assert snapshot.confidence is Confidence.OBSERVED


class _StubRepo:
    def __init__(self, events: list[object], latest: object | None) -> None:
        self._events = events
        self._latest = latest

    async def list_provider_usage(self, provider: str, since: object | None = None) -> list[object]:
        del provider, since
        return self._events

    async def latest_quota(self, provider: str) -> object | None:
        del provider
        return self._latest


async def test_hydrate_quota_restores_paid_and_exhaustion() -> None:
    from polyweb.models.contracts import UsageEvent, UsageOperation, UsageStatus

    now = datetime.now(UTC)
    events = [
        UsageEvent(
            provider="keenable",
            operation=UsageOperation.SEARCH,
            units=Decimal("2"),
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            observed_at=now,
            status=UsageStatus.SUCCESS,
            metadata={"paid": True},
        )
    ]
    adapter, client = _adapter(_ok_handler())
    try:
        await adapter.hydrate_quota(_StubRepo(events, None))  # type: ignore[arg-type]
        assert adapter._paid_usage_seen is True
        assert adapter._paid_spend == Decimal("2")
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()
    assert snapshot is not None
    assert snapshot.remaining is None
    assert snapshot.confidence is Confidence.UNKNOWN


async def test_retry_429_uses_fake_sleeper_with_three_attempts() -> None:
    calls: list[object] = []
    delays: list[float] = []

    async def fake_sleeper(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "HTTP 429"})

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting), timeout=30.0)
    try:
        runner = ResilientRunner(client, sleeper=fake_sleeper, base_delay=0.01, max_delay=0.05)
        adapter = KeenableAdapter(client, api_key=_KEY, runner=runner)
        with pytest.raises(ProviderOperationError) as exc_info:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            )
    finally:
        await client.aclose()
    assert exc_info.value.error.retryable is True
    assert len(calls) == 3
    assert len(delays) >= 2


async def test_no_retry_402_with_single_attempt() -> None:
    calls: list[object] = []
    adapter, client = _adapter(
        lambda request: httpx.Response(402, json={"error": "HTTP 402"}), calls
    )
    try:
        with pytest.raises(ProviderOperationError) as exc_info:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2)
            )
    finally:
        await client.aclose()
    assert exc_info.value.error.code == "quota_exhausted"
    assert exc_info.value.error.retryable is False
    assert len(calls) == 1


# ------------------------------------------- AC #11: billed responses report credits


def _http_usage_payload(
    *, credits: int = 1, paid: bool = True, credits_remaining: int | None = 4000
) -> dict[str, object]:
    usage: dict[str, object] = {
        "sku": "search.pro",
        "amount": credits,
        "credits": credits,
        "paid": paid,
    }
    if credits_remaining is not None:
        usage["credits_remaining"] = credits_remaining
    return {"results": [{"title": "k", "url": "https://example.com/k"}], "usage": usage}


def test_http_usage_object_keeps_credits_remaining_and_paid() -> None:
    """AC #11: the HTTP ``usage`` object is read, including ``credits_remaining``."""

    credits, paid, metadata = KeenableAdapter._reported_usage(
        _http_usage_payload(credits=2, paid=True, credits_remaining=99120)
    )

    assert (credits, paid) == (Decimal("2"), True)
    assert metadata["credits_remaining"] == "99120"
    assert metadata["paid"] is True


async def test_credits_remaining_is_published_as_a_vendor_fact() -> None:
    """AC #11: a billed response's ``credits_remaining`` is the key's observed balance."""

    adapter, client = _adapter(lambda request: httpx.Response(200, json=_http_usage_payload()))
    try:
        await adapter.search(SearchRequest(project_id=_PROJECT, query="q", limit=1))
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()

    assert snapshot is not None
    assert (snapshot.source, snapshot.confidence) == ("vendor_api", Confidence.OBSERVED)
    assert snapshot.remaining == Decimal("4000")


async def test_paid_use_past_the_free_allowance_does_not_block_the_key() -> None:
    """AC #11: a spent free allowance is not a zero balance; purchased credits may remain."""

    adapter, client = _adapter(lambda request: httpx.Response(200, json=_http_usage_payload()))
    try:
        adapter._allowance_spend = Decimal("100000")
        before = await adapter.quota()
        await adapter.search(SearchRequest(project_id=_PROJECT, query="q", limit=1))
        after = await adapter.quota()
    finally:
        await client.aclose()

    assert before is not None and before.remaining != Decimal("0")
    assert after is not None and after.remaining == Decimal("4000")


async def test_spent_free_allowance_without_a_vendor_balance_stays_unknown() -> None:
    """A10 (AC #11): free credits spent, no paid use and no credits_remaining is unknown.

    The free tier is large, so Polyweb never blocks a key on a guess: purchased
    credits may remain. The vendor 402 is the hard stop.
    """

    adapter, client = _adapter(_ok_handler(credits=1, paid=False))
    try:
        adapter.apply_usage(credits=Decimal("100000"), paid=False)
        await adapter.search(SearchRequest(project_id=_PROJECT, query="q", limit=1))
        quota = await adapter.quota()
        snapshot = await adapter.usage_snapshot(
            UsageSyncRequest(provider="keenable", auth_mode=AuthMode.KEYED, observed_at=FIXED_AT)
        )
    finally:
        await client.aclose()

    assert quota is not None and quota.remaining is None
    assert snapshot is not None
    assert (snapshot.source, snapshot.remaining) == ("local_ledger", None)
    assert snapshot.confidence is Confidence.ESTIMATED
