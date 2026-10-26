"""Upstream quota pools, credential pool links, and project allocations (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    upstream_quota_pools(id, account_id, provider_type, upstream_scope, pool_key,
        label, constraints, max_concurrency, max_queued_requests, native_pool_id,
        status, created_at, updated_at, version)
    credential_pool_links(credential_id, operation_scope, pool_id, provider_type,
        created_at, version)
    project_pool_allocations(project_id, pool_id, operation_scope, base_rate,
        rate_window_seconds, borrow_enabled, max_rate, weight, best_effort,
        max_concurrency, max_queued_requests, max_queued_bytes,
        max_queue_wait_ms, granted_by, created_at, updated_at, version)

A pool is the real upstream quota boundary and a shared-pool row: it never
carries an owning project. Its balance lives once, in the
``provider_native_pools`` row ``native_pool_id`` names; no pool, link,
allocation, or credential column stores a balance. A credential links to one
pool per operation, and the composite keys on ``provider_type`` keep a
credential from linking to another provider's pool. An allocation is a
project's strict cap on one pool and operation: loans are disabled by default
and ``max_rate`` may then only be ``NULL`` or equal to ``base_rate``.

Pool reads are account-bounded; allocation reads of one project take its id.
The caller owns the transaction; methods flush and never commit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.models.credentials import CredentialOperation
from freesearch.models.schema_enums import PoolStatus, UpstreamScope
from freesearch.persistence.storage import Base
from freesearch.persistence.timestamps import resolve_now, stored_timestamp

_OPERATION_SCOPE_CHECK = "operation_scope IN ('search', 'fetch')"


class UpstreamQuotaPoolRow(Base):
    """One upstream quota boundary shared by every credential and project using it."""

    __tablename__ = "upstream_quota_pools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="upstream_quota_pools_account_id_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["native_pool_id"],
            ["provider_native_pools.pool_id"],
            name="upstream_quota_pools_native_pool_id_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "upstream_scope IN ('account', 'credential', 'ip', 'installation')",
            name="upstream_quota_pools_upstream_scope_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')", name="upstream_quota_pools_status_allowed"
        ),
        CheckConstraint("length(pool_key) > 0", name="upstream_quota_pools_pool_key_not_empty"),
        CheckConstraint(
            "max_concurrency IS NULL OR max_concurrency > 0",
            name="upstream_quota_pools_max_concurrency_positive",
        ),
        CheckConstraint(
            "max_queued_requests IS NULL OR max_queued_requests >= 0",
            name="upstream_quota_pools_max_queued_requests_nonnegative",
        ),
        CheckConstraint("version >= 1", name="upstream_quota_pools_version_positive"),
        Index(
            "upstream_quota_pools_pool_key",
            "account_id",
            "provider_type",
            "pool_key",
            unique=True,
        ),
        Index("upstream_quota_pools_id_provider_key", "id", "provider_type", unique=True),
        Index("upstream_quota_pools_native_pool_key", "native_pool_id", unique=True),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    pool_key: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    constraints: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_queued_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    native_pool_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class CredentialPoolLinkRow(Base):
    """The one upstream pool a credential draws on for one operation."""

    __tablename__ = "credential_pool_links"
    __table_args__ = (
        PrimaryKeyConstraint("credential_id", "operation_scope", name="credential_pool_links_pkey"),
        ForeignKeyConstraint(
            ["credential_id", "provider_type"],
            ["provider_credentials.id", "provider_credentials.provider_type"],
            name="credential_pool_links_credential_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["pool_id", "provider_type"],
            ["upstream_quota_pools.id", "upstream_quota_pools.provider_type"],
            name="credential_pool_links_pool_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_OPERATION_SCOPE_CHECK, name="credential_pool_links_operation_allowed"),
        CheckConstraint("version >= 1", name="credential_pool_links_version_positive"),
        Index("ix_credential_pool_links_pool_id", "pool_id"),
    )

    credential_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    operation_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    pool_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ProjectPoolAllocationRow(Base):
    """One project's capacity share of one pool and operation."""

    __tablename__ = "project_pool_allocations"
    __table_args__ = (
        PrimaryKeyConstraint(
            "project_id", "pool_id", "operation_scope", name="project_pool_allocations_pkey"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_pool_allocations_project_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="project_pool_allocations_pool_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(_OPERATION_SCOPE_CHECK, name="project_pool_allocations_operation_allowed"),
        CheckConstraint(
            "(borrow_enabled = 0 AND (max_rate IS NULL OR max_rate = base_rate)) "
            "OR (borrow_enabled = 1 AND max_rate IS NOT NULL AND max_rate >= base_rate)",
            name="project_pool_allocations_borrow_consistent",
        ),
        CheckConstraint("base_rate >= 0", name="project_pool_allocations_base_rate_nonnegative"),
        CheckConstraint(
            "base_rate > 0 OR best_effort = 1",
            name="project_pool_allocations_zero_rate_best_effort",
        ),
        CheckConstraint(
            "rate_window_seconds > 0", name="project_pool_allocations_rate_window_positive"
        ),
        CheckConstraint("weight >= 1", name="project_pool_allocations_weight_positive"),
        CheckConstraint(
            "max_concurrency IS NULL OR max_concurrency > 0",
            name="project_pool_allocations_max_concurrency_positive",
        ),
        CheckConstraint(
            "max_queued_requests IS NULL OR max_queued_requests >= 0",
            name="project_pool_allocations_max_queued_requests_nonnegative",
        ),
        CheckConstraint(
            "max_queued_bytes IS NULL OR max_queued_bytes >= 0",
            name="project_pool_allocations_max_queued_bytes_nonnegative",
        ),
        CheckConstraint(
            "max_queue_wait_ms IS NULL OR max_queue_wait_ms >= 0",
            name="project_pool_allocations_max_queue_wait_nonnegative",
        ),
        CheckConstraint("version >= 1", name="project_pool_allocations_version_positive"),
        Index("ix_project_pool_allocations_pool_id", "pool_id"),
    )

    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    pool_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    operation_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    base_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    borrow_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    max_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    best_effort: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_queued_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_queued_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_queue_wait_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    granted_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


@dataclass(frozen=True)
class StoredPool:
    """One stored upstream quota pool; it carries no balance."""

    id: UUID
    account_id: UUID
    provider_type: str
    upstream_scope: UpstreamScope
    pool_key: str
    label: str
    constraints: list[dict[str, Any]]
    max_concurrency: int | None
    max_queued_requests: int | None
    native_pool_id: str | None
    status: PoolStatus
    version: int


@dataclass(frozen=True)
class StoredPoolLink:
    """One stored credential-to-pool link for one operation."""

    credential_id: UUID
    operation: CredentialOperation
    pool_id: UUID
    provider_type: str
    version: int


@dataclass(frozen=True)
class StoredAllocation:
    """One stored project allocation of one pool and operation."""

    project_id: UUID
    pool_id: UUID
    operation: CredentialOperation
    base_rate: int
    rate_window_seconds: int
    borrow_enabled: bool
    max_rate: int | None
    weight: int
    best_effort: bool
    max_concurrency: int | None
    max_queued_requests: int | None
    max_queued_bytes: int | None
    max_queue_wait_ms: int | None
    granted_by: UUID
    version: int

    @property
    def effective_max_rate(self) -> int:
        """Return the loan ceiling with loans enabled, else the strict base rate."""

        if self.borrow_enabled and self.max_rate is not None:
            return self.max_rate
        return self.base_rate


def _decode_constraints(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]


def _stored_pool(row: UpstreamQuotaPoolRow) -> StoredPool:
    return StoredPool(
        id=UUID(row.id),
        account_id=UUID(row.account_id),
        provider_type=row.provider_type,
        upstream_scope=UpstreamScope(row.upstream_scope),
        pool_key=row.pool_key,
        label=row.label,
        constraints=_decode_constraints(row.constraints),
        max_concurrency=row.max_concurrency,
        max_queued_requests=row.max_queued_requests,
        native_pool_id=row.native_pool_id,
        status=PoolStatus(row.status),
        version=row.version,
    )


def _stored_link(row: CredentialPoolLinkRow) -> StoredPoolLink:
    return StoredPoolLink(
        credential_id=UUID(row.credential_id),
        operation=CredentialOperation(row.operation_scope),
        pool_id=UUID(row.pool_id),
        provider_type=row.provider_type,
        version=row.version,
    )


def _stored_allocation(row: ProjectPoolAllocationRow) -> StoredAllocation:
    return StoredAllocation(
        project_id=UUID(row.project_id),
        pool_id=UUID(row.pool_id),
        operation=CredentialOperation(row.operation_scope),
        base_rate=row.base_rate,
        rate_window_seconds=row.rate_window_seconds,
        borrow_enabled=bool(row.borrow_enabled),
        max_rate=row.max_rate,
        weight=row.weight,
        best_effort=bool(row.best_effort),
        max_concurrency=row.max_concurrency,
        max_queued_requests=row.max_queued_requests,
        max_queued_bytes=row.max_queued_bytes,
        max_queue_wait_ms=row.max_queue_wait_ms,
        granted_by=UUID(row.granted_by),
        version=row.version,
    )


class UpstreamPoolRepository:
    """System and shared-pool scope queries, always bounded by one account."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pool(
        self,
        *,
        account_id: UUID,
        provider_type: str,
        upstream_scope: UpstreamScope,
        pool_key: str,
        label: str,
        constraints: list[dict[str, Any]],
        native_pool_id: str | None = None,
        max_concurrency: int | None = None,
        max_queued_requests: int | None = None,
        now: datetime | None = None,
    ) -> StoredPool:
        """Insert one active pool."""

        timestamp = stored_timestamp(resolve_now(now))
        row = UpstreamQuotaPoolRow(
            id=str(uuid4()),
            account_id=str(account_id),
            provider_type=provider_type,
            upstream_scope=UpstreamScope(upstream_scope).value,
            pool_key=pool_key,
            label=label,
            constraints=json.dumps(constraints, separators=(",", ":"), sort_keys=True),
            max_concurrency=max_concurrency,
            max_queued_requests=max_queued_requests,
            native_pool_id=native_pool_id,
            status=PoolStatus.ACTIVE.value,
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return _stored_pool(row)

    async def get_pool(self, *, account_id: UUID, pool_id: UUID) -> StoredPool | None:
        """Return one pool of this account, or ``None``."""

        row = await self._session.scalar(
            select(UpstreamQuotaPoolRow).where(
                UpstreamQuotaPoolRow.id == str(pool_id),
                UpstreamQuotaPoolRow.account_id == str(account_id),
            )
        )
        return None if row is None else _stored_pool(row)

    async def list_pools(self, *, account_id: UUID) -> list[StoredPool]:
        """List this account's pools by provider type and pool key."""

        rows = await self._session.scalars(
            select(UpstreamQuotaPoolRow)
            .where(UpstreamQuotaPoolRow.account_id == str(account_id))
            .order_by(UpstreamQuotaPoolRow.provider_type, UpstreamQuotaPoolRow.pool_key)
        )
        return [_stored_pool(row) for row in rows]

    async def link_credential(
        self,
        *,
        credential_id: UUID,
        operation: CredentialOperation,
        pool_id: UUID,
        provider_type: str,
        now: datetime | None = None,
    ) -> StoredPoolLink:
        """Link a credential's operation to one pool; relinking replaces the pool."""

        statement = sqlite_insert(CredentialPoolLinkRow).values(
            credential_id=str(credential_id),
            operation_scope=CredentialOperation(operation).value,
            pool_id=str(pool_id),
            provider_type=provider_type,
            created_at=stored_timestamp(resolve_now(now)),
            version=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                CredentialPoolLinkRow.credential_id,
                CredentialPoolLinkRow.operation_scope,
            ],
            set_={
                "pool_id": statement.excluded.pool_id,
                "provider_type": statement.excluded.provider_type,
                "version": CredentialPoolLinkRow.version + 1,
            },
        )
        await self._session.execute(statement)
        await self._session.flush()
        link = await self.pool_for_credential(credential_id=credential_id, operation=operation)
        if link is None:
            raise RuntimeError("credential pool link was not stored")
        return link

    async def pool_for_credential(
        self, *, credential_id: UUID, operation: CredentialOperation
    ) -> StoredPoolLink | None:
        """Return the pool link of one credential and operation, or ``None``."""

        row = await self._session.scalar(
            select(CredentialPoolLinkRow)
            .where(
                CredentialPoolLinkRow.credential_id == str(credential_id),
                CredentialPoolLinkRow.operation_scope == CredentialOperation(operation).value,
            )
            .execution_options(populate_existing=True)
        )
        return None if row is None else _stored_link(row)

    async def links_for_pool(self, *, pool_id: UUID) -> list[StoredPoolLink]:
        """List every credential link of one shared pool."""

        rows = await self._session.scalars(
            select(CredentialPoolLinkRow)
            .where(CredentialPoolLinkRow.pool_id == str(pool_id))
            .order_by(CredentialPoolLinkRow.credential_id, CredentialPoolLinkRow.operation_scope)
            .execution_options(populate_existing=True)
        )
        return [_stored_link(row) for row in rows]


