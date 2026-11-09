"""Project retention run persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    retention_runs(id, project_id, data_class, cutoff, status, started_at,
        finished_at, deleted_rows, error_code)

Every run names one project and one data class (``traces``, ``usage``, or
``audit``); there is no installation-wide run. Every method takes the project
id and filters by it in SQL. The caller owns the transaction; methods flush and
never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.schema_enums import RetentionDataClass, RetentionRunStatus
from polyweb.persistence.storage import Base
from polyweb.persistence.timestamps import (
    parse_optional_timestamp,
    parse_timestamp,
    resolve_now,
    stored_timestamp,
)

_FINISHED_STATUSES = frozenset({RetentionRunStatus.COMPLETED, RetentionRunStatus.FAILED})


class RetentionRunRow(Base):
    """One retention pass over one project's data class."""

    __tablename__ = "retention_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="retention_runs_project_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "data_class IN ('traces', 'usage', 'audit')", name="retention_runs_data_class_allowed"
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="retention_runs_status_allowed"
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) "
            "OR (status <> 'running' AND finished_at IS NOT NULL)",
            name="retention_runs_finish_consistent",
        ),
        CheckConstraint("deleted_rows >= 0", name="retention_runs_deleted_rows_nonnegative"),
        Index("retention_runs_project_class_started", "project_id", "data_class", "started_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    data_class: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


@dataclass(frozen=True)
class StoredRetentionRun:
    """One stored retention run."""

    id: UUID
    project_id: UUID
    data_class: RetentionDataClass
    cutoff: datetime
    status: RetentionRunStatus
    started_at: datetime
    finished_at: datetime | None
    deleted_rows: int
    error_code: str | None


def _stored(row: RetentionRunRow) -> StoredRetentionRun:
    return StoredRetentionRun(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        data_class=RetentionDataClass(row.data_class),
        cutoff=parse_timestamp(row.cutoff),
        status=RetentionRunStatus(row.status),
        started_at=parse_timestamp(row.started_at),
        finished_at=parse_optional_timestamp(row.finished_at),
        deleted_rows=row.deleted_rows,
        error_code=row.error_code,
    )


class RetentionRunRepository:
    """Project-scoped retention run records on one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self,
        *,
        project_id: UUID,
        data_class: RetentionDataClass,
        cutoff: datetime,
        now: datetime | None = None,
    ) -> StoredRetentionRun:
        """Record a running retention pass over one project's data class."""

        row = RetentionRunRow(
            id=str(uuid4()),
            project_id=str(project_id),
            data_class=RetentionDataClass(data_class).value,
            cutoff=stored_timestamp(cutoff),
            status=RetentionRunStatus.RUNNING.value,
            started_at=stored_timestamp(resolve_now(now)),
            finished_at=None,
            deleted_rows=0,
            error_code=None,
        )
        self._session.add(row)
        await self._session.flush()
        return _stored(row)

    async def finish(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        status: RetentionRunStatus,
        deleted_rows: int,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Finish one running run of this project as completed or failed."""

        final = RetentionRunStatus(status)
        if final not in _FINISHED_STATUSES:
            raise ValueError("a retention run finishes as completed or failed")
        result = await self._session.execute(
            update(RetentionRunRow)
            .where(
                RetentionRunRow.id == str(run_id),
                RetentionRunRow.project_id == str(project_id),
                RetentionRunRow.status == RetentionRunStatus.RUNNING.value,
            )
            .values(
                status=final.value,
                finished_at=stored_timestamp(resolve_now(now)),
                deleted_rows=deleted_rows,
                error_code=error_code,
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def latest(
        self, *, project_id: UUID, data_class: RetentionDataClass
    ) -> StoredRetentionRun | None:
        """Return this project's most recently started run of one data class."""

        row = await self._session.scalar(
            select(RetentionRunRow)
            .where(
                RetentionRunRow.project_id == str(project_id),
                RetentionRunRow.data_class == RetentionDataClass(data_class).value,
            )
            .order_by(RetentionRunRow.started_at.desc(), RetentionRunRow.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _stored(row)


__all__ = ["RetentionRunRepository", "RetentionRunRow", "StoredRetentionRun"]
