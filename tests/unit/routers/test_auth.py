"""Unit tests for the auth transport seam without I/O (P2, PLAN Section 11)."""

from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from freesearch.models.users import UserPrincipal, UserRole
from freesearch.routers.auth import (
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
        role=UserRole.AGENT,
        session_id=uuid4(),
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    request = _request("/users/me")
    request.state.user = principal
    assert static_principal(request) is principal

    impostor = _request("/users/me")
    impostor.state.user = "agent"
    assert static_principal(impostor) is None


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


def test_registration_body_rejects_roles_and_provider_fields() -> None:
    with pytest.raises(ValidationError):
        UserCreate(
            email="unit@example.com",
            password="StrongPass123!x-Unit",
            role="admin",  # type: ignore[call-arg]
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
    read = UserRead(
        id=uuid4(),
        email="unit@example.com",
        is_active=True,
        is_superuser=False,
        is_verified=False,
        role=UserRole.AGENT,
    )

    assert read.role is UserRole.AGENT
    assert "hashed_password" not in read.model_dump()