class PoolAllocationRepository:
    """Project allocation queries; project reads take the owning project id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: UUID,
        pool_id: UUID,
        operation: CredentialOperation,
        base_rate: int,
        rate_window_seconds: int,
        granted_by: UUID,
        borrow_enabled: bool = False,
        max_rate: int | None = None,
        weight: int = 1,
        best_effort: bool = False,
        max_concurrency: int | None = None,
        max_queued_requests: int | None = None,
        max_queued_bytes: int | None = None,
        max_queue_wait_ms: int | None = None,
        now: datetime | None = None,
    ) -> StoredAllocation:
        """Insert one allocation; strict caps with loans disabled by default."""

        timestamp = stored_timestamp(resolve_now(now))
        row = ProjectPoolAllocationRow(
            project_id=str(project_id),
            pool_id=str(pool_id),
            operation_scope=CredentialOperation(operation).value,
            base_rate=base_rate,
            rate_window_seconds=rate_window_seconds,
            borrow_enabled=borrow_enabled,
            max_rate=max_rate,
            weight=weight,
            best_effort=best_effort,
            max_concurrency=max_concurrency,
            max_queued_requests=max_queued_requests,
            max_queued_bytes=max_queued_bytes,
            max_queue_wait_ms=max_queue_wait_ms,
            granted_by=str(granted_by),
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return _stored_allocation(row)

    async def update(
        self,
        *,
        project_id: UUID,
        pool_id: UUID,
        operation: CredentialOperation,
        expected_version: int,
        base_rate: int,
        rate_window_seconds: int,
        borrow_enabled: bool,
        max_rate: int | None,
        weight: int,
        best_effort: bool,
        max_concurrency: int | None,
        max_queued_requests: int | None,
        max_queued_bytes: int | None,
        max_queue_wait_ms: int | None,
        granted_by: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredAllocation | None:
        """Replace every tunable at the expected version; ``None`` when absent or stale."""

        values: dict[str, Any] = {
            "base_rate": base_rate,
            "rate_window_seconds": rate_window_seconds,
            "borrow_enabled": borrow_enabled,
            "max_rate": max_rate,
            "weight": weight,
            "best_effort": best_effort,
            "max_concurrency": max_concurrency,
            "max_queued_requests": max_queued_requests,
            "max_queued_bytes": max_queued_bytes,
            "max_queue_wait_ms": max_queue_wait_ms,
            "updated_at": stored_timestamp(resolve_now(now)),
            "version": ProjectPoolAllocationRow.version + 1,
        }
        if granted_by is not None:
            values["granted_by"] = str(granted_by)
        row = await self._session.scalar(
            update(ProjectPoolAllocationRow)
            .where(
                *self._key(project_id=project_id, pool_id=pool_id, operation=operation),
                ProjectPoolAllocationRow.version == expected_version,
            )
            .values(**values)
            .returning(ProjectPoolAllocationRow)
            .execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored_allocation(row)

    async def get(
        self, *, project_id: UUID, pool_id: UUID, operation: CredentialOperation
    ) -> StoredAllocation | None:
        """Return one allocation of this project, or ``None``."""

        row = await self._session.scalar(
            select(ProjectPoolAllocationRow).where(
                *self._key(project_id=project_id, pool_id=pool_id, operation=operation)
            )
        )
        return None if row is None else _stored_allocation(row)

    async def list_for_project(self, *, project_id: UUID) -> list[StoredAllocation]:
        """List this project's allocations by pool and operation."""

        rows = await self._session.scalars(
            select(ProjectPoolAllocationRow)
            .where(ProjectPoolAllocationRow.project_id == str(project_id))
            .order_by(ProjectPoolAllocationRow.pool_id, ProjectPoolAllocationRow.operation_scope)
        )
        return [_stored_allocation(row) for row in rows]

    async def list_for_pool(self, *, pool_id: UUID) -> list[StoredAllocation]:
        """List every project's allocation of one shared pool (a system read)."""

        rows = await self._session.scalars(
            select(ProjectPoolAllocationRow)
            .where(ProjectPoolAllocationRow.pool_id == str(pool_id))
            .order_by(ProjectPoolAllocationRow.project_id, ProjectPoolAllocationRow.operation_scope)
        )
        return [_stored_allocation(row) for row in rows]

    async def delete(
        self, *, project_id: UUID, pool_id: UUID, operation: CredentialOperation
    ) -> bool:
        """Remove one allocation of this project; return whether a row was removed."""

        result = await self._session.execute(
            delete(ProjectPoolAllocationRow).where(
                *self._key(project_id=project_id, pool_id=pool_id, operation=operation)
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    @staticmethod
    def _key(*, project_id: UUID, pool_id: UUID, operation: CredentialOperation) -> tuple[Any, ...]:
        return (
            ProjectPoolAllocationRow.project_id == str(project_id),
            ProjectPoolAllocationRow.pool_id == str(pool_id),
            ProjectPoolAllocationRow.operation_scope == CredentialOperation(operation).value,
        )


__all__ = [
    "CredentialPoolLinkRow",
    "PoolAllocationRepository",
    "ProjectPoolAllocationRow",
    "StoredAllocation",
    "StoredPool",
    "StoredPoolLink",
    "UpstreamPoolRepository",
    "UpstreamQuotaPoolRow",
]
