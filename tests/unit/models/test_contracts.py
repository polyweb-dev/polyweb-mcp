from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from polyweb.models.contracts import (
    FetchRequest,
    ManualQuota,
    ManualQuotaUpdate,
    ProviderError,
    ProviderStatusResponse,
    QuotaSnapshot,
    QuotaSource,
    RoutingMode,
    RoutingPreference,
    SearchRequest,
    UsageEvent,
    UsageOperation,
)


def test_search_request_defaults_are_stable() -> None:
    request = SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="Polyweb MCP")

    assert request.limit == 10
    assert request.routing.mode is RoutingMode.AUTO
    assert request.routing.allow_fallback is True


def test_provider_options_are_optional_ordered_after_routing_and_use_public_alias() -> None:
    search_properties = list(SearchRequest.model_json_schema(by_alias=True)["properties"])
    fetch_properties = list(FetchRequest.model_json_schema(by_alias=True)["properties"])

    assert search_properties.index("providerOptions") == search_properties.index("routing") + 1
    assert fetch_properties.index("providerOptions") == fetch_properties.index("routing") + 1
    assert "tavily" not in search_properties
    assert "tavily" not in fetch_properties
    assert SearchRequest.model_fields["provider_options"].alias == "providerOptions"
    assert FetchRequest.model_fields["provider_options"].alias == "providerOptions"


def test_provider_options_validate_per_operation_without_changing_routing() -> None:
    search = SearchRequest.model_validate(
        {
            "project_id": "00000000-0000-4000-8000-0000000000aa",
            "query": "q",
            "providerOptions": {"tavily": {"search_depth": "fast"}},
        }
    )
    assert search.provider_options is not None
    assert search.provider_options.tavily is not None
    assert search.provider_options.tavily.search_depth == "fast"
    assert search.routing.mode is RoutingMode.AUTO
    assert search.routing.providers == ()

    fetch = FetchRequest.model_validate(
        {
            "project_id": "00000000-0000-4000-8000-0000000000aa",
            "url": "https://example.com/page",
            "providerOptions": {"tavily": {"extract_depth": "advanced"}},
        }
    )
    assert fetch.provider_options is not None
    assert fetch.provider_options.tavily is not None
    assert fetch.provider_options.tavily.extract_depth == "advanced"

    with pytest.raises(ValidationError):
        SearchRequest.model_validate(
            {
                "project_id": "00000000-0000-4000-8000-0000000000aa",
                "query": "q",
                "tavily": {"topic": "news"},
            }
        )
    with pytest.raises(ValidationError):
        FetchRequest.model_validate(
            {
                "project_id": "00000000-0000-4000-8000-0000000000aa",
                "url": "https://example.com/page",
                "providerOptions": {"tavily": {"topic": "news"}},
            }
        )


def test_contract_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", query="query", provider="unexpected"
        )  # type: ignore[call-arg]


def test_fetch_request_requires_an_http_url() -> None:
    with pytest.raises(ValidationError):
        FetchRequest(project_id="00000000-0000-4000-8000-0000000000aa", url="not-a-url")


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


def _status_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "provider_id": "tavily",
        "enabled": True,
        "enable_mask": 7,
        "support_mask": 7,
        "health": None,
        "circuit_breaker": {"state": "closed", "updated_at": "2026-01-01T00:00:00Z"},
        "latency_p95_ms": None,
        "secret_presence": "missing",
        "free_tier_estimates": {},
        "reset_schedule": None,
    }
    base.update(overrides)
    return base


def test_provider_status_tavily_key_environment_defaults_none() -> None:
    """The readback is absent unless the control seam sets it (other providers null)."""

    status = ProviderStatusResponse(**_status_kwargs())  # type: ignore[arg-type]

    assert status.tavily_key_environment is None


@pytest.mark.parametrize("value", ["dev", "prod"])
def test_provider_status_tavily_key_environment_accepts_dev_prod(value: str) -> None:
    """Strict dev/prod readback values validate."""

    status = ProviderStatusResponse(**_status_kwargs(tavily_key_environment=value))  # type: ignore[arg-type]

    assert status.tavily_key_environment == value


def test_provider_status_tavily_key_environment_accepts_explicit_none() -> None:
    """Explicit null stays null (unknown/absent stored environment)."""

    status = ProviderStatusResponse(**_status_kwargs(tavily_key_environment=None))  # type: ignore[arg-type]

    assert status.tavily_key_environment is None


@pytest.mark.parametrize("bad", ["staging", "DEV", "PROD", "", "keyless", 0, 1, True, False])
def test_provider_status_tavily_key_environment_rejects_other_values(bad: object) -> None:
    """Only dev/prod/None validate; no generic tier or inferred value passes."""

    with pytest.raises(ValidationError):
        ProviderStatusResponse(**_status_kwargs(tavily_key_environment=bad))  # type: ignore[arg-type]


@pytest.mark.parametrize("provider_id", ["exa", "brave", "keenable", "tinyfish", "tavily"])
def test_provider_status_other_records_keep_null_default(provider_id: str) -> None:
    """Non-Tavily readback stays null; Tavily without a value also stays null."""

    status = ProviderStatusResponse(**_status_kwargs(provider_id=provider_id))  # type: ignore[arg-type]

    assert status.tavily_key_environment is None


def test_provider_status_response_keeps_all_current_fields() -> None:
    """All current status fields stay intact beside the nullable readback."""

    assert set(ProviderStatusResponse.model_fields) == {
        "provider_id",
        "enabled",
        "enable_mask",
        "support_mask",
        "call_cost_usd",
        "keyless_call_cost_usd",
        "health",
        "health_checked_at",
        "circuit_breaker",
        "latency_p95_ms",
        "secret_presence",
        "free_tier_estimates",
        "reset_schedule",
        "tavily_key_environment",
    }
