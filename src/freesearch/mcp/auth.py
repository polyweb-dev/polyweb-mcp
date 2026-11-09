"""MCP transport credentials: project API keys only (TASK-000041).

MCP clients authenticate with a project API key, exactly like REST machine
clients. There is no anonymous tool call and no human-session MCP access.

* Streamable HTTP: the outer ASGI guard verifies a project API key on every
  ``/mcp`` request and rejects anything else with HTTP 401. Each tool call uses
  the principal the guard stored on the HTTP request that carried that call,
  so a persistent session is checked again on every call, and the execution
  boundary re-reads the key before any provider access.
* Stdio: the key arrives through the process credential channel
  ``FREESEARCH_MCP_BEARER_TOKEN`` and is verified again on every tool call.

The raw key is only ever held as a :class:`~pydantic.SecretStr` and is never
logged or put in a trace.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AnyHttpUrl, SecretStr
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from freesearch.configuration.config import Settings, require_transport_port
from freesearch.infrastructure.auth_asgi import BearerAuthMiddleware, bearer_credential_from_scope
from freesearch.models.projects import ProjectApiKeyPrincipal
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.api_keys import DEFAULT_USE_RECORDER, ApiKeyVerifier
from freesearch.services.users import AuthService

#: The SDK Streamable HTTP endpoint, and the resource path of its metadata URL.
STREAMABLE_HTTP_PATH: str = "/mcp"

#: Streamable HTTP uses POST for JSON-RPC, GET for an optional event stream,
#: and DELETE to close a stateful session. Every one needs a project API key.
MCP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", STREAMABLE_HTTP_PATH),
        ("GET", STREAMABLE_HTTP_PATH),
        ("DELETE", STREAMABLE_HTTP_PATH),
    }
)

#: One fixed, secret-free message for every rejected tool call.
MCP_AUTH_ERROR: str = "authentication is required"


class McpAuthenticationError(RuntimeError):
    """Raised when a tool call carries no valid project API key."""


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


def _transport_request(ctx: Any) -> Any | None:
    """Return the HTTP request that carried this tool call, else ``None``."""

    if ctx is None:
        return None
    try:
        return ctx.request_context.request
    except (AttributeError, LookupError, ValueError):
        return None


def tool_credential(
    ctx: Context | None,  # type: ignore[type-arg]
    *,
    stdio_key: SecretStr | None,
) -> SecretStr | None:
    """Return the raw key presented for this one tool call, else ``None``.

    A call that arrived over HTTP uses only the ``Authorization`` header of its
    own HTTP request; the process key can never authenticate an HTTP call. A
    call without an HTTP request (stdio) uses the process credential channel.
    """

    request = _transport_request(ctx)
    if request is not None:
        scope = getattr(request, "scope", None)
        token = bearer_credential_from_scope(scope) if isinstance(scope, dict) else None
        return SecretStr(token) if token else None
    return stdio_key


async def require_mcp_api_key(
    repository: SQLiteRepository, credential: SecretStr | None
) -> ProjectApiKeyPrincipal:
    """Verify one tool call's project API key, or reject that call.

    Runs the shared :class:`ApiKeyVerifier` on every call. Every failure,
    including a storage failure, is the same generic authentication error.
    """

    if credential is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    try:
        principal = await ApiKeyVerifier(repository).verify(credential)
    except Exception as error:
        raise McpAuthenticationError(MCP_AUTH_ERROR) from error
    if principal is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    return principal


def guard_principal(ctx: Context | None) -> ProjectApiKeyPrincipal | None:  # type: ignore[type-arg]
    """Return the key principal the guard verified for this call's own HTTP request.

    Only the ASGI scope of the HTTP request that carried this tool call counts;
    no context variable or session-level state is read, because the SDK can run
    a tool in a session task created by an earlier request.
    """

    request = _transport_request(ctx)
    scope = getattr(request, "scope", None) if request is not None else None
    state = scope.get("state") if isinstance(scope, dict) else None
    principal = state.get("user") if isinstance(state, dict) else None
    return principal if isinstance(principal, ProjectApiKeyPrincipal) else None


async def resolve_tool_principal(
    ctx: Context | None,  # type: ignore[type-arg]
    *,
    stdio_key: SecretStr | None,
    repository: SQLiteRepository | None,
) -> ProjectApiKeyPrincipal:
    """Return the verified project API key principal of one tool call, or reject it.

    Over HTTP the guard verified the key on the very request that carried this
    call, so that principal is used and the key is not verified twice; a call
    whose request carries none is rejected. Over stdio the process key is
    verified again on every call.
    """

    if _transport_request(ctx) is not None:
        principal = guard_principal(ctx)
        if principal is None:
            raise McpAuthenticationError(MCP_AUTH_ERROR)
        return principal
    credential = tool_credential(ctx, stdio_key=stdio_key)
    if credential is None:
        raise McpAuthenticationError(MCP_AUTH_ERROR)
    if repository is None:
        raise RuntimeError("execution is temporarily unavailable")
    return await require_mcp_api_key(repository, credential)


async def _verify_guard_key(auth_service: AuthService, token: str) -> ProjectApiKeyPrincipal | None:
    repository = auth_service.repository
    if repository is None:
        return None
    return await ApiKeyVerifier(repository).verify(token)


def build_http_app(server: FastMCP, *, auth_service: AuthService, settings: Settings) -> Starlette:
    """Return the key-guarded Search/Fetch transport; own the account-store lifespan."""

    del settings  # Auth metadata is not advertised by the transport.
    inner = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await auth_service.open()
        try:
            async with inner.router.lifespan_context(inner):
                yield
        finally:
            await DEFAULT_USE_RECORDER.drain()
            await auth_service.close()

    return Starlette(
        routes=[Mount("/", app=inner)],
        middleware=[
            Middleware(
                BearerAuthMiddleware,
                verify_token=None,
                verify_api_key=lambda token: _verify_guard_key(auth_service, token),
                api_key_routes=MCP_ROUTES,
                public_routes=frozenset(),
                operation_routes=MCP_ROUTES,
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
    """Serve the key-authenticated tools over stdio."""

    del settings
    await auth_service.open()
    try:
        await server.run_stdio_async()
    finally:
        await DEFAULT_USE_RECORDER.drain()
        await auth_service.close()


__all__ = [
    "MCP_AUTH_ERROR",
    "MCP_ROUTES",
    "STREAMABLE_HTTP_PATH",
    "McpAuthenticationError",
    "build_auth_settings",
    "build_http_app",
    "guard_principal",
    "require_mcp_api_key",
    "resolve_tool_principal",
    "run_http_server",
    "run_stdio_server",
    "tool_credential",
]
