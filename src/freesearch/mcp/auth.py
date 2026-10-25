"""MCP transport helpers for authenticated Search/Fetch tool calls.

Search and Fetch require a verified account: a supplied Bearer token is
verified by the outer ASGI guard (or the explicit stdio credential), and the
tool call resolves the caller's project scope before executing. Anonymous
calls are rejected as tool errors. This keeps MCP aligned with REST while the
REST control plane remains protected.
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
from freesearch.infrastructure.auth_asgi import (
    BearerAuthMiddleware,
    current_verified_principal,
    has_auth_request_context,
)
from freesearch.models.users import UserPrincipal
from freesearch.services.users import AuthService

#: The SDK Streamable HTTP endpoint, and the resource path of its metadata URL.
STREAMABLE_HTTP_PATH: str = "/mcp"

#: Streamable HTTP uses POST for JSON-RPC, GET for an optional event stream,
#: and DELETE to close a stateful session. Only this transport path is public.
MCP_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", STREAMABLE_HTTP_PATH),
        ("GET", STREAMABLE_HTTP_PATH),
        ("DELETE", STREAMABLE_HTTP_PATH),
    }
)

#: One fixed, secret-free message for every rejected tool call.
MCP_AUTH_ERROR: str = "authentication is required"


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


async def optional_mcp_user(
    auth_service: AuthService | None, *, stdio_token: SecretStr | None = None
) -> UserPrincipal | None:
    """Return an optional verified account; anonymous tool calls return ``None``."""

    if has_auth_request_context():
        # The ASGI boundary allows an absent credential and rejects any invalid
        # supplied Bearer token before dispatching the MCP request.
        return current_verified_principal()
    if stdio_token is None:
        return None
    if auth_service is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    principal = await auth_service.verify_token(stdio_token.get_secret_value())
    if principal is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    return principal


def build_http_app(server: FastMCP, *, auth_service: AuthService, settings: Settings) -> Starlette:
    """Return public Search/Fetch transport and own account-service lifespan."""

    del settings  # Auth metadata is not advertised by the public transport.
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
                public_routes=MCP_PUBLIC_ROUTES,
                optional_auth_routes=MCP_PUBLIC_ROUTES,
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
    """Serve the authenticated tools over stdio using the configured token."""

    del settings
    await auth_service.open()
    try:
        await server.run_stdio_async()
    finally:
        await auth_service.close()


__all__ = [
    "MCP_AUTH_ERROR",
    "MCP_PUBLIC_ROUTES",
    "STREAMABLE_HTTP_PATH",
    "LocalTokenVerifier",
    "McpAuthenticationError",
    "build_auth_settings",
    "build_http_app",
    "optional_mcp_user",
    "require_mcp_user",
    "run_http_server",
    "run_stdio_server",
]
