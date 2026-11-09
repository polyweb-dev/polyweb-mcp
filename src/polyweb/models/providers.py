"""Project provider bindings, provider views, pools and allocations (A4).

Wire/domain DTOs only. No model here carries secret material, secret slot
names, digests, pool balances or consumption, or another project's data.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from polyweb.models.contracts import ContractModel, UsageOperation
from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import CredentialOwnerScope
from polyweb.models.schema_enums import PoolStatus, UpstreamScope

RateAlgorithm = Literal["fixed_window", "rolling_window", "token_bucket"]


def _reject_control_characters(value: str, field_name: str) -> str:
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


# ----------------------------------------------------------------------
# Project bindings
# ----------------------------------------------------------------------


class BindingCreate(ContractModel):
    """Create one project binding. It always starts with no enabled operations.

    ``enabled_operations`` is not accepted here: enabling is a separate,
    explicit update, so a new binding never silently enables execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: UUID
    route_label: str = Field(min_length=1, max_length=100)
    priority: StrictInt = Field(default=100, ge=0, le=1_000_000)

    @field_validator("route_label")
    @classmethod
    def _validate_route_label(cls, value: str) -> str:
        return _reject_control_characters(value, "route_label")


class BindingUpdate(ContractModel):
    """Change one binding; omitted fields keep their value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled_operations: frozenset[CredentialOperation] | None = None
    priority: StrictInt | None = Field(default=None, ge=0, le=1_000_000)
    route_label: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("route_label")
    @classmethod
    def _validate_route_label(cls, value: str | None) -> str | None:
        return None if value is None else _reject_control_characters(value, "route_label")

    @model_validator(mode="after")
    def _reject_null_fields(self) -> BindingUpdate:
        for name in ("enabled_operations", "priority", "route_label"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


# ----------------------------------------------------------------------
# Upstream pools, credential links and project allocations (system only)
# ----------------------------------------------------------------------


class RateConstraint(ContractModel):
    """One upstream rate constraint with an explicit algorithm and window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: RateAlgorithm
    window_seconds: StrictInt = Field(ge=1)
    limit: StrictInt = Field(ge=0)


def _validate_constraints(constraints: list[RateConstraint]) -> list[RateConstraint]:
    windows = [constraint.window_seconds for constraint in constraints]
    if len(windows) != len(set(windows)):
        raise ValueError("a pool has at most one rate constraint per window")
    return constraints


