"""MCP transport authentication: SDK token verification and tool-call checks.

Auth policy stays in :mod:`freesearch.services.users`. This module composes that
policy onto the MCP SDK seams:

* :class:`LocalTokenVerifier` implements the SDK ``TokenVerifier`` protocol and
  delegates every check to the shared service, so the API surface and the MCP
  surfaces use one secret, one audience, one expiry rule, and one live session
  family.
* :func:`require_mcp_user` runs at the start of both tool bodies. It reads the
  HTTP credential from the SDK request auth context, or the explicit stdio
  environment credential, and it verifies the account and its family again.
* :func:`build_http_app` composes the SDK Streamable HTTP application inside the
  whole-application Bearer guard, so the SDK metadata routes and unknown paths
  need a credential too.
* :func:`run_http_server` and :func:`run_stdio_server` own the transport
  lifecycle. The auth repository opens before the first request and closes after
  the last session and its trace flush.

Under Q1 this transport has no public exception. Under Q6 the server implements
no OAuth authorization server and no anonymous discovery route.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl, SecretStr
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from freesearch.configuration.config import Settings, require_transport_port
from freesearch.infrastructure.auth_asgi import BearerAuthMiddleware
from freesearch.models.users import UserPrincipal
from freesearch.services.users import AuthService

#: The SDK Streamable HTTP endpoint, and the resource path of its metadata URL.
STREAMABLE_HTTP_PATH: str = "/mcp"

#: One fixed, secret-free message for every rejected tool call.
MCP_AUTH_ERROR: str = "authentication is required"

#: Startup error for a stdio process without its explicit credential.
_STDIO_TOKEN_REQUIRED: str = "FREESEARCH_MCP_BEARER_TOKEN is required for the stdio transport"


class McpAuthenticationError(RuntimeError):
    """Raised when a tool call carries no verified account credential."""


class LocalTokenVerifier(TokenVerifier):
    """SDK Bearer verifier backed by the shared account service.

    The raw token stays in the SDK request auth object. Only the canonical
    account UUID leaves this method, as both ``client_id`` and ``subject``.
    """

    def __init__(self, auth_service: AuthService) -> None:
        self._auth_service = auth_service

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return SDK access info for a live account, else ``None``."""

        principal = await self._auth_service.verify_token(token)
        if principal is None:
            return None
        account = str(principal.id)
        return AccessToken(token=token, client_id=account, scopes=[], subject=account)


def build_auth_settings(settings: Settings) -> AuthSettings:
    """Derive the SDK resource metadata from the local transport settings.

    The issuer and the resource URL come from the configured host and port. An
    explicit ``FREESEARCH_AUTH_ISSUER_URL`` or ``FREESEARCH_MCP_RESOURCE_URL``
    override wins, so a reverse proxy can advertise its public URLs.
    """

    authority = settings.mcp_host
    if settings.mcp_port is not None:
        authority = f"{authority}:{settings.mcp_port}"
    base = f"http://{authority}"
    issuer = settings.auth_issuer_url or base
    resource = settings.mcp_resource_url or f"{base}{STREAMABLE_HTTP_PATH}"
    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
    )


async def require_mcp_user(
    auth_service: AuthService, *, stdio_token: SecretStr | None = None
) -> UserPrincipal:
    """Return the verified account of one tool call, or reject that call.

    A call over HTTP must carry the SDK request auth context. A stdio call must
    carry the explicit process credential. The account, its active flag, its
    role, and its session family are checked again on every call, so a stateful
    session cannot keep access after expiry, logout, or deactivation.
    """

    access = get_access_token()
    if access is not None:
        token = access.token
    elif stdio_token is not None:
        token = stdio_token.get_secret_value()
    else:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    principal = await auth_service.verify_token(token)
    if principal is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    if access is not None and access.subject not in (None, str(principal.id)):
        # The SDK subject is a consistency check only. It can reject a call and
        # can never grant one, so client metadata cannot select another account.
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    return principal


def build_http_app(server: FastMCP, *, auth_service: AuthService, settings: Settings) -> Starlette:
    """Return the guarded Streamable HTTP application for ``server``.

    The SDK reads its auth settings when it builds the application, so the
    effective settings decide the advertised issuer and resource URLs. The
    returned application owns the auth lifecycle: the repository opens and
    migrates before the first request, and the SDK session manager stops before
    that repository closes.
    """

    if server.settings.auth is None:
        # Fail at startup instead of denying every authenticated call later: the
        # SDK arms its Bearer middleware only for a server that has a verifier.
        raise McpAuthenticationError("the MCP server was created without account authentication")
    server.settings.auth = build_auth_settings(settings)
    inner = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await auth_service.open()
        try:
            async with inner.router.lifespan_context(inner):
                yield
        finally:
            await auth_service.close()

    return Starlette(
        routes=[Mount("/", app=inner)],
        middleware=[
            Middleware(
                BearerAuthMiddleware,
                verify_token=auth_service.verify_token,
                # This transport mounts no account route, so the two API
                # exceptions stay closed here and every path needs a credential.
                public_routes=frozenset(),
            )
        ],
        lifespan=lifespan,
    )


async def run_http_server(
    server: FastMCP, *, auth_service: AuthService, settings: Settings
) -> None:
    """Serve the guarded Streamable HTTP application on the configured port."""

    import uvicorn

    port = require_transport_port(settings, transport="mcp")
    server.settings.host = settings.mcp_host
    server.settings.port = port
    config = uvicorn.Config(
        build_http_app(server, auth_service=auth_service, settings=settings),
        host=settings.mcp_host,
        port=port,
        log_level=server.settings.log_level.lower(),
    )
    await uvicorn.Server(config).serve()


async def run_stdio_server(
    server: FastMCP, *, auth_service: AuthService, settings: Settings
) -> None:
    """Serve the stdio transport under the explicit process credential."""

    if settings.mcp_bearer_token is None:
        raise McpAuthenticationError(_STDIO_TOKEN_REQUIRED)
    await auth_service.open()
    try:
        await server.run_stdio_async()
    finally:
        await auth_service.close()


__all__ = [
    "MCP_AUTH_ERROR",
    "STREAMABLE_HTTP_PATH",
    "LocalTokenVerifier",
    "McpAuthenticationError",
    "build_auth_settings",
    "build_http_app",
    "require_mcp_user",
    "run_http_server",
    "run_stdio_server",
]
