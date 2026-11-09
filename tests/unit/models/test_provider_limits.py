"""Synthetic S0 unit tests for provider-limit contracts.

No provider builders, no vendor I/O, no DB. Period and link rules that live
in the router are noted where the model only decodes.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from polyweb.models.contracts import UnitKind
from polyweb.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    CRDGrantPayload,
    CRDGrantsSummary,
    CRDState,
    CRDView,
    LimitHistoryQuery,
    LimitOperation,
    NativePool,
    ProviderAuthLimits,
    ProviderLimitDetail,
    ProviderLimitsResponse,
    RateProgressView,
    RateUnit,
    TierBalance,
    local_funds_denial,
    local_rate_denial,
    native_pool_id,
    parse_exact_decimal,
    unpriced_ceiling_error,
)
from polyweb.routers.limits import _validate_usage_url

FIXED = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


# parse_exact_decimal ---------------------------------------------------------


def test_parse_accepts_int_exact_str_and_decimal() -> None:
    assert parse_exact_decimal(5) == Decimal("5")
    assert parse_exact_decimal("0.005") == Decimal("0.005")
    assert parse_exact_decimal(Decimal("0.599")) == Decimal("0.599")


def test_parse_rejects_bool() -> None:
    with pytest.raises(ValueError):
        parse_exact_decimal(True)
    with pytest.raises(ValueError):
        parse_exact_decimal(False)


def test_parse_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        parse_exact_decimal(float("inf"))
    with pytest.raises(ValueError):
        parse_exact_decimal(Decimal("NaN"))
    with pytest.raises(ValueError):
        parse_exact_decimal(Decimal("Infinity"))


def test_parse_rejects_negative_by_default_accepts_when_allowed() -> None:
    with pytest.raises(ValueError):
        parse_exact_decimal("-1")
    with pytest.raises(ValueError):
        parse_exact_decimal(Decimal("-0.5"))
    assert parse_exact_decimal("-1", allow_negative=True) == Decimal("-1")


def test_json_float_half_stays_exact() -> None:
    assert parse_exact_decimal(0.5) == Decimal("0.5")
    assert isinstance(parse_exact_decimal(0.5), Decimal)


def test_exact_decimal_serializes_as_string() -> None:
    block = BudgetBlock(standard_native_cost=Decimal("0.005"))
    payload = block.model_dump(mode="json")
    assert payload["standard_native_cost"] == "0.005"


# BudgetBlock -----------------------------------------------------------------


def test_budget_block_defaults_and_priced_flag() -> None:
    # No zero-divisor validator exists; the priced flag carries the state.
    block = BudgetBlock()
    assert block.standard_native_cost == Decimal("1")
    assert block.priced is True
    unpriced = BudgetBlock(standard_native_cost=Decimal("0.005"), priced=False)
    assert unpriced.priced is False
    assert unpriced.standard_native_cost == Decimal("0.005")


# Enums -----------------------------------------------------------------------


def test_limit_operation_only_search_and_fetch() -> None:
    assert {item.value for item in LimitOperation} == {"search", "fetch"}
    assert LimitOperation.SEARCH.usage_operation == "search"
    assert LimitOperation.FETCH.usage_operation == "fetch"
    with pytest.raises(ValueError):
        LimitOperation("cost_estimate")


def test_auth_mode_keyless_and_keyed() -> None:
    assert {item.value for item in AuthMode} == {"keyless", "keyed"}
    with pytest.raises(ValueError):
        AuthMode("oauth")


def test_crd_state_has_four_values() -> None:
    assert {item.value for item in CRDState} == {"finite", "unmetered", "unavailable", "unknown"}


# Response shape --------------------------------------------------------------


def _auth_entry(mode: AuthMode) -> ProviderAuthLimits:
    return ProviderAuthLimits(
        auth_mode=mode,
        transport_available=True,
        free_tiers=[
            TierBalance(pool_id="p-free", tier="free", native_unit=UnitKind.USD),
        ],
        paid_tiers=[
            TierBalance(pool_id="p-paid", tier="paid", native_unit=UnitKind.USD),
        ],
        unknown_tiers=[],
        tier_split_known=True,
        aggregate_pool=NativePool(
            pool_id="synth:keyed:usd",
            provider="synth",
            auth_mode=mode,
            native_unit=UnitKind.USD,
            remaining=Decimal("5"),
        ),
        crd_views=[
            CRDView(state=CRDState.FINITE, operation=LimitOperation.SEARCH),
        ],
        rate_progress=[
            RateProgressView(
                bucket_id="synth-hour",
                operation=LimitOperation.SEARCH,
                window="1h",
                unit=RateUnit.REQUESTS,
            ),
        ],
        grants=CRDGrantsSummary(
            provider="synth",
            auth_mode=mode,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        ),
        detail=ProviderLimitDetail(plan_name="synthetic"),
    )


def test_provider_limits_response_auth_shape() -> None:
    response = ProviderLimitsResponse(
        provider="synth",
        active_auth_mode=AuthMode.KEYED,
        auths=[_auth_entry(AuthMode.KEYED), _auth_entry(AuthMode.KEYLESS)],
        generated_at=FIXED,
    )
    assert len(response.auths) == 2
    keyed = response.auth(AuthMode.KEYED)
    assert keyed is not None
    assert keyed.auth_mode is AuthMode.KEYED
    assert len(keyed.free_tiers) == 1
    assert len(keyed.paid_tiers) == 1
    assert keyed.unknown_tiers == []
    assert keyed.aggregate_pool is not None
    assert keyed.aggregate_pool.pool_id == "synth:keyed:usd"
    assert keyed.tier_split_known is True
    assert len(keyed.crd_views) == 1
    assert len(keyed.rate_progress) == 1
    assert keyed.grants is not None
    assert keyed.detail is not None
    assert response.auth(AuthMode.KEYED) is keyed
    assert response.auth(AuthMode.KEYLESS) is not response.auth(AuthMode.KEYED)


# Grants and history ----------------------------------------------------------


def test_grant_payload_grants_mapping() -> None:
    payload = CRDGrantPayload(
        period="month",
        search_crd=Decimal("10"),
        fetch_crd=Decimal("4"),
    )
    assert payload.grants[LimitOperation.SEARCH] == Decimal("10")
    assert payload.grants[LimitOperation.FETCH] == Decimal("4")


def test_grant_period_defaults_to_month_and_rejects_custom_ranges() -> None:
    assert CRDGrantPayload().period == "month"
    with pytest.raises(ValidationError):
        CRDGrantPayload.model_validate({"period": "year"})


def test_history_limit_accepts_one_to_one_hundred() -> None:
    assert LimitHistoryQuery(provider="synth", limit=1).limit == 1
    assert LimitHistoryQuery(provider="synth").limit == 50
    assert LimitHistoryQuery(provider="synth", limit=100).limit == 100
    with pytest.raises(ValidationError):
        LimitHistoryQuery(provider="synth", limit=0)
    with pytest.raises(ValidationError):
        LimitHistoryQuery(provider="synth", limit=101)


# Links and pool IDs ----------------------------------------------------------


def test_usage_url_decode_preserves_router_enforces() -> None:
    # The model only decodes; _validate_usage_url owns https/no-credentials.
    from polyweb.models.provider_limits import ProviderLimitRecord

    record = ProviderLimitRecord(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        usage_url="http://example.com/usage",
    )
    assert record.usage_url == "http://example.com/usage"
    _validate_usage_url(None)
    _validate_usage_url("https://example.com/usage")
    with pytest.raises(HTTPException):
        _validate_usage_url("http://example.com/usage")
    with pytest.raises(HTTPException):
        _validate_usage_url("https://user:secret@example.com")


def test_native_pool_id_format() -> None:
    assert native_pool_id("synth", AuthMode.KEYED, UnitKind.USD) == "synth:keyed:usd"
    assert native_pool_id("synth", AuthMode.KEYED, UnitKind.CREDIT) == "synth:keyed:credit"
    assert native_pool_id("synth", AuthMode.KEYLESS, UnitKind.REQUEST) == "synth:keyless:request"
    assert native_pool_id("you", AuthMode.KEYED, UnitKind.FREE) == "you:keyed:free"


# Denials ---------------------------------------------------------------------


def test_local_funds_denial_is_402_with_local_origin() -> None:
    error = local_funds_denial("synth", operation=LimitOperation.SEARCH, reasons=["empty"])
    assert error.status_code == 402
    assert error.refusal == "funds"
    assert error.error.status_code == 402
    assert error.error.code == "budget_exhausted"
    assert error.error.details["origin"] == "local"
    assert error.error.details["refusal"] == "funds"
    assert error.retry_after_seconds is None


def test_unknown_budget_price_has_public_error_code() -> None:
    error = unpriced_ceiling_error("synth", LimitOperation.SEARCH)
    assert error.error.code == "budget_price_unknown"
    assert error.error.status_code == 422
    assert error.error.details["reasons"] == ["price_unknown"]


def test_local_rate_denial_is_429_with_retry_after() -> None:
    error = local_rate_denial(
        "synth",
        operation=LimitOperation.SEARCH,
        reasons=["capacity"],
        retry_after_seconds=3600,
    )
    assert error.status_code == 429
    assert error.refusal == "rate"
    assert error.retry_after_seconds == 3600
    assert error.error.status_code == 429
    assert error.error.code == "rate_limited"
    assert error.error.details["origin"] == "local"
    assert error.error.details["retry_after_seconds"] == 3600
