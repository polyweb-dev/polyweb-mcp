"""Project retention orchestration (TASK-000044).

A run always names one project and one data class. Authorization is the live
project ``settings.write`` permission, the deletion statements are project
scoped, and the run record, deletions, and audit event commit together. Trace
retention without an explicit cutoff uses that project's effective
``trace.retention_days``; every other class requires an explicit cutoff, so a
caller can never trigger a surprise global cleanup.

Mandatory audit rows are written independently of request-trace sampling and
are retained by the project's own audit policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    PermissionAction,
    ProjectSettingsDocument,
)
from freesearch.models.retention import RetentionRunRead, RetentionRunRequest
from freesearch.models.schema_enums import RetentionDataClass, RetentionRunStatus
from freesearch.models.settings import (
    SETTINGS_NAMESPACE,
    SETTINGS_SCHEMA_VERSION,
    SystemSettingsDocument,
    resolve_trace_policy,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.retention import RetentionRunRepository
from freesearch.persistence.retention_data import (
    delete_project_audit_events,
    delete_project_traces,
    delete_project_usage,
)
from freesearch.persistence.settings import ProjectSettingsRepository, SystemSettingsRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.timestamps import resolve_now
from freesearch.services.audit_events import record_project_event
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.control_access import require_project_permission, run_control_write
from freesearch.services.control_errors import ResourceConflict, ResourceInvalid

#: Conflict code for a retention write that conflicts with stored state.
RETENTION_CONFLICT: Final[str] = "RETENTION_CONFLICT"
#: Invalid-request code for a non-trace run without a cutoff.
RETENTION_CUTOFF_REQUIRED: Final[str] = "RETENTION_CUTOFF_REQUIRED"
#: Invalid-request code for a cutoff in the future.
RETENTION_CUTOFF_FUTURE: Final[str] = "RETENTION_CUTOFF_FUTURE"
#: Conflict code for unreadable stored settings.
RETENTION_SETTINGS_CORRUPT: Final[str] = "SETTINGS_CORRUPT"


class ProjectRetentionService:
    """Authorize and execute one explicit project's retention run."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)

    async def run(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        request: RetentionRunRequest,
    ) -> RetentionRunRead:
        """Purge the selected class for this project only and record the run."""

        async def operation(session: AsyncSession) -> RetentionRunRead:
            await require_project_permission(
                session,
                self._authorization,
                actor,
                project_id,
                PermissionAction.SETTINGS_WRITE,
            )
            now = resolve_now(None)
            cutoff = request.cutoff
            if cutoff is None:
                if request.data_class is not RetentionDataClass.TRACES:
                    raise ResourceInvalid(
                        RETENTION_CUTOFF_REQUIRED,
                        "a cutoff is required for this retention data class",
                    )
                cutoff = now - timedelta(days=await self._retention_days(session, project_id))
            elif cutoff > now:
                raise ResourceInvalid(
                    RETENTION_CUTOFF_FUTURE,
                    "a retention cutoff must not be in the future",
                )

            runs = RetentionRunRepository(session)
            run = await runs.start(
                project_id=project_id,
                data_class=request.data_class,
                cutoff=cutoff,
                now=now,
            )
            deleted_rows = await self._delete(
                session, project_id=project_id, data_class=request.data_class, cutoff=cutoff
            )
            finished = await runs.finish(
                project_id=project_id,
                run_id=run.id,
                status=RetentionRunStatus.COMPLETED,
                deleted_rows=deleted_rows,
                now=now,
            )
            if not finished:
                raise ResourceConflict(RETENTION_CONFLICT, "the retention run could not finish")
            await record_project_event(
                session,
                project_id=project_id,
                actor=actor,
                action="retention.run",
                target_type="retention_run",
                target_id=str(run.id),
                detail={
                    "data_class": request.data_class.value,
                    "cutoff": cutoff.isoformat(),
                    "deleted_rows": deleted_rows,
                },
            )
            return RetentionRunRead(
                id=run.id,
                project_id=project_id,
                data_class=request.data_class,
                cutoff=cutoff,
                status=RetentionRunStatus.COMPLETED,
                started_at=now,
                finished_at=now,
                deleted_rows=deleted_rows,
                error_code=None,
            )

        return await run_control_write(
            self._repository,
            operation,
            conflict_code=RETENTION_CONFLICT,
        )

    async def _retention_days(self, session: AsyncSession, project_id: UUID) -> int:
        """Return the project's effective trace retention window."""

        system = await self._system_document(session)
        stored = await ProjectSettingsRepository(session).get(
            project_id=project_id, namespace=SETTINGS_NAMESPACE
        )
        if stored is None:
            project = ProjectSettingsDocument()
        else:
            if stored.schema_version != SETTINGS_SCHEMA_VERSION:
                raise ResourceConflict(
                    RETENTION_SETTINGS_CORRUPT, "stored project settings are invalid"
                )
            try:
                project = ProjectSettingsDocument.model_validate(
                    {**stored.document, "revision": stored.revision}
                )
            except (ValueError, TypeError) as error:
                raise ResourceConflict(
                    RETENTION_SETTINGS_CORRUPT, "stored project settings are invalid"
                ) from error
        return resolve_trace_policy(system=system, project=project).retention_days

    async def _system_document(self, session: AsyncSession) -> SystemSettingsDocument:
        """Return the validated system settings or the documented catalog defaults."""

        stored = await SystemSettingsRepository(session).get(SETTINGS_NAMESPACE)
        if stored is None:
            return SystemSettingsDocument(revision=0)
        if stored.schema_version != SETTINGS_SCHEMA_VERSION:
            raise ResourceConflict(RETENTION_SETTINGS_CORRUPT, "stored system settings are invalid")
        try:
            return SystemSettingsDocument.model_validate(
                {**stored.document, "revision": stored.revision}
            )
        except (ValueError, TypeError) as error:
            raise ResourceConflict(
                RETENTION_SETTINGS_CORRUPT, "stored system settings are invalid"
            ) from error

    @staticmethod
    async def _delete(
        session: AsyncSession,
        *,
        project_id: UUID,
        data_class: RetentionDataClass,
        cutoff: datetime,
    ) -> int:
        """Run the project-scoped deletion for one data class."""

        if data_class is RetentionDataClass.TRACES:
            return await delete_project_traces(session, project_id=project_id, cutoff=cutoff)
        if data_class is RetentionDataClass.USAGE:
            return await delete_project_usage(session, project_id=project_id, cutoff=cutoff)
        return await delete_project_audit_events(session, project_id=project_id, cutoff=cutoff)


__all__ = [
    "RETENTION_CONFLICT",
    "RETENTION_CUTOFF_FUTURE",
    "RETENTION_CUTOFF_REQUIRED",
    "ProjectRetentionService",
]
