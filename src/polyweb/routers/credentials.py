"""Owner-filtered legacy project credential projection for the UI."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import ProjectCredentialRead
from polyweb.models.users import UserPrincipal
from polyweb.persistence.credentials import CredentialRepository
from polyweb.routers.auth import current_principal
from polyweb.routers.control_errors import control_repository
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.credentials import (
    CredentialConflict,
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
    CredentialStorageUnavailable,
    CredentialValidationError,
)
from polyweb.services.users import AuthService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _credential_service(request: Request) -> CredentialService:
    """Return the credential service over the app's shared repository."""

    account_service = getattr(request.app.state, "auth_service", None)
    if not isinstance(account_service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="credentials are not configured",
        )
    repository = account_service.repository
    secret_store = getattr(request.app.state, "secret_store", None)
    if repository is None or not isinstance(secret_store, EncryptedDbSecretStore):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="credentials are not configured",
        )
    return CredentialService(
        repository,
        secret_store,
        rollout_state=account_service.settings.projects_rollout_state,
    )


def _register_error_handlers(app: FastAPI) -> None:
    """Map credential failures to safe transport responses."""

    @app.exception_handler(AuthorizationDenied)
    async def _authorization_denied(_: Request, __: AuthorizationDenied) -> Response:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(CredentialNotFound)
    async def _credential_not_found(_: Request, __: CredentialNotFound) -> Response:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(CredentialConflict)
    async def _credential_conflict(_: Request, exc: CredentialConflict) -> Response:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(CredentialValidationError)
    async def _credential_invalid(_: Request, __: CredentialValidationError) -> Response:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(CredentialStorageUnavailable)
    async def _credential_unavailable(_: Request, __: CredentialStorageUnavailable) -> Response:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(CredentialServiceError)
    async def _credential_error(_: Request, __: CredentialServiceError) -> Response:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def register_project_credential_read_routes(app: FastAPI) -> None:
    """Keep the legacy project list for the UI, restricted to the caller's vault."""

    _register_error_handlers(app)

    @app.get(
        "/api/v1/projects/{project_id}/credentials",
        response_model=list[ProjectCredentialRead],
    )
    async def list_owned_project_credentials(
        request: Request, principal: _Principal, project_id: UUID
    ) -> list[ProjectCredentialRead]:
        projected = await _credential_service(request).list_project_credentials(
            principal, project_id
        )
        async with control_repository(request).session() as session:
            owned = await CredentialRepository(session).list_for_owner(principal.id)
        owned_ids = {key.credential.id for key in owned}
        return [item for item in projected if item.id in owned_ids]


__all__ = ["register_project_credential_read_routes"]
