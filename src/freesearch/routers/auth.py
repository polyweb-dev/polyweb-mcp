"""Auth HTTP surface: registration, credential pairs, refresh, and logout.

Transport only: request parsing, the two public endpoints, the protected refresh
route, and the current-account read. Policy lives in
:mod:`freesearch.services.users`.

Under Q1 the public endpoints are exactly ``POST /auth/register`` and
``POST /auth/jwt/login``. ``POST /auth/jwt/refresh`` is authenticated by an
opaque refresh credential in the Bearer header and by nothing else. The access
JWT gates ``POST /auth/jwt/logout`` and ``GET /users/me``.

Every credential response carries ``Cache-Control: no-store`` and never echoes a
submitted password. A schema failure on an auth route returns one fixed safe
message, so no raw input, hash, or token value can leak through a 422 body.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi_users import exceptions, schemas
from fastapi_users.router.common import ErrorCode
from fastapi_users.router.register import get_register_router
from pydantic import BaseModel, ConfigDict, Field

from freesearch.models.users import AuthTokens, UserPrincipal, UserRole
from freesearch.services.users import (
    AuthConfigurationError,
    AuthService,
    AuthStorageUnavailable,
    LoginRateLimited,
    UserManager,
    has_role,
)

#: Auth routes whose validation failures must not echo submitted credentials.
_AUTH_VALIDATION_PREFIXES = ("/auth/", "/users/me")

#: Roles allowed to mutate provider controls and to start provider OAuth flows.
ADMIN_ROLES: frozenset[UserRole] = frozenset({UserRole.ADMIN})

#: Roles allowed to read sanitized control views, statistics, and dashboard data.
CONTROL_READ_ROLES: frozenset[UserRole] = frozenset({UserRole.ADMIN, UserRole.DEVELOPER})

_SAFE_VALIDATION_DETAIL = "invalid authentication request"

_BEARER_PREFIX = "bearer "

#: The token URL the OpenAPI Bearer scheme advertises, matching fastapi-users.
_OPENAPI_TOKEN_URL = "auth/jwt/login"


def _publish_bearer_scheme(app: FastAPI) -> None:
    """Publish the Bearer token scheme in the OpenAPI document.

    ``fastapi-users`` publishes this scheme through ``BearerTransport``. The
    whole-application ASGI guard enforces the credential instead of a per-route
    dependency, so the scheme stays documentation and no operation gains a
    security requirement.
    """

    default_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = default_openapi()
        scheme = OAuth2PasswordBearer(_OPENAPI_TOKEN_URL, auto_error=False)
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes[scheme.scheme_name] = jsonable_encoder(
            scheme.model, by_alias=True, exclude_none=True
        )
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


class UserCreate(schemas.BaseUserCreate):
    """Registration body: email and password only.

    ``extra="forbid"`` rejects client-supplied roles, provider fields, and
    privilege flags. The password is hidden from the model representation, and
    the accepted rule is enforced by the user manager with a clear message.
    """

    model_config = ConfigDict(extra="forbid")

    password: str = Field(repr=False)


class UserRead(schemas.BaseUser[UUID]):
    """Account projection returned by registration and ``GET /users/me``."""

    role: UserRole


class TokenPairResponse(BaseModel):
    """Credential pair plus both expiry intervals, in seconds."""

    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int


def _auth_service(request: Request) -> AuthService:
    """Return the composed auth service, or reject an unconfigured app."""

    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account authentication is not configured",
        )
    return service


def peer_address(request: Request) -> str:
    """Return the actual peer address of the request.

    A forwarded header is deliberately ignored: no trusted-proxy policy exists
    in this cycle, so a client cannot pick its own rate-limit bucket.
    """

    client = request.client
    return client.host if client is not None else "unknown"


def bearer_credential(request: Request) -> str | None:
    """Return the single Bearer credential of the request, else ``None``.

    Duplicate headers and other schemes are rejected as absent credentials.
    """

    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return None
    value = values[0]
    if not value.lower().startswith(_BEARER_PREFIX):
        return None
    return value[len(_BEARER_PREFIX) :].strip() or None


def static_principal(request: Request) -> UserPrincipal | None:
    """Return the principal a transport guard already verified, else ``None``."""

    principal = getattr(request.state, "user", None)
    return principal if isinstance(principal, UserPrincipal) else None


def _unauthenticated(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _access_principal(request: Request) -> UserPrincipal:
    """Return the current account, or reject with HTTP 401.

    The whole-application guard already verified this request and stored the
    principal in ASGI state, so that value wins. The header check stays as a
    fallback for a composition that mounts these routes without the guard.
    """

    verified = static_principal(request)
    if verified is not None:
        return verified
    token = bearer_credential(request)
    if token is None:
        raise _unauthenticated("not authenticated")
    principal = await _auth_service(request).verify_token(token)
    if principal is None:
        raise _unauthenticated("not authenticated")
    return principal


def current_principal(request: Request) -> UserPrincipal:
    """Return the verified principal of this request, or reject with HTTP 401.

    Only the guard's verified principal counts. No role claim, cookie, query
    parameter, or client header can replace it.
    """

    principal = static_principal(request)
    if principal is None:
        raise _unauthenticated("not authenticated")
    return principal


def _require_role(request: Request, allowed: frozenset[UserRole]) -> UserPrincipal:
    """Return the principal only when its current database role is permitted.

    A missing or invalid credential stays HTTP 401. A valid credential with an
    insufficient role is HTTP 403, and the caller runs before any provider or
    persistence side effect.
    """

    principal = current_principal(request)
    if not has_role(principal, allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
    return principal


async def require_admin(request: Request) -> UserPrincipal:
    """Require an active Admin account for a control mutation or OAuth handler."""

    return _require_role(request, ADMIN_ROLES)


async def require_control_reader(request: Request) -> UserPrincipal:
    """Require an Admin or Developer account for a sanitized control read."""

    return _require_role(request, CONTROL_READ_ROLES)


async def get_user_manager(request: Request) -> AsyncIterator[UserManager]:
    """Yield the library user manager bound to one request-scoped session."""

    async with _auth_service(request).user_manager() as manager:
        yield manager


async def auth_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Replace auth request-validation bodies with one fixed safe message.

    Non-auth routes keep the framework's detailed response, so this change cannot
    weaken or alter any existing endpoint contract.
    """

    path = request.url.path
    if any(path.startswith(prefix) for prefix in _AUTH_VALIDATION_PREFIXES):
        # The literal status avoids a Starlette deprecation alias while keeping
        # the documented FastAPI 422 contract.
        return JSONResponse(
            status_code=422,
            content={"detail": _SAFE_VALIDATION_DETAIL},
        )
    return await request_validation_exception_handler(request, exc)


