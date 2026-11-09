"""Project API key persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    project_api_keys(id, project_id, label, prefix, verifier_digest, scopes,
        created_by, created_at, expires_at, revoked_at, last_used_at,
        rotated_from_id, version)

A key stores its public lookup ``prefix`` and a one-way ``verifier_digest``
only; no column can hold a recoverable secret. A ``NULL`` ``expires_at`` means
the key never expires. ``rotated_from_id`` must name a key of the same project,
which the composite foreign key ``(rotated_from_id, project_id)`` enforces.
``created_by`` is an attribution snapshot without a foreign key, so removing a
human account never deletes project-owned keys.

Every method except :meth:`ProjectApiKeyRepository.find_by_prefix` takes the
owning project id and filters by it in SQL. The caller owns the transaction;
methods flush and never commit.
"""

from __future__ import annotations

import json
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
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.persistence.storage import Base
from polyweb.persistence.timestamps import (
    optional_timestamp,
    parse_optional_timestamp,
    parse_timestamp,
    resolve_now,
    stored_timestamp,
)


class ProjectApiKeyRow(Base):
    """One project API key: lookup prefix and verifier digest, never the secret."""

    __tablename__ = "project_api_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_api_keys_project_id_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["rotated_from_id", "project_id"],
            ["project_api_keys.id", "project_api_keys.project_id"],
            name="project_api_keys_rotated_from_fkey",
        ),
        CheckConstraint(
            "length(verifier_digest) >= 64", name="project_api_keys_verifier_digest_length"
        ),
        CheckConstraint("length(prefix) > 0", name="project_api_keys_prefix_not_empty"),
        CheckConstraint(
            "json_valid(scopes) AND json_type(scopes) = 'array' AND json_array_length(scopes) > 0",
            name="project_api_keys_scopes_not_empty",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="project_api_keys_expires_after_created",
        ),
        CheckConstraint("version >= 1", name="project_api_keys_version_positive"),
        Index("project_api_keys_prefix_key", "prefix", unique=True),
        Index("project_api_keys_id_project_key", "id", "project_id", unique=True),
        Index("project_api_keys_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_digest: Mapped[str] = mapped_column(String(256), nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    rotated_from_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


@dataclass(frozen=True)
class StoredApiKey:
    """One stored project API key; it carries no secret material."""

    id: UUID
    project_id: UUID
    label: str
    prefix: str
    verifier_digest: str
    scopes: frozenset[str]
    created_by: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    rotated_from_id: UUID | None
    version: int


def _decode_scopes(raw: str) -> frozenset[str]:
    values = json.loads(raw)
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(value) for value in values)


def _stored(row: ProjectApiKeyRow) -> StoredApiKey:
    return StoredApiKey(
        id=UUID(row.id),
        project_id=UUID(row.project_id),
        label=row.label,
        prefix=row.prefix,
        verifier_digest=row.verifier_digest,
        scopes=_decode_scopes(row.scopes),
        created_by=UUID(row.created_by),
        created_at=parse_timestamp(row.created_at),
        expires_at=parse_optional_timestamp(row.expires_at),
        revoked_at=parse_optional_timestamp(row.revoked_at),
        last_used_at=parse_optional_timestamp(row.last_used_at),
        rotated_from_id=UUID(row.rotated_from_id) if row.rotated_from_id else None,
        version=row.version,
    )


