"""Auth HTTP surface: registration, credential pairs, refresh, and logout.

Transport only: request parsing, the two public endpoints, the protected refresh
route, and the current-account read. Policy lives in
:mod:`freesearch.services.users`.

Under Q1 the public endpoints are exactly ``POST /auth/register`` and
``POST /auth/jwt/login``. ``POST /auth/jwt/refresh`` is authenticated by an
opaque refresh credential in the Bearer header and by nothing else. The access
JWT gates ``POST /auth/jwt/logout`` and ``GET /users/me``.

Public registration creates one ordinary human account: no role, account type
or privilege field exists in the request.

Every human dependency here accepts only a verified human session principal. A
project API key never satisfies one: the guard rejects keys outside execution
routes, and :func:`static_principal` ignores any non-human principal.

Two transports answer the same routes. A request with no browser evidence keeps
the programmatic contract: one JSON credential pair and an opaque Bearer refresh
credential. A request with browser evidence keeps the refresh credential in the
strict cookie and receives no refresh value in JSON. Browser evidence exists only
when API composition supplies the operator origin allowlist and the request
passes every check in :mod:`freesearch.infrastructure.browser_auth`. A failed
check returns HTTP 403 before any credential issue or rotation.

Every credential response carries ``Cache-Control: no-store`` and never echoes a
submitted password. A schema failure on an auth route returns one fixed safe
message, so no raw input, hash, or token value can leak through a 422 body.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal, cast

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
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from freesearch.infrastructure.browser_auth import (
    REFRESH_COOKIE_PATH,
    browser_transport,
    clear_refresh_cookie,
    refresh_cookie_deletion_header,
    refresh_credential_from_scope,
    set_refresh_cookie,
    validate_browser_request,
)
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, PermissionAction
from freesearch.models.users import AuthTokens, UserAccount, UserPrincipal
from freesearch.services.authorization import ScopedAuthorizationService, system_query
from freesearch.services.users import (
    AuthConfigurationError,
    AuthService,
    AuthStorageUnavailable,
    LoginRateLimited,
    UserManager,
)

#: Auth routes whose validation failures must not echo submitted credentials.
_AUTH_VALIDATION_PREFIXES = ("/auth/", "/users/me")

_SAFE_VALIDATION_DETAIL = "invalid authentication request"

_BEARER_PREFIX = "bearer "

#: The token URL the OpenAPI Bearer scheme advertises, matching fastapi-users.
_OPENAPI_TOKEN_URL = "auth/jwt/login"


def _publish_bearer_scheme(app: FastAPI) -> None:
    """Publish the Bearer token scheme in the OpenAPI document.

    ``fastapi-users`` publishes this scheme through ``BearerTransport``. The
    whole-application ASGI guard enforces the credential instead of a per-route
    dependency, so the scheme stays documentation and no operation gains a
    second round of credential parsing.
    """

    scheme = OAuth2PasswordBearer(tokenUrl=_OPENAPI_TOKEN_URL, auto_error=False)
    original = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original()
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes[scheme.scheme_name] = jsonable_encoder(
            scheme.model, by_alias=True, exclude_none=True
        )
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


class UserCreate(schemas.CreateUpdateDictModel):
    """Registration body: email and password only.

    ``extra="forbid"`` rejects a role, a privilege or status flag, provider
    fields and any other field with HTTP 422, so no request can ask for
    authority. The password is hidden from the model representation, and the
    accepted rule is enforced by the user manager with a clear message.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(repr=False)


#: Account projection returned by registration and ``GET /users/me``.
UserRead = UserAccount


class TokenPairResponse(BaseModel):
    """Credential pair plus both expiry intervals, in seconds."""

    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int


class BrowserTokenResponse(BaseModel):
    """Browser access projection: the refresh credential stays in its cookie.

    The model has no ``refresh_token`` field, so the response body omits the key
    instead of sending a null value. :class:`TokenPairResponse` stays the
    programmatic shape.
    """

    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int


