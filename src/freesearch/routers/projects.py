"""Project lifecycle and membership HTTP surface (TASK-000019).

Thin transport only: parse the request, obtain the shared auth repository, and
delegate every policy decision and write to :class:`ProjectService`. The common
authorization service resolves live scoped assignments inside each service
operation. Responses never include role definitions, session material, or
account credentials.

All project management routes are gated by the configured projects rollout
state. Preview mode exposes the management surface while execution remains
fixture/fake-adapter based; strict and fair retain the same management surface.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from freesearch.models.projects import (
    ProjectAccessRead,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
    RoleAssignmentRead,
    SystemAccessRead,
)
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import UserRead, current_principal
from freesearch.services.authorization import AuthorizationDenied
from freesearch.services.projects import (
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
    ProjectServiceError,
    ProjectStorageUnavailable,
    ProjectValidationError,
)
from freesearch.services.users import AuthLastSystemAdmin, AuthService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _project_service(request: Request) -> ProjectService:
    """Return the project service over the app's shared account repository."""

    account_service = getattr(request.app.state, "auth_service", None)
    if not isinstance(account_service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project management is not configured",
        )
    repository = account_service.repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project management is not configured",
        )
    return ProjectService(
        repository,
        rollout_state=account_service.settings.projects_rollout_state,
    )


def _register_error_handlers(app: FastAPI) -> None:
    """Map project service failures to safe transport responses."""

    @app.exception_handler(AuthorizationDenied)
    async def _authorization_denied(_: Request, __: AuthorizationDenied) -> Response:
        # Deliberately generic: a caller learns that the operation is denied,
        # not which assignment or permission is missing.
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(ProjectNotFound)
    async def _project_not_found(_: Request, __: ProjectNotFound) -> Response:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(ProjectConflict)
    async def _project_conflict(_: Request, exc: ProjectConflict) -> Response:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(AuthLastSystemAdmin)
    async def _last_system_admin(_: Request, exc: AuthLastSystemAdmin) -> Response:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(ProjectValidationError)
    async def _project_validation(_: Request, __: ProjectValidationError) -> Response:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(ProjectStorageUnavailable)
    async def _project_unavailable(_: Request, __: ProjectStorageUnavailable) -> Response:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(ProjectServiceError)
    async def _project_error(_: Request, __: ProjectServiceError) -> Response:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def register_project_routes(app: FastAPI) -> None:
    """Register the project lifecycle and membership routes on ``app``."""

    _register_error_handlers(app)

    @app.get("/api/v1/projects", response_model=list[ProjectRead])
    async def list_projects(
        request: Request,
        principal: _Principal,
        include_archived: bool = True,
    ) -> list[ProjectRead]:
        """List only projects the caller can currently read."""

        return await _project_service(request).list_projects(
            principal, include_archived=include_archived
        )

    @app.post(
        "/api/v1/projects",
        response_model=ProjectRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_project(
        request: Request,
        principal: _Principal,
        body: ProjectCreate,
    ) -> ProjectRead:
        """Create a project and its first active administrator atomically."""

        return await _project_service(request).create_project(principal, body)

    @app.post("/api/v1/projects/{project_id}/archive", response_model=ProjectRead)
    async def archive_project(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> ProjectRead:
        """Archive one project through the live project-scope check."""

        return await _project_service(request).archive_project(principal, project_id)

    @app.get(
        "/api/v1/projects/{project_id}/access",
        response_model=ProjectAccessRead,
    )
    async def read_project_access(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> ProjectAccessRead:
        """Return the caller's live permissions and role keys for one project."""

        return await _project_service(request).project_access(principal, project_id)

    @app.get(
        "/api/v1/projects/{project_id}/members",
        response_model=list[ProjectMemberRead],
    )
    async def list_project_members(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> list[ProjectMemberRead]:
        """Read membership only with live project membership permission."""

        return await _project_service(request).list_members(principal, project_id)

    @app.post(
        "/api/v1/projects/{project_id}/members",
        response_model=ProjectMemberRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_project_member(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: ProjectMemberAdd,
    ) -> ProjectMemberRead:
        """Add an existing active human with a bounded initial project role."""

        return await _project_service(request).add_member(principal, project_id, body)

    @app.patch(
        "/api/v1/projects/{project_id}/members/bulk",
        response_model=list[ProjectMemberRead],
    )
    async def bulk_update_project_members(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: ProjectMembersBulkUpdate,
    ) -> list[ProjectMemberRead]:
        """Apply a bulk membership change atomically under the same guard."""

        return await _project_service(request).bulk_update_members(principal, project_id, body)

    @app.patch(
        "/api/v1/projects/{project_id}/members/{user_id}",
        response_model=ProjectMemberRead,
    )
    async def update_project_member(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        user_id: UUID,
        body: ProjectMemberUpdate,
    ) -> ProjectMemberRead:
        """Suspend or reactivate one membership under the last-admin guard."""

        return await _project_service(request).update_member(principal, project_id, user_id, body)

    @app.delete(
        "/api/v1/projects/{project_id}/members/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_project_member(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        user_id: UUID,
    ) -> Response:
        """Remove one membership and its roles under the last-admin guard."""

        await _project_service(request).remove_member(principal, project_id, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put(
        "/api/v1/projects/{project_id}/members/{user_id}/roles/{role_key}",
        response_model=RoleAssignmentRead,
    )
    async def assign_project_role(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
    ) -> RoleAssignmentRead:
        """Assign one extra built-in project role within delegation limits."""

        return await _project_service(request).assign_role(principal, project_id, user_id, role_key)

    @app.delete(
        "/api/v1/projects/{project_id}/members/{user_id}/roles/{role_key}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_project_role(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
    ) -> Response:
        """Remove one project role under delegation and last-admin guards."""

        await _project_service(request).remove_role(principal, project_id, user_id, role_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/v1/system/access", response_model=SystemAccessRead)
    async def read_system_access(
        request: Request,
        principal: _Principal,
    ) -> SystemAccessRead:
        """Return the caller's live system-scope effective permissions."""

        return await _project_service(request).system_access(principal)

    @app.post(
        "/api/v1/users/{user_id}/deactivate",
        response_model=UserRead,
        status_code=status.HTTP_200_OK,
    )
    async def deactivate_user_account(
        request: Request,
        principal: _Principal,
        user_id: UUID,
    ) -> UserRead:
        """Deactivate one human account as a live system-scope operation."""

        accounts = await _project_service(request).deactivate_accounts([user_id], actor=principal)
        return UserRead.model_validate(accounts[0])


__all__ = ["register_project_routes"]