def _token_response(tokens: AuthTokens, response: Response) -> TokenPairResponse:
    """Project internal credentials onto the wire shape, uncacheable."""

    response.headers["Cache-Control"] = "no-store"
    return TokenPairResponse(
        access_token=tokens.access_token.get_secret_value(),
        refresh_token=tokens.refresh_token.get_secret_value(),
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        refresh_expires_in=tokens.refresh_expires_in,
    )


def _login_responses() -> dict[int | str, dict[str, object]]:
    return {
        status.HTTP_400_BAD_REQUEST: {"description": "Bad credentials or an inactive account."},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Attempt limit reached."},
    }


def _library_register_route() -> APIRoute:
    """Return the library's generated registration route.

    The route carries the library's request schema, response schema, status code,
    documented errors, and handler, so registration keeps the standard error
    contract without a hand-written copy.
    """

    router = get_register_router(get_user_manager, UserRead, UserCreate)
    for route in router.routes:
        if isinstance(route, APIRoute):
            return route
    raise RuntimeError("the library registration router has no API route")


def register_auth_routes(app: FastAPI) -> None:
    """Register the account routes and the auth validation handler on ``app``."""

    app.add_exception_handler(RequestValidationError, auth_validation_exception_handler)  # type: ignore[arg-type]
    _publish_bearer_scheme(app)

    # The library owns the registration logic and its error contract. Its route
    # is registered directly on the application router rather than through
    # ``include_router``, so every entry in ``app.routes`` stays a plain route
    # with a ``path`` attribute, in line with the control-plane convention.
    built = _library_register_route()
    app.add_api_route(
        f"/auth{built.path}",
        built.endpoint,
        response_model=built.response_model,
        status_code=built.status_code,
        name=built.name,
        responses=built.responses,
        methods=["POST"],
        dependencies=built.dependencies,
    )

    @app.post(
        "/auth/jwt/login",
        response_model=TokenPairResponse,
        responses=_login_responses(),
    )
    async def login(
        request: Request,
        response: Response,
        credentials: Annotated[OAuth2PasswordRequestForm, Depends()],
    ) -> TokenPairResponse:
        """Authenticate a local account and issue one session family's credentials."""

        service = _auth_service(request)
        try:
            tokens = await service.login(credentials, peer_address=peer_address(request))
        except LoginRateLimited as limited:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many authentication attempts",
                headers={"Retry-After": str(limited.retry_after)},
            ) from limited
        except AuthStorageUnavailable as unavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication is temporarily unavailable",
            ) from unavailable
        except AuthConfigurationError as unconfigured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="account authentication is not configured",
            ) from unconfigured
        if tokens is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
            )
        return _token_response(tokens, response)

    @app.post("/auth/jwt/refresh", response_model=TokenPairResponse)
    async def refresh(request: Request, response: Response) -> TokenPairResponse:
        """Rotate one refresh credential into exactly one successor pair."""

        token = bearer_credential(request)
        if token is None:
            raise _unauthenticated("invalid refresh credential")
        try:
            tokens = await _auth_service(request).rotate_refresh_token(token)
        except AuthStorageUnavailable as unavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication is temporarily unavailable",
            ) from unavailable
        except AuthConfigurationError as unconfigured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="account authentication is not configured",
            ) from unconfigured
        if tokens is None:
            raise _unauthenticated("invalid refresh credential")
        return _token_response(tokens, response)

    @app.post("/auth/jwt/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        """Revoke exactly the authenticated current session family."""

        principal = await _access_principal(request)
        await _auth_service(request).logout(principal)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/users/me", response_model=UserRead)
    async def users_me(request: Request) -> UserRead:
        """Return the authenticated account's own record, never its hash."""

        principal = await _access_principal(request)
        async with _auth_service(request).user_manager() as manager:
            try:
                account = await manager.get(principal.id)
            except (exceptions.InvalidID, exceptions.UserNotExists) as missing:
                raise _unauthenticated("not authenticated") from missing
        return UserRead.model_validate(account)


__all__ = [
    "ADMIN_ROLES",
    "CONTROL_READ_ROLES",
    "TokenPairResponse",
    "UserCreate",
    "UserRead",
    "auth_validation_exception_handler",
    "bearer_credential",
    "current_principal",
    "get_user_manager",
    "peer_address",
    "register_auth_routes",
    "require_admin",
    "require_control_reader",
    "static_principal",
]
