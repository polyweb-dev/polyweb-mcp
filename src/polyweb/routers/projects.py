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

from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.project_permissions import PERMISSION_CATALOG
from polyweb.models.projects import (
    ProjectAccessRead,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
    ProviderOwnerChange,
    ProviderOwnerRead,
    ProviderOwnerTransferRead,
    SystemAccessRead,
)
from polyweb.models.users import UserPrincipal
from polyweb.routers.auth import current_principal
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.projects import (
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
    ProjectServiceError,
    ProjectStorageUnavailable,
    ProjectValidationError,
)
from polyweb.services.users import AuthService

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
    secret_store = getattr(request.app.state, "secret_store", None)
    return ProjectService(
        repository,
        rollout_state=account_service.settings.projects_rollout_state,
        secret_store=secret_store if isinstance(secret_store, EncryptedDbSecretStore) else None,
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

    @app.get("/api/v1/permissions/project-catalog")
    async def project_permission_catalog(principal: _Principal) -> dict[str, object]:
        """Return the project permission definitions and developer presets."""

        labels = (
            ("Run searches", "Send search requests in the playground."),
            ("Fetch pages", "Fetch web pages in the playground."),
            ("View activity", "Open request traces."),
            ("View usage", "See request counts."),
            ("Edit project settings", "Change the trace and routing settings."),
            ("Copy settings", "Copy settings from another project."),
            (
                "Change provider order",
                "Change the Search order and the Fetch order. Turn operations on or off.",
            ),
            ("Manage API keys", "Create, rotate, and revoke project API keys."),
            ("Provider owner", "Supply provider capacity for the project."),
        )
        return {
            "permissions": [
                {**item.model_dump(), "label": label, "description": description}
                for item, (label, description) in zip(PERMISSION_CATALOG, labels, strict=True)
            ],
            "presets": [
                {"key": "read_only", "label": "Read only", "permissions": 12},
                {"key": "standard", "label": "Standard", "permissions": 15},
                {"key": "full_developer", "label": "Full developer", "permissions": 255},
            ],
        }

    @app.get(
        "/api/v1/projects/{project_id}/provider-owner", response_model=ProviderOwnerRead | None
    )
    async def read_provider_owner(
        request: Request, principal: _Principal, project_id: UUID
    ) -> ProviderOwnerRead | None:
        return await _project_service(request).provider_owner(principal, project_id)

    @app.post(
        "/api/v1/projects/{project_id}/provider-owner",
        response_model=ProviderOwnerTransferRead,
    )
    async def transfer_provider_owner(
        request: Request, principal: _Principal, project_id: UUID, body: ProviderOwnerChange
    ) -> ProviderOwnerTransferRead:
        return await _project_service(request).transfer_provider_owner(
            principal, project_id, body.user_id
        )

    @app.get("/api/v1/system/access", response_model=SystemAccessRead)
    async def read_system_access(
        request: Request,
        principal: _Principal,
    ) -> SystemAccessRead:
        """Return the caller's live system-scope effective permissions."""

        return await _project_service(request).system_access(principal)

    @app.get("/api/v1/system/projects", response_model=list[ProjectRead])
    async def list_system_projects(
        request: Request,
        principal: _Principal,
        include_archived: bool = True,
    ) -> list[ProjectRead]:
        """List every project for credential grants and pool allocations."""

        return await _project_service(request).list_system_projects(
            principal, include_archived=include_archived
        )


__all__ = ["register_project_routes"]
