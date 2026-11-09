#!/usr/bin/env python3
"""Create a disposable polyweb.dev.db for manual project workflow testing.

Run from the repository root: uv run python scripts/seed_dev.py
Existing files are never overwritten. Stop the backend and delete the dev DB
before recreating it. Provider keys are imported into the encrypted vault;
this script never contacts providers or changes the application's key resolver.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import SecretStr

from polyweb.configuration.config import Settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.infrastructure.secrets import (
    PROVIDER_ENV_VARS,
    ProviderName,
    provider_env_var_names,
)
from polyweb.models.project_permissions import STANDARD
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    CredentialOwnerScope,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectRead,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.credentials import credential_secret_slot
from polyweb.services.pool_materializer import materialize_pools
from polyweb.services.projects import ProjectService
from polyweb.services.provider_bindings import provider_capability
from polyweb.services.users import AuthService

DEV_DATABASE = "polyweb.dev.db"
# Deliberately public fixture password, for this disposable local database only.
DEV_PASSWORD = "PolywebDev123!"
USER_EMAILS = (
    "admin1@example.com",
    "admin2@example.com",
    "user1@example.com",
    "user2@example.com",
    "user3@example.com",
)
# User indices: first member is the initial admin; all listed admins get that role.
PROJECTS = (
    ("Alpha - Shared team", "alpha", (0, 1), (2, 3)),
    ("Beta - Single admin", "beta", (1,), (2, 3, 4)),
    ("Gamma - Admins only", "gamma", (0, 1), ()),
)


def read_provider_keys(env_file: Path) -> dict[ProviderName, SecretStr]:
    """Read import-only keys, with process values taking precedence over the file."""

    values = dotenv_values(env_file, interpolate=False)
    keys: dict[ProviderName, SecretStr] = {}
    for provider in PROVIDER_ENV_VARS:
        for name in provider_env_var_names(provider):
            value = os.environ.get(name, values.get(name))
            if value and value.strip():
                keys[provider] = SecretStr(value.strip())
                break
    return keys


def reserve_database(database: Path) -> Path:
    """Exclusively reserve the dev filename, ignoring the runtime DB selector."""

    if database.name != DEV_DATABASE or database.is_symlink():
        raise ValueError(f"Only a new {DEV_DATABASE} is allowed; normal databases are protected.")
    database = database.absolute()
    if any(Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")):
        raise FileExistsError("Dev database sidecars exist. Stop the backend before recreating it.")
    # x prevents a concurrent seed from opening or overwriting the same database.
    with database.open("xb"):
        pass
    return database


async def seed_users(auth: AuthService, password: SecretStr) -> list[UserPrincipal]:
    """Create real password hashes and explicit system-admin assignments."""

    users: list[UserPrincipal] = []
    for index, email in enumerate(USER_EMAILS):
        account = await auth.provision_account(email, password)
        if index < 2:
            await auth.grant_system_admin(account.id)
        users.append(
            UserPrincipal(
                id=account.id,
                email=account.email,
                session_id=uuid4(),
                is_active=account.is_active,
                is_verified=account.is_verified,
            )
        )
    return users


async def seed_projects(
    service: ProjectService, users: Sequence[UserPrincipal]
) -> list[tuple[ProjectRead, UserPrincipal]]:
    """Build the membership matrix using each project's own administrator."""

    seeded: list[tuple[ProjectRead, UserPrincipal]] = []
    for name, slug, admins, members in PROJECTS:
        administrator = users[admins[0]]
        project = await service.create_project(
            administrator,
            ProjectCreate(name=name, slug=slug, initial_admin_user_id=administrator.id),
        )
        for index in (*admins[1:], *members):
            role = BuiltinRole.PROJECT_ADMIN if index in admins else BuiltinRole.PROJECT_MEMBER
            await service.add_member(
                administrator,
                project.id,
                ProjectMemberAdd(user_id=users[index].id, initial_role=role),
            )
        seeded.append((project, administrator))
    return seeded


async def seed_permissions(
    repository: SQLiteRepository,
    users: Sequence[UserPrincipal],
    projects: Sequence[tuple[ProjectRead, UserPrincipal]],
) -> None:
    """Give each developer the standard search, fetch, traces and usage bits."""

    async with repository.session() as session:
        members = ProjectRepository(session)
        for (project, _), (_, _, _, indices) in zip(projects, PROJECTS, strict=True):
            for index in indices:
                if not await members.set_member_permissions(project.id, users[index].id, STANDARD):
                    raise ValueError("Seeded project member not found.")
        await session.commit()


