"""Vault pool persistence and budget usage rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.persistence.storage import Base


class KeyPoolRow(Base):
    """Storage for a key's project capacity."""

    __tablename__ = "key_pools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["credential_id", "provider_type"],
            ["provider_credentials.id", "provider_credentials.provider_type"],
            ondelete="CASCADE",
            name="key_pools_credential_fkey",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="SET NULL", name="key_pools_project_fkey"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["user.id"], ondelete="RESTRICT", name="key_pools_created_by_fkey"
        ),
        CheckConstraint(
            "CASE WHEN json_valid(operations) THEN json_type(operations) = 'array' "
            "AND json_array_length(operations) > 0 ELSE 0 END",
            name="key_pools_operations_nonempty",
        ),
        CheckConstraint("rate_limit IS NULL OR rate_limit >= 0", name="key_pools_rate_nonnegative"),
        CheckConstraint("rate_window_seconds > 0", name="key_pools_rate_window_positive"),
        CheckConstraint(
            "budget_limit IS NULL OR budget_limit >= 0", name="key_pools_budget_nonnegative"
        ),
        CheckConstraint(
            "budget_window_seconds IS NULL OR budget_window_seconds IN (86400, 604800, 2592000)",
            name="key_pools_budget_window_allowed",
        ),
        CheckConstraint("version >= 1", name="key_pools_version_positive"),
        UniqueConstraint("credential_id", "label", name="key_pools_credential_label_key"),
        Index(
            "key_pools_credential_project_key",
            "credential_id",
            "project_id",
            unique=True,
            sqlite_where=text("project_id IS NOT NULL"),
        ),
        Index(
            "key_pools_project_provider_key",
            "project_id",
            "provider_type",
            unique=True,
            sqlite_where=text("project_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    credential_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    project_id: Mapped[str | None] = mapped_column(CHAR(36))
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    rate_limit: Mapped[int | None] = mapped_column(Integer)
    rate_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    budget_limit: Mapped[int | None] = mapped_column(Integer)
    budget_window_seconds: Mapped[int | None] = mapped_column(
        Integer().evaluates_none(), server_default="2592000"
    )
    operations: Mapped[str] = mapped_column(Text, nullable=False)
    operation_limits: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class PoolBudgetUsageRow(Base):
    """Accumulated spend for a key pool and calendar window."""

    __tablename__ = "pool_budget_usage"
    __table_args__ = (CheckConstraint("spent_micros >= 0", name="pool_budget_usage_nonnegative"),)

    pool_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("key_pools.id", ondelete="CASCADE"), primary_key=True
    )
    window_start: Mapped[str] = mapped_column(String(10), primary_key=True)
    spent_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class KeyPoolValues(BaseModel):
    """Editable pool settings. Budget amounts are integer micro-dollars."""

    label: str = Field(min_length=1, max_length=100)
    rate_limit: int | None = Field(default=None, ge=0)
    rate_window_seconds: int = Field(default=60, gt=0)
    budget_limit: int | None = Field(default=None, ge=0)
    budget_window_seconds: Literal[86400, 604800, 2592000] | None = 2592000
    operations: frozenset[Literal["search", "fetch"]] = Field(min_length=1)
    operation_limits: dict[str, Any] | None = None


class StoredKeyPool(KeyPoolValues):
    """A stored pool, including its source and assignment."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    credential_id: UUID
    project_id: UUID | None
    provider_type: str
    created_by: UUID
    created_at: str
    updated_at: str
    version: int


def _stored(row: KeyPoolRow) -> StoredKeyPool:
    return StoredKeyPool(
        id=UUID(row.id),
        credential_id=UUID(row.credential_id),
        project_id=UUID(row.project_id) if row.project_id else None,
        provider_type=row.provider_type,
        label=row.label,
        rate_limit=row.rate_limit,
        rate_window_seconds=row.rate_window_seconds,
        budget_limit=row.budget_limit,
        budget_window_seconds=row.budget_window_seconds,  # type: ignore[arg-type]
        operations=frozenset(json.loads(row.operations)),
        operation_limits=json.loads(row.operation_limits) if row.operation_limits else None,
        created_by=UUID(row.created_by),
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
    )


def _values(values: KeyPoolValues) -> dict[str, Any]:
    values = KeyPoolValues.model_validate(values.model_dump())
    result = values.model_dump()
    result["operations"] = json.dumps(sorted(values.operations))
    result["operation_limits"] = (
        json.dumps(values.operation_limits, sort_keys=True)
        if values.operation_limits is not None
        else None
    )
    return result


class KeyPoolRepository:
    """Pool methods participate in the caller's transaction; none commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        credential_id: UUID,
        project_id: UUID | None,
        provider_type: str,
        created_by: UUID,
        values: KeyPoolValues,
    ) -> StoredKeyPool:
        now = datetime.now(UTC).isoformat()
        row = KeyPoolRow(
            id=str(uuid4()),
            credential_id=str(credential_id),
            project_id=str(project_id) if project_id else None,
            provider_type=provider_type,
            created_by=str(created_by),
            created_at=now,
            updated_at=now,
            version=1,
            **_values(values),
        )
        self._session.add(row)
        await self._session.flush()
        return _stored(row)

    async def get(self, pool_id: UUID) -> StoredKeyPool | None:
        row = await self._session.scalar(
            select(KeyPoolRow)
            .where(KeyPoolRow.id == str(pool_id))
            .execution_options(populate_existing=True)
        )
        return _stored(row) if row else None

    async def update(self, pool_id: UUID, values: KeyPoolValues) -> StoredKeyPool | None:
        row = await self._session.scalar(
            update(KeyPoolRow)
            .where(KeyPoolRow.id == str(pool_id))
            .values(
                **_values(values),
                updated_at=datetime.now(UTC).isoformat(),
                version=KeyPoolRow.version + 1,
            )
            .returning(KeyPoolRow)
            .execution_options(populate_existing=True)
        )
        return _stored(row) if row else None

    async def delete(self, pool_id: UUID) -> bool:
        result = await self._session.execute(
            delete(KeyPoolRow).where(KeyPoolRow.id == str(pool_id)).returning(KeyPoolRow.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_for_key(self, credential_id: UUID) -> list[StoredKeyPool]:
        return await self._list(KeyPoolRow.credential_id == str(credential_id))

    async def list_for_project(self, project_id: UUID) -> list[StoredKeyPool]:
        return await self._list(KeyPoolRow.project_id == str(project_id))

    async def get_for_project_provider(
        self, project_id: UUID, provider_type: str
    ) -> StoredKeyPool | None:
        row = await self._session.scalar(
            select(KeyPoolRow)
            .where(
                KeyPoolRow.project_id == str(project_id), KeyPoolRow.provider_type == provider_type
            )
            .execution_options(populate_existing=True)
        )
        return _stored(row) if row else None

    async def assign(self, pool_id: UUID, project_id: UUID) -> StoredKeyPool | None:
        return await self._assign(pool_id, project_id)

    async def unassign(self, pool_id: UUID) -> StoredKeyPool | None:
        return await self._assign(pool_id, None)

    async def duplicate_to_project(
        self, pool_id: UUID, project_id: UUID, label: str, created_by: UUID
    ) -> StoredKeyPool | None:
        source = await self.get(pool_id)
        if source is None:
            return None
        values = KeyPoolValues.model_validate(source.model_dump() | {"label": label})
        return await self.create(
            credential_id=source.credential_id,
            project_id=project_id,
            provider_type=source.provider_type,
            created_by=created_by,
            values=values,
        )

    async def unassign_owner_pools(self, project_id: UUID, owner_user_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            text(
                "UPDATE key_pools SET project_id = NULL, updated_at = :now, version = version + 1 "
                "WHERE project_id = :project AND credential_id IN "
                "(SELECT id FROM provider_credentials WHERE owner_user_id = :owner) RETURNING id"
            ),
            {
                "project": str(project_id),
                "owner": str(owner_user_id),
                "now": datetime.now(UTC).isoformat(),
            },
        )
        return [UUID(row[0]) for row in result]

    async def _assign(self, pool_id: UUID, project_id: UUID | None) -> StoredKeyPool | None:
        row = await self._session.scalar(
            update(KeyPoolRow)
            .where(KeyPoolRow.id == str(pool_id))
            .values(
                project_id=str(project_id) if project_id else None,
                updated_at=datetime.now(UTC).isoformat(),
                version=KeyPoolRow.version + 1,
            )
            .returning(KeyPoolRow)
            .execution_options(populate_existing=True)
        )
        return _stored(row) if row else None

    async def _list(self, condition: Any) -> list[StoredKeyPool]:
        rows = await self._session.scalars(
            select(KeyPoolRow)
            .where(condition)
            .order_by(KeyPoolRow.id)
            .execution_options(populate_existing=True)
        )
        return [_stored(row) for row in rows]
