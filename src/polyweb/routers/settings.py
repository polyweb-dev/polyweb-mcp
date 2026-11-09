"""Scoped typed settings HTTP surface (P03).

Thin transport only. The settings service resolves the immutable project
context, evaluates live scoped permissions through the common authorization
service, and applies revisioned resolution. A project settings request for an
unknown project and one for an existing project the caller cannot access both
return HTTP 404, so the response does not reveal cross-project existence.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from polyweb.models.projects import SettingsResolution
from polyweb.models.settings import (
    ProjectSettingsUpdate,
    SettingsCopyPreview,
    SettingsCopyRequest,
    SettingsCopyResult,
    SystemSettingsDocument,
    SystemSettingsUpdate,
)
from polyweb.models.users import UserPrincipal
from polyweb.routers.auth import current_principal
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.settings import (
    SettingsConflict,
    SettingsCorrupt,
    SettingsNotFound,
    SettingsService,
    SettingsServiceError,
    SettingsStorageUnavailable,
    SettingsValidationError,
)
from polyweb.services.users import AuthService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _settings_service(request: Request) -> SettingsService:
    """Return the typed settings service over the app's shared repository."""

    account_service = getattr(request.app.state, "auth_service", None)
    if not isinstance(account_service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="settings are not configured",
        )
    repository = account_service.repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="settings are not configured",
        )
    return SettingsService(
        repository,
        rollout_state=account_service.settings.projects_rollout_state,
    )


def _register_error_handlers(app: FastAPI) -> None:
    """Map settings failures to safe transport responses."""

    @app.exception_handler(AuthorizationDenied)
    async def _authorization_denied(_: Request, __: AuthorizationDenied) -> Response:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(SettingsNotFound)
    async def _settings_not_found(_: Request, __: SettingsNotFound) -> Response:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(SettingsConflict)
    async def _settings_conflict(_: Request, exc: SettingsConflict) -> Response:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(SettingsValidationError)
    async def _settings_invalid(_: Request, __: SettingsValidationError) -> Response:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(SettingsCorrupt)
    async def _settings_corrupt(_: Request, __: SettingsCorrupt) -> Response:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @app.exception_handler(SettingsStorageUnavailable)
    async def _settings_unavailable(_: Request, __: SettingsStorageUnavailable) -> Response:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(SettingsServiceError)
    async def _settings_error(_: Request, __: SettingsServiceError) -> Response:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def register_settings_routes(app: FastAPI) -> None:
    """Register system and project typed settings routes on ``app``."""

    _register_error_handlers(app)

    @app.get("/api/v1/system/settings", response_model=SystemSettingsDocument)
    async def get_system_settings(
        request: Request,
        principal: _Principal,
    ) -> SystemSettingsDocument:
        """Return system defaults, safety limits, and their revision."""

        return await _settings_service(request).get_system_settings(principal)

    @app.put("/api/v1/system/settings", response_model=SystemSettingsDocument)
    async def put_system_settings(
        request: Request,
        principal: _Principal,
        body: SystemSettingsUpdate,
    ) -> SystemSettingsDocument:
        """Replace system defaults at one expected revision."""

        return await _settings_service(request).update_system_settings(principal, body)

    @app.get(
        "/api/v1/projects/{project_id}/settings",
        response_model=SettingsResolution,
    )
    async def get_project_settings(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> SettingsResolution:
        """Resolve one project's effective settings with per-field provenance."""

        return await _settings_service(request).get_project_settings(principal, project_id)

    @app.put(
        "/api/v1/projects/{project_id}/settings",
        response_model=SettingsResolution,
    )
    async def put_project_settings(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: ProjectSettingsUpdate,
    ) -> SettingsResolution:
        """Apply a bounded project override write at one expected revision."""

        return await _settings_service(request).update_project_settings(principal, project_id, body)

    @app.post(
        "/api/v1/projects/{project_id}/settings/copy/preview",
        response_model=SettingsCopyPreview,
    )
    async def preview_project_settings_copy(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: SettingsCopyRequest,
    ) -> SettingsCopyPreview:
        """Return a revision-bound copy plan without writing anything."""

        return await _settings_service(request).preview_copy(principal, project_id, body)

    @app.post(
        "/api/v1/projects/{project_id}/settings/copy",
        response_model=SettingsCopyResult,
    )
    async def apply_project_settings_copy(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: SettingsCopyRequest,
    ) -> SettingsCopyResult:
        """Apply a previewed settings copy atomically and audit the result."""

        return await _settings_service(request).apply_copy(principal, project_id, body)


__all__ = ["register_settings_routes"]
