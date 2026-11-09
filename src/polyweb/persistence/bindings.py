"""Project provider binding persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    project_provider_bindings(id, project_id, credential_id, credential_scope,
        private_project_id, granted_project_id, route_label, enabled_operations,
        priority, overrides, created_by, created_at, updated_at, version)

A binding routes one project's execution to one credential. The database
enforces who may bind what: a ``project`` binding fills ``private_project_id``
so the composite key ``(credential_id, private_project_id)`` must match the
credential's owning project, and a ``system`` binding fills
``granted_project_id`` so ``(credential_id, granted_project_id)`` must match an
existing grant to the same project. Binding another project's private
credential, or a system credential without a grant, fails with
``IntegrityError``. A new binding starts with no enabled operations.

Every method takes the owning project id and filters by it in SQL. The caller
owns the transaction; methods flush and never commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    delete,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import CredentialOwnerScope
from polyweb.persistence.storage import Base
from polyweb.persistence.timestamps import parse_timestamp, resolve_now, stored_timestamp


class ProjectBindingRow(Base):
    """One project's route to one private or granted system credential."""

    __tablename__ = "project_provider_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_provider_bindings_project_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["credential_id", "credential_scope"],
            ["provider_credentials.id", "provider_credentials.owner_scope"],
            name="project_provider_bindings_credential_scope_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["credential_id", "private_project_id"],
            ["provider_credentials.id", "provider_credentials.owner_project_id"],
            name="project_provider_bindings_private_credential_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["credential_id", "granted_project_id"],
            ["credential_project_grants.credential_id", "credential_project_grants.project_id"],
            name="project_provider_bindings_grant_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "credential_scope IN ('system', 'project')",
            name="project_provider_bindings_scope_allowed",
        ),
        CheckConstraint(
            "(credential_scope = 'project' AND private_project_id IS NOT NULL "
            "AND private_project_id = project_id AND granted_project_id IS NULL) "
            "OR (credential_scope = 'system' AND granted_project_id IS NOT NULL "
            "AND granted_project_id = project_id AND private_project_id IS NULL)",
            name="project_provider_bindings_owner_consistent",
        ),
        CheckConstraint("priority >= 0", name="project_provider_bindings_priority_nonnegative"),
        CheckConstraint(
            "length(route_label) > 0", name="project_provider_bindings_route_label_not_empty"
        ),
        CheckConstraint("version >= 1", name="project_provider_bindings_version_positive"),
        Index(
            "project_provider_bindings_route_key",
            "project_id",
            "credential_id",
            "route_label",
            unique=True,
        ),
        Index("ix_project_provider_bindings_credential_id", "credential_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    credential_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    credential_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    private_project_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    granted_project_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    route_label: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled_operations: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    overrides: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


@dataclass(frozen=True)
class StoredBinding:
    """One stored project provider binding."""

    id: UUID
    project_id: UUID
    credential_id: UUID
    credential_scope: CredentialOwnerScope
    route_label: str
    enabled_operations: frozenset[CredentialOperation]
    priority: int
    overrides: dict[str, Any]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    version: int


def _encode_operations(operations: frozenset[CredentialOperation]) -> str:
    return json.dumps(sorted(CredentialOperation(operation).value for operation in operations))


def _decode_operations(raw: str) -> frozenset[CredentialOperation]:
    values = json.loads(raw)
    if not isinstance(values, list):
        return frozenset()
    operations: set[CredentialOperation] = set()
    for value in values:
        try:
            operations.add(CredentialOperation(str(value)))
        except ValueError:
            continue
    return frozenset(operations)


def _decode_overrides(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _stored(row: ProjectBindingRow) -> StoredBinding:
    return StoredBinding(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        credential_id=UUID(row.credential_id),
        credential_scope=CredentialOwnerScope(row.credential_scope),
        route_label=row.route_label,
        enabled_operations=_decode_operations(row.enabled_operations),
        priority=row.priority,
        overrides=_decode_overrides(row.overrides),
        created_by=UUID(row.created_by),
        created_at=parse_timestamp(row.created_at),
        updated_at=parse_timestamp(row.updated_at),
        version=row.version,
    )


class ProjectBindingRepository:
    """Project-scoped binding queries on one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: UUID,
        credential_id: UUID,
        credential_scope: CredentialOwnerScope,
        route_label: str,
        created_by: UUID,
        priority: int = 100,
        overrides: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> StoredBinding:
        """Insert one disabled binding; ownership and grant are database-enforced."""

        scope = CredentialOwnerScope(credential_scope)
        timestamp = stored_timestamp(resolve_now(now))
        row = ProjectBindingRow(
            id=str(uuid4()),
            project_id=str(project_id),
            credential_id=str(credential_id),
            credential_scope=scope.value,
            private_project_id=str(project_id) if scope is CredentialOwnerScope.PROJECT else None,
            granted_project_id=str(project_id) if scope is CredentialOwnerScope.SYSTEM else None,
            route_label=route_label,
            enabled_operations=_encode_operations(frozenset()),
            priority=priority,
            overrides=json.dumps(overrides or {}, separators=(",", ":"), sort_keys=True),
            created_by=str(created_by),
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return _stored(row)

    async def get(self, *, project_id: UUID, binding_id: UUID) -> StoredBinding | None:
        """Return one binding of this project, or ``None`` when absent or foreign."""

        row = await self._session.scalar(
            select(ProjectBindingRow).where(
                ProjectBindingRow.id == str(binding_id),
                ProjectBindingRow.project_id == str(project_id),
            )
        )
        return None if row is None else _stored(row)

    async def list_for_project(self, *, project_id: UUID) -> list[StoredBinding]:
        """List this project's bindings by priority, route label, and id."""

        rows = await self._session.scalars(
            select(ProjectBindingRow)
            .where(ProjectBindingRow.project_id == str(project_id))
            .order_by(
                ProjectBindingRow.priority,
                ProjectBindingRow.route_label,
                ProjectBindingRow.id,
            )
        )
        return [_stored(row) for row in rows]

    async def set_enabled_operations(
        self,
        *,
        project_id: UUID,
        binding_id: UUID,
        operations: frozenset[CredentialOperation],
        expected_version: int,
        now: datetime | None = None,
    ) -> StoredBinding | None:
        """Replace the enabled operations at the expected version.

        Returns ``None`` when the binding is absent, foreign, or stale.
        """

        row = await self._session.scalar(
            update(ProjectBindingRow)
            .where(
                ProjectBindingRow.id == str(binding_id),
                ProjectBindingRow.project_id == str(project_id),
                ProjectBindingRow.version == expected_version,
            )
            .values(
                enabled_operations=_encode_operations(operations),
                updated_at=stored_timestamp(resolve_now(now)),
                version=ProjectBindingRow.version + 1,
            )
            .returning(ProjectBindingRow)
            .execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored(row)

    async def update(
        self,
        *,
        project_id: UUID,
        binding_id: UUID,
        enabled_operations: frozenset[CredentialOperation],
        priority: int,
        route_label: str,
        now: datetime | None = None,
    ) -> StoredBinding | None:
        """Replace the tunable fields of one binding of this project.

        The caller validates the values inside its serialized transaction;
        ``None`` means the binding is absent or belongs to another project.
        """

        row = await self._session.scalar(
            update(ProjectBindingRow)
            .where(
                ProjectBindingRow.id == str(binding_id),
                ProjectBindingRow.project_id == str(project_id),
            )
            .values(
                enabled_operations=_encode_operations(enabled_operations),
                priority=priority,
                route_label=route_label,
                updated_at=stored_timestamp(resolve_now(now)),
                version=ProjectBindingRow.version + 1,
            )
            .returning(ProjectBindingRow)
            .execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored(row)

    async def list_for_credential(
        self, *, project_id: UUID, credential_id: UUID
    ) -> list[StoredBinding]:
        """List this project's bindings of one credential."""

        rows = await self._session.scalars(
            select(ProjectBindingRow)
            .where(
                ProjectBindingRow.project_id == str(project_id),
                ProjectBindingRow.credential_id == str(credential_id),
            )
            .order_by(ProjectBindingRow.id)
            .execution_options(populate_existing=True)
        )
        return [_stored(row) for row in rows]

    async def restrict_operations_for_credential(
        self,
        *,
        project_id: UUID,
        credential_id: UUID,
        allowed: frozenset[CredentialOperation],
        now: datetime | None = None,
    ) -> int:
        """Drop every enabled operation outside ``allowed``; return the changed count.

        Used when a grant narrows: no binding of this project may keep an
        operation its credential no longer permits.
        """

        changed = 0
        for binding in await self.list_for_credential(
            project_id=project_id, credential_id=credential_id
        ):
            narrowed = binding.enabled_operations & allowed
            if narrowed == binding.enabled_operations:
                continue
            await self._session.execute(
                update(ProjectBindingRow)
                .where(
                    ProjectBindingRow.id == str(binding.id),
                    ProjectBindingRow.project_id == str(project_id),
                )
                .values(
                    enabled_operations=_encode_operations(narrowed),
                    updated_at=stored_timestamp(resolve_now(now)),
                    version=ProjectBindingRow.version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            changed += 1
        await self._session.flush()
        return changed

    async def delete_for_credential(self, *, project_id: UUID, credential_id: UUID) -> int:
        """Remove every binding of this project to one credential; return the count."""

        result = await self._session.execute(
            delete(ProjectBindingRow).where(
                ProjectBindingRow.project_id == str(project_id),
                ProjectBindingRow.credential_id == str(credential_id),
            )
        )
        await self._session.flush()
        return int(getattr(result, "rowcount", 0))

    async def delete(self, *, project_id: UUID, binding_id: UUID) -> bool:
        """Remove one binding of this project; return whether a row was removed."""

        result = await self._session.execute(
            delete(ProjectBindingRow).where(
                ProjectBindingRow.id == str(binding_id),
                ProjectBindingRow.project_id == str(project_id),
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))


__all__ = ["ProjectBindingRepository", "ProjectBindingRow", "StoredBinding"]
