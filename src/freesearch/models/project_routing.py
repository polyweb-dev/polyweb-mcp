"""Contracts for a project's per-operation provider order."""

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from freesearch.models.contracts import ContractModel


class RoutingStrategy(StrEnum):
    FREE_FIRST = "free_first"
    LOWEST_COST = "lowest_cost"
    CUSTOM = "custom"


class RoutingOperation(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"


class OrderItem(ContractModel):
    provider: str
    name: str
    call_cost_usd: Decimal | None
    keyless: bool = False


class OperationOrder(ContractModel):
    strategy: RoutingStrategy = RoutingStrategy.LOWEST_COST
    providers: list[OrderItem] = Field(default_factory=list)
    has_saved_custom: bool = False
    not_allowed: list[str] = Field(default_factory=list)


class ProjectOrderResponse(ContractModel):
    revision: int
    search: OperationOrder
    fetch: OperationOrder


class OperationOrderUpdate(ContractModel):
    strategy: RoutingStrategy
    order: list[str] | None = None

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.strategy != RoutingStrategy.CUSTOM and "order" in self.model_fields_set:
            raise ValueError("order is only allowed with custom strategy")
        return self


class StoredOperationOrder(ContractModel):
    strategy: RoutingStrategy = RoutingStrategy.LOWEST_COST
    custom_order: list[str] | None = None


class StoredProjectOrder(ContractModel):
    search: StoredOperationOrder = Field(default_factory=StoredOperationOrder)
    fetch: StoredOperationOrder = Field(default_factory=StoredOperationOrder)
