"""Fresh alpha database fixtures and isolated bootstrap helpers (P01 Foundation).

These fixtures support testing against a clean alpha database without touching
the live database, without requiring legacy migrations or migrations of old
accounts, settings, credentials, or history, and without real provider keys.

Architecture & Scope Note (P01 Foundation):
- The physical database initialized by `create_alpha_test_db` conforms to the
  current SQLite schema at Alembic head (`0007_project_settings`), where
  accounts, projects, project memberships, system/project role assignments, and
  typed system/project settings are persisted in their dedicated tables.
- `bootstrap_fresh_alpha` idempotently seeds the single internal installation account,
  provisions an ordinary human administrator, assigns `system_admin`, and
  atomically creates the default project with the administrator as `project_admin`.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final
from uuid import UUID, uuid4

from fastapi_users.password import PasswordHelper
from pydantic import AwareDatetime

from freesearch.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    DEFAULT_TOKEN_LIFETIME_DAYS,
    PROJECT_TOKEN_PREFIX,
    BuiltinRole,
    HumanPrincipal,
    PermissionAction,
    ProjectContext,
    ProjectCreate,
    ProjectRead,
    ProjectStatus,
    ProjectTokenIssueResponse,
    ProjectTokenRead,
    RoleAssignmentRead,
)
from freesearch.persistence.database_migrations import upgrade_database, validate_database_schema
from freesearch.persistence.projects import (
    ProjectRepository,
    bootstrap_fresh_installation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow

#: Default password for bootstrap administrative user in isolated test fixtures.
ALPHA_ADMIN_PASSWORD: Final[str] = "AlphaAdmin123!SecureKey"


@dataclass(frozen=True)
class AlphaBootstrapResult:
    """Outcome of an isolated fresh-alpha database bootstrap.

    Persists physical records for installation account, administrator, default project,
    membership, and role assignments.
    """

    database_path: Path
    repository: SQLiteRepository
    account_id: UUID
    admin_user: UserRow
    admin_principal: HumanPrincipal
    default_project: ProjectRead
    system_role_assignment: RoleAssignmentRead
    project_admin_context: ProjectContext


async def create_alpha_test_db(db_path: Path) -> SQLiteRepository:
    """Initialize a fresh SQLite database at Alembic head and validate its schema.

    Safety Guarantee:
    - Never unlinks or overwrites an existing database file.
    - If db_path exists, raises FileExistsError to protect production and test assets.
    - Must be provided a fresh, non-existent temporary path.
    """
    if db_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing database at {db_path}. "
            "Alpha test fixtures must provide a fresh, non-existent database path."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    upgrade_database(db_path)
    validate_database_schema(db_path)
    return await SQLiteRepository.open(db_path)


@asynccontextmanager
async def alpha_test_db_context() -> AsyncIterator[tuple[Path, SQLiteRepository]]:
    """Context manager providing an isolated temporary alpha database with safe cleanup."""
    with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "fresh_alpha_test.db"
        repo = await create_alpha_test_db(db_path)
        try:
            yield db_path, repo
        finally:
            await repo.close()


async def seed_alpha_system_admin(
    repository: SQLiteRepository,
    *,
    email: str = "admin@freesearch.local",
    password: str = ALPHA_ADMIN_PASSWORD,
) -> tuple[UserRow, HumanPrincipal]:
    """Seed the initial system administrator in a fresh alpha database.

    Persists into current `user` table at migration head as an ordinary human
    account without legacy role/superuser flags. Authority is granted via
    system_role_assignments.
    """
    helper = PasswordHelper()
    hashed = helper.hash(password)

    async with repository.session() as session:
        database = UserDatabase(session, UserRow)
        user = await database.create(
            {
                "email": email,
                "hashed_password": hashed,
                "is_active": True,
                "is_superuser": False,
                "is_verified": True,
            }
        )
        await session.commit()
        await session.refresh(user)

    principal = HumanPrincipal(user_id=user.id, session_id=uuid4())
    return user, principal


def build_alpha_project(
    *,
    account_id: UUID,
    created_by: UUID,
    name: str = "Default Alpha Project",
    slug: str = "default",
    initial_admin_user_id: UUID | None = None,
) -> ProjectRead:
    """Build an in-memory ProjectRead model for alpha bootstrap.

    Validates that the project create specification includes an atomic initial admin.
    """
    admin_id = initial_admin_user_id or created_by
    # Validate contract model
    ProjectCreate(name=name, slug=slug, initial_admin_user_id=admin_id)

    return ProjectRead(
        id=uuid4(),
        account_id=account_id,
        name=name,
        slug=slug,
        status=ProjectStatus.ACTIVE,
        created_by=created_by,
        created_at=datetime.now(UTC),
        version=1,
    )


def build_alpha_project_token(
    *,
    project_id: UUID,
    created_by: UUID,
    label: str = "Default Alpha Token",
    scopes: frozenset[str] = frozenset(
        {PermissionAction.SEARCH_EXECUTE.value, PermissionAction.FETCH_EXECUTE.value}
    ),
    expires_at: AwareDatetime | None = None,
    no_expiration: bool = False,
) -> tuple[ProjectTokenIssueResponse, str]:
    """Generate an in-memory project token pair: plaintext secret and hashed verifier.

    Returns the (ProjectTokenIssueResponse, sha256_hash).
    """
    raw_secret_suffix = secrets.token_urlsafe(32)
    token_secret = f"{PROJECT_TOKEN_PREFIX}{raw_secret_suffix}"
    secret_hash = hashlib.sha256(token_secret.encode("utf-8")).hexdigest()

    effective_expires_at: AwareDatetime | None
    if not no_expiration and expires_at is None:
        effective_expires_at = datetime.now(UTC) + timedelta(days=DEFAULT_TOKEN_LIFETIME_DAYS)
    else:
        effective_expires_at = expires_at

    prefix_segment = token_secret[len(PROJECT_TOKEN_PREFIX) : len(PROJECT_TOKEN_PREFIX) + 6]
    token_read = ProjectTokenRead(
        id=uuid4(),
        project_id=project_id,
        label=label,
        prefix=f"{PROJECT_TOKEN_PREFIX}{prefix_segment}",
        scopes=scopes,
        created_by=created_by,
        created_at=datetime.now(UTC),
        expires_at=effective_expires_at,
        revoked_at=None,
        last_used_at=None,
    )

    issue_response = ProjectTokenIssueResponse(
        token=token_read,
        secret=token_secret,
    )
    return issue_response, secret_hash


async def bootstrap_fresh_alpha(
    db_path: Path,
    *,
    admin_email: str = "admin@freesearch.local",
    admin_password: str = ALPHA_ADMIN_PASSWORD,
    project_name: str = "Default Alpha Project",
) -> AlphaBootstrapResult:
    """Execute complete isolated alpha bootstrap sequence.

    1. Validates and initializes fresh SQLite database without unlinking.
    2. Seeds initial system admin user in the legacy `user` table.
    3. Idempotently provisions internal installation account and assigns system_admin.
    4. Atomically creates default project and assigns admin as project_admin.
    5. Returns AlphaBootstrapResult with persisted entities and project context.
    """
    repository = await create_alpha_test_db(db_path)
    admin_user, admin_principal = await seed_alpha_system_admin(
        repository, email=admin_email, password=admin_password
    )

    account_id = DEFAULT_INSTALLATION_ACCOUNT_ID
    async with repository.session() as session:
        system_role = await bootstrap_fresh_installation(
            session, admin_user.id, account_id=account_id
        )
        repo = ProjectRepository(session)
        default_project, _, _ = await repo.create_project_with_admin(
            account_id=account_id,
            created_by=admin_user.id,
            project_create=ProjectCreate(
                name=project_name,
                slug="default",
                initial_admin_user_id=admin_user.id,
            ),
        )
        await session.commit()

    project_admin_context = ProjectContext(
        account_id=account_id,
        project_id=default_project.id,
        principal=admin_principal,
        effective_permissions=BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_ADMIN].permissions,
        policy_revision=1,
    )

    return AlphaBootstrapResult(
        database_path=db_path,
        repository=repository,
        account_id=account_id,
        admin_user=admin_user,
        admin_principal=admin_principal,
        default_project=default_project,
        system_role_assignment=system_role,
        project_admin_context=project_admin_context,
    )