def _browser_origins(request: Request) -> frozenset[str]:
    """Return the browser origin allowlist of this application, if any.

    Only API composition sets the value. An application without one keeps the
    programmatic contract, so MCP and test compositions gain no cookie behavior.
    """

    origins = getattr(request.app.state, "auth_browser_origins", None)
    return origins if isinstance(origins, frozenset) else frozenset()


def _browser_mode(request: Request) -> bool:
    """Return whether this request is a valid browser transport request."""

    origins = _browser_origins(request)
    if not origins or not browser_transport(request.scope):
        return False
    return validate_browser_request(request.scope, origins)


def _forbidden() -> HTTPException:
    """Return the browser evidence rejection, which carries no request content."""

    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="browser request rejected",
    )


def _require_browser_transport(request: Request) -> bool:
    """Return the browser transport mode, or reject an invalid browser request.

    ``False`` means the request carries no browser evidence, so the handler must
    answer the programmatic contract. An exception means the request does carry
    browser evidence that failed a check, so no credential may leave the server.
    """

    origins = _browser_origins(request)
    if not origins or not browser_transport(request.scope):
        return False
    if not validate_browser_request(request.scope, origins):
        raise _forbidden()
    return True


def _auth_service(request: Request) -> AuthService:
    """Return the composed auth service, or reject an unconfigured app."""

    service = getattr(request.app.state, "auth_service", None)
    if not isinstance(service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account authentication is not configured",
        )
    return service


