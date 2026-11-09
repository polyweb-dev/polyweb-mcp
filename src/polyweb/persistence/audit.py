"""Scoped audit event persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    system_audit_events(id, account_id, occurred_at, category, action,
        actor_type, actor_id, target_type, target_id, outcome, correlation_id,
        detail)
    project_audit_events(id, project_id, occurred_at, action, actor_type,
        actor_id, target_type, target_id, outcome, correlation_id, detail)

System events are installation scope: ``category`` is ``audit`` or
``security``, and an authentication failure before a project is resolved is a
``security`` event with no project. Project events always belong to one
project. ``actor_id`` is an attribution snapshot without a foreign key, so
history survives the removal of a human account. ``detail`` is sanitized in
the strict mode of the telemetry sanitizer: a key that contains a secret-like
part (``token``, ``secret``, ``apikey``, ``digest``, ...) and does not end with an
identifier-like suffix (``id``, ``count``, ``status``, ...), or a value that starts
with a project API key prefix or ``Bearer`` raises ``ValueError`` and nothing
is written.

Project reads take the project id and system reads take the account id; both
page newest first by ``(occurred_at, id)``. The caller owns the transaction;
methods flush and never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    and_,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from polyweb.persistence.storage import Base, decode_metadata_json, sanitized_metadata_json
from polyweb.persistence.timestamps import parse_timestamp, resolve_now, stored_timestamp

#: Exclusive paging cursor: ``(occurred_at, id)`` of the last row already seen.
AuditCursor = tuple[datetime, UUID]

MIN_AUDIT_LIMIT = 1
MAX_AUDIT_LIMIT = 500

_ACTOR_CHECK = "actor_type IN ('human', 'project_api_key', 'system', 'anonymous')"
_OUTCOME_CHECK = "outcome IN ('success', 'denied', 'failed')"


class SystemAuditEventRow(Base):
    """One installation-scope audit or security event."""

    __tablename__ = "system_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="system_audit_events_account_id_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "category IN ('audit', 'security')", name="system_audit_events_category_allowed"
        ),
        CheckConstraint(_ACTOR_CHECK, name="system_audit_events_actor_type_allowed"),
        CheckConstraint(_OUTCOME_CHECK, name="system_audit_events_outcome_allowed"),
        CheckConstraint("length(action) > 0", name="system_audit_events_action_not_empty"),
        Index("system_audit_events_account_occurred", "account_id", "occurred_at", "id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")


class ProjectAuditEventRow(Base):
    """One audit event owned by one project."""

    __tablename__ = "project_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_audit_events_project_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(_ACTOR_CHECK, name="project_audit_events_actor_type_allowed"),
        CheckConstraint(_OUTCOME_CHECK, name="project_audit_events_outcome_allowed"),
        CheckConstraint("length(action) > 0", name="project_audit_events_action_not_empty"),
        Index("project_audit_events_project_occurred", "project_id", "occurred_at", "id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")


@dataclass(frozen=True)
class StoredAuditEvent:
    """One stored audit event of either scope.

    ``scope_id`` is the account id of a system event or the project id of a
    project event; project events are always :attr:`AuditCategory.AUDIT`.
    """

    id: UUID
    scope_id: UUID
    occurred_at: datetime
    category: AuditCategory
    action: str
    actor_type: AuditActorType
    actor_id: UUID | None
    target_type: str | None
    target_id: str | None
    outcome: AuditOutcome
    correlation_id: str | None
    detail: dict[str, object]


def _stored(
    row: SystemAuditEventRow | ProjectAuditEventRow,
    *,
    scope_id: str,
    category: str,
) -> StoredAuditEvent:
    return StoredAuditEvent(
        id=UUID(row.id),
        scope_id=UUID(scope_id),
        occurred_at=parse_timestamp(row.occurred_at),
        category=AuditCategory(category),
        action=row.action,
        actor_type=AuditActorType(row.actor_type),
        actor_id=UUID(row.actor_id) if row.actor_id else None,
        target_type=row.target_type,
        target_id=row.target_id,
        outcome=AuditOutcome(row.outcome),
        correlation_id=row.correlation_id,
        detail=decode_metadata_json(row.detail),
    )


def _stored_system(row: SystemAuditEventRow) -> StoredAuditEvent:
    return _stored(row, scope_id=row.account_id, category=row.category)


def _stored_project(row: ProjectAuditEventRow) -> StoredAuditEvent:
    return _stored(row, scope_id=row.project_id, category=AuditCategory.AUDIT.value)


def _clamped(limit: int) -> int:
    return min(max(limit, MIN_AUDIT_LIMIT), MAX_AUDIT_LIMIT)


def _before(occurred_at: Any, row_id: Any, cursor: AuditCursor) -> Any:
    """Return the exclusive ``(occurred_at, id) < cursor`` predicate."""

    at = stored_timestamp(cursor[0])
    return or_(occurred_at < at, and_(occurred_at == at, row_id < str(cursor[1])))


class AuditRepository:
    """Append-only audit writes and scoped newest-first reads."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_system_event(
        self,
        *,
        account_id: UUID,
        category: AuditCategory,
        action: str,
        actor_type: AuditActorType,
        actor_id: UUID | None,
        outcome: AuditOutcome,
        target_type: str | None = None,
        target_id: str | None = None,
        correlation_id: str | None = None,
        detail: dict[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> StoredAuditEvent:
        """Append one installation-scope event."""

        row = SystemAuditEventRow(
            id=str(uuid4()),
            account_id=str(account_id),
            occurred_at=stored_timestamp(resolve_now(occurred_at)),
            category=AuditCategory(category).value,
            action=action,
            actor_type=AuditActorType(actor_type).value,
            actor_id=str(actor_id) if actor_id is not None else None,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditOutcome(outcome).value,
            correlation_id=correlation_id,
            detail=sanitized_metadata_json(detail or {}, strict=True),
        )
        self._session.add(row)
        await self._session.flush()
        return _stored_system(row)

    async def append_project_event(
        self,
        *,
        project_id: UUID,
        action: str,
        actor_type: AuditActorType,
        actor_id: UUID | None,
        outcome: AuditOutcome,
        target_type: str | None = None,
        target_id: str | None = None,
        correlation_id: str | None = None,
        detail: dict[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> StoredAuditEvent:
        """Append one event owned by this project."""

        row = ProjectAuditEventRow(
            id=str(uuid4()),
            project_id=str(project_id),
            occurred_at=stored_timestamp(resolve_now(occurred_at)),
            action=action,
            actor_type=AuditActorType(actor_type).value,
            actor_id=str(actor_id) if actor_id is not None else None,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditOutcome(outcome).value,
            correlation_id=correlation_id,
            detail=sanitized_metadata_json(detail or {}, strict=True),
        )
        self._session.add(row)
        await self._session.flush()
        return _stored_project(row)

    async def list_project_events(
        self,
        *,
        project_id: UUID,
        limit: int = 50,
        before: AuditCursor | None = None,
    ) -> list[StoredAuditEvent]:
        """List this project's events newest first, strictly older than ``before``."""

        statement = (
            select(ProjectAuditEventRow)
            .where(ProjectAuditEventRow.project_id == str(project_id))
            .order_by(ProjectAuditEventRow.occurred_at.desc(), ProjectAuditEventRow.id.desc())
            .limit(_clamped(limit))
        )
        if before is not None:
            statement = statement.where(
                _before(ProjectAuditEventRow.occurred_at, ProjectAuditEventRow.id, before)
            )
        rows = await self._session.scalars(statement)
        return [_stored_project(row) for row in rows]

    async def list_system_events(
        self,
        *,
        account_id: UUID,
        limit: int = 50,
        before: AuditCursor | None = None,
        category: AuditCategory | None = None,
    ) -> list[StoredAuditEvent]:
        """List this account's system events newest first, optionally of one category."""

        statement = (
            select(SystemAuditEventRow)
            .where(SystemAuditEventRow.account_id == str(account_id))
            .order_by(SystemAuditEventRow.occurred_at.desc(), SystemAuditEventRow.id.desc())
            .limit(_clamped(limit))
        )
        if before is not None:
            statement = statement.where(
                _before(SystemAuditEventRow.occurred_at, SystemAuditEventRow.id, before)
            )
        if category is not None:
            statement = statement.where(
                SystemAuditEventRow.category == AuditCategory(category).value
            )
        rows = await self._session.scalars(statement)
        return [_stored_system(row) for row in rows]


__all__ = [
    "MAX_AUDIT_LIMIT",
    "MIN_AUDIT_LIMIT",
    "AuditCursor",
    "AuditRepository",
    "ProjectAuditEventRow",
    "StoredAuditEvent",
    "SystemAuditEventRow",
]
