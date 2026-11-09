"""Project API key fixtures (TASK-000041).

Machine clients (REST and MCP) authenticate with a project API key issued
through the real :class:`~polyweb.services.api_keys.ApiKeyService`, so every
fixture key has a real prefix, a stored verifier digest and an owning project.
The owner is an ordinary human who administers the project through membership;
no fixture grants system authority to issue a key.

The raw key is held only in a :class:`~pydantic.SecretStr` with ``repr=False``
so an assertion failure cannot print it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from pydantic import SecretStr
from tests.fixtures.auth import auth_service_for, temp_principal
from tests.fixtures.execution import seed_execution_project, seed_execution_user

from polyweb.models.observability import ActorType, ExecutionAttribution
from polyweb.models.projects import API_KEY_SCOPES, ProjectApiKeyCreate
from polyweb.models.users import UserPrincipal
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.api_keys import ApiKeyService
from polyweb.services.users import AuthService


class _Omitted:
    """Sentinel: leave ``expires_at`` out of the issue request (default lifetime)."""

    def __repr__(self) -> str:
        return "OMITTED"


#: Leave ``expires_at`` out of the request, so the 90-day default applies.
OMITTED: Final[Any] = _Omitted()


@dataclass(frozen=True)
class ProjectKey:
    """One issued project API key, its project and its human owner."""

    key: SecretStr = field(repr=False)
    api_key_id: UUID
    project_id: UUID
    prefix: str
    owner: UserPrincipal

    @property
    def raw(self) -> str:
        """Return the raw key for a request header; never print it."""

        return self.key.get_secret_value()

    def headers(self) -> dict[str, str]:
        """Return the Bearer header that carries this key."""

        return {"Authorization": f"Bearer {self.raw}"}

    @property
    def attribution(self) -> ExecutionAttribution:
        """Return the attribution every execution with this key must carry."""

        return ExecutionAttribution(
            project_id=self.project_id,
            actor_type=ActorType.PROJECT_API_KEY,
            actor_id=self.api_key_id,
        )


async def issue_project_key(
    repository: SQLiteRepository,
    *,
    owner: UserPrincipal | None = None,
    project_id: UUID | None = None,
    prefix: str = "key-owner",
    label: str = "fixture key",
    scopes: Iterable[str] | None = None,
    expires_at: datetime | Any | None = OMITTED,
    service: ApiKeyService | None = None,
) -> ProjectKey:
    """Issue one real key; create an ordinary owner and its project when omitted."""

    if owner is None:
        owner = temp_principal(await seed_execution_user(repository, prefix))
    if project_id is None:
        project_id = (await seed_execution_project(repository, user_id=owner.id)).project_id
    body: dict[str, Any] = {"label": label}
    if scopes is not None:
        body["scopes"] = frozenset(scopes)
    if expires_at is not OMITTED:
        body["expires_at"] = expires_at
    issued = await (service or ApiKeyService(repository)).issue(
        owner, project_id, ProjectApiKeyCreate.model_validate(body)
    )
    return ProjectKey(
        key=issued.key,
        api_key_id=issued.id,
        project_id=project_id,
        prefix=issued.prefix,
        owner=owner,
    )


async def key_for_account(
    repository: SQLiteRepository, account_id: UUID, project_id: UUID, **options: Any
) -> ProjectKey:
    """Issue a key in ``project_id`` as the existing account ``account_id``.

    The account must already hold ``tokens.manage`` there (for example as the
    project administrator a fixture seeded); the service re-checks it live.
    """

    from uuid import uuid4

    owner = UserPrincipal(
        id=account_id,
        email="fixture-owner@example.com",
        session_id=uuid4(),
        is_active=True,
        is_verified=False,
    )
    return await issue_project_key(repository, owner=owner, project_id=project_id, **options)


async def mcp_project_key(
    repository: SQLiteRepository, prefix: str = "mcp"
) -> tuple[AuthService, ProjectKey]:
    """Return an account-store service plus one full-scope project key for MCP tests."""

    key = await issue_project_key(repository, prefix=prefix)
    return auth_service_for(repository), key


async def mcp_key_credentials(
    repository: SQLiteRepository, prefix: str = "mcp"
) -> tuple[AuthService, SecretStr, str]:
    """Return ``(account service, raw key, project id)`` for one MCP composition.

    A1 replacement of the former human-JWT ``mcp_account_token`` helper: MCP
    authenticates only with a project API key, and the key's own project is
    the project the tool call executes in.
    """

    service, key = await mcp_project_key(repository, prefix)
    return service, key.key, str(key.project_id)


async def expire_key(
    repository: SQLiteRepository, key: ProjectKey, *, seconds_ago: int = 5
) -> None:
    """Move one stored key's expiry into the past (an authoritative-clock expiry)."""

    from datetime import UTC, timedelta

    from sqlalchemy import update

    from polyweb.persistence.api_keys import ProjectApiKeyRow, stored_timestamp

    now = datetime.now(UTC)
    async with repository.session() as session:
        # The schema requires expires_at > created_at, so the issue time moves
        # back too; the key is otherwise unchanged (same prefix and verifier).
        result = await session.execute(
            update(ProjectApiKeyRow)
            .where(ProjectApiKeyRow.id == str(key.api_key_id))
            .values(
                created_at=stored_timestamp(now - timedelta(hours=1)),
                expires_at=stored_timestamp(now - timedelta(seconds=seconds_ago)),
            )
        )
        assert getattr(result, "rowcount", 0) == 1
        await session.commit()


