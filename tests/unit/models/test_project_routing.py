"""Provider order model validation."""

import pytest
from pydantic import ValidationError

from polyweb.models.contracts import RoutingConfigResponse, RoutingConfigUpdate
from polyweb.models.project_routing import OperationOrderUpdate, StoredProjectOrder


def test_missing_operations_default_to_lowest_cost() -> None:
    order = StoredProjectOrder.model_validate({})
    assert order.search.strategy == order.fetch.strategy == "lowest_cost"
    assert order.search.custom_order is None


def test_preset_rejects_an_order() -> None:
    with pytest.raises(ValidationError):
        OperationOrderUpdate.model_validate({"strategy": "free_first", "order": []})
    with pytest.raises(ValidationError):
        OperationOrderUpdate.model_validate({"strategy": "free_first", "order": None})


def test_custom_accepts_order_or_restore() -> None:
    assert OperationOrderUpdate.model_validate({"strategy": "custom"}).order is None
    assert OperationOrderUpdate.model_validate({"strategy": "custom", "order": ["exa"]}).order == [
        "exa"
    ]


def test_legacy_system_routing_loads_without_exposing_preset() -> None:
    legacy = {
        "fallback_policy": "first_only",
        "max_attempts": 7,
        "cost_optimization_preset": "free_first",
    }
    loaded = RoutingConfigResponse.model_validate(legacy)
    assert loaded.model_dump(mode="json") == {"fallback_policy": "first_only", "max_attempts": 7}
    with pytest.raises(ValidationError):
        RoutingConfigUpdate.model_validate(legacy)
