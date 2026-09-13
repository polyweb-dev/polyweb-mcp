from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from freesearch.models.contracts import (
    FetchRequest,
    ManualQuota,
    ManualQuotaUpdate,
    ProviderError,
    QuotaSnapshot,
    QuotaSource,
    RoutingMode,
    RoutingPreference,
    SearchRequest,
    UsageEvent,
    UsageOperation,
)


def test_search_request_defaults_are_stable() -> None:
    request = SearchRequest(query="free search")

    assert request.limit == 10
    assert request.routing.mode is RoutingMode.AUTO
    assert request.routing.allow_fallback is True


def test_contract_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="query", provider="unexpected")  # type: ignore[call-arg]


def test_fetch_request_requires_an_http_url() -> None:
    with pytest.raises(ValidationError):
        FetchRequest(url="not-a-url")


def test_quota_source_distinguishes_estimates_from_authoritative_data() -> None:
    quota = QuotaSnapshot(
        provider="example",
        source=QuotaSource.ESTIMATED,
        remaining=Decimal("3"),
        observed_at=datetime.now(UTC),
    )

    assert quota.source is QuotaSource.ESTIMATED


def test_usage_event_is_provider_neutral() -> None:
    event = UsageEvent(
        provider="example",
        operation=UsageOperation.SEARCH,
        units=Decimal("0.25"),
        observed_at=datetime.now(UTC),
    )

    assert event.model_dump(mode="json")["operation"] == "search"


def test_provider_error_does_not_require_vendor_fields() -> None:
    error = ProviderError(provider="example", code="rate_limited", message="Try again")

    assert error.retryable is False


def test_routing_preference_rejects_blank_provider_names() -> None:
    with pytest.raises(ValidationError):
        RoutingPreference(mode=RoutingMode.PREFER, providers=("",))


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-01", "2026-09-01"),
        ("2026-09-02", "2026-09-01"),
        ("2026-10-01", "2026-08-01"),
    ],
)
def test_manual_quota_update_rejects_bad_window(start: str, end: str) -> None:
    """Lock ManualQuotaUpdate window parity with ManualQuota (slice 2.1)."""
    with pytest.raises(ValidationError):
        ManualQuotaUpdate(
            billing_start=start,  # type: ignore[arg-type]
            billing_end=end,  # type: ignore[arg-type]
            allowance="5.00",
            current_usage="0.00",
        )


@pytest.mark.parametrize("bad", [True, False, 5.0, 0.88])
@pytest.mark.parametrize("field", ["allowance", "current_usage"])
def test_manual_quota_update_rejects_bool_and_float(bad: object, field: str) -> None:
    """Lock TypeError->ValueError conversion parity on ManualQuotaUpdate."""
    payload: dict[str, object] = {
        "billing_start": "2026-08-01",
        "billing_end": "2026-09-01",
        "allowance": "5.00",
        "current_usage": "0.00",
    }
    payload[field] = bad
    with pytest.raises(ValidationError):
        ManualQuotaUpdate.model_validate(payload)


@pytest.mark.parametrize("model", [ManualQuota, ManualQuotaUpdate])
def test_manual_quota_inputs_keep_note_optional(
    model: type[ManualQuota] | type[ManualQuotaUpdate],
) -> None:
    """Lock optional note handling shared by both input models."""
    assert (
        model(
            billing_start="2026-08-01",  # type: ignore[arg-type]
            billing_end="2026-09-01",  # type: ignore[arg-type]
            allowance="5.00",
            current_usage="0.00",
        ).note
        is None
    )
    assert (
        model(
            billing_start="2026-08-01",  # type: ignore[arg-type]
            billing_end="2026-09-01",  # type: ignore[arg-type]
            allowance="5.00",
            current_usage="0.00",
            note="x" * 500,
        ).note
        == "x" * 500
    )
    with pytest.raises(ValidationError):
        model(
            billing_start="2026-08-01",  # type: ignore[arg-type]
            billing_end="2026-09-01",  # type: ignore[arg-type]
            allowance="5.00",
            current_usage="0.00",
            note="x" * 501,
        )


@pytest.mark.parametrize("model", [ManualQuota, ManualQuotaUpdate])
def test_manual_quota_inputs_permit_zero_allowance(
    model: type[ManualQuota] | type[ManualQuotaUpdate],
) -> None:
    """Lock backend zero-allowance acceptance (differs from client validation)."""
    quota = model(
        billing_start="2026-08-01",  # type: ignore[arg-type]
        billing_end="2026-09-01",  # type: ignore[arg-type]
        allowance="0",
        current_usage="0",
    )
    assert quota.allowance == Decimal("0")
