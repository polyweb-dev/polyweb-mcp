"""Admin provisioning and legacy denial over HTTP with isolated SQLite.

Every test uses a temporary database, stub adapters, and a generated signing
secret. The suite pins T2-PROVISION (authenticated creation of each role with
a safe projection and an unchanged caller session) and T2-DENY-EDIT (the
legacy lookup and role-change routes deny every authenticated caller with
HTTP 403 and change no account and revoke no family).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.configuration.config import get_settings
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    raw_auth_headers,
    temp_email,
)
from tests.integration.routers.test_users_transport import _StubAdapter

_SAFE_FIELDS = {"id", "email", "role", "is_active", "is_superuser", "is_verified"}
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
    """Build Admin, Developer, and Agent accounts with one public registration.

    Only the Admin uses the public route, so the shared peer counter keeps room
    for the provisioning calls of the same test. Developer and Agent rows come
    from the repository directly and then log in over HTTP. Open signup for each
    role is pinned separately in the BDD suite and in test_auth_api.
    """

    from tests.fixtures.auth import create_temp_user

    pairs: dict[str, dict[str, object]] = {}
    admin_email = temp_email("role-admin")
    registered = client.post(
        "/auth/register",
        json={"email": admin_email, "password": TEMP_PASSWORD, "role": "admin"},
    )
    assert registered.status_code == 201
    assert registered.json()["role"] == "admin"
    logged_in = client.post(
        "/auth/jwt/login", data={"username": admin_email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    body = logged_in.json()
    pairs["admin"] = {
        "email": admin_email,
        "id": registered.json()["id"],
        "access": body["access_token"],
        "refresh": body["refresh_token"],
    }
    for role in (UserRole.DEVELOPER, UserRole.AGENT):
        email = temp_email(f"role-{role.value}")
        await create_temp_user(repository, email, role=role)
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        body = logged_in.json()
        me = client.get("/users/me", headers=_headers(body["access_token"]))
        assert me.status_code == 200
        pairs[role.value] = {
            "email": email,
            "id": me.json()["id"],
            "access": body["access_token"],
            "refresh": body["refresh_token"],
        }
    return pairs


def _headers(token: object) -> dict[str, str]:
    assert isinstance(token, str)
    return raw_auth_headers(token)


def test_admin_provision_creates_each_role_with_safe_projection(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-PROVISION: Admin creates each role; response holds only safe fields."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    admin_headers = _headers(pairs["admin"]["access"])

    for role, superuser in (("admin", True), ("developer", False), ("agent", False)):
        email = temp_email(f"provision-{role}")
        created = client.post(
            "/api/v1/users",
            json={"email": email, "password": TEMP_PASSWORD, "role": role},
            headers=admin_headers,
        )
        assert created.status_code == 201
        body = created.json()
        assert set(body.keys()) == _SAFE_FIELDS
        assert body["email"] == email.lower()
        assert body["role"] == role
        assert body["is_active"] is True
        assert body["is_superuser"] is superuser
        assert body["is_verified"] is False
        assert "hashed_password" not in created.text
        assert "access_token" not in created.text
        assert "refresh_token" not in created.text
        assert "set-cookie" not in created.headers
        # The new account signs in with its own role and no project link.
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        me = client.get("/users/me", headers=_headers(logged_in.json()["access_token"]))
        assert me.status_code == 200
        assert me.json()["role"] == role


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
        json={"email": temp_email("provision-self"), "password": TEMP_PASSWORD, "role": "agent"},
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
    """T2-PROVISION: Developer and Agent receive 403; anonymous receives 401."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))

    for role in ("developer", "agent"):
        denied = client.post(
            "/api/v1/users",
            json={
                "email": temp_email(f"blocked-{role}"),
                "password": TEMP_PASSWORD,
                "role": "agent",
            },
            headers=_headers(pairs[role]["access"]),
        )
        assert denied.status_code == 403
        # The denied caller keeps its own live session.
        assert client.get("/users/me", headers=_headers(pairs[role]["access"])).status_code == 200

    assert (
        client.post(
            "/api/v1/users",
            json={"email": temp_email("blocked-anon"), "password": TEMP_PASSWORD, "role": "agent"},
        ).status_code
        == 401
    )


def test_legacy_lookup_and_role_change_deny_every_authenticated_caller(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """T2-DENY-EDIT: legacy routes deny Admin, Developer, and Agent with 403."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    existing = str(pairs["agent"]["id"])
    unknown = str(uuid4())
    own = str(pairs["admin"]["id"])

    for role in ("admin", "developer", "agent"):
        headers = _headers(pairs[role]["access"])
        for target in (existing, unknown, own, "not-a-uuid"):
            denied_get = client.get(f"/api/v1/users/{target}", headers=headers)
            assert denied_get.status_code == 403
            assert denied_get.json() == {"detail": _DENIED_DETAIL}
            denied_patch = client.patch(
                f"/api/v1/users/{target}/role",
                json={"role": "agent"},
                headers=headers,
            )
            assert denied_patch.status_code == 403
            assert denied_patch.json() == {"detail": _DENIED_DETAIL}

    # No denial changed a stored role and no denial revoked a family.
    me = client.get("/users/me", headers=_headers(pairs["agent"]["access"]))
    assert me.status_code == 200
    assert me.json()["role"] == "agent"
    for role in ("admin", "developer", "agent"):
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
            json={"role": "agent"},
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
                "role": "agent",
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

    for bad in ("superadmin", "ADMIN", None):
        rejected = client.post(
            "/api/v1/users",
            json={"email": temp_email("bad-role"), "password": TEMP_PASSWORD, "role": bad},
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
            "role": "agent",
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

    flagged = client.post(
        "/api/v1/users",
        json={
            "email": temp_email("flagged"),
            "password": TEMP_PASSWORD,
            "role": "agent",
            "is_superuser": True,
        },
        headers=headers,
    )
    assert flagged.status_code == 201
    assert flagged.json()["role"] == "agent"
    assert flagged.json()["is_superuser"] is False

    weak = client.post(
        "/api/v1/users",
        json={"email": temp_email("weak"), "password": "short", "role": "agent"},
        headers=headers,
    )
    assert weak.status_code == 400
    assert "short" not in weak.text

    email = temp_email("dup-provision")
    first = client.post(
        "/api/v1/users",
        json={"email": email, "password": TEMP_PASSWORD, "role": "agent"},
        headers=headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/users",
        json={"email": email, "password": TEMP_PASSWORD, "role": "agent"},
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
    headers = _headers(pairs["admin"]["access"])

    big_email = f"{'a' * 5000}@example.com"
    oversize = client.post(
        "/api/v1/users",
        json={"email": big_email, "password": TEMP_PASSWORD, "role": "agent"},
        headers=headers,
    )
    assert oversize.status_code == 413
    assert TEMP_PASSWORD not in oversize.text
