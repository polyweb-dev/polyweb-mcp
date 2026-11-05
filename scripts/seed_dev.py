#!/usr/bin/env python3
"""Create a disposable freesearch.dev.db for manual project workflow testing.

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

from freesearch.configuration.config import Settings
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from freesearch.infrastructure.secrets import (
    PROVIDER_ENV_VARS,
    ProviderName,
    provider_env_var_names,
)
from freesearch.models.credentials import CredentialCreate, CredentialGrantUpsert
from freesearch.models.projects import BuiltinRole, ProjectCreate, ProjectMemberAdd, ProjectRead
from freesearch.models.providers import BindingCreate, BindingUpdate
from freesearch.models.users import UserPrincipal
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.credentials import CredentialService
from freesearch.services.projects import ProjectService
from freesearch.services.provider_bindings import ProviderBindingService, provider_capability
from freesearch.services.users import AuthService

DEV_DATABASE = "freesearch.dev.db"
# Deliberately public fixture password, for this disposable local database only.
DEV_PASSWORD = "FreeSearchDev123!"
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
            users[0],
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


async def seed_providers(
    repository: SQLiteRepository,
    settings: Settings,
    users: Sequence[UserPrincipal],
    projects: Sequence[tuple[ProjectRead, UserPrincipal]],
    keys: Mapping[ProviderName, SecretStr],
) -> None:
    """Store one shared encrypted credential per provider, grant it, and enable bindings."""

    store = EncryptedDbSecretStore(repository, load_secret_codec(settings))
    credentials = CredentialService(repository, store)
    bindings = ProviderBindingService(repository)
    for priority, (provider, secret) in enumerate(keys.items(), start=1):
        operations = provider_capability(provider.value)
        credential = await credentials.create_system_credential(
            users[0],
            CredentialCreate(provider_type=provider.value, label=f"dev-{provider}", secret=secret),
        )
        for project, administrator in projects:
            await credentials.put_grant(
                users[0],
                credential.id,
                project.id,
                CredentialGrantUpsert(permitted_operations=operations),
            )
            binding = await bindings.create_binding(
                administrator,
                project.id,
                BindingCreate(
                    credential_id=credential.id, route_label=provider.value, priority=priority
                ),
            )
            await bindings.update_binding(
                administrator,
                project.id,
                binding.id,
                BindingUpdate(enabled_operations=operations),
            )


async def seed_database(
    database: Path,
    settings: Settings,
    keys: Mapping[ProviderName, SecretStr],
    password: SecretStr,
) -> list[ProjectRead]:
    """Seed only a new dev database; errors leave it available for diagnosis/removal."""

    if settings.environment != "development":
        raise ValueError("The dev seed requires FREESEARCH_ENVIRONMENT=development.")
    database = reserve_database(database)
    # Do not use resolve_database_path: FREESEARCH_DB may still point at the normal DB.
    async with await SQLiteRepository.open(database) as repository:
        auth = AuthService(settings, repository=repository)
        users = await seed_users(auth, password)
        projects = await seed_projects(ProjectService(repository), users)
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
            os.environ.get("FREESEARCH_DEV_PASSWORD")
            or values.get("FREESEARCH_DEV_PASSWORD")
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
    print("Set FREESEARCH_DB=freesearch.dev.db in .env, then restart the API and MCP.")
    print("Login password: docs/development-database.md, or your FREESEARCH_DEV_PASSWORD override.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
