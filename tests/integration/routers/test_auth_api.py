"""Real-token auth API tests over HTTP with isolated SQLite (P2, T1/T2/T12 parts).

Every test uses a temporary database, stub adapters, and a generated signing
secret with a cleared settings cache, so tokens are real verified JWTs.
P7 limit suites stay for a later turn: each test keeps registrations and
failed logins far below the attempt caps.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt as pyjwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from fastapi_users.router.common import ErrorCode

from polyweb.configuration.config import get_settings
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserDatabase, UserRow
from polyweb.routers.api import create_app
from tests.fixtures.auth import TEMP_PASSWORD, raw_auth_headers, temp_email
from tests.integration.routers.test_users_transport import _StubAdapter

_ACCESS_LIFETIME = 900
_REFRESH_LIFETIME = 604800

_PROFILE_FIRST_NAME = "Ada"
_PROFILE_LAST_NAME = "Lovelace"


@pytest.fixture
def auth_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point this test at a generated signing secret, restored on cleanup."""

    import secrets as secrets_module

    secret = secrets_module.token_urlsafe(32)
    monkeypatch.setenv("POLYWEB_AUTH_JWT_SECRET", secret)
    get_settings.cache_clear()
    yield secret
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def auth_client(tmp_path: Path, auth_secret: str) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "auth-api.db")
    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        yield client
    await repository.close()


def _username_for(email: str) -> str:
    """Return a unique valid username derived from one fixture email."""

    local = email.split("@")[0].strip().lower()
    return (local[:64] if local else "user") or "user"


def _valid_signup_payload(email: str, password: str = TEMP_PASSWORD) -> dict[str, object]:
    """Return one valid registration body with mandatory profile names."""

    return {
        "email": email,
        "password": password,
        "username": _username_for(email),
        "first_name": _PROFILE_FIRST_NAME,
        "last_name": _PROFILE_LAST_NAME,
    }


def _register(client: TestClient, email: str, password: str = TEMP_PASSWORD):
    return client.post("/auth/register", json=_valid_signup_payload(email, password))


def _login(client: TestClient, email: str, password: str = TEMP_PASSWORD):
    return client.post("/auth/jwt/login", data={"username": email, "password": password})


def _assert_register_field_error(response: Any, field: str) -> None:
    """Assert one /auth/register 422 carries a safe input-free field entry."""

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload, dict)
    detail = payload.get("detail")
    assert isinstance(detail, list) and detail
    matches = [
        entry for entry in detail if isinstance(entry, dict) and entry.get("loc") == ["body", field]
    ]
    assert matches, f"expected field {field!r} in {detail!r}"
    raw = response.text
    assert TEMP_PASSWORD not in raw
    assert '"input"' not in raw
    assert '"ctx"' not in raw
    for entry in detail:
        assert set(entry) == {"loc", "msg", "type"}
        loc = entry["loc"]
        assert isinstance(loc, list) and loc and loc[0] == "body"


def _decode(token: str, secret: str) -> dict:
    return pyjwt.decode(token, secret, algorithms=["HS256"], audience="polyweb:auth")


def _craft(
    secret: str,
    *,
    sub: object,
    sid: object,
    audience: object = ("polyweb:auth",),
    lifetime: int | None = _ACCESS_LIFETIME,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(sub),
        "aud": list(audience),  # type: ignore[arg-type]
        "sid": str(sid),
        "iat": int(now.timestamp()),
    }
    if lifetime is not None:
        payload["exp"] = int((now + timedelta(seconds=lifetime)).timestamp())
    return pyjwt.encode(payload, secret, algorithm="HS256")


