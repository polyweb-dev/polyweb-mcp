"""Human-attributed audit appends for provider control-plane mutations.

Each helper appends inside the caller's open write transaction, so the
mutation and its mandatory audit row commit or roll back together.
Identifiers go in ``target_type``/``target_id``; ``detail`` passes the strict
audit sanitizer and must never carry secret material.
"""

from __future__ import annotations

from collections.abc import Awaitable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from polyweb.models.users import UserPrincipal
from polyweb.persistence.audit import AuditRepository, StoredAuditEvent


async def record_system_event(
    session: AsyncSession,
    *,
    account_id: UUID,
    actor: UserPrincipal,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, object] | None = None,
) -> None:
    """Append one successful installation-scope audit event."""

    await AuditRepository(session).append_system_event(
        account_id=account_id,
        category=AuditCategory.AUDIT,
        action=action,
        actor_type=AuditActorType.HUMAN,
        actor_id=actor.id,
        outcome=AuditOutcome.SUCCESS,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    )


def record_project_event(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor: UserPrincipal,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, object] | None = None,
) -> Awaitable[StoredAuditEvent]:
    """Append one successful project-scope audit event."""

    return AuditRepository(session).append_project_event(
        project_id=project_id,
        action=action,
        actor_type=AuditActorType.HUMAN,
        actor_id=actor.id,
        outcome=AuditOutcome.SUCCESS,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    )


__all__ = ["record_project_event", "record_system_event"]
