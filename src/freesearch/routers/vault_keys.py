"""HTTP endpoints for account-owned vault keys."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from freesearch.models.credentials import (
    CredentialOAuthDeviceRead,
    CredentialOAuthStatusRead,
    CredentialRotate,
)
from freesearch.models.users import UserPrincipal
from freesearch.models.vault import (
    VaultKeyCreate,
    VaultKeyDeleteResult,
    VaultKeyDetails,
    VaultKeyUpdate,
)
from freesearch.routers.auth import current_principal
from freesearch.routers.control_errors import control_repository, control_secret_store
from freesearch.routers.credential_oauth import OAUTH_HTTP_CLIENT_STATE
from freesearch.services.credential_oauth import OAuthTarget
from freesearch.services.vault_keys import VaultKeyService, VaultOAuthService


class _SecretSafeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Invalid request"})

        return safe_handler


router = APIRouter(
    prefix="/api/v1/account/vault/keys", tags=["vault"], route_class=_SecretSafeRoute
)
Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _service(request: Request) -> VaultKeyService:
    http = getattr(request.app.state, OAUTH_HTTP_CLIENT_STATE, None)
    return VaultKeyService(
        control_repository(request),
        control_secret_store(request),
        http_client=http if isinstance(http, httpx.AsyncClient) else None,
    )


def _oauth(request: Request, actor: UserPrincipal) -> VaultOAuthService:
    http = getattr(request.app.state, OAUTH_HTTP_CLIENT_STATE, None)
    return VaultOAuthService(
        control_repository(request),
        control_secret_store(request),
        actor.id,
        http_client=http if isinstance(http, httpx.AsyncClient) else None,
    )


@router.get("", response_model=list[VaultKeyDetails])
async def list_keys(request: Request, actor: Principal) -> list[VaultKeyDetails]:
    return await _service(request).list_keys(actor)


@router.post("", response_model=VaultKeyDetails, status_code=status.HTTP_201_CREATED)
async def create_key(request: Request, actor: Principal, body: VaultKeyCreate) -> VaultKeyDetails:
    return await _service(request).create(actor, body)


@router.patch("/{key_id}", response_model=VaultKeyDetails)
async def update_key(
    request: Request, actor: Principal, key_id: UUID, body: VaultKeyUpdate
) -> VaultKeyDetails:
    return await _service(request).update(actor, key_id, body)


@router.post("/{key_id}/rotate", response_model=VaultKeyDetails)
async def rotate_key(
    request: Request, actor: Principal, key_id: UUID, body: CredentialRotate
) -> VaultKeyDetails:
    return await _service(request).rotate(actor, key_id, body)


@router.delete("/{key_id}", response_model=VaultKeyDeleteResult)
async def delete_key(request: Request, actor: Principal, key_id: UUID) -> VaultKeyDeleteResult:
    return await _service(request).delete(actor, key_id)


@router.post("/{key_id}/oauth/device", response_model=CredentialOAuthDeviceRead)
async def start_oauth(
    request: Request, actor: Principal, key_id: UUID
) -> CredentialOAuthDeviceRead:
    return await _oauth(request, actor).start(actor, OAuthTarget(), key_id)


@router.post("/{key_id}/oauth/poll", response_model=CredentialOAuthStatusRead)
async def poll_oauth(request: Request, actor: Principal, key_id: UUID) -> CredentialOAuthStatusRead:
    return await _oauth(request, actor).poll(actor, OAuthTarget(), key_id)


@router.get("/{key_id}/oauth", response_model=CredentialOAuthStatusRead)
async def oauth_status(
    request: Request, actor: Principal, key_id: UUID
) -> CredentialOAuthStatusRead:
    return await _oauth(request, actor).status(actor, OAuthTarget(), key_id)


@router.delete("/{key_id}/oauth", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_oauth(request: Request, actor: Principal, key_id: UUID) -> Response:
    await _oauth(request, actor).disconnect(actor, OAuthTarget(), key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
