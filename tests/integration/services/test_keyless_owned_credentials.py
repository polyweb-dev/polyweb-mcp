"""TASK-000065 cloud integration: owned keyless credentials end to end.

CLOUD ONLY — do not run locally. These tests open real SQLite databases,
run Alembic migrations (0007 -> 0008), and exercise VaultKeyService, the
REST vault/pool routers, and pool assignment including cross-user denial.
No provider calls are made: keyless execution needs no vendor secret.
Gate: ``api-integration`` on Woodpecker (root CI ledger owned by orchestrator).
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import CredentialAuthMode
from polyweb.models.projects import CredentialOwnerScope, ProjectCreate
from polyweb.models.vault import KeyPoolCreate, VaultKeyCreate
from polyweb.persistence.credentials import CredentialRepository, ProviderCredentialRow
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_errors import ResourceNotFound
from polyweb.services.credentials import (
    CredentialService,
    CredentialValidationError,
    credential_secret_slot,
)
from polyweb.services.key_pools import KeyPoolService
from polyweb.services.projects import ProjectService
from polyweb.services.vault_keys import VaultKeyService
from tests.fixtures.alpha_fixtures import AlphaBootstrapResult, bootstrap_fresh_alpha
from tests.fixtures.auth import (
    create_temp_user,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
    temp_principal,
)


def _vault_services(
    boot: AlphaBootstrapResult,
) -> tuple[CredentialService, VaultKeyService, EncryptedDbSecretStore]:
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    return CredentialService(boot.repository, store), VaultKeyService(boot.repository, store), store


@pytest.mark.asyncio
async def test_cloud_keyless_vault_create_needs_no_secret_and_persists_owner(
    tmp_path: Path,
) -> None:
    """VaultKeyService creates an owned keyless credential with no secret slot."""

    boot = await bootstrap_fresh_alpha(tmp_path / "keyless-cloud-create.db")
    try:
        admin = temp_principal(boot.admin_user)
        _, vault, store = _vault_services(boot)
        created = await vault.create(
            admin,
            VaultKeyCreate(provider_type="keenable", label="free-tier", auth_mode="keyless"),
        )
        assert created.auth_mode == CredentialAuthMode.KEYLESS.value
        assert created.generation == 1
        async with boot.repository.session() as session:
            row = await session.get(ProviderCredentialRow, str(created.id))
            assert row is not None
            assert row.owner_scope == CredentialOwnerScope.SYSTEM.value
            assert row.owner_user_id == str(admin.id)
            assert row.created_by == str(admin.id)
            slot = await store.get_in_session(session, credential_secret_slot(created.id, 1))
            assert slot is None
            assert await CredentialRepository(session).list_grants(credential_id=created.id) == []
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_cloud_keyless_pool_create_assign_and_unassign(tmp_path: Path) -> None:
    """Owned keyless credential -> pool -> assign -> unassign round trip."""

    boot = await bootstrap_fresh_alpha(tmp_path / "keyless-cloud-pool.db")
    try:
        admin = temp_principal(boot.admin_user)
        _, vault, _ = _vault_services(boot)
        created = await vault.create(
            admin,
            VaultKeyCreate(provider_type="keenable", label="free-tier", auth_mode="keyless"),
        )
        project = await ProjectService(boot.repository).create_project(
            admin,
            ProjectCreate(
                name="Keyless",
                slug=f"keyless-{uuid4().hex[:8]}",
                initial_admin_user_id=admin.id,
            ),
        )
        pools = KeyPoolService(boot.repository)
        pool = await pools.create(
            admin,
            created.id,
            KeyPoolCreate(label="free-tier-pool", project_id=project.id),
        )
        assert pool.provider_type == "keenable"
        assert pool.project_id == project.id
        async with boot.repository.session() as session:
            stored = await KeyPoolRepository(session).list_for_project(project.id)
            assert [item.id for item in stored] == [pool.id]
            await session.commit()
        await pools.assign(admin, pool.id, None)
        async with boot.repository.session() as session:
            assert await KeyPoolRepository(session).list_for_project(project.id) == []
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_cloud_keyless_foreign_user_cannot_copy_or_assign_pool(
    tmp_path: Path,
) -> None:
    """Owner/project isolation: a foreign user is denied on copy and assign."""

    boot = await bootstrap_fresh_alpha(tmp_path / "keyless-cloud-isolation.db")
    try:
        admin = temp_principal(boot.admin_user)
        outsider = temp_principal(await create_temp_user(boot.repository, temp_email("outsider")))
        _, vault, _ = _vault_services(boot)
        created = await vault.create(
            admin,
            VaultKeyCreate(provider_type="tavily", label="free-tier", auth_mode="keyless"),
        )
        pools = KeyPoolService(boot.repository)
        pool = await pools.create(admin, created.id, KeyPoolCreate(label="free-tier-pool"))
        project = await ProjectService(boot.repository).create_project(
            admin,
            ProjectCreate(
                name="Other",
                slug=f"other-{uuid4().hex[:8]}",
                initial_admin_user_id=admin.id,
            ),
        )
        with pytest.raises(AuthorizationDenied):
            await pools.copy(outsider, pool.id, project.id, None)
        with pytest.raises(AuthorizationDenied):
            await pools.assign(outsider, pool.id, project.id)
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_cloud_keyless_unsupported_provider_and_rotation_guards(
    tmp_path: Path,
) -> None:
    """Non-keyless providers reject keyless; keyless rows refuse rotation."""

    boot = await bootstrap_fresh_alpha(tmp_path / "keyless-cloud-guards.db")
    try:
        from polyweb.models.credentials import CredentialRotate

        admin = temp_principal(boot.admin_user)
        credentials, vault, _ = _vault_services(boot)
        with pytest.raises(CredentialValidationError, match="does not support keyless"):
            await vault.create(
                admin, VaultKeyCreate(provider_type="exa", label="nope", auth_mode="keyless")
            )
        created = await vault.create(
            admin,
            VaultKeyCreate(provider_type="keenable", label="free-tier", auth_mode="keyless"),
        )
        with pytest.raises(CredentialValidationError, match="no secret to rotate"):
            await credentials.rotate_system_credential(
                admin,
                created.id,
                CredentialRotate(expected_generation=1, secret=SecretStr("rotation-secret")),
            )
        with pytest.raises(ResourceNotFound):
            await vault.create(
                admin,
                VaultKeyCreate(
                    provider_type="keenable",
                    label="free-tier",
                    auth_mode="keyless",
                    secret=SecretStr("unexpected"),
                ),
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_cloud_keyless_rest_create_without_secret(tmp_path: Path) -> None:
    """POST /api/v1/account/vault/keys accepts a keyless body with no secret."""

    repository = await SQLiteRepository.open(tmp_path / "keyless-cloud-rest.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = await register_system_admin_login(client, repository, temp_email("rest"))
            headers = raw_auth_headers(pair["access_token"])
            response = client.post(
                "/api/v1/account/vault/keys",
                json={"provider_type": "keenable", "label": "free-tier", "auth_mode": "keyless"},
                headers=headers,
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["auth_mode"] == "keyless"
            assert body["generation"] == 1
            listed = client.get("/api/v1/account/vault/keys", headers=headers)
            assert listed.status_code == 200
            assert body["id"] in {key["id"] for key in listed.json()}
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_cloud_0007_populated_upgrade_preserves_and_coexists(
    tmp_path: Path,
) -> None:
    """Populated 0007 DB (public keyless, keyed+pools) upgrades cleanly.

    After upgrade: singleton still unique, existing credentials/pools/slots
    intact, and two users each hold an owned same-provider keyless row.
    """

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    import polyweb.persistence.database_migrations as migration_module
    from polyweb.persistence.database_migrations import validate_database_schema

    database = tmp_path / "keyless-cloud-upgrade.db"
    config = AlembicConfig()
    config.set_main_option(
        "script_location",
        str(Path(migration_module.__file__).with_name("migrations").resolve()),
    )
    config.attributes["database_path"] = database
    alembic_command.upgrade(config, "0007_provider_budget_period")

    repository = await SQLiteRepository.open(database)
    try:
        store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
        vault = VaultKeyService(repository, store)
        from tests.fixtures.alpha_fixtures import seed_alpha_system_admin

        admin_user, _ = await seed_alpha_system_admin(repository, email=temp_email("up"))

        admin = temp_principal(admin_user)
        second = temp_principal(
            await create_temp_user(repository, temp_email("up-two"), system_admin=True)
        )
        keyed = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="exa",
                label="keyed",
                secret=SecretStr("fake-keyless-upgrade-secret"),
            ),
        )
        async with repository.session() as session:
            before_singleton = (
                await session.execute(
                    text(
                        "SELECT id FROM provider_credentials "
                        "WHERE auth_mode='keyless' AND owner_user_id IS NULL "
                        "ORDER BY provider_type"
                    )
                )
            ).all()
            await session.commit()
    finally:
        await repository.close()

    alembic_command.upgrade(config, "head")

    repository = await SQLiteRepository.open(database)
    try:
        validate_database_schema(database)
        store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
        vault = VaultKeyService(repository, store)
        admin = temp_principal(admin_user)
        async with repository.session() as session:
            after_singleton = (
                await session.execute(
                    text(
                        "SELECT id FROM provider_credentials "
                        "WHERE auth_mode='keyless' AND owner_user_id IS NULL "
                        "ORDER BY provider_type"
                    )
                )
            ).all()
            assert after_singleton == before_singleton
            keyed_row = await session.get(ProviderCredentialRow, str(keyed.id))
            assert keyed_row is not None and keyed_row.status == "active"
            await session.commit()
        first = await vault.create(
            admin, VaultKeyCreate(provider_type="keenable", label="mine", auth_mode="keyless")
        )
        other = await vault.create(
            second, VaultKeyCreate(provider_type="keenable", label="mine", auth_mode="keyless")
        )
        assert first.id != other.id
        async with repository.session() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM provider_credentials "
                        "WHERE auth_mode='keyless' AND provider_type='keenable' "
                        "AND owner_user_id IS NOT NULL"
                    )
                )
            ).scalar_one()
            assert count == 2
            await session.commit()
    finally:
        await repository.close()
