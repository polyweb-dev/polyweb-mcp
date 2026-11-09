"""Unit tests for vault pool validation and money conversion."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from freesearch.models.credentials import CredentialOperation
from freesearch.models.vault import KeyPoolCreate, KeyPoolRead, PoolBudget
from freesearch.services.control_errors import ResourceInvalid
from freesearch.services.key_pools import pool_budget, pool_values, validate_operations

_BOTH = frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH})


def test_operations_default_to_supported_capabilities() -> None:
    assert validate_operations("example", None, supported=_BOTH) == {"search", "fetch"}


@pytest.mark.parametrize(
    ("operations", "code"),
    [(frozenset(), "OPERATIONS_REQUIRED"), (frozenset({"other"}), "OPERATION_NOT_SUPPORTED")],
)
def test_invalid_operations_have_stable_codes(operations: frozenset[str], code: str) -> None:
    with pytest.raises(ResourceInvalid) as error:
        validate_operations("example", operations, supported=_BOTH)
    assert error.value.code == code


def test_operation_limits_must_match_allowed_operations() -> None:
    with pytest.raises(ResourceInvalid) as error:
        validate_operations("example", frozenset({"search"}), {"fetch": 1}, supported=_BOTH)
    assert error.value.code == "OPERATION_NOT_SUPPORTED"


@pytest.mark.parametrize("period", ["day", "week", "month"])
def test_decimal_budget_round_trip(period: str) -> None:
    body = KeyPoolCreate.model_validate(
        {"label": "pool", "budget": {"limit": "12.345678", "period": period}}
    )
    values = pool_values("example", body, supported=_BOTH)
    assert values.budget_limit == 12_345_678
    budget = pool_budget(values.budget_limit, values.budget_window_seconds)
    assert budget is not None
    assert budget.limit == Decimal("12.345678")
    assert budget.period == period


def test_budget_defaults_to_month_and_rejects_sub_microdollars() -> None:
    assert PoolBudget(limit=Decimal("1")).period == "month"
    with pytest.raises(ValidationError):
        PoolBudget(limit=Decimal("0.0000001"))


def test_migrated_operation_limits_round_trip() -> None:
    from uuid import uuid4

    limits = {
        "search": {"rate_limit": 20, "rate_window_seconds": 60},
        "fetch": {"rate_limit": None, "rate_window_seconds": 3600},
    }
    body = KeyPoolCreate.model_validate(
        {"label": "legacy", "operations": ["search", "fetch"], "operation_limits": limits}
    )
    values = pool_values("example", body, supported=_BOTH)
    assert values.operation_limits == limits
    view = KeyPoolRead.model_validate(
        {
            "id": uuid4(),
            "credential_id": uuid4(),
            "project_id": None,
            "provider_type": "example",
            "label": "legacy",
            "rate": {"limit": 20, "window_seconds": 60},
            "budget": None,
            "budget_used_usd": 0,
            "operations": ["search", "fetch"],
            "operation_limits": values.operation_limits,
        }
    )
    assert view.model_dump(mode="json")["operation_limits"] == limits
