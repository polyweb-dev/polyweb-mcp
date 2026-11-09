"""Durable typed system and project settings storage (P03).

Rows follow the accepted schema shape::

    system_settings(namespace, schema_version, document, revision)
    project_settings(project_id, namespace, schema_version, overrides, revision)

Revisions are compare-and-set values. A caller that expects revision ``n`` may
only replace that exact revision; a concurrent or out-of-order writer receives
``False`` instead of overwriting newer settings. Writes stay inside the
caller-owned transaction so the service can place the read, check, write, and
project-status validation in one SQLite ``BEGIN IMMEDIATE`` unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.persistence.storage import Base


def _encode(document: dict[str, Any]) -> str:
    """Return deterministic JSON for one validated settings document."""

    return json.dumps(document, separators=(",", ":"), allow_nan=False, sort_keys=True)


def _decode(raw: str) -> dict[str, Any]:
    """Decode one stored settings document, rejecting non-object payloads."""

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("stored settings document must be a JSON object")
    return value


@dataclass(frozen=True)
class StoredSettings:
    """One durable settings document and its compare-and-set revision."""

    namespace: str
    schema_version: int
    document: dict[str, Any]
    revision: int


class SystemSettingsRow(Base):
    """System-scope typed settings document."""

    __tablename__ = "system_settings"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="system_settings_schema_version_positive"),
        CheckConstraint("revision >= 1", name="system_settings_revision_positive"),
    )

    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[str] = mapped_column("document", Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class ProjectSettingsRow(Base):
    """Project-scope typed settings overrides document."""

    __tablename__ = "project_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_settings_project_id_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint("schema_version >= 1", name="project_settings_schema_version_positive"),
        CheckConstraint("revision >= 1", name="project_settings_revision_positive"),
    )

    project_id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    overrides_json: Mapped[str] = mapped_column("overrides", Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


def _stored_system(row: SystemSettingsRow) -> StoredSettings:
    return StoredSettings(
        namespace=row.namespace,
        schema_version=row.schema_version,
        document=_decode(row.document_json),
        revision=row.revision,
    )


def _stored_project(row: ProjectSettingsRow) -> StoredSettings:
    return StoredSettings(
        namespace=row.namespace,
        schema_version=row.schema_version,
        document=_decode(row.overrides_json),
        revision=row.revision,
    )


class SystemSettingsRepository:
    """Strict system-scope settings reads and revision compare-and-set writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, namespace: str) -> StoredSettings | None:
        """Return one system settings document or ``None`` when it is absent."""

        row = await self._session.get(SystemSettingsRow, namespace)
        return None if row is None else _stored_system(row)

    async def revision(self, namespace: str) -> int:
        """Return the current system revision, or ``0`` when no row exists."""

        row = await self._session.execute(
            select(SystemSettingsRow.revision).where(SystemSettingsRow.namespace == namespace)
        )
        revision = row.scalar_one_or_none()
        return 0 if revision is None else int(revision)

    async def compare_and_set(
        self,
        *,
        namespace: str,
        schema_version: int,
        document: dict[str, Any],
        expected_revision: int,
    ) -> bool:
        """Write only the expected revision; return whether the write applied.

        ``expected_revision == 0`` creates the first document. Any other value
        replaces exactly that revision. The caller runs this inside one write
        transaction, so the check and write cannot interleave with another
        writer in this or another process.
        """

        payload = _encode(document)
        if expected_revision == 0:
            insert_statement = (
                sqlite_insert(SystemSettingsRow)
                .values(
                    namespace=namespace,
                    schema_version=schema_version,
                    document_json=payload,
                    revision=1,
                )
                .on_conflict_do_nothing(index_elements=[SystemSettingsRow.namespace])
            )
            insert_result = cast(CursorResult[Any], await self._session.execute(insert_statement))
            return bool(insert_result.rowcount)

        update_statement = (
            update(SystemSettingsRow)
            .where(
                SystemSettingsRow.namespace == namespace,
                SystemSettingsRow.revision == expected_revision,
            )
            .values(
                schema_version=schema_version,
                document_json=payload,
                revision=expected_revision + 1,
            )
        )
        update_result = cast(CursorResult[Any], await self._session.execute(update_statement))
        return bool(update_result.rowcount)


class ProjectSettingsRepository:
    """Strict project-scope settings reads and revision compare-and-set writes.

    Every method requires a project identifier. There is no optional scope and
    no query that can select another project's row.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, project_id: UUID, namespace: str) -> StoredSettings | None:
        """Return one project's overrides document or ``None`` when absent."""

        row = await self._session.get(ProjectSettingsRow, (str(project_id), namespace))
        return None if row is None else _stored_project(row)

    async def revision(self, *, project_id: UUID, namespace: str) -> int:
        """Return one project's current revision, or ``0`` when no row exists."""

        result = await self._session.execute(
            select(ProjectSettingsRow.revision).where(
                ProjectSettingsRow.project_id == str(project_id),
                ProjectSettingsRow.namespace == namespace,
            )
        )
        revision = result.scalar_one_or_none()
        return 0 if revision is None else int(revision)

    async def compare_and_set(
        self,
        *,
        project_id: UUID,
        namespace: str,
        schema_version: int,
        overrides: dict[str, Any],
        expected_revision: int,
    ) -> bool:
        """Write only the expected revision; return whether the write applied."""

        payload = _encode(overrides)
        if expected_revision == 0:
            insert_statement = (
                sqlite_insert(ProjectSettingsRow)
                .values(
                    project_id=str(project_id),
                    namespace=namespace,
                    schema_version=schema_version,
                    overrides_json=payload,
                    revision=1,
                )
                .on_conflict_do_nothing(
                    index_elements=[ProjectSettingsRow.project_id, ProjectSettingsRow.namespace]
                )
            )
            insert_result = cast(CursorResult[Any], await self._session.execute(insert_statement))
            return bool(insert_result.rowcount)

        update_statement = (
            update(ProjectSettingsRow)
            .where(
                ProjectSettingsRow.project_id == str(project_id),
                ProjectSettingsRow.namespace == namespace,
                ProjectSettingsRow.revision == expected_revision,
            )
            .values(
                schema_version=schema_version,
                overrides_json=payload,
                revision=expected_revision + 1,
            )
        )
        update_result = cast(CursorResult[Any], await self._session.execute(update_statement))
        return bool(update_result.rowcount)


__all__ = [
    "ProjectSettingsRepository",
    "ProjectSettingsRow",
    "StoredSettings",
    "SystemSettingsRepository",
    "SystemSettingsRow",
]