class PoolCreate(ContractModel):
    """Create one upstream quota pool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_type: str = Field(min_length=1, max_length=32)
    upstream_scope: UpstreamScope
    pool_key: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    constraints: list[RateConstraint] = Field(default_factory=list)
    max_concurrency: StrictInt | None = Field(default=None, ge=1)
    max_queued_requests: StrictInt | None = Field(default=None, ge=0)

    @field_validator("label", "pool_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _reject_control_characters(value, "text")

    @field_validator("constraints")
    @classmethod
    def _validate_constraint_windows(cls, value: list[RateConstraint]) -> list[RateConstraint]:
        return _validate_constraints(value)


class PoolUpdate(ContractModel):
    """Change one pool; omitted fields keep their value, explicit ``null`` clears limits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    upstream_scope: UpstreamScope | None = None
    pool_key: str | None = Field(default=None, min_length=1, max_length=200)
    label: str | None = Field(default=None, min_length=1, max_length=100)
    constraints: list[RateConstraint] | None = None
    max_concurrency: StrictInt | None = Field(default=None, ge=1)
    max_queued_requests: StrictInt | None = Field(default=None, ge=0)
    status: PoolStatus | None = None

    @field_validator("label", "pool_key")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _reject_control_characters(value, "text")

    @field_validator("constraints")
    @classmethod
    def _validate_constraint_windows(
        cls, value: list[RateConstraint] | None
    ) -> list[RateConstraint] | None:
        return None if value is None else _validate_constraints(value)

    @model_validator(mode="after")
    def _reject_null_required_fields(self) -> PoolUpdate:
        for name in ("upstream_scope", "pool_key", "label", "constraints", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class PoolRead(ContractModel):
    """System view of one upstream pool; never a balance or consumption."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    provider_type: str
    upstream_scope: UpstreamScope
    pool_key: str
    label: str
    constraints: list[RateConstraint]
    max_concurrency: int | None
    max_queued_requests: int | None
    status: PoolStatus
    version: int


class PoolLinkRead(ContractModel):
    """One credential's link to a pool for one operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: UUID
    pool_id: UUID
    operation_scope: CredentialOperation
    provider_type: str
    version: int


class AllocationPut(ContractModel):
    """Set one project's allocation of one pool and operation.

    Strict by default: with ``borrow_enabled`` false, ``max_rate`` is omitted,
    ``null`` or equal to ``base_rate``. With loans, ``max_rate >= base_rate``.
    A zero ``base_rate`` needs ``best_effort``. ``weight >= 1``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_rate: StrictInt = Field(ge=0)
    rate_window_seconds: StrictInt = Field(ge=1)
    borrow_enabled: StrictBool = False
    max_rate: StrictInt | None = Field(default=None, ge=0)
    weight: StrictInt = Field(default=1, ge=1)
    best_effort: StrictBool = False
    max_concurrency: StrictInt | None = Field(default=None, ge=1)
    max_queued_requests: StrictInt | None = Field(default=None, ge=0)
    max_queued_bytes: StrictInt | None = Field(default=None, ge=0)
    max_queue_wait_ms: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_envelope(self) -> AllocationPut:
        if self.borrow_enabled:
            if self.max_rate is None or self.max_rate < self.base_rate:
                raise ValueError("with loans enabled, max_rate must be at least base_rate")
        elif self.max_rate is not None and self.max_rate != self.base_rate:
            raise ValueError("a strict allocation has max_rate null or equal to base_rate")
        if self.base_rate == 0 and not self.best_effort:
            raise ValueError("a zero base_rate requires best_effort")
        return self


class AllocationRead(ContractModel):
    """One project's allocation of one pool and operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    pool_id: UUID
    operation_scope: CredentialOperation
    base_rate: int | None
    rate_window_seconds: int
    borrow_enabled: bool
    max_rate: int | None
    effective_max_rate: int | None
    weight: int
    best_effort: bool
    max_concurrency: int | None
    max_queued_requests: int | None
    max_queued_bytes: int | None
    max_queue_wait_ms: int | None
    version: int


# ----------------------------------------------------------------------
# Project provider view: available versus enabled
# ----------------------------------------------------------------------


class ProviderPoolRead(ContractModel):
    """Pool ownership of one available credential's operation.

    Pools are always system-managed (``owner_scope`` is ``system``). No
    balance, consumption, sharing detail or other project's data appears.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_scope: CredentialOperation
    pool_id: UUID
    label: str
    upstream_scope: UpstreamScope
    status: PoolStatus
    owner_scope: Literal["system"] = "system"


class AvailableCredentialRead(ContractModel):
    """One credential this project may bind: its own private or a granted system one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    label: str
    owner_scope: CredentialOwnerScope
    auth_mode: str
    status: str
    health_status: str | None = None
    health_checked_at: datetime | None = None
    granted_operations: frozenset[CredentialOperation]
    supported_operations: frozenset[CredentialOperation]
    pools: list[ProviderPoolRead] = Field(default_factory=list)


class ProviderBindingView(ContractModel):
    """One project binding with its configured and effective operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    credential_id: UUID
    route_label: str
    priority: int
    enabled_operations: frozenset[CredentialOperation]
    effective_operations: frozenset[CredentialOperation]


class ProviderTypeView(ContractModel):
    """Available and enabled state of one provider type in one project.

    ``effective_operations`` is capability AND not killed by system policy
    AND ownership/grant AND binding enablement. Principal permission,
    capacity and live health are evaluated at dispatch, not here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_type: str
    keyless: bool = False
    call_cost_usd: dict[UsageOperation, Decimal] = Field(default_factory=dict)
    keyless_call_cost_usd: dict[UsageOperation, Decimal] = Field(default_factory=dict)
    capability: frozenset[CredentialOperation]
    kill_switch: bool
    system_enabled_operations: frozenset[CredentialOperation]
    available: bool
    enabled: bool
    health_status: str | None = None
    health_checked_at: datetime | None = None
    credentials: list[AvailableCredentialRead]
    bindings: list[ProviderBindingView]
    effective_operations: frozenset[CredentialOperation]


class ProjectProvidersRead(ContractModel):
    """The project's provider view plus its own allocations only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    providers: list[ProviderTypeView]
    allocations: list[AllocationRead]


__all__ = [
    "AllocationPut",
    "AllocationRead",
    "AvailableCredentialRead",
    "BindingCreate",
    "BindingUpdate",
    "PoolCreate",
    "PoolLinkRead",
    "PoolRead",
    "PoolUpdate",
    "ProjectProvidersRead",
    "ProviderBindingView",
    "ProviderPoolRead",
    "ProviderTypeView",
    "RateAlgorithm",
    "RateConstraint",
]
