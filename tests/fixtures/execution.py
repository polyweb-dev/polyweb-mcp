"""Execution-scope test fixtures: projects, memberships, and attributions (P04).

Two layers of helpers share one contract:

* Pure contract/unit tests that never reach the execution boundary use
  :data:`EXECUTION_PROJECT_ID` and :func:`test_attribution` — placeholder
  identities that satisfy the required request/attribution fields without any
  database work.
* Tests on a real SQLite repository use :func:`seed_execution_project` and
  :func:`add_execution_member`, which persist a real project (and, when needed,
  a fresh human) so the NOT NULL foreign keys on ``usage_events`` and
  ``trace_spans`` hold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from tests.fixtures.alpha_fixtures import seed_alpha_system_admin
from tests.fixtures.auth import temp_email

from freesearch.models.observability import ActorType, ExecutionAttribution
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    ProjectCreate,
    ProjectRead,
)
from freesearch.persistence.projects import ProjectMembershipRow, ProjectRepository
from freesearch.persistence.storage import SQLiteRepository

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

#: Placeholder identities for tests that never hit a real execution boundary.
EXECUTION_PROJECT_ID: Final[UUID] = UUID("00000000-0000-4000-8000-0000000000aa")
EXECUTION_ACTOR_ID: Final[UUID] = UUID("00000000-0000-4000-8000-0000000000bb")


def test_attribution(
    *,
    project_id: UUID = EXECUTION_PROJECT_ID,
    actor_id: UUID = EXECUTION_ACTOR_ID,
    actor_type: ActorType = ActorType.HUMAN,
) -> ExecutionAttribution:
    """Return an in-memory attribution for tests without a real project row."""

    return ExecutionAttribution(project_id=project_id, actor_type=actor_type, actor_id=actor_id)


# Imported into test modules; must not be collected as a test itself.
test_attribution.__test__ = False


async def seed_execution_user(repository: SQLiteRepository, prefix: str = "exec") -> Any:
    """Create one ordinary active human and return its user row."""

    user, _principal = await seed_alpha_system_admin(repository, email=temp_email(prefix))
    return user


async def seed_execution_project(
    repository: SQLiteRepository,
    *,
    user_id: UUID | None = None,
    name: str = "Execution Project",
    slug: str | None = None,
) -> ExecutionAttribution:
    """Create an active project administered by ``user_id`` (a fresh user when omitted).

    Returns the trusted :class:`ExecutionAttribution` for the project admin.
    """

    if user_id is None:
        user = await seed_execution_user(repository)
        user_id = user.id
    async with repository.session() as session:
        project, _membership, _role = await ProjectRepository(session).create_project_with_admin(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            created_by=user_id,
            project_create=ProjectCreate(
                name=name,
                slug=slug or f"exec-{uuid4().hex[:8]}",
                initial_admin_user_id=user_id,
            ),
        )
        await session.commit()
    return ExecutionAttribution(project_id=project.id, actor_type=ActorType.HUMAN, actor_id=user_id)


async def add_execution_member(
    repository: SQLiteRepository,
    *,
    project_id: UUID,
    user_id: UUID,
    role_key: str = BuiltinRole.PROJECT_MEMBER,
    granted_by: UUID | None = None,
) -> ExecutionAttribution:
    """Add ``user_id`` to a project with one role; return its attribution."""

    async with repository.session() as session:
        await ProjectRepository(session).add_project_member(
            project_id=project_id,
            user_id=user_id,
            role_key=role_key,
            granted_by=granted_by or user_id,
        )
        await session.commit()
    return ExecutionAttribution(project_id=project_id, actor_type=ActorType.HUMAN, actor_id=user_id)


async def suspend_execution_member(
    repository: SQLiteRepository, *, project_id: UUID, user_id: UUID
) -> None:
    """Mark one membership suspended in place."""

    async with repository.session() as session:
        membership = (
            await session.execute(
                select(ProjectMembershipRow).where(
                    ProjectMembershipRow.project_id == str(project_id),
                    ProjectMembershipRow.user_id == str(user_id),
                )
            )
        ).scalar_one_or_none()
        assert membership is not None
        membership.status = MembershipStatus.SUSPENDED.value
        await session.commit()


async def project_read(repository: SQLiteRepository, project_id: UUID) -> ProjectRead | None:
    """Re-read one project row through the project repository."""

    async with repository.session() as session:
        return await ProjectRepository(session).get_project(project_id=project_id)


def account_id_from_token(token: Any) -> UUID:
    """Decode the account id (JWT ``sub``) from a raw or SecretStr token."""

    import jwt as pyjwt

    raw = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
    claims = pyjwt.decode(raw, options={"verify_signature": False})
    return UUID(str(claims["sub"]))


async def seed_token_project(repository: SQLiteRepository, token: Any) -> ExecutionAttribution:
    """Seed an active project administered by the account a JWT belongs to."""

    return await seed_execution_project(repository, user_id=account_id_from_token(token))


def account_id_from_headers(headers: dict[str, str]) -> UUID:
    """Decode the account id (JWT ``sub``) from Bearer auth headers."""

    import jwt as pyjwt

    token = headers["Authorization"].removeprefix("Bearer ").strip()
    claims = pyjwt.decode(token, options={"verify_signature": False})
    return UUID(str(claims["sub"]))


async def seed_member_project(
    repository: SQLiteRepository, headers: dict[str, str]
) -> ExecutionAttribution:
    """Seed an active project administered by the account behind ``headers``."""

    return await seed_execution_project(repository, user_id=account_id_from_headers(headers))


def bdd_project_id(context: Any, headers: dict[str, str]) -> str:
    """Project id owned by the account behind ``headers``, seeded once per account.

    Behave scenarios drive the event loop synchronously; each account's
    project is created on first use and cached for the scenario.
    """

    account = str(account_id_from_headers(headers))
    pids = getattr(context, "_bdd_pids", None)
    if pids is None:
        pids = {}
        context._bdd_pids = pids
    if account not in pids:
        attribution = context.loop.run_until_complete(
            seed_member_project(context.repository, headers)
        )
        pids[account] = str(attribution.project_id)
    return pids[account]


def bdd_token_project_id(context: Any, token: Any) -> str:
    """Project id owned by the account behind a raw/SecretStr JWT, cached."""

    account = str(account_id_from_token(token))
    pids = getattr(context, "_bdd_pids", None)
    if pids is None:
        pids = {}
        context._bdd_pids = pids
    if account not in pids:
        attribution = context.loop.run_until_complete(seed_token_project(context.repository, token))
        pids[account] = str(attribution.project_id)
    return pids[account]


def scenario_attribution(context: Any) -> ExecutionAttribution:
    """Lazily seed one execution project for a BDD scenario repository.

    Returns a placeholder attribution when the scenario has no repository.
    Steps that reopen ``context.repository`` get a fresh project for the new
    database so the foreign key always resolves.
    """

    repo = getattr(context, "repository", None)
    attribution = getattr(context, "_exec_attribution", None)
    owner = getattr(context, "_exec_attribution_repo", None)
    if attribution is None or (repo is not None and owner is not repo):
        if repo is None:
            attribution = test_attribution()
        else:
            attribution = context.loop.run_until_complete(seed_execution_project(repo))
            context._exec_attribution_repo = repo
        context._exec_attribution = attribution
    return attribution


async def register_project_admin(
    client: TestClient, repository: SQLiteRepository, prefix: str
) -> tuple[dict[str, str], ExecutionAttribution]:
    """Register and log in over HTTP, then create a project the account admins.

    Returns ``(auth headers, attribution)`` for execution calls.
    """

    from tests.fixtures.auth import account_id_from_pair, raw_auth_headers, register_and_login

    pair = register_and_login(client, temp_email(prefix))
    attribution = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
    return raw_auth_headers(pair["access_token"]), attribution
