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
from freesearch.models.observability import TraceOperation, TraceSpanKind, TraceSpanRecord
from freesearch.models.users import UserRole
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserDatabase, UserRow
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    http_jwt_service,
    temp_email,
)

_PASSWORD = "StrongPass123!x-CliBDD"


def _prompt(monkeypatch: pytest.MonkeyPatch, password: str = _PASSWORD) -> None:
    monkeypatch.setattr("freesearch.cli.users._prompt_password", lambda: SecretStr(password))


async def _account(repository: SQLiteRepository, email: str) -> object:
    async with repository.session() as session:
        return await UserDatabase(session, UserRow).get_by_email(email)


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
        assert account.role == UserRole.ADMIN.value
        assert account.is_superuser is True
        assert f"Account: {account.id}" in captured.out
        assert "Role: admin" in captured.out
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
                "set-role",
                "--user-id",
                str(__import__("uuid").uuid4()),
                "--role",
                "admin",
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
    database = tmp_path / "cli-role.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-role")
        await create_temp_user(repository, email, password=TEMP_PASSWORD)
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
            == 0
        )

        captured = capsys.readouterr()
        assert f"Account: {user_id}" in captured.out
        assert "Role: developer" in captured.out
        assert access not in captured.out

        updated = await _account(repository, email)
        assert updated is not None
        assert updated.role == UserRole.DEVELOPER.value
        assert updated.is_superuser is False
        assert await service.verify_token(access) is None
    finally:
        await repository.close()


async def test_set_role_to_the_same_role_revokes_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_secret: str,
) -> None:
    database = tmp_path / "cli-rerole.db"
    repository = await SQLiteRepository.open(database)
    try:
        email = temp_email("cli-rerole")
        await create_temp_user(repository, email, password=TEMP_PASSWORD)
        service = http_jwt_service(repository)
        first = await service.login(
            OAuth2PasswordRequestForm(username=email, password=TEMP_PASSWORD),
            peer_address="cli-rerole-one",
        )
        assert first is not None
        check = await _account(repository, email)
        assert check is not None

        assert (
            await _run(
                [
                    "set-role",
                    "--user-id",
                    str(check.id),
                    "--role",
                    "developer",
                    "--database",
                    str(database),
                ]
            )
            == 0
        )
        second = await service.login(
            OAuth2PasswordRequestForm(username=email, password=TEMP_PASSWORD),
            peer_address="cli-rerole-two",
        )
        assert second is not None
        assert (
            await _run(
                [
                    "set-role",
                    "--user-id",
                    str(check.id),
                    "--role",
                    "developer",
                    "--database",
                    str(database),
                ]
            )
            == 0
        )
        assert await service.verify_token(second.access_token.get_secret_value()) is None
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

    assert (
        await _run(
            ["set-role", "--user-id", str(uuid4()), "--role", "admin", "--database", str(database)]
        )
        == 1
    )
    assert (
        await _run(
            ["set-role", "--user-id", "not-a-uuid", "--role", "admin", "--database", str(database)]
        )
        == 1
    )

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
        write_trace_spans(
            repository.database_path,
            [
                TraceSpanRecord(
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
                    "set-role",
                    "--user-id",
                    str(check.id),
                    "--role",
                    "developer",
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
