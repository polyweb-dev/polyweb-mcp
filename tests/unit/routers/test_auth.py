"""Unit tests for the auth transport seam without I/O (P2, PLAN Section 11)."""

import json
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from polyweb.models.projects import ProjectApiKeyPrincipal
from polyweb.models.users import UserPrincipal
from polyweb.routers.auth import (
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

    register_response = await auth_validation_exception_handler(_request("/auth/register"), error)

    assert register_response.status_code == 422
    payload = json.loads(register_response.body)
    assert isinstance(payload["detail"], list)
    assert len(payload["detail"]) == 1
    entry = payload["detail"][0]
    assert entry["loc"] == ["body", "password"]
    assert entry["msg"] == " test password rule"
    assert entry["type"] == "value_error"
    # The field-error entry never echoes input, context, or secrets.
    assert set(entry) == {"loc", "msg", "type"}
    assert b"SubmittedPass123" not in register_response.body

    # Other auth paths keep the fixed safe string.
    login_response = await auth_validation_exception_handler(_request("/auth/jwt/login"), error)
    assert login_response.status_code == 422
    assert login_response.body == b'{"detail":"invalid authentication request"}'
    assert b"SubmittedPass123" not in login_response.body


def _valid_signup_payload() -> dict[str, object]:
    return {
        "email": "unit@example.com",
        "password": "StrongPass123!x-Unit",
        "username": "unituser",
        "first_name": "Unit",
        "last_name": "Tester",
    }


def test_registration_body_accepts_each_role_with_agent_default() -> None:
    """T2-SIGNUP: signup carries identity plus mandatory profile names.

    The old contract accepted a requested role with an Agent default. The body
    has no role field at all, so no request can ask for authority; the valid
    request now requires username, first_name, and last_name instead.
    """

    created = UserCreate.model_validate(_valid_signup_payload())
    assert set(created.model_dump()) == {
        "email",
        "password",
        "username",
        "first_name",
        "last_name",
    }
    assert created.username == "unituser"
    assert created.first_name == "Unit"
    assert created.last_name == "Tester"
    assert "role" not in UserCreate.model_fields
    assert "is_superuser" not in UserCreate.model_fields
    assert "auth_provider" not in UserCreate.model_fields
    assert "auth_provider_id" not in UserCreate.model_fields


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

    payload = dict(_valid_signup_payload())
    payload[field] = value
    with pytest.raises(ValidationError):
        UserCreate.model_validate(payload)


@pytest.mark.parametrize("field", ["username", "first_name", "last_name"])
@pytest.mark.parametrize(
    "case,value",
    [
        ("omitted", None),
        ("null", None),
        ("empty", ""),
        ("whitespace", "   "),
        ("whitespace-tabs", "\t \n "),
    ],
)
def test_registration_profile_fields_reject_missing_null_and_blank(
    field: str, case: str, value: object
) -> None:
    """Signup profile names are mandatory: omitted, null, empty, blank rejected."""

    base = _valid_signup_payload()
    if case == "omitted":
        omitted = dict(base)
        del omitted[field]
        with pytest.raises(ValidationError):
            UserCreate.model_validate(omitted)
    else:
        payload = dict(base)
        payload[field] = value
        with pytest.raises(ValidationError):
            UserCreate.model_validate(payload)


@pytest.mark.parametrize(
    "field,max_len",
    [("username", 64), ("first_name", 100), ("last_name", 100)],
)
def test_registration_profile_fields_reject_overlong(field: str, max_len: int) -> None:
    """Overlong profile names are rejected at the documented per-field limit."""

    payload = dict(_valid_signup_payload())
    payload[field] = "x" * (max_len + 1)
    with pytest.raises(ValidationError):
        UserCreate.model_validate(payload)

    payload[field] = "x" * max_len
    assert UserCreate.model_validate(payload).model_dump()[field] == "x" * max_len


def test_registration_profile_fields_trim_surrounding_whitespace() -> None:
    """Valid profile names trim; blank-after-trim is already rejected above."""

    created = UserCreate.model_validate(
        {
            **_valid_signup_payload(),
            "username": "  unituser  ",
            "first_name": "  Unit  ",
            "last_name": "\tTester\n",
        }
    )
    assert created.username == "unituser"
    assert created.first_name == "Unit"
    assert created.last_name == "Tester"


async def test_registration_errors_hide_password_and_invalid_input() -> None:
    """Real signup failures surface as input-free field errors on /auth/register."""

    bad_payload: dict[str, object] = {
        **_valid_signup_payload(),
        "password": "SubmittedPass123!x",
        "username": "   ",
    }
    try:
        UserCreate.model_validate(bad_payload)
    except ValidationError as model_error:
        request_error = RequestValidationError(model_error.errors(), body=bad_payload)
    else:  # pragma: no cover - the payload is invalid by construction
        raise AssertionError("blank username must fail UserCreate validation")

    response = await auth_validation_exception_handler(_request("/auth/register"), request_error)
    assert response.status_code == 422
    payload = json.loads(response.body)
    assert isinstance(payload["detail"], list)
    assert payload["detail"]
    raw = response.body.decode("utf-8")
    assert "SubmittedPass123" not in raw
    for entry in payload["detail"]:
        assert set(entry) == {"loc", "msg", "type"}
        assert entry["loc"][0] == "body"
    assert "input" not in raw
    assert "ctx" not in raw


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

    from polyweb.infrastructure.browser_auth import (
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
