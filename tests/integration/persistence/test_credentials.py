"""P08 persistence: credential/grant schema, constraints, cascades, migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

import polyweb.persistence.database_migrations as migration_module
from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
)
from polyweb.persistence.credentials import (
    CredentialProjectGrantRow,
    CredentialRepository,
    ProviderCredentialRow,
)
from polyweb.persistence.database_migrations import (
    upgrade_database,
    validate_database_schema,
)
from polyweb.persistence.projects import ProjectRow
from polyweb.persistence.users import UserDatabase, UserRow
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha


def _config_for(database: Path) -> Config:
    assert migration_module.__file__ is not None
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(migration_module.__file__).with_name("migrations").resolve()),
    )
    config.attributes["database_path"] = database
    return config


def _credential_row(**overrides: object) -> ProviderCredentialRow:
    payload: dict[str, object] = {
        "id": str(uuid4()),
        "account_id": str(DEFAULT_INSTALLATION_ACCOUNT_ID),
        "provider_type": "tavily",
        "owner_scope": "system",
        "owner_project_id": None,
        "label": f"label-{uuid4().hex[:8]}",
        "auth_mode": "api_key",
        "generation": 1,
        "status": "active",
        "created_by": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "version": 1,
    }
    payload.update(overrides)
    return ProviderCredentialRow(**payload)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_fresh_database_at_head_has_credential_schema(tmp_path: Path) -> None:
    """A fresh database at head validates and exposes both credential tables."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-schema.db")
    try:
        validate_database_schema(boot.database_path)
        async with boot.repository.session() as session:
            assert (
                await session.execute(select(func.count()).select_from(ProviderCredentialRow))
            ).scalar_one() == 0
            assert (
                await session.execute(select(func.count()).select_from(CredentialProjectGrantRow))
            ).scalar_one() == 0
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_owner_scope_check_constraints_reject_inconsistent_rows(
    tmp_path: Path,
) -> None:
    """system+project_id and project+NULL owner rows fail their CHECKs."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-scope-checks.db")
    try:
        admin_id = str(boot.admin_user.id)
        async with boot.repository.session() as session:
            session.add(
                _credential_row(
                    created_by=admin_id,
                    owner_scope="system",
                    owner_project_id=str(boot.default_project.id),
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with boot.repository.session() as session:
            session.add(
                _credential_row(
                    created_by=admin_id,
                    owner_scope="project",
                    owner_project_id=None,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with boot.repository.session() as session:
            session.add(_credential_row(created_by=admin_id, owner_scope="system"))
            session.add(
                _credential_row(
                    created_by=admin_id,
                    owner_scope="project",
                    owner_project_id=str(boot.default_project.id),
                )
            )
            await session.commit()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_grant_on_private_credential_fails_composite_fk(tmp_path: Path) -> None:
    """A grant row can never reference a project-private credential."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-grant-fk.db")
    try:
        async with boot.repository.session() as session:
            private = await CredentialRepository(session).insert_credential(
                account_id=boot.account_id,
                provider_type="exa",
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=boot.default_project.id,
                label="private-one",
                auth_mode="api_key",
                created_by=boot.admin_user.id,
            )
            session.add(
                CredentialProjectGrantRow(
                    credential_id=str(private.id),
                    owner_scope="system",
                    project_id=str(boot.default_project.id),
                    permitted_operations='["search"]',
                    granted_by=str(boot.admin_user.id),
                    created_at="2026-01-01T00:00:00+00:00",
                    version=1,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_live_label_partial_unique_index(tmp_path: Path) -> None:
    """Duplicate live labels conflict only within (vault owner, provider, label)."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-labels.db")
    try:
        async with boot.repository.session() as session:
            other = await UserDatabase(session, UserRow).create(
                {
                    "email": "other-vault@example.test",
                    "hashed_password": "hash",
                    "is_active": True,
                    "is_verified": True,
                }
            )
            await session.commit()
            other_id = str(other.id)

        async def insert(**overrides: object) -> None:
            async with boot.repository.session() as session:
                values: dict[str, object] = {
                    "created_by": str(boot.admin_user.id),
                }
                values.update(overrides)
                owner = values.pop("owner_user_id", str(boot.admin_user.id))
                row = _credential_row(**values)
                session.add(row)
                await session.flush()
                await session.execute(
                    text("UPDATE provider_credentials SET owner_user_id=:owner WHERE id=:id"),
                    {"owner": owner, "id": row.id},
                )
                await session.commit()

        await insert(provider_type="tavily", label="dup", owner_scope="system")
        # Same (account, owner, provider, label) while active: rejected.
        with pytest.raises(IntegrityError):
            await insert(provider_type="tavily", label="dup", owner_scope="system")
        # Same label, other provider: allowed.
        await insert(provider_type="exa", label="dup", owner_scope="system")
        # Same label+provider in another user's vault: allowed.
        await insert(
            provider_type="tavily",
            label="dup",
            owner_scope="system",
            owner_user_id=other_id,
        )
        # Same label again in the other vault: rejected.
        with pytest.raises(IntegrityError):
            await insert(
                provider_type="tavily",
                label="dup",
                owner_scope="system",
                owner_user_id=other_id,
            )

        # After the system row is deleted, its label frees up.
        async with boot.repository.session() as session:
            await session.execute(
                delete(ProviderCredentialRow).where(
                    ProviderCredentialRow.owner_scope == "system",
                    text("owner_user_id = :owner"),
                    ProviderCredentialRow.provider_type == "tavily",
                    ProviderCredentialRow.label == "dup",
                ),
                {"owner": str(boot.admin_user.id)},
            )
            await session.commit()
        await insert(provider_type="tavily", label="dup", owner_scope="system", status="deleted")
        await insert(provider_type="tavily", label="dup", owner_scope="system")
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_project_delete_cascades_private_credentials_and_grants(
    tmp_path: Path,
) -> None:
    """Deleting a project removes its private credentials and grant rows."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-cascade.db")
    try:
        async with boot.repository.session() as session:
            credentials = CredentialRepository(session)
            private = await credentials.insert_credential(
                account_id=boot.account_id,
                provider_type="exa",
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=boot.default_project.id,
                label="private",
                auth_mode="api_key",
                created_by=boot.admin_user.id,
            )
            system = await credentials.insert_credential(
                account_id=boot.account_id,
                provider_type="tavily",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                label="shared",
                auth_mode="api_key",
                created_by=boot.admin_user.id,
            )
            await credentials.upsert_grant(
                credential_id=system.id,
                project_id=boot.default_project.id,
                permitted_operations=frozenset({CredentialOperation.SEARCH}),
                granted_by=boot.admin_user.id,
            )
            await session.commit()
            private_id, system_id = private.id, system.id

        async with boot.repository.session() as session:
            await session.execute(
                delete(ProjectRow).where(ProjectRow.id == str(boot.default_project.id))
            )
            await session.commit()

        async with boot.repository.session() as session:
            credentials = CredentialRepository(session)
            assert (
                await credentials.get_private_credential(
                    account_id=boot.account_id,
                    project_id=boot.default_project.id,
                    credential_id=private_id,
                )
                is None
            )
            assert await credentials.list_grants(credential_id=system_id) == []
            assert (
                await credentials.get_system_credential(
                    account_id=boot.account_id, credential_id=system_id
                )
                is not None
            )
    finally:
        await boot.repository.close()


def test_downgrade_to_base_then_upgrade_restores_head(tmp_path: Path) -> None:
    """The keyless migration refuses an unsafe downgrade and preserves head."""

    database = tmp_path / "p08-roundtrip.db"
    upgrade_database(database)

    with pytest.raises(NotImplementedError, match="cannot be safely downgraded"):
        migration_module.command.downgrade(_config_for(database), "base")
    with sqlite3.connect(database) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "provider_credentials" in tables
    assert "credential_project_grants" in tables

    validate_database_schema(database)
