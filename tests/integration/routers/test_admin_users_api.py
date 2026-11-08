"""Removed global account endpoints over isolated SQLite."""

from __future__ import annotations

from pathlib import Path
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


def test_global_account_list_and_creation_are_removed(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """Even a system administrator cannot access the removed endpoints."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    headers = _headers(pairs["admin"]["access"])
    assert client.get("/api/v1/users", headers=headers).status_code in {404, 405}
    assert client.post("/api/v1/users", headers=headers, json={}).status_code in {404, 405}
    assert "/api/v1/users" not in client.get("/openapi.json").json()["paths"]


def test_legacy_account_routes_are_removed_for_authenticated_callers(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """Removed account routes cannot change users, roles, or sessions."""

    import asyncio

    client, repository = admin_app
    pairs = asyncio.get_event_loop().run_until_complete(_accounts(client, repository))
    existing = str(pairs["agent"]["id"])
    unknown = str(uuid4())
    own = str(pairs["admin"]["id"])

    for role in ("admin", "agent"):
        headers = _headers(pairs[role]["access"])
        for target in (existing, unknown, own, "not-a-uuid"):
            assert client.get(f"/api/v1/users/{target}", headers=headers).status_code in {404, 405}
            assert client.post(
                f"/api/v1/users/{target}/deactivate", headers=headers
            ).status_code in {404, 405}
            assert client.patch(
                f"/api/v1/users/{target}/role", json={"role": "admin"}, headers=headers
            ).status_code in {404, 405}

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/users/me" in paths
    assert "/api/v1/users/{user_id}" not in paths
    assert "/api/v1/users/{user_id}/deactivate" not in paths
    assert "/api/v1/users/{user_id}/role" not in paths

    # No request changed a system role or revoked a family.
    loop = asyncio.get_event_loop()
    assert loop.run_until_complete(_system_roles(repository, existing)) == set()
    assert loop.run_until_complete(_system_roles(repository, own)) == {"system_admin"}
    for role in ("admin", "agent"):
        headers = _headers(pairs[role]["access"])
        me = client.get("/users/me", headers=headers)
        versioned_me = client.get("/api/v1/users/me", headers=headers)
        assert me.status_code == versioned_me.status_code == 200
        assert me.json() == versioned_me.json()
        assert (
            client.post(
                "/auth/jwt/refresh", headers=_headers(str(pairs[role]["refresh"]))
            ).status_code
            == 200
        )


def test_anonymous_and_malformed_credentials_receive_401(
    admin_app: tuple[TestClient, SQLiteRepository],
) -> None:
    """The authentication guard still rejects absent or malformed credentials."""

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
