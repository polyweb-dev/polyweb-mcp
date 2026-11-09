"""Transport mapping of provider control-plane failures and shared dependencies.

Not found is an empty HTTP 404 (non-revealing); conflicts (409) and invalid
requests (422) carry ``{"detail": {"code", "message"}}``; storage trouble is
503 and an unusable vendor answer 502. Denied authorization stays the
application-wide empty 403.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_errors import (
    ControlPlaneError,
    ControlStorageUnavailable,
    ResourceConflict,
    ResourceInvalid,
    ResourceNotFound,
    UpstreamUnavailable,
)
from polyweb.services.users import AuthService


def control_repository(request: Request) -> SQLiteRepository:
    """Return the app's shared repository, or HTTP 503 when unconfigured."""

    account_service = getattr(request.app.state, "auth_service", None)
    repository = account_service.repository if isinstance(account_service, AuthService) else None
    if not isinstance(repository, SQLiteRepository):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="provider administration is not configured",
        )
    return repository


def control_secret_store(request: Request) -> EncryptedDbSecretStore:
    """Return the app's encrypted secret store, or HTTP 503 when unconfigured."""

    secret_store = getattr(request.app.state, "secret_store", None)
    if not isinstance(secret_store, EncryptedDbSecretStore):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="credentials are not configured",
        )
    return secret_store


def _coded(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"detail": {"code": code, "message": message}}
    )


def register_control_error_handlers(app: FastAPI) -> None:
    """Map control-plane failures to safe responses (idempotent)."""

    @app.exception_handler(AuthorizationDenied)
    async def _denied(_: Request, __: AuthorizationDenied) -> Response:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    @app.exception_handler(ResourceNotFound)
    async def _not_found(_: Request, __: ResourceNotFound) -> Response:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(ResourceConflict)
    async def _conflict(_: Request, exc: ResourceConflict) -> Response:
        return _coded(status.HTTP_409_CONFLICT, exc.code, str(exc))

    @app.exception_handler(ResourceInvalid)
    async def _invalid(_: Request, exc: ResourceInvalid) -> Response:
        return _coded(422, exc.code, str(exc))

    @app.exception_handler(ControlStorageUnavailable)
    async def _unavailable(_: Request, __: ControlStorageUnavailable) -> Response:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(UpstreamUnavailable)
    async def _upstream(_: Request, __: UpstreamUnavailable) -> Response:
        return Response(status_code=status.HTTP_502_BAD_GATEWAY)

    @app.exception_handler(ControlPlaneError)
    async def _error(_: Request, __: ControlPlaneError) -> Response:
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


__all__ = ["control_repository", "control_secret_store", "register_control_error_handlers"]