def test_register_creates_agent_and_login_returns_verified_pair(
    auth_client: TestClient, auth_secret: str
) -> None:
    email = temp_email("route")

    registered = _register(auth_client, email)

    assert registered.status_code == 201
    body = registered.json()
    assert body["email"] == email.lower()
    # A1: an ordinary account; the projection carries no role or superuser flag.
    assert "role" not in body
    assert "is_superuser" not in body
    assert body["is_active"] is True
    assert body["username"] == _username_for(email)
    assert body["first_name"] == _PROFILE_FIRST_NAME
    assert body["last_name"] == _PROFILE_LAST_NAME
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "hashed_password" not in body

    assert _register(auth_client, email).status_code == 400

    logged_in = _login(auth_client, email)

    assert logged_in.status_code == 200
    pair = logged_in.json()
    assert pair["token_type"] == "bearer"
    assert pair["expires_in"] == _ACCESS_LIFETIME
    assert pair["refresh_expires_in"] == _REFRESH_LIFETIME
    assert logged_in.headers["cache-control"] == "no-store"

    claims = _decode(pair["access_token"], auth_secret)
    assert claims["sub"] == body["id"]
    assert claims["aud"] == ["polyweb:auth"]
    assert claims["sid"]
    remaining = claims["exp"] - int(datetime.now(UTC).timestamp())
    assert 890 <= remaining <= _ACCESS_LIFETIME

    me = auth_client.get("/users/me", headers=raw_auth_headers(pair["access_token"]))

    assert me.status_code == 200
    assert me.json()["id"] == body["id"]
    assert me.json()["username"] == _username_for(email)
    assert me.json()["first_name"] == _PROFILE_FIRST_NAME
    assert me.json()["last_name"] == _PROFILE_LAST_NAME
    assert "hashed_password" not in me.json()


def test_login_accepts_caseblind_email(auth_client: TestClient) -> None:
    email = temp_email("case")

    assert _register(auth_client, email).status_code == 201
    assert _login(auth_client, email.upper()).status_code == 200


@pytest.mark.parametrize("duplicate_username", ["SharedName", "SHAREDNAME"])
def test_registration_rejects_duplicate_username(
    auth_client: TestClient, duplicate_username: str
) -> None:
    """Distinct emails cannot share a username: exact and case-variant both conflict."""

    first_email = temp_email("dup-username-first")
    first_payload = {**_valid_signup_payload(first_email), "username": "SharedName"}
    created = auth_client.post("/auth/register", json=first_payload)
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["username"] == "SharedName"
    assert created_body["first_name"] == _PROFILE_FIRST_NAME
    assert created_body["last_name"] == _PROFILE_LAST_NAME

    second_email = temp_email("dup-username-second")
    second_payload = {**_valid_signup_payload(second_email), "username": duplicate_username}
    conflict = auth_client.post("/auth/register", json=second_payload)
    assert conflict.status_code == 400
    assert conflict.json()["detail"] == ErrorCode.REGISTER_USER_ALREADY_EXISTS.value

    unknown = _login(auth_client, second_email)
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == ErrorCode.LOGIN_BAD_CREDENTIALS.value

    pair = _login(auth_client, first_email)
    assert pair.status_code == 200
    me = auth_client.get("/users/me", headers=raw_auth_headers(pair.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == created_body["id"]
    assert me.json()["email"] == first_email.lower()
    assert me.json()["username"] == "SharedName"
    assert me.json()["first_name"] == _PROFILE_FIRST_NAME
    assert me.json()["last_name"] == _PROFILE_LAST_NAME


def test_registration_rejects_extra_fields_and_bad_email(auth_client: TestClient) -> None:
    """T2-SIGNUP (A1): unknown, role and privilege fields are all rejected."""

    extra_email = temp_email("extra")
    extra = auth_client.post(
        "/auth/register",
        json={**_valid_signup_payload(extra_email), "extra": "agent"},
    )
    _assert_register_field_error(extra, "extra")
    assert _login(auth_client, extra_email).status_code == 400

    flagged_email = temp_email("flagged")
    flagged = auth_client.post(
        "/auth/register",
        json={**_valid_signup_payload(flagged_email), "is_superuser": True},
    )
    _assert_register_field_error(flagged, "is_superuser")
    assert _login(auth_client, flagged_email).status_code == 400

    bad_email = auth_client.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": TEMP_PASSWORD,
            "username": "bad-email-user",
            "first_name": _PROFILE_FIRST_NAME,
            "last_name": _PROFILE_LAST_NAME,
        },
    )
    _assert_register_field_error(bad_email, "email")