async def archive_project(repository: SQLiteRepository, project_id: UUID) -> None:
    """Archive one project directly in storage (no service-side guard involved)."""

    from polyweb.models.projects import ProjectStatus
    from polyweb.persistence.projects import ProjectRepository

    async with repository.session() as session:
        await ProjectRepository(session).set_project_status(
            project_id=project_id, status=ProjectStatus.ARCHIVED
        )
        await session.commit()


async def audit_rows(
    repository: SQLiteRepository, *, scope: str, action: str | None = None
) -> list[dict[str, Any]]:
    """Return raw audit rows of one scope (``system`` or ``project``) as dicts.

    Denial security events are written off the request path (R3), so this
    first drains the process-wide background writer of the current loop.
    """

    import json

    from polyweb.services.api_keys import DEFAULT_USE_RECORDER

    await DEFAULT_USE_RECORDER.drain()

    from sqlalchemy import select

    from polyweb.persistence.audit import ProjectAuditEventRow, SystemAuditEventRow

    table = SystemAuditEventRow if scope == "system" else ProjectAuditEventRow
    statement = select(table)
    if action is not None:
        statement = statement.where(table.action == action)
    async with repository.session() as session:
        rows = (await session.execute(statement)).scalars().all()
        return [
            {
                column.name: getattr(row, column.key)
                for column in table.__table__.columns  # type: ignore[attr-defined]
            }
            | {"detail_json": json.loads(row.detail)}
            for row in rows
        ]


def database_dump(repository: SQLiteRepository) -> str:
    """Return every row of every table plus the WAL bytes, for secret scans."""

    import sqlite3

    con = sqlite3.connect(repository.database_path)
    try:
        lines = list(con.iterdump())
    finally:
        con.close()
    text = "\n".join(lines)
    wal = repository.database_path.with_name(repository.database_path.name + "-wal")
    if wal.exists():
        text += wal.read_bytes().decode("latin-1")
    return text


#: Both execution scopes, the default of an issued key.
ALL_SCOPES: Final[frozenset[str]] = API_KEY_SCOPES

__all__ = [
    "ALL_SCOPES",
    "OMITTED",
    "ProjectKey",
    "archive_project",
    "audit_rows",
    "database_dump",
    "expire_key",
    "issue_project_key",
    "key_for_account",
    "mcp_key_credentials",
    "mcp_project_key",
]
