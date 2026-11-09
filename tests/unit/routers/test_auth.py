"""Unit tests for the auth transport seam without I/O (P2, PLAN Section 11)."""

from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from freesearch.models.projects import ProjectApiKeyPrincipal
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import (
    BrowserTokenResponse,
    TokenPairResponse,
    UserCreate,
    UserRead,
    auth_validation_exception_handler,
    bearer_credential,
    peer_address,
    static_principal,
)


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": headers or [],
        }
    )


def test_bearer_credential_accepts_single_bearer_value() -> None:
    request = _request("/users/me", [(b"authorization", b"Bearer abc123")])

    assert bearer_credential(request) == "abc123"


def test_bearer_credential_rejects_duplicates_and_schemes() -> None:
    duplicated = _request(
        "/users/me",
        [(b"authorization", b"Bearer one"), (b"authorization", b"Bearer two")],
    )
    assert bearer_credential(duplicated) is None
    assert bearer_credential(_request("/users/me", [(b"authorization", b"Token abc")])) is None
    assert bearer_credential(_request("/users/me")) is None
    assert bearer_credential(_request("/users/me", [(b"authorization", b"Bearer ")])) is None


def test_peer_address_uses_actual_peer_only() -> None:
    assert peer_address(_request("/auth/jwt/login")) == "unknown"

    connected = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/jwt/login",
            "headers": [],
            "client": ("10.0.0.9", 5123),
        }
    )
    assert peer_address(connected) == "10.0.0.9"


def test_static_principal_returns_verified_principal_only() -> None:
    assert static_principal(_request("/users/me")) is None

    principal = UserPrincipal(
        id=uuid4(),
        email="unit@example.com",
        session_id=uuid4(),
        is_active=True,
        is_verified=False,
    )
    request = _request("/users/me")
    request.state.user = principal
    assert static_principal(request) is principal

    impostor = _request("/users/me")
    impostor.state.user = "agent"
    assert static_principal(impostor) is None

    # A1/AC5: a verified project API key is never a human principal.
    machine = _request("/users/me")
    machine.state.user = ProjectApiKeyPrincipal(
        api_key_id=uuid4(), project_id=uuid4(), scopes=frozenset({"search.execute"})
    )
    assert static_principal(machine) is None


async def test_auth_validation_errors_hide_credentials() -> None:
    error = RequestValidationError(
        [
            {
                "loc": ("body", "password"),
                "msg": " test password rule",
                "type": "value_error",
                "input": "SubmittedPass123!x",
            }
        ],
        body={"password": "SubmittedPass123!x"},
    )

    response = await auth_validation_exception_handler(_request("/auth/register"), error)

    assert response.status_code == 422
    assert response.body == b'{"detail":"invalid authentication request"}'
    assert b"SubmittedPass123" not in response.body


def test_registration_body_accepts_each_role_with_agent_default() -> None:
    """T2-SIGNUP (A1 replacement): signup carries email and password only.

    The old contract accepted a requested role with an Agent default. Under A1
    the body has no role field at all, so no request can ask for authority.
    """

    created = UserCreate(email="unit@example.com", password="StrongPass123!x-Unit")
    assert set(created.model_dump()) == {"email", "password"}
    assert "role" not in UserCreate.model_fields
    assert "is_superuser" not in UserCreate.model_fields


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "admin"),
        ("role", "agent"),
        ("role", None),
        ("is_superuser", True),
        ("is_superuser", False),
        ("is_active", False),
        ("is_verified", True),
        ("system_role", "system_admin"),
        ("account_type", "human"),
        ("auth_provider", "workos"),
        ("auth_provider_id", "sso-1"),
    ],
)
def test_registration_body_rejects_invalid_roles_and_provider_fields(
    field: str, value: object
) -> None:
    """T2-SIGNUP (A1 replacement): every role, privilege or provider field is a 422."""

    with pytest.raises(ValidationError):
        UserCreate.model_validate(
            {"email": "unit@example.com", "password": "StrongPass123!x-Unit", field: value}
        )


def test_token_pair_response_defaults_to_bearer() -> None:
    pair = TokenPairResponse(
        access_token="access-secret-value",
        refresh_token="refresh-secret-value",
        expires_in=900,
        refresh_expires_in=604800,
    )

    assert pair.token_type == "bearer"
    assert "access-secret-value" not in repr(pair)
    assert "refresh-secret-value" not in repr(pair)


def test_user_read_carries_role_without_hash() -> None:
    """A1 replacement: the account projection has no role, no superuser flag, no hash."""

    read = UserRead(
        id=uuid4(),
        email="unit@example.com",
        is_active=True,
        is_verified=False,
    )

    dumped = read.model_dump()
    assert "hashed_password" not in dumped
    assert "role" not in dumped
    assert "is_superuser" not in dumped
    with pytest.raises(ValidationError):
        UserRead.model_validate({**dumped, "role": "agent"})
    with pytest.raises(ValidationError):
        UserRead.model_validate({**dumped, "is_superuser": False})


def test_browser_token_response_omits_refresh_key() -> None:
    body = BrowserTokenResponse(
        access_token="access-value",
        expires_in=900,
        refresh_expires_in=604800,
    )

    assert body.token_type == "bearer"
    assert body.model_dump() == {
        "access_token": "access-value",
        "token_type": "bearer",
        "expires_in": 900,
        "refresh_expires_in": 604800,
    }
    assert "refresh_token" not in body.model_dump()
    assert "refresh_token" not in body.model_dump_json()
    assert "access-value" not in repr(body)


def test_programmatic_pair_keeps_json_refresh_credential() -> None:
    pair = TokenPairResponse(
        access_token="access-value",
        refresh_token="refresh-value",
        expires_in=900,
        refresh_expires_in=604800,
    )

    assert pair.token_type == "bearer"
    assert pair.model_dump()["refresh_token"] == "refresh-value"


def test_refresh_cookie_helpers_set_strict_scoped_attributes() -> None:
    from starlette.responses import Response

    from freesearch.infrastructure.browser_auth import (
        REFRESH_COOKIE_NAME,
        clear_refresh_cookie,
        set_refresh_cookie,
    )

    issued = Response(content="ok")
    set_refresh_cookie(issued, "opaque-refresh", 604800)
    raw = issued.headers.get("set-cookie", "")

    assert raw.startswith(f"{REFRESH_COOKIE_NAME}=opaque-refresh; ")
    assert "Path=/auth/jwt/refresh" in raw
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "SameSite=Strict" in raw
    assert "Domain=" not in raw

    expired = Response(content="ok")
    clear_refresh_cookie(expired)
    deleted = expired.headers.get("set-cookie", "")

    assert deleted.startswith(f"{REFRESH_COOKIE_NAME}=; ")
    assert "Path=/auth/jwt/refresh" in deleted
    assert "Max-Age=0" in deleted
    assert "HttpOnly" in deleted
    assert "Secure" in deleted
    assert "SameSite=Strict" in deleted
