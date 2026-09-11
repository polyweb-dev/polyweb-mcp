from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from freesearch.models.contracts import (
    FetchRequest,
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
