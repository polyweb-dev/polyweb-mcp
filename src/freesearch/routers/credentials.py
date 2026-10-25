"""Provider credential instance HTTP surface (P08).

Thin transport only. The credential service resolves the immutable project
context, evaluates live scoped permissions through the common authorization
service, and bundles row and secret-slot mutations in one transaction. A
request for an unknown credential and one for a credential the caller cannot
access both return HTTP 404, so responses never reveal cross-scope existence.
No response ever contains secret material.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.credentials import (
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialRotate,
    ProjectCredentialRead,
)
from freesearch.models.projects import (
    CredentialInstanceRead,
    CredentialProjectGrantRead,
)
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.services.authorization import AuthorizationDenied
from freesearch.services.credentials import (
    CredentialConflict,
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
    CredentialStorageUnavailable,
    CredentialValidationError,
)
from freesearch.services.users import AuthService

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


def register_credential_routes(app: FastAPI) -> None:
    """Register system and project credential routes on ``app``."""

    _register_error_handlers(app)

    @app.get(
        "/api/v1/system/credentials",
        response_model=list[CredentialInstanceRead],
    )
    async def list_system_credentials(
        request: Request,
        principal: _Principal,
    ) -> list[CredentialInstanceRead]:
        """List active system-owned credential instances."""

        return await _credential_service(request).list_system_credentials(principal)

    @app.post(
        "/api/v1/system/credentials",
        response_model=CredentialInstanceRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_system_credential(
        request: Request,
        principal: _Principal,
        body: CredentialCreate,
    ) -> CredentialInstanceRead:
        """Create one system-owned credential instance."""

        return await _credential_service(request).create_system_credential(principal, body)

    @app.post(
        "/api/v1/system/credentials/{credential_id}/rotate",
        response_model=CredentialInstanceRead,
    )
    async def rotate_system_credential(
        request: Request,
        principal: _Principal,
        credential_id: UUID,
        body: CredentialRotate,
    ) -> CredentialInstanceRead:
        """Rotate one system credential to its next generation."""

        return await _credential_service(request).rotate_system_credential(
            principal, credential_id, body
        )

    @app.delete(
        "/api/v1/system/credentials/{credential_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_system_credential(
        request: Request,
        principal: _Principal,
        credential_id: UUID,
    ) -> Response:
        """Delete one system credential, tombstoning its live slot."""

        await _credential_service(request).delete_system_credential(principal, credential_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/system/credentials/{credential_id}/grants",
        response_model=list[CredentialProjectGrantRead],
    )
    async def list_credential_grants(
        request: Request,
        principal: _Principal,
        credential_id: UUID,
    ) -> list[CredentialProjectGrantRead]:
        """List every project grant on one system credential."""

        return await _credential_service(request).list_grants(principal, credential_id)

    @app.put(
        "/api/v1/system/credentials/{credential_id}/grants/{project_id}",
        response_model=CredentialProjectGrantRead,
    )
    async def put_credential_grant(
        request: Request,
        principal: _Principal,
        credential_id: UUID,
        project_id: UUID,
        body: CredentialGrantUpsert,
    ) -> CredentialProjectGrantRead:
        """Create or replace one project's grant on a system credential."""

        return await _credential_service(request).put_grant(
            principal, credential_id, project_id, body
        )

    @app.delete(
        "/api/v1/system/credentials/{credential_id}/grants/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_credential_grant(
        request: Request,
        principal: _Principal,
        credential_id: UUID,
        project_id: UUID,
    ) -> Response:
        """Remove one project's grant on a system credential."""

        await _credential_service(request).delete_grant(principal, credential_id, project_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/projects/{project_id}/credentials",
        response_model=list[ProjectCredentialRead],
    )
    async def list_project_credentials(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> list[ProjectCredentialRead]:
        """List this project's private and granted system credentials."""

        return await _credential_service(request).list_project_credentials(principal, project_id)

    @app.post(
        "/api/v1/projects/{project_id}/credentials",
        response_model=ProjectCredentialRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_project_credential(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: CredentialCreate,
    ) -> ProjectCredentialRead:
        """Create one project-private credential instance."""

        return await _credential_service(request).create_project_credential(
            principal, project_id, body
        )

    @app.get(
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        response_model=ProjectCredentialRead,
    )
    async def get_project_credential(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        credential_id: UUID,
    ) -> ProjectCredentialRead:
        """Return one project-visible credential instance."""

        return await _credential_service(request).get_project_credential(
            principal, project_id, credential_id
        )

    @app.post(
        "/api/v1/projects/{project_id}/credentials/{credential_id}/rotate",
        response_model=ProjectCredentialRead,
    )
    async def rotate_project_credential(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        credential_id: UUID,
        body: CredentialRotate,
    ) -> ProjectCredentialRead:
        """Rotate one project-private credential to its next generation."""

        return await _credential_service(request).rotate_project_credential(
            principal, project_id, credential_id, body
        )

    @app.delete(
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_project_credential(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        credential_id: UUID,
    ) -> Response:
        """Delete one project-private credential instance."""

        await _credential_service(request).delete_project_credential(
            principal, project_id, credential_id
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["register_credential_routes"]