async def test_public_registration_creates_each_role_with_safe_projection(
    tmp_path: Path, auth_secret: str
) -> None:
    """T2-SIGNUP (A1): public signup creates an ordinary account with no system role.

    The old contract let a signup request choose admin/developer/agent. Now a
    role request is refused, and the ordinary account that signup does create
    has no system assignment, no project, and no control-plane access.
    """

    from sqlalchemy import func, select

    from polyweb.persistence.projects import ProjectMembershipRow, SystemRoleAssignmentRow

    repository = await SQLiteRepository.open(tmp_path / "auth-signup.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            for role in ("admin", "developer", "agent", "system_admin"):
                email = temp_email(f"public-{role}")
                refused = client.post(
                    "/auth/register",
                    json={**_valid_signup_payload(email), "role": role},
                )
                _assert_register_field_error(refused, "role")
                assert _login(client, email).status_code == 400

            email = temp_email("public-ordinary")
            created = client.post("/auth/register", json=_valid_signup_payload(email))
            assert created.status_code == 201
            body = created.json()
            assert body["email"] == email.lower()
            assert body["username"] == _username_for(email)
            assert body["first_name"] == _PROFILE_FIRST_NAME
            assert body["last_name"] == _PROFILE_LAST_NAME
            assert "role" not in body
            assert "is_superuser" not in body
            assert body["is_active"] is True
            assert body["is_verified"] is False
            assert "access_token" not in body
            assert "refresh_token" not in body
            assert "hashed_password" not in body
            logged_in = _login(client, email)
            assert logged_in.status_code == 200
            headers = raw_auth_headers(logged_in.json()["access_token"])
            me = client.get("/users/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["username"] == _username_for(email)
            assert me.json()["first_name"] == _PROFILE_FIRST_NAME
            assert me.json()["last_name"] == _PROFILE_LAST_NAME
            assert "role" not in me.json()
            assert client.get("/stats", headers=headers).status_code == 403
            assert client.get("/api/v1/projects", headers=headers).json() == []

        async with repository.session() as session:
            assignments = await session.scalar(
                select(func.count()).select_from(SystemRoleAssignmentRow)
            )
            memberships = await session.scalar(
                select(func.count()).select_from(ProjectMembershipRow)
            )
        assert assignments == 0
        assert memberships == 0
    finally:
        await repository.close()


def test_public_registration_rejects_invalid_roles_safely(auth_client: TestClient) -> None:
    """T2-SIGNUP: null, unknown, and uppercase roles return safe HTTP 422."""

    for bad in ("superadmin", "ADMIN", None):
        email = temp_email("bad-role")
        payload = dict(_valid_signup_payload(email))
        payload["role"] = bad
        rejected = auth_client.post("/auth/register", json=payload)
        _assert_register_field_error(rejected, "role")
        assert "superadmin" not in rejected.text
        assert TEMP_PASSWORD not in rejected.text
        assert _login(auth_client, email).status_code == 400


@pytest.mark.parametrize("field", ["username", "first_name", "last_name"])
@pytest.mark.parametrize("case", ["omitted", "null", "empty", "whitespace", "whitespace-tabs"])
def test_registration_profile_fields_reject_missing_null_and_blank(
    auth_client: TestClient, field: str, case: str
) -> None:
    """Signup profile names are mandatory: omitted, null, empty, blank rejected."""

    email = temp_email(f"profile-{field}-{case}")
    payload = dict(_valid_signup_payload(email))
    if case == "omitted":
        del payload[field]
    elif case == "null":
        payload[field] = None
    elif case == "empty":
        payload[field] = ""
    elif case == "whitespace":
        payload[field] = "   "
    else:
        payload[field] = "\t \n "
    response = auth_client.post("/auth/register", json=payload)
    _assert_register_field_error(response, field)
    assert _login(auth_client, email).status_code == 400


@pytest.mark.parametrize(
    "field,max_len",
    [("username", 64), ("first_name", 100), ("last_name", 100)],
)
def test_registration_profile_fields_enforce_max_lengths(
    auth_client: TestClient, field: str, max_len: int
) -> None:
    """Overlong profile names reject with a field error; boundary lengths persist."""

    overlong_email = temp_email(f"overlong-{field}")
    overlong = dict(_valid_signup_payload(overlong_email))
    overlong[field] = "x" * (max_len + 1)
    refused = auth_client.post("/auth/register", json=overlong)
    _assert_register_field_error(refused, field)
    assert _login(auth_client, overlong_email).status_code == 400

    boundary_email = temp_email(f"boundary-{field}")
    boundary = dict(_valid_signup_payload(boundary_email))
    boundary[field] = "y" * max_len
    created = auth_client.post("/auth/register", json=boundary)
    assert created.status_code == 201
    assert created.json()[field] == "y" * max_len
    logged_in = _login(auth_client, boundary_email)
    assert logged_in.status_code == 200
    me = auth_client.get("/users/me", headers=raw_auth_headers(logged_in.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()[field] == "y" * max_len


def test_registration_trims_and_persists_profile_through_login_and_me(
    auth_client: TestClient,
) -> None:
    """Valid padded profile names trim and persist through login, me, and re-login."""

    email = temp_email("trimmed")
    padded_username = f"  {_username_for(email)}  "
    registered = auth_client.post(
        "/auth/register",
        json={
            "email": email,
            "password": TEMP_PASSWORD,
            "username": padded_username,
            "first_name": "  Ada  ",
            "last_name": "\tGrace\n",
        },
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["username"] == _username_for(email)
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Grace"

    logged_in = _login(auth_client, email)
    assert logged_in.status_code == 200
    me = auth_client.get("/users/me", headers=raw_auth_headers(logged_in.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == _username_for(email)
    assert me.json()["first_name"] == "Ada"
    assert me.json()["last_name"] == "Grace"
    assert "hashed_password" not in me.json()

    again = _login(auth_client, email)
    assert again.status_code == 200
    reread = auth_client.get("/users/me", headers=raw_auth_headers(again.json()["access_token"]))
    assert reread.status_code == 200
    assert reread.json()["username"] == _username_for(email)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "admin"),
        ("is_superuser", True),
        ("is_active", False),
        ("is_verified", True),
        ("system_role", "system_admin"),
        ("account_type", "human"),
        ("auth_provider", "workos"),
        ("auth_provider_id", "sso-1"),
        ("extra", "agent"),
    ],
)
def test_registration_rejects_privilege_and_provider_injection_without_account(
    auth_client: TestClient, field: str, value: object
) -> None:
    """Privilege, provider, and unknown fields stay forbidden with no account."""

    email = temp_email(f"inject-{field}")
    payload = dict(_valid_signup_payload(email))
    payload[field] = value
    response = auth_client.post("/auth/register", json=payload)
    _assert_register_field_error(response, field)
    assert TEMP_PASSWORD not in response.text
    if isinstance(value, str):
        assert value not in response.text
    assert _login(auth_client, email).status_code == 400


async def test_legacy_nullable_profile_login_and_read_still_usable(
    tmp_path: Path, auth_secret: str
) -> None:
    """Trusted rows with null or partial profile still log in and read."""

    from fastapi_users.password import PasswordHelper

    repository = await SQLiteRepository.open(tmp_path / "auth-legacy.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            null_email = temp_email("legacy-null")
            partial_email = temp_email("legacy-partial")
            async with repository.session() as session:
                database = UserDatabase(session, UserRow)
                helper = PasswordHelper()
                await database.create_trusted(
                    email=null_email,
                    hashed_password=helper.hash(TEMP_PASSWORD),
                    username=None,
                    first_name=None,
                    last_name=None,
                )
                await database.create_trusted(
                    email=partial_email,
                    hashed_password=helper.hash(TEMP_PASSWORD),
                    username=_username_for(partial_email),
                    first_name=None,
                    last_name=None,
                )

            null_pair = _login(client, null_email)
            assert null_pair.status_code == 200
            null_me = client.get(
                "/users/me",
                headers=raw_auth_headers(null_pair.json()["access_token"]),
            )
            assert null_me.status_code == 200
            assert null_me.json()["username"] is None
            assert null_me.json()["first_name"] is None
            assert null_me.json()["last_name"] is None
            assert "hashed_password" not in null_me.json()

            partial_pair = _login(client, partial_email)
            assert partial_pair.status_code == 200
            partial_me = client.get(
                "/users/me",
                headers=raw_auth_headers(partial_pair.json()["access_token"]),
            )
            assert partial_me.status_code == 200
            assert partial_me.json()["username"] == _username_for(partial_email)
            assert partial_me.json()["first_name"] is None
            assert partial_me.json()["last_name"] is None
    finally:
        await repository.close()


def test_bad_credentials_share_one_generic_error(auth_client: TestClient) -> None:
    email = temp_email("generic")
    assert _register(auth_client, email).status_code == 201

    wrong = _login(auth_client, email, "WrongPass123!x-No")
    unknown = _login(auth_client, temp_email("ghost"), "WrongPass123!x-No")

    assert wrong.status_code == 400
    assert unknown.status_code == 400
    assert wrong.json()["detail"] == ErrorCode.LOGIN_BAD_CREDENTIALS.value
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_users_me_rejects_absent_and_malformed_tokens(auth_client: TestClient) -> None:
    assert auth_client.get("/users/me").status_code == 401

    response = auth_client.get("/users/me", headers={"Authorization": "Token abc"})
    assert response.status_code == 401

    garbage = auth_client.get("/users/me", headers=raw_auth_headers("not-a-token"))
    assert garbage.status_code == 401
    assert garbage.headers["www-authenticate"] == "Bearer"

    forged = auth_client.get(
        "/users/me",
        headers=raw_auth_headers(
            _craft("other-secret-0123456789abcdef01234567", sub=uuid4(), sid=uuid4())
        ),
    )
    assert forged.status_code == 401


def test_users_me_rejects_claim_violations(auth_client: TestClient, auth_secret: str) -> None:
    first = temp_email("first")
    second = temp_email("second")
    assert _register(auth_client, first).status_code == 201
    assert _register(auth_client, second).status_code == 201
    first_pair = _login(auth_client, first).json()
    second_claims = _decode(_login(auth_client, second).json()["access_token"], auth_secret)
    first_claims = _decode(first_pair["access_token"], auth_secret)

    cases = [
        _craft(auth_secret, sub=first_claims["sub"], sid=first_claims["sid"], audience=("other",)),
        _craft(
            "wrong-secret-0123456789abcdef01234567",
            sub=first_claims["sub"],
            sid=first_claims["sid"],
        ),
        _craft(auth_secret, sub=first_claims["sub"], sid=second_claims["sid"]),
        _craft(auth_secret, sub=first_claims["sub"], sid=first_claims["sid"], lifetime=-10),
    ]
    for token in cases:
        assert auth_client.get("/users/me", headers=raw_auth_headers(token)).status_code == 401

    missing_exp = _craft(
        auth_secret, sub=first_claims["sub"], sid=first_claims["sid"], lifetime=None
    )
    assert auth_client.get("/users/me", headers=raw_auth_headers(missing_exp)).status_code == 401


def test_expired_access_renews_only_through_refresh(
    auth_client: TestClient, auth_secret: str
) -> None:
    email = temp_email("expired")
    assert _register(auth_client, email).status_code == 201
    pair = _login(auth_client, email).json()
    claims = _decode(pair["access_token"], auth_secret)

    stale_access = _craft(auth_secret, sub=claims["sub"], sid=claims["sid"], lifetime=-10)
    assert auth_client.get("/users/me", headers=raw_auth_headers(stale_access)).status_code == 401

    renewed = auth_client.post("/auth/jwt/refresh", headers=raw_auth_headers(pair["refresh_token"]))
    assert renewed.status_code == 200
    assert renewed.json()["expires_in"] == _ACCESS_LIFETIME


def test_refresh_rotates_once_and_reuse_kills_family(auth_client: TestClient) -> None:
    email = temp_email("rotate")
    assert _register(auth_client, email).status_code == 201
    first = _login(auth_client, email).json()

    second_response = auth_client.post(
        "/auth/jwt/refresh", headers=raw_auth_headers(first["refresh_token"])
    )
    assert second_response.status_code == 200
    second = second_response.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["refresh_expires_in"] <= first["refresh_expires_in"]
    assert second_response.headers["cache-control"] == "no-store"

    third_response = auth_client.post(
        "/auth/jwt/refresh", headers=raw_auth_headers(second["refresh_token"])
    )
    assert third_response.status_code == 200
    third = third_response.json()
    assert third["refresh_expires_in"] <= second["refresh_expires_in"]

    assert (
        auth_client.post(
            "/auth/jwt/refresh", headers=raw_auth_headers(first["refresh_token"])
        ).status_code
        == 401
    )
    assert (
        auth_client.get("/users/me", headers=raw_auth_headers(third["access_token"])).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/jwt/refresh", headers=raw_auth_headers(third["refresh_token"])
        ).status_code
        == 401
    )


async def test_concurrent_refresh_has_no_grace_interval(tmp_path: Path, auth_secret: str) -> None:
    import asyncio

    from fastapi.security import OAuth2PasswordRequestForm

    from tests.fixtures.auth import auth_service_for

    repository = await SQLiteRepository.open(tmp_path / "auth-race.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            email = temp_email("race")
            assert _register(client, email).status_code == 201
            service = auth_service_for(repository)
            tokens = await service.login(
                OAuth2PasswordRequestForm(username=email, password=TEMP_PASSWORD),
                peer_address="race-probe",
            )
            assert tokens is not None
            raw = tokens.refresh_token.get_secret_value()

            first, second = await asyncio.gather(
                service.rotate_refresh_token(raw), service.rotate_refresh_token(raw)
            )

            assert (first is None) != (second is None)
            assert await service.rotate_refresh_token(raw) is None
            winner = first if first is not None else second
            assert winner is not None
            assert (
                await service.rotate_refresh_token(winner.refresh_token.get_secret_value()) is None
            )
    finally:
        await repository.close()


def test_logout_revokes_current_family_only(auth_client: TestClient) -> None:
    email = temp_email("logout")
    assert _register(auth_client, email).status_code == 201
    first = _login(auth_client, email).json()
    second = _login(auth_client, email).json()

    assert (
        auth_client.post(
            "/auth/jwt/logout", headers=raw_auth_headers(first["access_token"])
        ).status_code
        == 204
    )
    assert (
        auth_client.get("/users/me", headers=raw_auth_headers(first["access_token"])).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/jwt/refresh", headers=raw_auth_headers(first["refresh_token"])
        ).status_code
        == 401
    )
    assert (
        auth_client.get("/users/me", headers=raw_auth_headers(second["access_token"])).status_code
        == 200
    )
    assert (
        auth_client.post(
            "/auth/jwt/refresh", headers=raw_auth_headers(second["refresh_token"])
        ).status_code
        == 200
    )


def test_credentials_work_only_on_their_own_routes(auth_client: TestClient) -> None:
    email = temp_email("separate")
    assert _register(auth_client, email).status_code == 201
    pair = _login(auth_client, email).json()

    assert (
        auth_client.get("/users/me", headers=raw_auth_headers(pair["refresh_token"])).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/jwt/refresh", headers=raw_auth_headers(pair["access_token"])
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/auth/jwt/logout", headers=raw_auth_headers(pair["refresh_token"])
        ).status_code
        == 401
    )
    unknown_refresh = auth_client.post("/auth/jwt/refresh", headers=raw_auth_headers("x" * 43))
    assert unknown_refresh.status_code == 401


async def test_inactive_and_workos_accounts_fail_closed(tmp_path: Path, auth_secret: str) -> None:
    repository = await SQLiteRepository.open(tmp_path / "auth-closed.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            email = temp_email("sleeping")
            assert _register(client, email).status_code == 201
            async with repository.session() as session:
                database = UserDatabase(session, UserRow)
                account = await database.get_by_email(email)
                assert account is not None
                account.is_active = False
                await session.commit()

            sleeping = _login(client, email)
            unknown = _login(client, temp_email("ghost"), "WrongPass123!x-No")

            workos_email = temp_email("workos")
            async with repository.session() as session:
                session.add(
                    UserRow(
                        id=uuid4(),
                        email=workos_email,
                        hashed_password=None,
                        is_active=True,
                        is_verified=False,
                        auth_provider="workos",
                        auth_provider_id="ext-closed-1",
                    )
                )
                await session.commit()

            external = _login(client, workos_email, "WrongPass123!x-No")

            assert sleeping.status_code == 400
            assert unknown.status_code == 400
            assert external.status_code == 400
            assert sleeping.json()["detail"] == ErrorCode.LOGIN_BAD_CREDENTIALS.value
            assert unknown.json()["detail"] == sleeping.json()["detail"]
            assert external.json()["detail"] == sleeping.json()["detail"]
    finally:
        await repository.close()


async def test_users_me_reflects_deactivation(tmp_path: Path, auth_secret: str) -> None:
    repository = await SQLiteRepository.open(tmp_path / "auth-deactivate.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            email = temp_email("cutoff")
            assert _register(client, email).status_code == 201
            pair = _login(client, email).json()
            assert (
                client.get("/users/me", headers=raw_auth_headers(pair["access_token"])).status_code
                == 200
            )
            async with repository.session() as session:
                database = UserDatabase(session, UserRow)
                account = await database.get_by_email(email)
                assert account is not None
                account.is_active = False
                await session.commit()
            assert (
                client.get("/users/me", headers=raw_auth_headers(pair["access_token"])).status_code
                == 401
            )
    finally:
        await repository.close()
