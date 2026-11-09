"""Project API key HTTP surface (TASK-000041).

Thin transport over :class:`~polyweb.services.api_keys.ApiKeyService`:

* ``POST /api/v1/projects/{project_id}/api-keys`` issues a key (201). The raw
  ``key`` appears in this response and in the rotation response only.
* ``GET /api/v1/projects/{project_id}/api-keys`` lists key metadata.
* ``POST /api/v1/projects/{project_id}/api-keys/{key_id}/rotate`` replaces a
  live key (201) and bounds the old key to the overlap.
* ``DELETE /api/v1/projects/{project_id}/api-keys/{key_id}`` revokes a key
  (204, idempotent).

Every route needs a human session principal holding ``tokens.manage`` in the
project; a project API key is never accepted here. Unknown projects and key ids
of another project answer the same 404 as every other project resource.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from polyweb.models.projects import (
    DEFAULT_API_KEY_LIFETIME_DAYS,
    DEFAULT_ROTATION_OVERLAP_SECONDS,
    ProjectApiKeyCreate,
    ProjectApiKeyIssued,
    ProjectApiKeyRead,
    ProjectApiKeyRotate,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.auth import current_principal
from polyweb.services.api_keys import ApiKeyService, ApiKeyValidationError
from polyweb.services.users import AuthService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]

_ISSUE_DESCRIPTION = (
    "Issue one project API key with `search.execute` and/or `fetch.execute` scopes "
    "(both when `scopes` is omitted). An omitted `expires_at` uses the default lifetime "
    f"of {DEFAULT_API_KEY_LIFETIME_DAYS} days from issue; an explicit `expires_at: null` "
    "means the key never expires; a timestamp must be in the future. The raw `key` is "
    "returned once, in this response only."
)
_ROTATE_DESCRIPTION = (
    "Replace one active key with a new key of the same label and scopes. An omitted "
    "`expires_at` keeps the old key's lifetime (no expiration stays no expiration); "
    "`null` means no expiration; a timestamp sets it explicitly. The old key stays "
    "valid for `overlap_seconds` (default "
    f"{DEFAULT_ROTATION_OVERLAP_SECONDS}, at most its own expiry); `0` revokes it at once. "
    "The new raw `key` is returned once, in this response only."
)
_LIST_DESCRIPTION = (
    "List key metadata. `expires_at: null` means no expiration. No raw key and no "
    "verifier is ever returned."
)


def _api_key_service(request: Request) -> ApiKeyService:
    """Return the key service over the app's shared account repository."""

    account_service = getattr(request.app.state, "auth_service", None)
    repository = account_service.repository if isinstance(account_service, AuthService) else None
    if not isinstance(repository, SQLiteRepository):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project management is not configured",
        )
    return ApiKeyService(repository)


def _one_time(issued: ProjectApiKeyIssued) -> JSONResponse:
    """Return the one-time key response, never cacheable."""

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=issued.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def register_api_key_routes(app: FastAPI) -> None:
    """Register the project API key routes on ``app``."""

    @app.exception_handler(ApiKeyValidationError)
    async def _api_key_validation(_: Request, __: ApiKeyValidationError) -> Response:
        return JSONResponse(
            status_code=422,
            content={"detail": "expires_at must be in the future"},
        )

    @app.post(
        "/api/v1/projects/{project_id}/api-keys",
        response_model=ProjectApiKeyIssued,
        status_code=status.HTTP_201_CREATED,
        description=_ISSUE_DESCRIPTION,
    )
    async def issue_api_key(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: ProjectApiKeyCreate,
    ) -> JSONResponse:
        """Issue one project API key and return its raw value once."""

        issued = await _api_key_service(request).issue(principal, project_id, body)
        return _one_time(issued)

    @app.get(
        "/api/v1/projects/{project_id}/api-keys",
        response_model=list[ProjectApiKeyRead],
        description=_LIST_DESCRIPTION,
    )
    async def list_api_keys(
        request: Request,
        principal: _Principal,
        project_id: UUID,
    ) -> list[ProjectApiKeyRead]:
        """List the project's API key metadata."""

        return await _api_key_service(request).list_keys(principal, project_id)

    @app.post(
        "/api/v1/projects/{project_id}/api-keys/{key_id}/rotate",
        response_model=ProjectApiKeyIssued,
        status_code=status.HTTP_201_CREATED,
        description=_ROTATE_DESCRIPTION,
    )
    async def rotate_api_key(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        key_id: UUID,
        body: ProjectApiKeyRotate | None = None,
    ) -> JSONResponse:
        """Rotate one active key and return the replacement's raw value once."""

        issued = await _api_key_service(request).rotate(
            principal, project_id, key_id, body or ProjectApiKeyRotate()
        )
        return _one_time(issued)

    @app.delete(
        "/api/v1/projects/{project_id}/api-keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def revoke_api_key(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        key_id: UUID,
    ) -> Response:
        """Revoke one key; revoking it again changes nothing."""

        await _api_key_service(request).revoke(principal, project_id, key_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["register_api_key_routes"]