def _storage_unavailable() -> HTTPException:
    """Return the safe storage rejection of an account route."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="authentication is temporarily unavailable",
    )


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
    """Return the human principal a transport guard already verified, else ``None``.

    A verified project API key principal is not a human principal, so every
    human or control-plane dependency rejects it instead of falling through.
    """

    principal = getattr(request.state, "user", None)
    return principal if isinstance(principal, UserPrincipal) else None


def _unauthenticated(detail: str, *, clear_cookie: bool = False) -> HTTPException:
    """Return the generic HTTP 401, optionally expiring the refresh cookie.

    ``clear_cookie`` is ``True`` only for an authorized-origin browser refresh
    or browser logout request whose cookie failed verification: the browser must
    not keep a credential the server rejected.
    """

    headers = {"WWW-Authenticate": "Bearer"}
    if clear_cookie:
        headers["Set-Cookie"] = refresh_cookie_deletion_header()
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=headers,
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


def _system_authorization(request: Request) -> ScopedAuthorizationService:
    """Return the common live authorization service for one system operation."""

    account_service = _auth_service(request)
    repository = account_service.repository
    if repository is None:
        raise _storage_unavailable()
    return ScopedAuthorizationService(
        repository,
        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
    )


async def _require_system_permission(request: Request, action: PermissionAction) -> UserPrincipal:
    """Return the principal only when live system scope grants ``action``.

    A missing or invalid credential stays HTTP 401. A valid credential without
    the scoped assignment is HTTP 403, and this check runs before any provider
    or persistence side effect. Account-type labels and a stored superuser flag
    are never consulted; the common service reloads durable assignments.
    """

    principal = current_principal(request)
    decision = await _system_authorization(request).authorize(system_query(principal, action))
    if not decision.allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
    return principal


async def require_admin(request: Request) -> UserPrincipal:
    """Require the live system settings-write assignment for a control mutation."""

    return await _require_system_permission(request, PermissionAction.SYSTEM_SETTINGS_WRITE)


async def require_control_reader(request: Request) -> UserPrincipal:
    """Require the live system settings-read assignment for a sanitized read."""

    return await _require_system_permission(request, PermissionAction.SYSTEM_SETTINGS_READ)


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


def _token_response(
    tokens: AuthTokens, response: Response, request: Request
) -> TokenPairResponse | BrowserTokenResponse:
    """Project internal credentials onto the wire shape, uncacheable.

    A browser request receives the access projection and the refresh cookie. A
    programmatic request keeps the JSON pair and receives no cookie.
    """

    response.headers["Cache-Control"] = "no-store"
    access_token = tokens.access_token.get_secret_value()
    if not _browser_mode(request):
        return TokenPairResponse(
            access_token=access_token,
            refresh_token=tokens.refresh_token.get_secret_value(),
            token_type=tokens.token_type,
            expires_in=tokens.expires_in,
            refresh_expires_in=tokens.refresh_expires_in,
        )
    set_refresh_cookie(
        response,
        tokens.refresh_token.get_secret_value(),
        tokens.refresh_expires_in,
    )
    return BrowserTokenResponse(
        access_token=access_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
        refresh_expires_in=tokens.refresh_expires_in,
    )


async def _rotate_refresh(service: AuthService, token: str) -> AuthTokens | None:
    """Rotate one refresh credential, mapping transport failures to HTTP 503."""

    try:
        return await service.rotate_refresh_token(token)
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


def _login_responses() -> dict[int | str, dict[str, object]]:
    return {
        status.HTTP_400_BAD_REQUEST: {"description": "Bad credentials or an inactive account."},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Attempt limit reached."},
    }


def _library_register_route() -> APIRoute:
    """Return the library's generated registration route.

    The route carries the library's request schema, response schema, status code,
    documented errors, and handler, so registration keeps the standard error
    contract without a hand-written copy. The library types its schemas against
    its own base classes, which declare privilege flags; the account contracts
    here deliberately declare none, so both cross this adapter boundary untyped.
    """

    router = get_register_router(get_user_manager, cast(Any, UserRead), cast(Any, UserCreate))
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
        response_model=TokenPairResponse | BrowserTokenResponse,
        responses=_login_responses(),
    )
    async def login(
        request: Request,
        response: Response,
        credentials: Annotated[OAuth2PasswordRequestForm, Depends()],
    ) -> TokenPairResponse | BrowserTokenResponse:
        """Authenticate a local account and issue one session family's credentials."""

        # Reject failed browser evidence before any credential work.
        _require_browser_transport(request)
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
        return _token_response(tokens, response, request)

    @app.post(
        "/auth/jwt/refresh",
        response_model=TokenPairResponse | BrowserTokenResponse,
    )
    async def refresh(
        request: Request, response: Response
    ) -> TokenPairResponse | BrowserTokenResponse:
        """Rotate one refresh credential into exactly one successor pair.

        A browser request presents the strict cookie and receives a replacement
        cookie plus the access projection. A programmatic request presents the
        opaque Bearer credential and keeps the JSON pair.
        """

        browser = _require_browser_transport(request)
        token = (
            refresh_credential_from_scope(request.scope, _browser_origins(request))
            if browser
            else bearer_credential(request)
        )
        if token is None:
            raise _unauthenticated("invalid refresh credential", clear_cookie=browser)
        tokens = await _rotate_refresh(_auth_service(request), token)
        if tokens is None:
            raise _unauthenticated("invalid refresh credential", clear_cookie=browser)
        return _token_response(tokens, response, request)

    @app.delete(REFRESH_COOKIE_PATH, status_code=status.HTTP_204_NO_CONTENT)
    async def cookie_logout(request: Request) -> Response:
        """Revoke the browser session family and expire the refresh cookie.

        The route applies the same Origin, marker, cookie, and live-family checks
        as cookie refresh. It needs no valid access JWT, so a browser can log out
        after its access token expired. The path stays inside the cookie path, so
        no broader cookie scope is necessary."""

        if not _require_browser_transport(request):
            raise _forbidden()
        principal = current_principal(request)
        await _auth_service(request).logout(principal)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.headers["Cache-Control"] = "no-store"
        clear_refresh_cookie(response)
        return response

    @app.post("/auth/jwt/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request) -> Response:
        """Revoke exactly the authenticated current session family."""

        principal = await _access_principal(request)
        await _auth_service(request).logout(principal)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.headers["Cache-Control"] = "no-store"
        return response

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
    "BrowserTokenResponse",
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
