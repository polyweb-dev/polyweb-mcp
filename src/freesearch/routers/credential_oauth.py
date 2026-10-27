"""Per-credential OAuth HTTP surface (A4).

Thin transport over :class:`~freesearch.services.credential_oauth.CredentialOAuthService`.
System credentials (``system.credentials.manage``)::

    POST   /api/v1/system/credentials/{credential_id}/oauth/device
    POST   /api/v1/system/credentials/{credential_id}/oauth/poll
    GET    /api/v1/system/credentials/{credential_id}/oauth
    DELETE /api/v1/system/credentials/{credential_id}/oauth

Project-private credentials use the same set under
``/api/v1/projects/{project_id}/credentials/{credential_id}/oauth``: the
mutations need ``credentials.manage_private``, the status read
``providers.read``. No response carries a device code, client secret or token.

Test seam: set ``app.state.credential_oauth_http_client`` to an
``httpx.AsyncClient`` (for example over ``httpx.MockTransport``) and every
vendor call of these routes goes through it; nothing touches the network.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Request, Response, status

from freesearch.models.credentials import CredentialOAuthDeviceRead, CredentialOAuthStatusRead
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.routers.control_errors import (
    control_repository,
    control_secret_store,
    register_control_error_handlers,
)
from freesearch.services.credential_oauth import CredentialOAuthService, OAuthTarget

_Principal = Annotated[UserPrincipal, Depends(current_principal)]

_SYSTEM = OAuthTarget()

#: ``app.state`` attribute holding an injected vendor HTTP client (test seam).
OAUTH_HTTP_CLIENT_STATE: str = "credential_oauth_http_client"


def _oauth_service(request: Request) -> CredentialOAuthService:
    http_client = getattr(request.app.state, OAUTH_HTTP_CLIENT_STATE, None)
    return CredentialOAuthService(
        control_repository(request),
        control_secret_store(request),
        http_client=http_client if isinstance(http_client, httpx.AsyncClient) else None,
    )


def register_credential_oauth_routes(app: FastAPI) -> None:
    """Register the system and project credential OAuth routes on ``app``."""

    register_control_error_handlers(app)
    _register_system_routes(app)
    _register_project_routes(app)


def _register_system_routes(app: FastAPI) -> None:
    prefix = "/api/v1/system/credentials/{credential_id}/oauth"

    @app.post(
        prefix + "/device",
        response_model=CredentialOAuthDeviceRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def start_system_credential_oauth(
        request: Request, principal: _Principal, credential_id: UUID
    ) -> CredentialOAuthDeviceRead:
        """Start a device flow; returns only the user code and where to enter it."""

        return await _oauth_service(request).start(principal, _SYSTEM, credential_id)

    @app.post(prefix + "/poll", response_model=CredentialOAuthStatusRead)
    async def poll_system_credential_oauth(
        request: Request, principal: _Principal, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Make one device-code exchange and report the grant state."""

        return await _oauth_service(request).poll(principal, _SYSTEM, credential_id)

    @app.get(prefix, response_model=CredentialOAuthStatusRead)
    async def get_system_credential_oauth(
        request: Request, principal: _Principal, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Report the grant state, timestamps and scopes; never tokens."""

        return await _oauth_service(request).status(principal, _SYSTEM, credential_id)

    @app.delete(prefix, status_code=status.HTTP_204_NO_CONTENT)
    async def disconnect_system_credential_oauth(
        request: Request, principal: _Principal, credential_id: UUID
    ) -> Response:
        """Disconnect the grant (idempotent) and revoke its tokens best-effort."""

        await _oauth_service(request).disconnect(principal, _SYSTEM, credential_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def _register_project_routes(app: FastAPI) -> None:
    prefix = "/api/v1/projects/{project_id}/credentials/{credential_id}/oauth"

    @app.post(
        prefix + "/device",
        response_model=CredentialOAuthDeviceRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def start_project_credential_oauth(
        request: Request, principal: _Principal, project_id: UUID, credential_id: UUID
    ) -> CredentialOAuthDeviceRead:
        """Start a device flow for a private credential."""

        return await _oauth_service(request).start(
            principal, OAuthTarget(project_id), credential_id
        )

    @app.post(prefix + "/poll", response_model=CredentialOAuthStatusRead)
    async def poll_project_credential_oauth(
        request: Request, principal: _Principal, project_id: UUID, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Make one device-code exchange for a private credential."""

        return await _oauth_service(request).poll(principal, OAuthTarget(project_id), credential_id)

    @app.get(prefix, response_model=CredentialOAuthStatusRead)
    async def get_project_credential_oauth(
        request: Request, principal: _Principal, project_id: UUID, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Report a private credential's grant state; never tokens."""

        return await _oauth_service(request).status(
            principal, OAuthTarget(project_id), credential_id
        )

    @app.delete(prefix, status_code=status.HTTP_204_NO_CONTENT)
    async def disconnect_project_credential_oauth(
        request: Request, principal: _Principal, project_id: UUID, credential_id: UUID
    ) -> Response:
        """Disconnect a private credential's grant (idempotent)."""

        await _oauth_service(request).disconnect(principal, OAuthTarget(project_id), credential_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["OAUTH_HTTP_CLIENT_STATE", "register_credential_oauth_routes"]
