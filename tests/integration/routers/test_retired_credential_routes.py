"""Retired credential routes and vault-owner isolation."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from polyweb.configuration.config import get_settings
from polyweb.models.credentials import CredentialOperation, CredentialOwnerScope
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.credentials import CredentialService
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project


@pytest.mark.asyncio
async def test_retired_routes_and_foreign_vault_key(tmp_path, monkeypatch, auth_secret):
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "vault-route-test-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "key"))
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "retired-routes.db")
    try:
        with TestClient(create_app([], repository=repository)) as client:
            owner = await register_system_admin_login(client, repository, temp_email("vault-owner"))
            other = await register_system_admin_login(client, repository, temp_email("vault-other"))
            owner_headers = raw_auth_headers(owner["access_token"])
            other_headers = raw_auth_headers(other["access_token"])
            base = "/api/v1/account/vault/keys"
            created = client.post(
                base,
                headers=owner_headers,
                json={"provider_type": "tavily", "label": "owner-only", "secret": "owner-secret"},
            )
            assert created.status_code == 201, created.text
            key_id = created.json()["id"]
            async with repository.session() as session:
                defaults = await CredentialRepository(session).list_for_owner(
                    account_id_from_pair(other)
                )
            default_ids = {
                item.credential.provider_type: str(item.credential.id) for item in defaults
            }
            assert len(defaults) == 2
            assert set(default_ids) == {"keenable", "tavily"}
            listed = client.get(base, headers=other_headers)
            assert listed.status_code == 200, listed.text
            assert sorted(
                (
                    item["provider_type"],
                    item["id"],
                    item["auth_mode"],
                    item["label"],
                    item["status"],
                    item["generation"],
                    item["pool_count"],
                )
                for item in listed.json()
            ) == [
                (
                    "keenable",
                    default_ids["keenable"],
                    "keyless",
                    "Keenable keyless",
                    "active",
                    1,
                    1,
                ),
                ("tavily", default_ids["tavily"], "keyless", "Tavily keyless", "active", 1, 1),
            ]
            assert client.post(
                f"{base}/{key_id}/rotate",
                headers=other_headers,
                json={"expected_generation": 1, "secret": "foreign-secret"},
            ).status_code in (403, 404)
            assert client.delete(f"{base}/{key_id}", headers=other_headers).status_code in (
                403,
                404,
            )
            assert client.get(f"{base}/{key_id}/oauth", headers=other_headers).status_code in (
                403,
                404,
            )
            assert (
                next(
                    item
                    for item in client.get(base, headers=owner_headers).json()
                    if item["id"] == key_id
                )["generation"]
                == 1
            )

            project_context = await seed_execution_project(
                repository, user_id=account_id_from_pair(other)
            )
            async with repository.session() as session:
                credentials = CredentialRepository(session)
                assert (
                    await credentials.get_system_credential(
                        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, credential_id=UUID(key_id)
                    )
                    is None
                )
                assert all(
                    item.id != UUID(key_id)
                    for item in await credentials.list_system_credentials(
                        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID
                    )
                )
                await credentials.upsert_grant(
                    credential_id=UUID(key_id),
                    project_id=project_context.project_id,
                    permitted_operations=frozenset({CredentialOperation.SEARCH}),
                    granted_by=account_id_from_pair(owner),
                )
                await ProjectBindingRepository(session).create(
                    project_id=project_context.project_id,
                    credential_id=UUID(key_id),
                    credential_scope=CredentialOwnerScope.SYSTEM,
                    route_label="owner-only",
                    priority=1,
                    created_by=account_id_from_pair(owner),
                )
                await session.commit()
                usable = await CredentialService(
                    repository, client.app.state.secret_store
                ).usable_credential_in_session(
                    session,
                    project_id=project_context.project_id,
                    credential_id=UUID(key_id),
                    operation=CredentialOperation.SEARCH,
                )
                assert usable is not None

            project_base = f"/api/v1/projects/{project_context.project_id}"
            for suffix in ("credentials", "providers", "bindings"):
                response = client.get(f"{project_base}/{suffix}", headers=other_headers)
                assert response.status_code == 200, response.text
                assert key_id not in response.text
                assert "owner-only" not in response.text

            project = "00000000-0000-4000-8000-000000000001"
            pool = "00000000-0000-4000-8000-000000000002"
            system = "/api/v1/system/credentials"
            project_keys = f"/api/v1/projects/{project}/credentials"
            removed = [
                ("GET", system),
                ("POST", system),
                ("POST", f"{system}/{key_id}/rotate"),
                ("DELETE", f"{system}/{key_id}"),
                ("GET", f"{system}/{key_id}/grants"),
                ("PUT", f"{system}/{key_id}/grants/{project}"),
                ("DELETE", f"{system}/{key_id}/grants/{project}"),
                ("GET", f"{system}/{key_id}/oauth"),
                ("POST", f"{system}/{key_id}/oauth/device"),
                ("POST", f"{system}/{key_id}/oauth/poll"),
                ("DELETE", f"{system}/{key_id}/oauth"),
                ("POST", project_keys),
                ("GET", f"{project_keys}/{key_id}"),
                ("POST", f"{project_keys}/{key_id}/rotate"),
                ("DELETE", f"{project_keys}/{key_id}"),
                ("GET", f"{project_keys}/{key_id}/oauth"),
                ("POST", f"{project_keys}/{key_id}/oauth/device"),
                ("POST", f"{project_keys}/{key_id}/oauth/poll"),
                ("DELETE", f"{project_keys}/{key_id}/oauth"),
                ("GET", "/api/v1/system/pools"),
                ("POST", "/api/v1/system/pools"),
                ("GET", f"/api/v1/system/pools/{pool}"),
                ("PATCH", f"/api/v1/system/pools/{pool}"),
                ("GET", f"/api/v1/system/pools/{pool}/links"),
                ("PUT", f"/api/v1/system/pools/{pool}/links/{key_id}"),
                ("DELETE", f"/api/v1/system/pools/{pool}/links/{key_id}"),
                ("GET", f"/api/v1/system/projects/{project}/allocations"),
                ("GET", f"/api/v1/system/projects/{project}/allocations/{pool}"),
                ("PUT", f"/api/v1/system/projects/{project}/allocations/{pool}"),
                ("DELETE", f"/api/v1/system/projects/{project}/allocations/{pool}"),
                ("POST", f"/api/v1/projects/{project}/bindings"),
                ("PATCH", f"/api/v1/projects/{project}/bindings/{pool}"),
                ("DELETE", f"/api/v1/projects/{project}/bindings/{pool}"),
            ]
            for method, path in removed:
                response = client.request(method, path, headers=other_headers, json={})
                assert response.status_code in (404, 405), (method, path, response.status_code)
    finally:
        await repository.close()
        get_settings.cache_clear()