async def seed_providers(
    repository: SQLiteRepository,
    settings: Settings,
    users: Sequence[UserPrincipal],
    projects: Sequence[tuple[ProjectRead, UserPrincipal]],
    keys: Mapping[ProviderName, SecretStr],
) -> None:
    """Store admin1's vault keys and assign one pool per provider to Alpha."""

    store = EncryptedDbSecretStore(repository, load_secret_codec(settings))
    project, _ = projects[0]
    for provider, secret in keys.items():
        operations = provider_capability(provider.value)
        async with repository.session() as session:
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider.value,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=users[0].id,
                label=f"dev-{provider}",
                auth_mode="api_key",
                created_by=users[0].id,
            )
            await store.create_slot_in_session(
                session,
                credential_secret_slot(credential.id, credential.generation),
                secret.get_secret_value(),
            )
            await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=project.id,
                provider_type=provider.value,
                created_by=users[0].id,
                values=KeyPoolValues.model_validate(
                    {
                        "label": project.name,
                        "rate_limit": 60,
                        "budget_limit": 20_000_000,
                        "operations": operations,
                    }
                ),
            )
            await session.commit()
    async with repository.session() as session:
        await materialize_pools(session, project_id=project.id)
        await session.commit()


async def seed_database(
    database: Path,
    settings: Settings,
    keys: Mapping[ProviderName, SecretStr],
    password: SecretStr,
) -> list[ProjectRead]:
    """Seed only a new dev database; errors leave it available for diagnosis/removal."""

    if settings.environment != "development":
        raise ValueError("The dev seed requires POLYWEB_ENVIRONMENT=development.")
    database = reserve_database(database)
    # Do not use resolve_database_path: POLYWEB_DB may still point at the normal DB.
    async with await SQLiteRepository.open(database) as repository:
        auth = AuthService(settings, repository=repository)
        users = await seed_users(auth, password)
        projects = await seed_projects(ProjectService(repository), users)
        await seed_permissions(repository, users, projects)
        await seed_providers(repository, settings, users, projects, keys)
        return [project for project, _ in projects]


def main(argv: Sequence[str] | None = None) -> int:
    """Create the dev fixture and report identities and provider names, never secrets."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(DEV_DATABASE))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    if not args.env_file.is_file():
        parser.error("Environment file not found; pass --env-file or run from the repository root.")
    try:
        values = dotenv_values(args.env_file, interpolate=False)
        password = SecretStr(
            os.environ.get("POLYWEB_DEV_PASSWORD")
            or values.get("POLYWEB_DEV_PASSWORD")
            or DEV_PASSWORD
        )
        keys = read_provider_keys(args.env_file)
        # BaseSettings accepts _env_file; the Pydantic MyPy plugin omits it.
        settings = Settings(_env_file=args.env_file)  # type: ignore[call-arg]
        projects = asyncio.run(seed_database(args.database, settings, keys, password))
    except (FileExistsError, ValueError) as error:
        # Validation exceptions can include input; only print our own safe path errors.
        if type(error) in (FileExistsError, ValueError):
            print(f"Dev seed refused: {error}", file=sys.stderr)
        else:
            print("Dev seed failed validation; check local configuration.", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            f"Dev seed failed ({type(error).__name__}); no secret values printed.", file=sys.stderr
        )
        return 1
    print(f"Created {args.database.absolute()}")
    print("Accounts: " + ", ".join(USER_EMAILS))
    for project in projects:
        print(f"Project: {project.name} /p/{project.id}")
    print("Imported providers: " + (", ".join(key.value for key in keys) or "none"))
    print("Missing keys (skipped): " + ", ".join(p.value for p in ProviderName if p not in keys))
    print(
        "Brave Answers has no separate credential/adapter in this runtime; its env key is unused."
    )
    print("Set POLYWEB_DB=polyweb.dev.db in .env, then restart the API and MCP.")
    print("Login password: docs/development-database.md, or your POLYWEB_DEV_PASSWORD override.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
