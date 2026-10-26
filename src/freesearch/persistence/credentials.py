"""Provider credential instance and project grant persistence (P08).

Rows follow the accepted schema shape owned by Alembic revision
``0001_alpha_baseline``::

    provider_credentials(id, account_id, provider_type, owner_scope,
        owner_project_id, label, auth_mode, generation, status,
        created_by, created_at, updated_at, version)
    credential_project_grants(credential_id, owner_scope, project_id,
        permitted_operations, granted_by, created_at, version)

The ORM mirrors the migration for typed access only; Alembic owns all table
creation. The composite grant key ``(credential_id, owner_scope)`` references
``provider_credentials(id, owner_scope)`` with a ``system`` check, so a
project-private credential can never be granted at the database level.

Every repository method takes mandatory scope parameters. There is no query
that selects credentials across owners, and no optional project selector that
widens a read beyond one account or one project.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ColumnElement,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.models.credentials import CredentialOperation, CredentialStatus
from freesearch.models.projects import (
    CredentialInstanceRead,
    CredentialOwnerScope,
    CredentialProjectGrantRead,
)
from freesearch.persistence.storage import Base


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _encode_operations(operations: frozenset[CredentialOperation]) -> str:
    """Return the canonical sorted JSON list of permitted operation names."""

    return json.dumps(sorted(operation.value for operation in operations))


def _decode_operations(raw: str) -> frozenset[CredentialOperation]:
    """Restore stored operation names, dropping any unknown catalog value."""

    try:
        values = json.loads(raw)
    except ValueError:
        return frozenset()
    if not isinstance(values, list):
        return frozenset()
    operations: set[CredentialOperation] = set()
    for item in values:
        try:
            operations.add(CredentialOperation(str(item)))
        except ValueError:
            continue
    return frozenset(operations)


def _credential_read(row: ProviderCredentialRow) -> CredentialInstanceRead:
    return CredentialInstanceRead(
        id=UUID(row.id),
        provider_type=row.provider_type,
        owner_scope=CredentialOwnerScope(row.owner_scope),
        owner_project_id=UUID(row.owner_project_id) if row.owner_project_id else None,
        label=row.label,
        auth_mode=row.auth_mode,
        generation=row.generation,
        status=row.status,
    )


def _grant_read(row: CredentialProjectGrantRow) -> CredentialProjectGrantRead:
    return CredentialProjectGrantRead(
        credential_id=UUID(row.credential_id),
        project_id=UUID(row.project_id),
        permitted_operations=frozenset(
            operation.value for operation in _decode_operations(row.permitted_operations)
        ),
        version=row.version,
    )


class ProviderCredentialRow(Base):
    """One provider credential instance owned by the system or one project."""

    __tablename__ = "provider_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="provider_credentials_account_id_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_project_id"],
            ["projects.id"],
            name="provider_credentials_owner_project_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
            name="provider_credentials_created_by_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "owner_scope IN ('system', 'project')",
            name="provider_credentials_owner_scope_allowed",
        ),
        CheckConstraint(
            "(owner_scope = 'system' AND owner_project_id IS NULL) "
            "OR (owner_scope = 'project' AND owner_project_id IS NOT NULL)",
            name="provider_credentials_owner_scope_consistent",
        ),
        CheckConstraint(
            "auth_mode IN ('api_key', 'oauth')",
            name="provider_credentials_auth_mode_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'deleted')",
            name="provider_credentials_status_allowed",
        ),
        CheckConstraint("generation >= 1", name="provider_credentials_generation_positive"),
        CheckConstraint("version >= 1", name="provider_credentials_version_positive"),
        Index(
            "provider_credentials_id_owner_scope_key",
            "id",
            "owner_scope",
            unique=True,
        ),
        # Parent keys of the composite foreign keys that bind ownership,
        # provider type, and auth mode on bindings, pool links, and OAuth grants.
        Index(
            "provider_credentials_id_owner_project_key",
            "id",
            "owner_project_id",
            unique=True,
        ),
        Index("provider_credentials_id_provider_key", "id", "provider_type", unique=True),
        Index("provider_credentials_id_auth_mode_key", "id", "auth_mode", unique=True),
        Index(
            "provider_credentials_live_label_key",
            "account_id",
            "owner_scope",
            text("coalesce(owner_project_id, '')"),
            "provider_type",
            "label",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_provider_credentials_owner_project_id", "owner_project_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_project_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class CredentialProjectGrantRow(Base):
    """One explicit project grant on a system-owned credential instance."""

    __tablename__ = "credential_project_grants"
    __table_args__ = (
        PrimaryKeyConstraint("credential_id", "project_id", name="credential_project_grants_pkey"),
        ForeignKeyConstraint(
            ["credential_id", "owner_scope"],
            ["provider_credentials.id", "provider_credentials.owner_scope"],
            name="credential_project_grants_system_credential_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="credential_project_grants_project_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            name="credential_project_grants_granted_by_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "owner_scope = 'system'",
            name="credential_project_grants_owner_scope_system",
        ),
        CheckConstraint("version >= 1", name="credential_project_grants_version_positive"),
        Index("ix_credential_project_grants_project_id", "project_id"),
    )

    credential_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    owner_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="system", default="system"
    )
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    permitted_operations: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


def credential_owner_filter(
    *,
    owner_scope: CredentialOwnerScope,
    owner_project_id: UUID | None,
) -> tuple[ColumnElement[bool], ...]:
    """Return SQL predicates matching a credential with exactly this owner.

    A system owner has no project and a project owner needs one; an
    inconsistent pair raises ``ValueError`` instead of widening the match.
    """

    scope = CredentialOwnerScope(owner_scope)
    if scope is CredentialOwnerScope.SYSTEM and owner_project_id is not None:
        raise ValueError("a system credential has no owning project")
    if scope is CredentialOwnerScope.PROJECT and owner_project_id is None:
        raise ValueError("a project credential needs its owning project id")
    project = (
        ProviderCredentialRow.owner_project_id.is_(None)
        if owner_project_id is None
        else ProviderCredentialRow.owner_project_id == str(owner_project_id)
    )
    return (ProviderCredentialRow.owner_scope == scope.value, project)


class CredentialRepository:
    """Strict owner-scoped credential and grant queries on one session.

    The caller owns the transaction boundary; every method reads or mutates
    inside it and never commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_credential(
        self,
        *,
        account_id: UUID,
        provider_type: str,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        label: str,
        auth_mode: str,
        created_by: UUID,
        now: str | None = None,
    ) -> CredentialInstanceRead:
        """Insert one generation-1 active credential and return its read model."""

        timestamp = now or _now_iso()
        row = ProviderCredentialRow(
            id=str(uuid4()),
            account_id=str(account_id),
            provider_type=provider_type,
            owner_scope=owner_scope.value,
            owner_project_id=(str(owner_project_id) if owner_project_id is not None else None),
            label=label,
            auth_mode=auth_mode,
            generation=1,
            status=CredentialStatus.ACTIVE.value,
            created_by=str(created_by),
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return _credential_read(row)

    async def get_system_credential(
        self,
        *,
        account_id: UUID,
        credential_id: UUID,
    ) -> CredentialInstanceRead | None:
        """Return one active system-owned credential or ``None``."""

        row = await self._select_active(
            account_id=account_id,
            credential_id=credential_id,
            owner_scope=CredentialOwnerScope.SYSTEM,
        )
        return None if row is None else _credential_read(row)

    async def get_private_credential(
        self,
        *,
        account_id: UUID,
        project_id: UUID,
        credential_id: UUID,
    ) -> CredentialInstanceRead | None:
        """Return one active credential owned by exactly this project."""

        row = await self._select_active(
            account_id=account_id,
            credential_id=credential_id,
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=project_id,
        )
        return None if row is None else _credential_read(row)

    async def list_system_credentials(self, *, account_id: UUID) -> list[CredentialInstanceRead]:
        """List active system-owned credentials only, never project-private."""

        result = await self._session.execute(
            select(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == CredentialOwnerScope.SYSTEM.value,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(ProviderCredentialRow.created_at, ProviderCredentialRow.id)
        )
        return [_credential_read(row) for row in result.scalars()]

    async def list_private_credentials(
        self,
        *,
        account_id: UUID,
        project_id: UUID,
    ) -> list[CredentialInstanceRead]:
        """List active credentials owned by exactly this project."""

        result = await self._session.execute(
            select(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == CredentialOwnerScope.PROJECT.value,
                ProviderCredentialRow.owner_project_id == str(project_id),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(ProviderCredentialRow.created_at, ProviderCredentialRow.id)
        )
        return [_credential_read(row) for row in result.scalars()]

    async def list_granted_credentials(
        self,
        *,
        account_id: UUID,
        project_id: UUID,
    ) -> list[tuple[CredentialInstanceRead, frozenset[CredentialOperation]]]:
        """List active system credentials this project holds a grant for."""

        result = await self._session.execute(
            select(ProviderCredentialRow, CredentialProjectGrantRow)
            .join(
                CredentialProjectGrantRow,
                CredentialProjectGrantRow.credential_id == ProviderCredentialRow.id,
            )
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == CredentialOwnerScope.SYSTEM.value,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
                CredentialProjectGrantRow.project_id == str(project_id),
            )
            .order_by(ProviderCredentialRow.created_at, ProviderCredentialRow.id)
        )
        return [
            (_credential_read(row), _decode_operations(grant.permitted_operations))
            for row, grant in result.all()
        ]

    async def get_grant(
        self,
        *,
        credential_id: UUID,
        project_id: UUID,
    ) -> CredentialProjectGrantRead | None:
        """Return one project's grant on one credential or ``None``."""

        row = await self._session.get(
            CredentialProjectGrantRow, (str(credential_id), str(project_id))
        )
        return None if row is None else _grant_read(row)

    async def upsert_grant(
        self,
        *,
        credential_id: UUID,
        project_id: UUID,
        permitted_operations: frozenset[CredentialOperation],
        granted_by: UUID,
        now: str | None = None,
    ) -> CredentialProjectGrantRead:
        """Create or replace one grant, bumping its version when operations change."""

        encoded = _encode_operations(permitted_operations)
        row = await self._session.get(
            CredentialProjectGrantRow, (str(credential_id), str(project_id))
        )
        if row is None:
            row = CredentialProjectGrantRow(
                credential_id=str(credential_id),
                owner_scope=CredentialOwnerScope.SYSTEM.value,
                project_id=str(project_id),
                permitted_operations=encoded,
                granted_by=str(granted_by),
                created_at=now or _now_iso(),
                version=1,
            )
            self._session.add(row)
            await self._session.flush()
            return _grant_read(row)
        if row.permitted_operations != encoded:
            row.permitted_operations = encoded
            row.version += 1
            await self._session.flush()
        return _grant_read(row)

    async def delete_grant(self, *, credential_id: UUID, project_id: UUID) -> bool:
        """Remove one project's grant; return whether a row was removed."""

        result = await self._session.execute(
            delete(CredentialProjectGrantRow).where(
                CredentialProjectGrantRow.credential_id == str(credential_id),
                CredentialProjectGrantRow.project_id == str(project_id),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def delete_grants_for_credential(self, *, credential_id: UUID) -> int:
        """Remove every grant on one credential; return the removed count.

        A system-scope operation on one shared credential: grants exist only on
        system credentials, so no project selector applies.
        """

        result = await self._session.execute(
            delete(CredentialProjectGrantRow).where(
                CredentialProjectGrantRow.credential_id == str(credential_id)
            )
        )
        return int(getattr(result, "rowcount", 0))

    async def list_grants(self, *, credential_id: UUID) -> list[CredentialProjectGrantRead]:
        """List every project grant on one credential.

        A system-scope read of one shared credential: grants exist only on
        system credentials, so the result spans the projects granted it.
        """

        result = await self._session.execute(
            select(CredentialProjectGrantRow)
            .where(CredentialProjectGrantRow.credential_id == str(credential_id))
            .order_by(CredentialProjectGrantRow.project_id)
        )
        return [_grant_read(row) for row in result.scalars()]

    async def advance_generation(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        expected_generation: int,
        now: str | None = None,
    ) -> bool:
        """Advance ``generation`` by one only at the expected value and owner.

        A single compare-and-set ``UPDATE`` makes concurrent rotations safe:
        exactly one writer moves ``expected`` to ``expected + 1``. A credential
        of another owner is left unchanged and reported as ``False``.
        """

        result = await self._session.execute(
            update(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.id == str(credential_id),
                *credential_owner_filter(
                    owner_scope=owner_scope, owner_project_id=owner_project_id
                ),
                ProviderCredentialRow.generation == expected_generation,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .values(
                generation=expected_generation + 1,
                updated_at=now or _now_iso(),
                version=ProviderCredentialRow.version + 1,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def mark_deleted(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        now: str | None = None,
    ) -> bool:
        """Mark one credential of this owner deleted; return whether a row transitioned."""

        result = await self._session.execute(
            update(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.id == str(credential_id),
                *credential_owner_filter(
                    owner_scope=owner_scope, owner_project_id=owner_project_id
                ),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .values(
                status=CredentialStatus.DELETED.value,
                updated_at=now or _now_iso(),
                version=ProviderCredentialRow.version + 1,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def live_label_exists(
        self,
        *,
        account_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        provider_type: str,
        label: str,
    ) -> bool:
        """Return whether an active credential holds this label in this owner scope."""

        result = await self._session.execute(
            select(func.count())
            .select_from(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == owner_scope.value,
                func.coalesce(ProviderCredentialRow.owner_project_id, "")
                == (str(owner_project_id) if owner_project_id is not None else ""),
                ProviderCredentialRow.provider_type == provider_type,
                ProviderCredentialRow.label == label,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
        )
        return bool(result.scalar_one())

    async def _select_active(
        self,
        *,
        account_id: UUID,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None = None,
    ) -> ProviderCredentialRow | None:
        statement = select(ProviderCredentialRow).where(
            ProviderCredentialRow.id == str(credential_id),
            ProviderCredentialRow.account_id == str(account_id),
            ProviderCredentialRow.owner_scope == owner_scope.value,
            ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
        )
        if owner_project_id is not None:
            statement = statement.where(
                ProviderCredentialRow.owner_project_id == str(owner_project_id)
            )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()


__all__ = [
    "CredentialProjectGrantRow",
    "CredentialRepository",
    "ProviderCredentialRow",
    "credential_owner_filter",
]
