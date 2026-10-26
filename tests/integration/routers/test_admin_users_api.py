"""Admin provisioning and legacy denial over HTTP with isolated SQLite.

Every test uses a temporary database, stub adapters, and a generated signing
secret. The suite pins T2-PROVISION (authenticated creation of each role with
a safe projection and an unchanged caller session) and T2-DENY-EDIT (the
legacy lookup and role-change routes deny every authenticated caller with
HTTP 403 and change no account and revoke no family).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.configuration.config import get_settings
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    raw_auth_headers,
    temp_email,
)
from tests.integration.routers.test_users_transport import _StubAdapter

#: A1: the one safe account projection; no role and no superuser flag.
_SAFE_FIELDS = {
    "id",
    "email",
    "auth_provider",
    "auth_provider_id",
    "username",
    "first_name",
    "last_name",
    "is_active",
    "is_verified",
}
_DENIED_DETAIL = "account management is not available before project association"


@pytest.fixture
def auth_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point this test at a generated signing secret, restored on cleanup."""

    import secrets as secrets_module

    secret = secrets_module.token_urlsafe(32)
    monkeypatch.setenv("FREESEARCH_AUTH_JWT_SECRET", secret)
    get_settings.cache_clear()
    yield secret
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def admin_app(tmp_path: Path, auth_secret: str) -> tuple[TestClient, SQLiteRepository]:
    repository = await SQLiteRepository.open(tmp_path / "admin-users.db")
    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        yield client, repository
    await repository.close()


