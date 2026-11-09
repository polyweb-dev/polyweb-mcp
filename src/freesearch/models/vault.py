"""Wire contracts for vault keys and their project pools."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from freesearch.models.credentials import CredentialCreate

BudgetPeriod = Literal["day", "week", "month"]
ContentionMode = Literal["equal", "ratio"]


class VaultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PoolRate(VaultModel):
    limit: int | None = Field(default=None, ge=0)
    window_seconds: int = Field(default=60, gt=0)


class OperationRate(VaultModel):
    rate_limit: int | None = Field(ge=0)
    rate_window_seconds: int = Field(gt=0)


OperationLimit = int | None | OperationRate


class PoolBudget(VaultModel):
    limit: Decimal = Field(
        ge=0,
        le=Decimal("9223372036854.775807"),
        decimal_places=6,
        allow_inf_nan=False,
    )
    period: BudgetPeriod = "month"

    @field_serializer("limit", when_used="json")
    def serialize_limit(self, value: Decimal) -> float:
        return float(value)


class VaultKeyCreate(CredentialCreate):
    capacity: PoolRate | None = None
    overcommit: bool = True
    contention_mode: ContentionMode = "equal"


class VaultKeyUpdate(VaultModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    capacity: PoolRate | None = None
    overcommit: bool | None = None
    contention_mode: ContentionMode | None = None


class VaultKeyRead(VaultModel):
    id: UUID
    provider_type: str
    label: str
    auth_mode: str
    status: str
    generation: int
    created_at: str
    capacity: PoolRate | None
    overcommit: bool
    contention_mode: ContentionMode
    pool_count: int


class KeyPoolCreate(VaultModel):
    label: str = Field(min_length=1, max_length=100)
    project_id: UUID | None = None
    rate: PoolRate = Field(default_factory=PoolRate)
    budget: PoolBudget | None = None
    operations: frozenset[str] | None = None
    operation_limits: dict[str, OperationLimit] | None = None


class KeyPoolUpdate(VaultModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    rate: PoolRate | None = None
    budget: PoolBudget | None = None
    operations: frozenset[str] | None = None
    operation_limits: dict[str, OperationLimit] | None = None


class KeyPoolRead(VaultModel):
    id: UUID
    credential_id: UUID
    project_id: UUID | None
    provider_type: str
    label: str
    rate: PoolRate
    budget: PoolBudget | None
    budget_used_usd: Decimal
    operations: frozenset[str]
    operation_limits: dict[str, OperationLimit] | None

    @field_serializer("budget_used_usd", when_used="json")
    def serialize_used(self, value: Decimal) -> float:
        return float(value)


class PoolAssignment(VaultModel):
    project_id: UUID
    label: str | None = Field(default=None, min_length=1, max_length=100)


class VaultProject(VaultModel):
    id: UUID
    name: str
    available_providers: list[str]


class VaultKeyDetails(VaultKeyRead):
    rotated_at: str | None = None
    health: str | None = None


class DeletedVaultPool(VaultModel):
    id: UUID
    project_id: UUID | None


class VaultKeyDeleteResult(VaultModel):
    deleted_pools: list[DeletedVaultPool]