class ProjectApiKeyRepository:
    """Project-scoped API key queries on one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: UUID,
        label: str,
        prefix: str,
        verifier_digest: str,
        scopes: frozenset[str],
        created_by: UUID,
        expires_at: datetime | None,
        rotated_from_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredApiKey:
        """Insert one key; ``expires_at=None`` is stored as no expiration."""

        if not scopes:
            raise ValueError("a project API key needs at least one scope")
        created_at = resolve_now(now)
        row = ProjectApiKeyRow(
            id=str(uuid4()),
            project_id=str(project_id),
            label=label,
            prefix=prefix,
            verifier_digest=verifier_digest,
            scopes=json.dumps(sorted(scopes)),
            created_by=str(created_by),
            created_at=stored_timestamp(created_at),
            expires_at=optional_timestamp(expires_at),
            revoked_at=None,
            last_used_at=None,
            rotated_from_id=str(rotated_from_id) if rotated_from_id is not None else None,
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return _stored(row)

    async def get(self, *, project_id: UUID, api_key_id: UUID) -> StoredApiKey | None:
        """Return one key of this project, or ``None`` when absent or foreign."""

        row = await self._session.scalar(
            select(ProjectApiKeyRow).where(
                ProjectApiKeyRow.id == str(api_key_id),
                ProjectApiKeyRow.project_id == str(project_id),
            )
        )
        return None if row is None else _stored(row)

    async def list_for_project(self, *, project_id: UUID) -> list[StoredApiKey]:
        """List this project's keys, newest first."""

        rows = await self._session.scalars(
            select(ProjectApiKeyRow)
            .where(ProjectApiKeyRow.project_id == str(project_id))
            .order_by(ProjectApiKeyRow.created_at.desc(), ProjectApiKeyRow.id.desc())
        )
        return [_stored(row) for row in rows]

    async def find_by_prefix(self, *, prefix: str) -> StoredApiKey | None:
        """Return the key with this lookup prefix; the key determines its project."""

        row = await self._session.scalar(
            select(ProjectApiKeyRow).where(ProjectApiKeyRow.prefix == prefix)
        )
        return None if row is None else _stored(row)

    async def revoke(self, *, project_id: UUID, api_key_id: UUID, revoked_at: datetime) -> bool:
        """Revoke one live key of this project; ``False`` when absent, foreign, or revoked."""

        result = await self._session.execute(
            update(ProjectApiKeyRow)
            .where(
                ProjectApiKeyRow.id == str(api_key_id),
                ProjectApiKeyRow.project_id == str(project_id),
                ProjectApiKeyRow.revoked_at.is_(None),
            )
            .values(
                revoked_at=stored_timestamp(revoked_at),
                version=ProjectApiKeyRow.version + 1,
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def set_expiry(self, *, project_id: UUID, api_key_id: UUID, expires_at: datetime) -> bool:
        """Set the expiry of one live key of this project; ``False`` when absent or revoked."""

        result = await self._session.execute(
            update(ProjectApiKeyRow)
            .where(
                ProjectApiKeyRow.id == str(api_key_id),
                ProjectApiKeyRow.project_id == str(project_id),
                ProjectApiKeyRow.revoked_at.is_(None),
            )
            .values(
                expires_at=stored_timestamp(expires_at),
                version=ProjectApiKeyRow.version + 1,
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def has_successor(self, *, project_id: UUID, api_key_id: UUID) -> bool:
        """Return whether a key of this project was rotated from this key."""

        found = await self._session.scalar(
            select(ProjectApiKeyRow.id)
            .where(
                ProjectApiKeyRow.project_id == str(project_id),
                ProjectApiKeyRow.rotated_from_id == str(api_key_id),
            )
            .limit(1)
        )
        return found is not None

    async def record_use(self, *, project_id: UUID, api_key_id: UUID, used_at: datetime) -> bool:
        """Stamp the last use of one key of this project; it never moves backwards."""

        result = await self._session.execute(
            update(ProjectApiKeyRow)
            .where(
                ProjectApiKeyRow.id == str(api_key_id),
                ProjectApiKeyRow.project_id == str(project_id),
            )
            .values(
                last_used_at=func.max(
                    func.coalesce(ProjectApiKeyRow.last_used_at, ""), stored_timestamp(used_at)
                )
            )
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))


__all__ = ["ProjectApiKeyRepository", "ProjectApiKeyRow", "StoredApiKey"]
