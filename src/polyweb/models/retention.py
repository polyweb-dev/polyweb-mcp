"""Retention request and run projection contracts (TASK-000044).

One request always names one data class of one explicit project. The cutoff is
optional only for trace retention, where the project's effective retention
policy supplies it; every other class requires an explicit cutoff.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field

from polyweb.models.contracts import ContractModel
from polyweb.models.schema_enums import RetentionDataClass, RetentionRunStatus


class RetentionRunRequest(ContractModel):
    """Request to purge one project's data older than a cutoff."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_class: RetentionDataClass
    cutoff: AwareDatetime | None = None


class RetentionRunRead(ContractModel):
    """Safe projection of one completed retention run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    data_class: RetentionDataClass
    cutoff: AwareDatetime
    status: RetentionRunStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    deleted_rows: int = Field(default=0, ge=0)
    error_code: str | None = None


__all__ = ["RetentionRunRead", "RetentionRunRequest"]
