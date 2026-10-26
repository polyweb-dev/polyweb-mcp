"""Operator account CLI on real SQLite (P1b, T18 parts).

Every test uses an isolated database file that already exists, so the
missing-file refusal stays covered. The password prompt seam
``freesearch.cli.users._prompt_password`` supplies each password. No test
passes a password argument, and no password, token, or hash reaches the
captured output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.password import PasswordHelper
from pydantic import SecretStr

from freesearch.cli.users import _run
from freesearch.models.observability import (
    ActorType,
    TraceOperation,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.models.projects import BuiltinRole, ProjectCreate, ProjectMemberAdd
from freesearch.persistence.audit import SystemAuditEventRow
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.projects import ProjectRepository, SystemRoleAssignmentRow
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow
from freesearch.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import create_alpha_test_db
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    http_jwt_service,
    temp_email,
    temp_principal,
)
from tests.fixtures.execution import seed_execution_project

_PASSWORD = "StrongPass123!x-CliBDD"


def _prompt(monkeypatch: pytest.MonkeyPatch, password: str = _PASSWORD) -> None:
    monkeypatch.setattr("freesearch.cli.users._prompt_password", lambda: SecretStr(password))


async def _account(repository: SQLiteRepository, email: str) -> object:
    async with repository.session() as session:
        return await UserDatabase(session, UserRow).get_by_email(email)


async def _system_roles(repository: SQLiteRepository, user_id: object) -> set[str]:
    from sqlalchemy import select

    async with repository.session() as session:
        rows = await session.execute(
            select(SystemRoleAssignmentRow.role_key).where(
                SystemRoleAssignmentRow.user_id == str(user_id)
            )
        )
        return set(rows.scalars())


async def _system_audit(repository: SQLiteRepository, action: str) -> list[object]:
    from sqlalchemy import select

    async with repository.session() as session:
        rows = await session.execute(
            select(SystemAuditEventRow).where(SystemAuditEventRow.action == action)
        )
        return list(rows.scalars())


async def test_create_admin_prints_uuid_and_admin_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli-admin.db"
    repository = await SQLiteRepository.open(database)
    await repository.close()
    email = temp_email("cli-admin")
    _prompt(monkeypatch)

    assert await _run(["create-admin", "--email", email, "--database", str(database)]) == 0

    captured = capsys.readouterr()
    assert _PASSWORD not in captured.out
    assert _PASSWORD not in captured.err

    check = await SQLiteRepository.open(database)
    try:
        account = await _account(check, email)
        assert account is not None
        # A1: the bootstrap grants an explicit system_admin assignment, no flag.
        assert await _system_roles(check, account.id) == {"system_admin"}
        assert account.is_superuser is False
        assert f"Account: {account.id}" in captured.out
        assert "System role: system_admin" in captured.out
        granted = await _system_audit(check, "system_role.granted")
        assert len(granted) == 1
        verified, _ = PasswordHelper().verify_and_update(_PASSWORD, str(account.hashed_password))
        assert verified is True
    finally:
        await check.close()


async def test_create_admin_rejects_weak_password_without_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli-weak.db"
    repository = await SQLiteRepository.open(database)
    await repository.close()
    weak = "weakpass1"
    _prompt(monkeypatch, weak)

    assert (
        await _run(["create-admin", "--email", temp_email("cli-weak"), "--database", str(database)])
        == 1
    )

    captured = capsys.readouterr()
    assert weak not in captured.out
    assert weak not in captured.err
    assert "password" in captured.err.lower()


async def test_create_admin_rejects_duplicate_email(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli-dupe.db"
    repository = await SQLiteRepository.open(database)
    await repository.close()
    email = temp_email("cli-dupe")
    _prompt(monkeypatch)

    assert await _run(["create-admin", "--email", email, "--database", str(database)]) == 0
    assert await _run(["create-admin", "--email", email, "--database", str(database)]) == 1

    captured = capsys.readouterr()
    assert "already exists" in captured.err


async def test_commands_refuse_a_missing_database_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "absent.db"
    _prompt(monkeypatch)

    assert (
        await _run(["create-admin", "--email", temp_email("cli-gone"), "--database", str(missing)])
        == 1
    )
    assert (
        await _run(
            [
                "grant-system-admin",
                "--user-id",
                str(__import__("uuid").uuid4()),
                "--database",
                str(missing),
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert str(missing) in captured.err


async def test_set_role_assigns_role_and_revokes_old_families(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A1: grant adds a live assignment; revoke removes it and ends the old sessions."""

    database = tmp_path / "cli-role.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-role")
        await create_temp_user(repository, email, password=TEMP_PASSWORD)
        await create_temp_user(repository, temp_email("cli-role-peer"), system_admin=True)
        service = http_jwt_service(repository)
        tokens = await service.login(
            OAuth2PasswordRequestForm(username=email, password=TEMP_PASSWORD),
            peer_address="cli-role-probe",
        )
        assert tokens is not None
        access = tokens.access_token.get_secret_value()

        check = await _account(repository, email)
        assert check is not None
        user_id = check.id
        grant = ["grant-system-admin", "--user-id", str(user_id), "--database", str(database)]
        revoke = ["revoke-system-admin", "--user-id", str(user_id), "--database", str(database)]

        assert await _run(grant) == 0
        captured = capsys.readouterr()
        assert f"Account: {user_id}" in captured.out
        assert "System role: system_admin granted" in captured.out
        assert access not in captured.out
        assert await _system_roles(repository, user_id) == {"system_admin"}
        # Authority is live, so a grant needs no session revocation.
        assert await service.verify_token(access) is not None

        assert await _run(revoke) == 0
        captured = capsys.readouterr()
        assert "System role: system_admin revoked" in captured.out
        assert await _system_roles(repository, user_id) == set()
        assert await service.verify_token(access) is None
        assert len(await _system_audit(repository, "system_role.revoked")) == 1

        # The obsolete role command is gone.
        assert (
            await _run(
                [
                    "set-role",
                    "--user-id",
                    str(user_id),
                    "--role",
                    "developer",
                    "--database",
                    str(database),
                ]
            )
            == 2
        )
        assert "invalid command arguments" in capsys.readouterr().err
    finally:
        await repository.close()


