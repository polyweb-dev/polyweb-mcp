"""TASK-000065 cloud integration: owned keyless credentials end to end.

CLOUD ONLY — do not run locally. These tests open real SQLite databases,
run Alembic migrations (0007 -> 0008), and exercise VaultKeyService, the
REST vault/pool routers, and pool assignment including cross-user denial.
No provider calls are made: keyless execution needs no vendor secret.
Gate: ``api-integration`` on Woodpecker (root CI ledger owned by orchestrator).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine

from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import CredentialAuthMode
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    ProjectCreate,
)
from polyweb.models.vault import KeyPoolCreate, VaultKeyCreate
from polyweb.persistence.credentials import CredentialRepository, ProviderCredentialRow
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.oauth_grants import oauth_secret_slot
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
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
    register_and_login,
    temp_email,
    temp_principal,
)


def _vault_services(
    boot: AlphaBootstrapResult,
) -> tuple[CredentialService, VaultKeyService, EncryptedDbSecretStore]:
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    return CredentialService(boot.repository, store), VaultKeyService(boot.repository, store), store


def _vault_snapshot(database: Path) -> dict[str, set[tuple[object, ...]]]:
    """Compare persisted vault data, including encrypted slots, across the upgrade."""
    tables = (
        "provider_credentials",
        "key_pools",
        "credential_project_grants",
        "project_provider_bindings",
        "credential_oauth_grants",
        "runtime_settings",
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        return {
            table: set(connection.execute(f"SELECT * FROM {table}").fetchall()) for table in tables
        }


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
            VaultKeyCreate(
                provider_type="keenable", label="free-tier", auth_mode=CredentialAuthMode.KEYLESS
            ),
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
        owner = temp_principal(await create_temp_user(boot.repository, temp_email("creator")))
        project = await ProjectService(boot.repository).create_project(
            owner,
            ProjectCreate(
                name="Keyless",
                slug=f"keyless-{uuid4().hex[:8]}",
                initial_admin_user_id=owner.id,
            ),
        )
        async with boot.repository.session() as session:
            assert (
                await ProjectRepository(session).get_system_role_assignments(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, user_id=owner.id
                )
                == []
            )
        _, vault, _ = _vault_services(boot)
        created = await vault.create(
            owner,
            VaultKeyCreate(
                provider_type="keenable", label="free-tier", auth_mode=CredentialAuthMode.KEYLESS
            ),
        )
        pools = KeyPoolService(boot.repository)
        pool = await pools.create(
            owner,
            created.id,
            KeyPoolCreate(label="free-tier-pool", project_id=project.id),
        )
        assert pool.provider_type == "keenable"
        assert pool.project_id == project.id
        async with boot.repository.session() as session:
            stored = await KeyPoolRepository(session).list_for_project(project.id)
            assert [item.id for item in stored] == [pool.id]
            await session.commit()
        await pools.assign(owner, pool.id, None)
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
        other_project = await ProjectService(boot.repository).create_project(
            outsider,
            ProjectCreate(name="Other", slug=f"other-{uuid4().hex[:8]}"),
        )
        _, vault, _ = _vault_services(boot)
        # The second owner passes the vault gate, so denial must check pool ownership.
        assert await vault.list_keys(outsider) == []
        created = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="tavily", label="free-tier", auth_mode=CredentialAuthMode.KEYLESS
            ),
        )
        pools = KeyPoolService(boot.repository)
        pool = await pools.create(admin, created.id, KeyPoolCreate(label="free-tier-pool"))
        with pytest.raises(ResourceNotFound, match="pool is not available"):
            await pools.copy(outsider, pool.id, other_project.id, None)
        with pytest.raises(ResourceNotFound, match="pool is not available"):
            await pools.assign(outsider, pool.id, other_project.id)
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
        _, vault, store = _vault_services(boot)
        with pytest.raises(CredentialValidationError, match="does not support keyless"):
            await vault.create(
                admin,
                VaultKeyCreate(
                    provider_type="exa", label="nope", auth_mode=CredentialAuthMode.KEYLESS
                ),
            )
        created = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="keenable", label="free-tier", auth_mode=CredentialAuthMode.KEYLESS
            ),
        )
        with pytest.raises(CredentialValidationError, match="no secret to rotate"):
            await vault.rotate(
                admin,
                created.id,
                CredentialRotate(expected_generation=1, secret=SecretStr("rotation-secret")),
            )
        unchanged = next(key for key in await vault.list_keys(admin) if key.id == created.id)
        assert unchanged.generation == 1
        assert await store.get(credential_secret_slot(created.id, 1)) is None
        assert await store.get(credential_secret_slot(created.id, 2)) is None
        with pytest.raises(ValidationError, match="keyless credential needs no secret"):
            VaultKeyCreate(
                provider_type="keenable",
                label="free-tier",
                auth_mode=CredentialAuthMode.KEYLESS,
                secret=SecretStr("unexpected"),
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_cloud_keyless_rest_create_without_secret(tmp_path: Path, auth_secret: str) -> None:
    """POST /api/v1/account/vault/keys accepts a keyless body with no secret."""

    repository = await SQLiteRepository.open(tmp_path / "keyless-cloud-rest.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = register_and_login(client, temp_email("rest"))
            headers = raw_auth_headers(pair["access_token"])
            project = client.post(
                "/api/v1/projects",
                json={"name": "First project", "slug": f"first-{uuid4().hex[:8]}"},
                headers=headers,
            )
            assert project.status_code == 201, project.text
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
    """Upgrade real 0007 data, retaining secrets and allowing distinct keyless owners."""

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

    # Unlike open()/initialize(), this constructor does not migrate the fixture.
    repository = SQLiteRepository(
        create_async_engine(URL.create("sqlite+aiosqlite", database=str(database)))
    )
    codec = SecretCodec(MasterKey(os.urandom(32)))
    # Freeze the pre-0008 public singleton identity rather than minting an arbitrary row.
    # Historical materialization inserts by this UUID5 and ignores conflicts on id only.
    singleton_id = uuid5(NAMESPACE_URL, "polyweb:keyless-credential:keenable")
    try:
        store = EncryptedDbSecretStore(repository, codec)
        vault = VaultKeyService(repository, store)
        admin = temp_principal(
            await create_temp_user(repository, temp_email("up"), system_admin=True)
        )
        second = temp_principal(
            await create_temp_user(repository, temp_email("up-two"), system_admin=True)
        )
        # Explicit legacy data: public dispatch is no longer implicitly seeded by projects.
        async with repository.session() as session:
            await session.execute(
                text(
                    "INSERT INTO provider_credentials "
                    "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
                    "created_by,created_at,updated_at,version,owner_user_id) "
                    "VALUES (:id,:account,'keenable','system','public-keenable','keyless',"
                    "1,'active',NULL,:now,:now,1,NULL)"
                ),
                {
                    "id": str(singleton_id),
                    "account": str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                    "now": datetime.now(UTC).isoformat(),
                },
            )
            await session.commit()
        keyed = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="exa",
                label="keyed",
                secret=SecretStr("fake-keyless-upgrade-secret"),
            ),
        )
        oauth = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel", label="oauth", auth_mode=CredentialAuthMode.OAUTH
            ),
        )
        access_slot = oauth_secret_slot(oauth.id, "access", 1)
        async with repository.session() as session:
            await session.execute(
                text(
                    "INSERT INTO credential_oauth_grants "
                    "(credential_id,auth_mode,credential_generation,token_generation,status,"
                    "updated_at,version) VALUES (:id,'oauth',1,1,'connected',:now,1)"
                ),
                {"id": str(oauth.id), "now": datetime.now(UTC).isoformat()},
            )
            await store.create_slot_in_session(session, access_slot, "fake-upgrade-access-token")
            await session.commit()
        project = await ProjectService(repository).create_project(
            admin, ProjectCreate(name="Preserved", slug=f"preserved-{uuid4().hex[:8]}")
        )
        await KeyPoolService(repository).create(
            admin, keyed.id, KeyPoolCreate(label="preserved-pool", project_id=project.id)
        )
    finally:
        await repository.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0007_provider_budget_period",
        )
        assert connection.execute(
            "SELECT id FROM provider_credentials WHERE auth_mode='keyless' "
            "AND provider_type='keenable' AND owner_user_id IS NULL"
        ).fetchall() == [(str(singleton_id),)]
    before = _vault_snapshot(database)
    assert before["key_pools"]
    assert before["credential_oauth_grants"]
    assert len(before["runtime_settings"]) >= 2
    alembic_command.upgrade(config, "head")
    assert _vault_snapshot(database) == before

    repository = await SQLiteRepository.open(database)
    try:
        validate_database_schema(database)
        store = EncryptedDbSecretStore(repository, codec)
        vault = VaultKeyService(repository, store)
        assert await store.get(credential_secret_slot(keyed.id, 1)) == "fake-keyless-upgrade-secret"
        assert await store.get(access_slot) == "fake-upgrade-access-token"
        first = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="keenable", label="mine", auth_mode=CredentialAuthMode.KEYLESS
            ),
        )
        other = await vault.create(
            second,
            VaultKeyCreate(
                provider_type="keenable", label="mine", auth_mode=CredentialAuthMode.KEYLESS
            ),
        )
        assert first.id != other.id
        async with repository.session() as session:
            owners = (
                (
                    await session.execute(
                        text(
                            "SELECT owner_user_id FROM provider_credentials "
                            "WHERE auth_mode='keyless' AND provider_type='keenable' "
                            "AND owner_user_id IS NOT NULL"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert set(owners) == {str(admin.id), str(second.id)}
            for credential in (first, other):
                assert (
                    await store.get_in_session(session, credential_secret_slot(credential.id, 1))
                    is None
                )
            await session.commit()
    finally:
        await repository.close()
    before_refused_downgrade = _vault_snapshot(database)
    with sqlite3.connect(database) as connection:
        schema_before = set(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master"))
        revision_before = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision_before == ("0008_owned_keyless_credentials",)
    with pytest.raises(NotImplementedError, match="owned keyless credentials cannot be downgraded"):
        alembic_command.downgrade(config, "0007_provider_budget_period")
    # A rejected rollback must not rebuild tables, change the index/CHECK, or lose vault data.
    assert _vault_snapshot(database) == before_refused_downgrade
    with sqlite3.connect(database) as connection:
        assert set(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master")) == (
            schema_before
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            revision_before
        )
    validate_database_schema(database)
    with (
        sqlite3.connect(database) as connection,
        pytest.raises(sqlite3.IntegrityError, match=r"provider_credentials\.account_id"),
    ):
        connection.execute(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version,owner_user_id) "
            "VALUES (?,?,'keenable','system','duplicate-public','keyless',"
            "1,'active',NULL,'now','now',1,NULL)",
            (str(uuid4()), str(DEFAULT_INSTALLATION_ACCOUNT_ID)),
        )
