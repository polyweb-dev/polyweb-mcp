"""USD boundary conversion leaves persisted credit values and native balances intact."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from freesearch.models.provider_limits import (
    CRD_PRICE_VERSION,
    AuthMode,
    CRDGrantsSummary,
    CRDUsageTotal,
    CRDView,
    LimitAuditEvent,
    LimitHistoryPage,
    LimitOperation,
    NativePool,
    ProviderAuthLimits,
    ProviderLimitsResponse,
    TierBalance,
    VaultKeyUsage,
)
from freesearch.models.quota_api import (
    USDBudgetPayload,
    USDGrantsSummary,
    USDHistoryPage,
    USDProviderLimits,
    USDUsageTotal,
    USDVaultKeyUsage,
)
from freesearch.routers.api import create_app


def test_existing_budget_projects_to_usd_without_mutation() -> None:
    stored = CRDGrantsSummary(
        provider="tavily",
        auth_mode=AuthMode.KEYED,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        search_granted_crd=Decimal("1234.567"),
        search_consumed_crd=Decimal("8"),
        search_reserved_crd=Decimal("1.6"),
        fetch_granted_crd=Decimal("4.500"),
    )
    result = USDGrantsSummary.model_validate(stored).model_dump(mode="json")
    assert Decimal(result["search_granted_usd"]) == Decimal("1.234567")
    assert Decimal(result["search_consumed_usd"]) == Decimal("0.008")
    assert Decimal(result["search_reserved_usd"]) == Decimal("0.0016")
    assert Decimal(result["fetch_granted_usd"]) == Decimal("0.0045")
    assert stored.search_granted_crd == Decimal("1234.567")
    assert not any("crd" in key for key in result)


def test_budget_write_converts_exact_usd_to_existing_ledger_unit() -> None:
    payload = USDBudgetPayload(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        search_usd=Decimal("1.234567"),
        fetch_usd=Decimal("0.0045"),
    )
    stored = payload.to_ledger()
    assert stored.search_crd == Decimal("1234.567")
    assert stored.fetch_crd == Decimal("4.5")


def test_budget_rejects_old_credit_fields_and_negative_usd() -> None:
    bounds = {"period_start": "2026-11-01", "period_end": "2026-11-30"}
    with pytest.raises(ValidationError):
        USDBudgetPayload.model_validate({**bounds, "search_crd": "10"})
    with pytest.raises(ValidationError):
        USDBudgetPayload.model_validate({**bounds, "search_usd": "-1"})


def test_provider_projection_converts_views_and_local_tiers_once() -> None:
    tier = TierBalance(
        pool_id="tavily:keyed:grant:search",
        tier="paid",
        native_unit="CREDIT",
        native_remaining=Decimal("8"),
        native_allowance=Decimal("16"),
        remaining_crd=Decimal("8"),
        allowance_crd=Decimal("16"),
        source="operator_grant",
    )
    vendor = tier.model_copy(update={"source": "vendor_api", "pool_id": "tavily:keyed:free"})
    stored = ProviderLimitsResponse(
        provider="tavily",
        active_auth_mode=AuthMode.KEYED,
        generated_at=datetime.now(UTC),
        auths=[
            ProviderAuthLimits(
                auth_mode=AuthMode.KEYED,
                paid_tiers=[tier],
                free_tiers=[vendor],
                aggregate_pool=NativePool(
                    pool_id="tavily:keyed:credit",
                    provider="tavily",
                    auth_mode=AuthMode.KEYED,
                    native_unit="CREDIT",
                    tiers=[vendor],
                ),
                crd_views=[
                    CRDView(
                        state="finite",
                        operation=LimitOperation.SEARCH,
                        remaining_crd=Decimal("8"),
                        request_cost_crd=Decimal("1.6"),
                        price_version=CRD_PRICE_VERSION,
                    )
                ],
            )
        ],
    )
    wire = USDProviderLimits.model_validate(stored)
    auth = wire.auths[0]
    assert auth.usd_views[0].remaining_usd == Decimal("0.008")
    assert auth.usd_views[0].request_cost_usd == Decimal("0.0016")
    assert auth.paid_tiers[0].native_unit == "USD"
    assert auth.paid_tiers[0].native_remaining == Decimal("0.008")
    assert auth.free_tiers[0].native_remaining == Decimal("8")
    assert auth.free_tiers[0].native_unit == "CREDIT"
    assert auth.aggregate_pool is not None
    assert auth.aggregate_pool.tiers[0].remaining_usd == Decimal("0.008")
    assert auth.aggregate_pool.tiers[0].native_remaining == Decimal("8")
    assert "remaining_crd" not in auth.aggregate_pool.model_dump()["tiers"][0]
    assert auth.usd_views[0].price_version == "usd-v1"
    key = USDVaultKeyUsage.model_validate(
        VaultKeyUsage(
            key_id=uuid4(),
            label="Key",
            owner_email="owner@example.test",
            balance=stored.auths[0].aggregate_pool,
        )
    )
    assert key.balance is not None
    assert key.balance.tiers[0].remaining_usd == Decimal("0.008")
    assert USDProviderLimits.model_validate(wire.model_dump()).model_dump() == wire.model_dump()


def test_openapi_does_not_expose_ledger_currency_names() -> None:
    schema = json.dumps(create_app([]).openapi()).lower()
    assert "crd" not in schema
    assert "normalized_credit" not in schema


def test_history_and_usage_totals_expose_usd() -> None:
    history = LimitHistoryPage(
        events=[
            LimitAuditEvent(
                event_id="event",
                provider="tavily",
                auth_mode=AuthMode.KEYED,
                observed_at=datetime.now(UTC),
                source="operator",
                reason="grant",
                old_crd=Decimal("5"),
                new_crd=Decimal("10"),
                crd_debit=Decimal("1.6"),
            )
        ]
    )
    event = USDHistoryPage.model_validate(history).events[0]
    assert event.old_usd == Decimal("0.005")
    assert event.new_usd == Decimal("0.010")
    assert event.debit_usd == Decimal("0.0016")
    total = USDUsageTotal.model_validate(
        CRDUsageTotal(
            provider="tavily",
            operation="search",
            normalized_crd=Decimal("16"),
            attempt_count=2,
        )
    )
    assert total.spend_usd == Decimal("0.016")
    assert total.attempt_count == 2
