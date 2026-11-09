"""Project-aware repository facades bound to one immutable ProjectContext (P03).

Callers cannot pass an optional project selector to these repositories. The
project and account identifiers come from the validated context, and every
operation is confined to that project. The facade also re-reads the project row
with the account boundary, so a stale or forged context cannot read or write a
project outside the installation account.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    ProjectContext,
    ProjectRead,
)
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.settings import (
    ProjectSettingsRepository,
    StoredSettings,
    SystemSettingsRepository,
)


class ScopedProjectSettings:
    """Settings operations that always use the context's project identity."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        project_id: UUID,
        namespace: str,
    ) -> None:
        self._project = ProjectSettingsRepository(session)
        self._system = SystemSettingsRepository(session)
        self._project_id = project_id
        self._namespace = namespace

    async def read(self) -> StoredSettings | None:
        """Return this project's stored overrides, never another project's."""

        return await self._project.get(project_id=self._project_id, namespace=self._namespace)

    async def revisions(self) -> tuple[int, int]:
        """Return ``(system_revision, project_revision)`` for this scope."""

        system_revision = await self._system.revision(self._namespace)
        project_revision = await self._project.revision(
            project_id=self._project_id, namespace=self._namespace
        )
        return system_revision, project_revision

    async def compare_and_set(
        self,
        *,
        schema_version: int,
        overrides: dict[str, Any],
        expected_revision: int,
    ) -> bool:
        """Write overrides only when this project is still at the expected revision."""

        return await self._project.compare_and_set(
            project_id=self._project_id,
            namespace=self._namespace,
            schema_version=schema_version,
            overrides=overrides,
            expected_revision=expected_revision,
        )


class ProjectScopedRepository:
    """Facade that binds one session to one validated project context."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        context: ProjectContext,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
    ) -> None:
        if context.account_id != account_id:
            raise ValueError("project context account does not match the installation account")
        self._session = session
        self._context = context
        self._account_id = account_id

    @property
    def context(self) -> ProjectContext:
        """Return the immutable context this facade is bound to."""

        return self._context

    async def require_project(self) -> ProjectRead:
        """Re-read the context project inside the account boundary."""

        project = await ProjectRepository(self._session).get_project(
            project_id=self._context.project_id,
            account_id=self._account_id,
        )
        if project is None:
            raise ValueError(f"Project {self._context.project_id} does not exist in this account")
        return project

    def settings(self, namespace: str) -> ScopedProjectSettings:
        """Return a project-scoped settings store for one typed namespace."""

        return ScopedProjectSettings(
            self._session,
            project_id=self._context.project_id,
            namespace=namespace,
        )


__all__ = ["ProjectScopedRepository", "ScopedProjectSettings"]