async def _accounts(
    client: TestClient, repository: SQLiteRepository
) -> dict[str, dict[str, object]]:
    """Build Admin and Agent accounts with trusted fixture seeding and login.

    Admin and Agent rows are seeded through the trusted fixture path on SQLite
    and then log in over HTTP.
    """

    from tests.fixtures.auth import create_temp_user

    pairs: dict[str, dict[str, object]] = {}
    admin_email = temp_email("role-admin")
    await create_temp_user(repository, admin_email, system_admin=True)
    logged_in = client.post(
        "/auth/jwt/login", data={"username": admin_email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    body = logged_in.json()
    me = client.get("/users/me", headers=_headers(body["access_token"]))
    assert me.status_code == 200
    pairs["admin"] = {
        "email": admin_email,
        "id": me.json()["id"],
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }
    agent_email = temp_email("role-agent")
    await create_temp_user(repository, agent_email)
    logged_in = client.post(
        "/auth/jwt/login", data={"username": agent_email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    body = logged_in.json()
    me = client.get("/users/me", headers=_headers(body["access_token"]))
    assert me.status_code == 200
    pairs["agent"] = {
        "email": agent_email,
        "id": me.json()["id"],
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }
    return pairs


def _headers(token: object) -> dict[str, str]:
    assert isinstance(token, str)
    return raw_auth_headers(token)


async def _system_roles(repository: SQLiteRepository, user_id: str) -> set[str]:
    from sqlalchemy import select

    from freesearch.persistence.projects import SystemRoleAssignmentRow

    async with repository.session() as session:
        rows = await session.execute(
            select(SystemRoleAssignmentRow.role_key).where(
                SystemRoleAssignmentRow.user_id == user_id
            )
        )
        return set(rows.scalars())


def test_admin_provision_creates_each_role_with_safe_projection(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-PROVISION (A1): a system admin provisions one ordinary account only."""

    import asyncio

    client, repository = admin_app
    loop = asyncio.get_event_loop()
    pairs = loop.run_until_complete(_accounts(client, repository))
    admin_headers = _headers(pairs["admin"]["access"])

    email = temp_email("provision-ordinary")
    created = client.post(
        "/api/v1/users",
        json={"email": email, "password": TEMP_PASSWORD},
        headers=admin_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert set(body.keys()) == _SAFE_FIELDS
    assert body["email"] == email.lower()
    assert body["is_active"] is True
    assert body["is_verified"] is False
    assert "hashed_password" not in created.text
    assert "access_token" not in created.text
    assert "refresh_token" not in created.text
    assert "set-cookie" not in created.headers
    # The new account holds no system role and no project membership.
    assert loop.run_until_complete(_system_roles(repository, body["id"])) == set()
    logged_in = client.post("/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD})
    assert logged_in.status_code == 200
    new_headers = _headers(logged_in.json()["access_token"])
    me = client.get("/users/me", headers=new_headers)
    assert me.status_code == 200
    assert set(me.json()) == _SAFE_FIELDS
    assert client.get("/stats", headers=new_headers).status_code == 403
    assert client.get("/api/v1/projects", headers=new_headers).json() == []

    # A requested role, including the old ones, is a 422 and creates nothing.
    for role in ("admin", "developer", "agent", "system_admin"):
        rejected = client.post(
            "/api/v1/users",
            json={
                "email": temp_email(f"provision-{role}"),
                "password": TEMP_PASSWORD,
                "role": role,
            },
            headers=admin_headers,
        )
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": "invalid authentication request"}


def test_provision_keeps_caller_session_and_identity(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-PROVISION: creation changes no caller credential, cookie, or store."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    admin = pairs["admin"]
    admin_headers = _headers(admin["access"])

    created = client.post(
        "/api/v1/users",
        json={"email": temp_email("provision-self"), "password": TEMP_PASSWORD},
        headers=admin_headers,
    )
    assert created.status_code == 201

    assert client.get("/users/me", headers=admin_headers).status_code == 200
    assert (
        client.post("/auth/jwt/refresh", headers=_headers(str(admin["refresh"]))).status_code == 200
    )


def test_non_admin_and_anonymous_cannot_provision(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-PROVISION: Agent receives 403; anonymous receives 401."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))

    for role in ("agent",):
        denied = client.post(
            "/api/v1/users",
            json={
                "email": temp_email(f"blocked-{role}"),
                "password": TEMP_PASSWORD,
            },
            headers=_headers(pairs[role]["access"]),
        )
        assert denied.status_code == 403
        # The denied caller keeps its own live session.
        assert client.get("/users/me", headers=_headers(pairs[role]["access"])).status_code == 200

    assert (
        client.post(
            "/api/v1/users",
            json={"email": temp_email("blocked-anon"), "password": TEMP_PASSWORD},
        ).status_code
        == 401
    )


def test_legacy_lookup_and_role_change_deny_every_authenticated_caller(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-DENY-EDIT: legacy routes deny Admin and Agent with 403."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    existing = str(pairs["agent"]["id"])
    unknown = str(uuid4())
    own = str(pairs["admin"]["id"])

    for role in ("admin", "agent"):
        headers = _headers(pairs[role]["access"])
        for target in (existing, unknown, own, "not-a-uuid"):
            denied_get = client.get(f"/api/v1/users/{target}", headers=headers)
            assert denied_get.status_code == 403
            assert denied_get.json() == {"detail": _DENIED_DETAIL}
            # A1: the legacy role-change route is gone; it can never succeed.
            removed = client.patch(
                f"/api/v1/users/{target}/role",
                json={"role": "admin"},
                headers=headers,
            )
            assert removed.status_code in {403, 404, 405}

    # No request changed a system role and no denial revoked a family.
    loop = asyncio.get_event_loop()
    assert loop.run_until_complete(_system_roles(repository, existing)) == set()
    assert loop.run_until_complete(_system_roles(repository, own)) == {"system_admin"}
    for role in ("admin", "agent"):
        assert client.get("/users/me", headers=_headers(pairs[role]["access"])).status_code == 200
        assert (
            client.post(
                "/auth/jwt/refresh", headers=_headers(str(pairs[role]["refresh"]))
            ).status_code
            == 200
        )


def test_anonymous_and_malformed_credentials_receive_401(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-DENY-EDIT: absent or invalid credentials stay 401 before the denial."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    target = pairs["agent"]["id"]

    assert client.get(f"/api/v1/users/{target}").status_code == 401
    assert (
        client.get(f"/api/v1/users/{target}", headers={"Authorization": "Token abc"}).status_code
        == 401
    )
    assert (
        client.patch(
            f"/api/v1/users/{target}/role",
            json={"role": "admin"},
            headers=raw_auth_headers("not-a-token"),
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/users",
            json={
                "email": temp_email("anon-provision"),
                "password": TEMP_PASSWORD,
            },
        ).status_code
        == 401
    )


def test_provision_rejects_bad_roles_and_unknown_fields(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-SIGNUP: invalid roles and unknown fields return safe HTTP 422."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    headers = _headers(pairs["admin"]["access"])

    for field, bad in (
        ("role", "superadmin"),
        ("role", "ADMIN"),
        ("role", None),
        ("is_superuser", True),
        ("is_active", False),
        ("is_verified", True),
        ("auth_provider", "workos"),
    ):
        rejected = client.post(
            "/api/v1/users",
            json={"email": temp_email("bad-role"), "password": TEMP_PASSWORD, field: bad},
            headers=headers,
        )
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": "invalid authentication request"}
        assert TEMP_PASSWORD not in rejected.text

    widened = client.post(
        "/api/v1/users",
        json={
            "email": temp_email("widen"),
            "password": TEMP_PASSWORD,
            "extra": "agent",
        },
        headers=headers,
    )
    assert widened.status_code == 422
    assert widened.json() == {"detail": "invalid authentication request"}


def test_provision_ignores_privilege_flags_but_fails_weak_and_duplicate(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-SIGNUP: privilege flags cannot widen authority; weak and duplicate fail safely."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    headers = _headers(pairs["admin"]["access"])

    # A1: a privilege flag is now rejected outright instead of silently ignored.
    flagged = client.post(
        "/api/v1/users",
        json={
            "email": temp_email("flagged"),
            "password": TEMP_PASSWORD,
            "is_superuser": True,
        },
        headers=headers,
    )
    assert flagged.status_code == 422

    weak = client.post(
        "/api/v1/users",
        json={"email": temp_email("weak"), "password": "short"},
        headers=headers,
    )
    assert weak.status_code == 400
    assert "short" not in weak.text

    email = temp_email("dup-provision")
    first = client.post(
        "/api/v1/users",
        json={"email": email, "password": TEMP_PASSWORD},
        headers=headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/users",
        json={"email": email, "password": TEMP_PASSWORD},
        headers=headers,
    )
    assert second.status_code == 400


def test_provision_body_above_cap_returns_413(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-PROVISION: a body above 4096 bytes fails with 413 before endpoint work."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    admin_headers = _headers(pairs["admin"]["access"])

    big_email = f"{'a' * 5000}@example.com"
    oversize = client.post(
        "/api/v1/users",
        json={"email": big_email, "password": TEMP_PASSWORD},
        headers=admin_headers,
    )
    assert oversize.status_code == 413
    assert TEMP_PASSWORD not in oversize.text


def test_provision_storage_unavailable_maps_to_503_sanitized(
    admin_app: tuple[TestClient, SQLiteRepository],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storage failure in provision_account maps to 503 without leaking raw details."""
    import asyncio

    from freesearch.services import users as users_service

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    admin_headers = _headers(pairs["admin"]["access"])

    secret_leak = "secret_db_failure_detail_hidden"

    async def _failing_provision(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise users_service.AuthStorageUnavailable(secret_leak)

    monkeypatch.setattr(users_service.AuthService, "provision_account", _failing_provision)

    res = client.post(
        "/api/v1/users",
        json={"email": temp_email("store-fail"), "password": TEMP_PASSWORD},
        headers=admin_headers,
    )
    assert res.status_code == 503
    assert secret_leak not in res.text
    body = res.json()
    assert body.get("detail") == "authentication is temporarily unavailable"
