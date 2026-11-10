"""Project pool projection and membership isolation against SQLite."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from polyweb.configuration.config import get_settings
from polyweb.models.projects import ProjectMemberAdd
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserRow
from polyweb.routers.api import create_app
from polyweb.services.pool_budget import reserve
from polyweb.services.projects import ProjectService
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
    temp_principal,
)
from tests.fixtures.execution import seed_execution_project, suspend_execution_member


@pytest.mark.asyncio
@pytest.mark.parametrize("budgeted", [True, False], ids=["budgeted", "unlimited"])
async def test_project_pools_member_access_and_secret_isolation(
    tmp_path, monkeypatch, auth_secret, budgeted
):
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "project-pool-test-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "vault-key"))
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "project-pools.db")
    try:
        with TestClient(create_app([], repository=repository)) as client:
            owner_email = temp_email("pool-owner")
            owner = await register_system_admin_login(client, repository, owner_email)
            member = register_and_login(client, temp_email("pool-member"))
            outsider = register_and_login(client, temp_email("pool-outsider"))
            owner_id = account_id_from_pair(owner)
            member_id = account_id_from_pair(member)
            project = await seed_execution_project(repository, user_id=owner_id)
            async with repository.session() as session:
                user = await session.get(UserRow, owner_id)
                assert user is not None
                user.username = "pool-owner"
                user.first_name = "Pool"
                user.last_name = "Owner"
                actor = temp_principal(user)
                await session.commit()
            await ProjectService(repository).add_member(
                actor, project.project_id, ProjectMemberAdd(user_id=member_id, permissions=0)
            )
            owner_headers = raw_auth_headers(owner["access_token"])
            member_headers = raw_auth_headers(member["access_token"])
            outsider_headers = raw_auth_headers(outsider["access_token"])
            path = f"/api/v1/projects/{project.project_id}/pools"
            assert client.get(path, headers=member_headers).json() == []

            secret = "project-pool-secret-never-exposed"
            key = client.post(
                "/api/v1/account/vault/keys",
                headers=owner_headers,
                json={
                    "provider_type": "exa",
                    "label": "Source key",
                    "secret": secret,
                    "overcommit": False,
                },
            )
            assert key.status_code == 201, key.text
            body = {
                "label": "Project pool",
                "project_id": str(project.project_id),
                "rate": {"limit": None if budgeted else 42, "window_seconds": 120},
                "budget": {"limit": 12.345678, "period": "week"} if budgeted else None,
                "operations": ["search"],
            }
            created = client.post(
                f"/api/v1/account/vault/keys/{key.json()['id']}/pools",
                headers=owner_headers,
                json=body,
            )
            assert created.status_code == 201, created.text
            if budgeted:
                async with repository.session() as session:
                    assert await reserve(session, UUID(created.json()["id"]), 1234567)
                    await session.commit()
            response = client.get(path, headers=member_headers)
            assert response.status_code == 200, response.text
            assert response.json() == [
                {
                    "pool_id": created.json()["id"],
                    "label": "Project pool",
                    "provider_type": "exa",
                    "key_label": "Source key",
                    "owner": {
                        "user_id": str(owner_id),
                        "email": owner_email,
                        "username": "pool-owner",
                        "first_name": "Pool",
                        "last_name": "Owner",
                    },
                    "rate": body["rate"],
                    "budget": body["budget"],
                    "budget_used": 1.234567 if budgeted else 0,
                    "operations": ["search"],
                    "operation_limits": None,
                    "overcommit": False,
                }
            ]
            assert secret not in response.text
            assert key.json()["id"] not in response.text
            async with repository.session() as session:
                legacy = await session.get(UserRow, owner_id)
                assert legacy is not None
                legacy.username = None
                legacy.first_name = None
                legacy.last_name = None
                await session.commit()
            legacy_response = client.get(path, headers=member_headers)
            assert legacy_response.status_code == 200, legacy_response.text
            assert legacy_response.json() == [
                {
                    "pool_id": created.json()["id"],
                    "label": "Project pool",
                    "provider_type": "exa",
                    "key_label": "Source key",
                    "owner": {
                        "user_id": str(owner_id),
                        "email": owner_email,
                        "username": None,
                        "first_name": None,
                        "last_name": None,
                    },
                    "rate": body["rate"],
                    "budget": body["budget"],
                    "budget_used": 1.234567 if budgeted else 0,
                    "operations": ["search"],
                    "operation_limits": None,
                    "overcommit": False,
                }
            ]
            assert client.get(path, headers=outsider_headers).status_code == 404
            assert (
                client.get(f"/api/v1/projects/{uuid4()}/pools", headers=member_headers).status_code
                == 404
            )
            await suspend_execution_member(
                repository, project_id=project.project_id, user_id=member_id
            )
            assert client.get(path, headers=member_headers).status_code == 404
    finally:
        await repository.close()
        get_settings.cache_clear()
