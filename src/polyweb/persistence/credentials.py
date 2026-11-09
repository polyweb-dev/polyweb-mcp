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

Owner-facing queries are scoped to one owner or project. The installation-wide
usage polling query is an internal exception and never returns secret material.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ColumnElement,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Select,
    String,
    Text,
    delete,
    func,
    literal_column,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.credentials import CredentialOperation, CredentialStatus
from polyweb.models.projects import (
    CredentialInstanceRead,
    CredentialOwnerScope,
    CredentialProjectGrantRead,
)
from polyweb.persistence.storage import Base, ProviderHealthRow
from polyweb.persistence.timestamps import parse_timestamp
from polyweb.persistence.users import UserRow


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StoredVaultCredential(BaseModel):
    """A credential and its vault policy, without secret material."""

    model_config = ConfigDict(frozen=True)

    credential: CredentialInstanceRead
    owner_user_id: UUID
    overcommit: bool
    contention_mode: str


class UsagePollingCredential(BaseModel):
    """Internal, secret-free identity for an active vault credential."""

    credential: CredentialInstanceRead
    owner_user_id: UUID
    owner_email: str


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
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["user.id"],
            name="provider_credentials_owner_user_id_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint("overcommit IN (0, 1)", name="provider_credentials_overcommit_allowed"),
        CheckConstraint(
            "contention_mode IN ('equal', 'ratio')",
            name="provider_credentials_contention_mode_allowed",
        ),
        CheckConstraint(
            "capacity_rate >= 0", name="provider_credentials_capacity_rate_nonnegative"
        ),
        CheckConstraint(
            "capacity_rate_window_seconds > 0",
            name="provider_credentials_capacity_rate_window_positive",
        ),
        CheckConstraint(
            "capacity_budget_micros >= 0",
            name="provider_credentials_capacity_budget_nonnegative",
        ),
        CheckConstraint(
            "capacity_budget_window IN ('day', 'week', 'month')",
            name="provider_credentials_capacity_budget_window_allowed",
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
            "auth_mode IN ('api_key', 'oauth', 'keyless')",
            name="provider_credentials_auth_mode_allowed",
        ),
        CheckConstraint(
            "(auth_mode = 'keyless' AND owner_scope = 'system' AND owner_user_id IS NULL "
            "AND created_by IS NULL) OR (auth_mode != 'keyless' AND created_by IS NOT NULL)",
            name="provider_credentials_keyless_system",
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
            "owner_user_id",
            "provider_type",
            "label",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "provider_credentials_keyless_provider_key",
            "account_id",
            "provider_type",
            unique=True,
            sqlite_where=text("auth_mode = 'keyless'"),
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
    created_by: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(CHAR(36))
    overcommit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    contention_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="equal")
    capacity_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_rate_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_budget_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_budget_window: Mapped[str | None] = mapped_column(String(5), nullable=True)


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
        owner_user_id: UUID | None = None,
        now: str | None = None,
    ) -> CredentialInstanceRead:
        """Insert one generation-1 active credential and return its read model."""

        if owner_user_id is not None and owner_scope != CredentialOwnerScope.SYSTEM:
            raise ValueError("vault credentials must be system scoped")
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
        if owner_user_id is not None:
            await self._session.execute(
                text("UPDATE provider_credentials SET owner_user_id=:owner WHERE id=:id"),
                {"owner": str(owner_user_id), "id": row.id},
            )
        return _credential_read(row)

    async def list_for_owner(self, user_id: UUID) -> list[StoredVaultCredential]:
        """Return active credentials owned by this user only."""
        result = await self._session.execute(
            self._vault_select()
            .where(
                literal_column("provider_credentials.owner_user_id") == str(user_id),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(ProviderCredentialRow.id)
        )
        return [
            StoredVaultCredential(
                credential=_credential_read(row),
                owner_user_id=UUID(owner),
                overcommit=bool(overcommit),
                contention_mode=mode,
            )
            for row, owner, overcommit, mode in result
        ]

    async def list_vault_credentials_for_usage_polling(
        self, *, account_id: UUID, provider: str
    ) -> list[UsagePollingCredential]:
        """List active vault identities for internal installation-wide polling only."""

        owner: ColumnElement[str] = literal_column("provider_credentials.owner_user_id")
        email: ColumnElement[str] = literal_column('"user".email')
        user_id: ColumnElement[str] = literal_column('"user".id')
        result = await self._session.execute(
            select(ProviderCredentialRow, owner, email)
            .join(UserRow, owner == user_id)
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.provider_type == provider,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
                owner.is_not(None),
            )
            .order_by(ProviderCredentialRow.created_at, ProviderCredentialRow.id)
        )
        return [
            UsagePollingCredential(
                credential=_credential_read(row), owner_user_id=UUID(owner_id), owner_email=address
            )
            for row, owner_id, address in result
        ]

    async def get_owned(self, user_id: UUID, credential_id: UUID) -> StoredVaultCredential | None:
        result = await self._session.execute(
            self._vault_select().where(
                ProviderCredentialRow.id == str(credential_id),
                literal_column("provider_credentials.owner_user_id") == str(user_id),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
        )
        found = result.one_or_none()
        if found is None:
            return None
        row, owner, overcommit, mode = found
        return StoredVaultCredential(
            credential=_credential_read(row),
            owner_user_id=UUID(owner),
            overcommit=bool(overcommit),
            contention_mode=mode,
        )

    async def update_policy(
        self, user_id: UUID, credential_id: UUID, *, overcommit: bool, contention_mode: str
    ) -> StoredVaultCredential | None:
        if contention_mode not in {"equal", "ratio"}:
            raise ValueError("invalid contention mode")
        result = await self._session.execute(
            text(
                "UPDATE provider_credentials SET overcommit=:overcommit, contention_mode=:mode, "
                "updated_at=:now, version=version+1 "
                "WHERE id=:id AND owner_user_id=:owner AND status='active' RETURNING id"
            ),
            {
                "overcommit": int(overcommit),
                "mode": contention_mode,
                "now": _now_iso(),
                "id": str(credential_id),
                "owner": str(user_id),
            },
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.get_owned(user_id, credential_id)

    async def update_capacity(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        rate: int | None,
        rate_window_seconds: int | None,
        budget_micros: int | None,
        window: str | None,
    ) -> bool:
        """Store capacity only for the active credential's owner."""

        result = await self._session.execute(
            update(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.id == str(credential_id),
                literal_column("provider_credentials.owner_user_id") == str(user_id),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
            .values(
                capacity_rate=rate,
                capacity_rate_window_seconds=rate_window_seconds,
                capacity_budget_micros=budget_micros,
                capacity_budget_window=window,
                updated_at=_now_iso(),
                version=ProviderCredentialRow.version + 1,
            )
            .returning(ProviderCredentialRow.id)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _vault_select() -> Select[tuple[ProviderCredentialRow, Any, Any, Any]]:
        return select(
            ProviderCredentialRow,
            literal_column("provider_credentials.owner_user_id"),
            literal_column("provider_credentials.overcommit"),
            literal_column("provider_credentials.contention_mode"),
        )

    async def get_system_credential(
        self,
        *,
        account_id: UUID,
        credential_id: UUID,
    ) -> CredentialInstanceRead | None:
        """Return a legacy system credential, never a user-owned vault key."""

        row = await self._session.scalar(
            select(ProviderCredentialRow).where(
                ProviderCredentialRow.id == str(credential_id),
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == CredentialOwnerScope.SYSTEM.value,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
                literal_column("provider_credentials.owner_user_id").is_(None),
            )
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

    async def get_active_credential(
        self,
        *,
        account_id: UUID,
        credential_id: UUID,
    ) -> CredentialInstanceRead | None:
        """Return one active credential of this account under any owner.

        A system-scope read for installation administration (pool links);
        project-facing code uses the owner-specific getters instead.
        """

        row = await self._session.scalar(
            select(ProviderCredentialRow).where(
                ProviderCredentialRow.id == str(credential_id),
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
            )
        )
        return None if row is None else _credential_read(row)

    async def list_system_credentials(self, *, account_id: UUID) -> list[CredentialInstanceRead]:
        """List legacy system credentials, excluding user-owned vault keys."""

        result = await self._session.execute(
            select(ProviderCredentialRow)
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                ProviderCredentialRow.owner_scope == CredentialOwnerScope.SYSTEM.value,
                ProviderCredentialRow.status == CredentialStatus.ACTIVE.value,
                literal_column("provider_credentials.owner_user_id").is_(None),
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

    async def latest_health(self, *, credential_ids: set[UUID]) -> dict[UUID, tuple[str, datetime]]:
        """Return the newest health status and check time of each named credential.

        Only the status and time are read; the free-text message, which may
        quote a vendor error, never leaves this method.
        """

        if not credential_ids:
            return {}
        ranked = (
            select(
                ProviderHealthRow.credential_id,
                ProviderHealthRow.status,
                ProviderHealthRow.checked_at,
                func.row_number()
                .over(
                    partition_by=ProviderHealthRow.credential_id,
                    order_by=(ProviderHealthRow.checked_at.desc(), ProviderHealthRow.id.desc()),
                )
                .label("rank"),
            )
            .where(
                ProviderHealthRow.credential_id.in_(
                    [str(credential_id) for credential_id in credential_ids]
                )
            )
            .subquery()
        )
        rows = await self._session.execute(
            select(ranked.c.credential_id, ranked.c.status, ranked.c.checked_at).where(
                ranked.c.rank == 1
            )
        )
        return {
            UUID(row.credential_id): (row.status, parse_timestamp(row.checked_at)) for row in rows
        }

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