async def test_set_role_to_the_same_role_revokes_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A1: repeated grant/revoke are idempotent no-ops without a second audit event."""

    database = tmp_path / "cli-rerole.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-rerole")
        await create_temp_user(repository, email, password=TEMP_PASSWORD)
        await create_temp_user(repository, temp_email("cli-rerole-peer"), system_admin=True)
        check = await _account(repository, email)
        assert check is not None
        grant = ["grant-system-admin", "--user-id", str(check.id), "--database", str(database)]
        revoke = ["revoke-system-admin", "--user-id", str(check.id), "--database", str(database)]

        assert await _run(grant) == 0
        assert await _run(grant) == 0
        assert "already held" in capsys.readouterr().out
        # The fixture peer was seeded directly; only the CLI grant is audited, once.
        assert len(await _system_audit(repository, "system_role.granted")) == 1

        assert await _run(revoke) == 0
        assert await _run(revoke) == 0
        assert "not held" in capsys.readouterr().out
        assert len(await _system_audit(repository, "system_role.revoked")) == 1
    finally:
        await repository.close()


async def test_revoke_refuses_the_last_active_system_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli-last-sysadmin.db"
    repository = await SQLiteRepository.open(database)
    try:
        only = await create_temp_user(repository, temp_email("cli-only"), system_admin=True)
        command = ["revoke-system-admin", "--user-id", str(only.id), "--database", str(database)]
        assert await _run(command) == 1
        assert "last active system administrator" in capsys.readouterr().err
        assert await _system_roles(repository, only.id) == {"system_admin"}
        assert await _system_audit(repository, "system_role.revoked") == []
    finally:
        await repository.close()


async def test_grant_refuses_an_inactive_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "cli-inactive-grant.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-inactive")
        row = await create_temp_user(repository, email)
        async with repository.session() as session:
            stored = await session.get(UserRow, row.id)
            assert stored is not None
            stored.is_active = False
            await session.commit()
        command = ["grant-system-admin", "--user-id", str(row.id), "--database", str(database)]
        assert await _run(command) == 1
        assert capsys.readouterr().err.strip()
        assert await _system_roles(repository, row.id) == set()
    finally:
        await repository.close()


async def test_set_role_rejects_unknown_and_malformed_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from uuid import uuid4

    database = tmp_path / "cli-unknown.db"
    repository = await SQLiteRepository.open(database)
    await repository.close()

    for command in ("grant-system-admin", "revoke-system-admin"):
        assert await _run([command, "--user-id", str(uuid4()), "--database", str(database)]) == 1
        assert await _run([command, "--user-id", "not-a-uuid", "--database", str(database)]) == 1

    captured = capsys.readouterr()
    assert "no account has this id" in captured.err
    assert "must be a UUID" in captured.err


async def test_set_role_preserves_account_owned_traces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
) -> None:
    database = tmp_path / "cli-traces.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-traces")
        await create_temp_user(repository, email, password=TEMP_PASSWORD)
        check = await _account(repository, email)
        assert check is not None
        moment = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        attribution = await seed_execution_project(repository, user_id=check.id)
        write_trace_spans(
            repository.database_path,
            [
                TraceSpanRecord(
                    project_id=attribution.project_id,
                    actor_type=ActorType.HUMAN,
                    actor_id=attribution.actor_id,
                    span_id="dd00000000000004",
                    trace_id="e" * 32,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=moment,
                    ended_at=moment,
                    duration_ms=5,
                    operation=TraceOperation.SEARCH,
                    provider="keenable",
                    user_id=str(check.id),
                )
            ],
        )

        assert (
            await _run(
                [
                    "grant-system-admin",
                    "--user-id",
                    str(check.id),
                    "--database",
                    str(database),
                ]
            )
            == 0
        )

        rows = await repository.list_trace_summaries(user_id=check.id)
        assert [item.trace_id for item in rows] == ["e" * 32]
    finally:
        await repository.close()


async def test_deactivate_uses_the_same_last_admin_guard(
    tmp_path: Path,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator CLI cannot deactivate an account that is the last admin."""

    database = tmp_path / "cli-deactivate.db"
    repository = await create_alpha_test_db(database)
    try:
        system_row = await create_temp_user(
            repository, temp_email("cli-deactivate-sys"), system_admin=True
        )
        admin_row = await create_temp_user(repository, temp_email("cli-deactivate-admin"))
        peer_row = await create_temp_user(repository, temp_email("cli-deactivate-peer"))
        system = temp_principal(system_row)
        admin = temp_principal(admin_row)
        peer = temp_principal(peer_row)
        project = await ProjectService(repository).create_project(
            system,
            ProjectCreate(
                name="CLI Deactivate",
                slug="cli-deactivate",
                initial_admin_user_id=admin.id,
            ),
        )

        async def stored_active(email: str) -> bool:
            async with repository.session() as session:
                record = await UserDatabase(session, UserRow).get_by_email(email)
                assert record is not None
                return bool(record.is_active)

        command = [
            "deactivate",
            "--user-id",
            str(admin.id),
            "--database",
            str(database),
        ]
        assert await _run(command) == 1
        refused = capsys.readouterr()
        assert "last active administrator" in refused.err
        assert await stored_active(admin_row.email) is True

        service = ProjectService(repository)
        await service.add_member(
            admin,
            project.id,
            ProjectMemberAdd(
                user_id=peer.id,
                initial_role=BuiltinRole.PROJECT_ADMIN.value,
            ),
        )
        assert await _run(command) == 0
        completed = capsys.readouterr()
        assert f"Account: {admin.id}" in completed.out
        assert "Active: false" in completed.out
        assert TEMP_PASSWORD not in completed.out
        assert TEMP_PASSWORD not in completed.err

        async with repository.session() as session:
            assert (
                await ProjectRepository(session).count_active_project_admins(project_id=project.id)
                == 1
            )

        # A mixed bulk request that would leave no active administrator is
        # rejected as one transaction, including for the already-inactive ID.
        refused_bulk = await _run(
            [
                "deactivate",
                "--user-id",
                str(admin.id),
                "--user-id",
                str(peer.id),
                "--database",
                str(database),
            ]
        )
        assert refused_bulk == 1
        assert "last active administrator" in capsys.readouterr().err
        assert await stored_active(admin_row.email) is False
        assert await stored_active(peer_row.email) is True
        async with repository.session() as session:
            assert (
                await ProjectRepository(session).count_active_project_admins(project_id=project.id)
                == 1
            )
    finally:
        await repository.close()


async def test_cli_deactivate_refuses_the_last_active_system_admin(
    tmp_path: Path,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """R2: the operator CLI cannot leave the installation without a system admin."""

    database = tmp_path / "cli-last-sysadmin-deactivate.db"
    repository = await create_alpha_test_db(database)
    try:
        only = await create_temp_user(repository, temp_email("cli-r2-only"), system_admin=True)
        command = ["deactivate", "--user-id", str(only.id), "--database", str(database)]
        assert await _run(command) == 1
        refused = capsys.readouterr()
        assert "last active system administrator" in refused.err
        assert refused.out == ""
        async with repository.session() as session:
            stored = await session.get(UserRow, only.id)
            assert stored is not None and stored.is_active is True
        assert await _system_audit(repository, "account.deactivated") == []

        second = await create_temp_user(repository, temp_email("cli-r2-second"), system_admin=True)
        assert await _run(command) == 0
        assert f"Account: {only.id}" in capsys.readouterr().out
        assert (
            await _run(["deactivate", "--user-id", str(second.id), "--database", str(database)])
            == 1
        )
        async with repository.session() as session:
            kept = await session.get(UserRow, second.id)
            assert kept is not None and kept.is_active is True
    finally:
        await repository.close()
