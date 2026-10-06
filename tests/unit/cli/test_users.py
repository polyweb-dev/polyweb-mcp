"""Unit tests for the operator account CLI (P1b, T18 parts).

No test touches the database or the network. The password prompt seam
``freesearch.cli.users._prompt_password`` is the only patched boundary, and
only the prompt tests replace it. Every failure uses one fixed message, and
no raw argument value reaches the output.
"""

from __future__ import annotations

import pytest
from fastapi_users import exceptions
from pydantic import SecretStr

from freesearch.cli.users import (
    CliError,
    _is_password_argument,
    _parser,
    _prompt_password,
    _report,
    _run,
    _selected_database,
    main,
)
from freesearch.services.users import (
    AuthRoleAssignmentFailed,
    AuthServiceError,
    AuthUserNotFound,
)


def test_password_flags_are_refused_without_echo() -> None:
    for flag in ("-p", "--pass", "--passwd", "--password", "--secret", "--password=x"):
        assert _is_password_argument(flag) is True
    for benign in ("--email", "--database", "--role", "--user-id", "create-admin", "set-role"):
        assert _is_password_argument(benign) is False


async def test_run_refuses_password_arguments_with_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "Sup3rSecret!x-NoEcho"

    assert await _run(["create-admin", "--email", "ops@example.com", "--password", secret]) == 2
    assert await _run(["set-role", "--user-id", "x", "--role", "admin", "-p", secret]) == 2

    captured = capsys.readouterr()
    assert secret not in captured.err
    assert secret not in captured.out
    assert "do not pass a password on the command line" in captured.err


async def test_run_rejects_bad_arguments_with_one_fixed_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await _run(["create-admin"]) == 2
    assert await _run(["unknown-command"]) == 2
    assert await _run(["set-role", "--user-id", "x", "--role", "owner"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "raw" not in captured.err
    for line in captured.err.strip().splitlines():
        assert line == "invalid command arguments"


def test_parser_accepts_both_commands() -> None:
    create = _parser().parse_args(["create-admin", "--email", "ops@example.com"])
    assert create.command == "create-admin"
    assert create.email == "ops@example.com"

    role = _parser().parse_args(["set-role", "--user-id", "u", "--role", "developer"])
    assert role.command == "set-role"
    assert role.role == "developer"


def test_parser_never_echoes_raw_text() -> None:
    with pytest.raises(CliError, match="invalid command arguments"):
        _parser().parse_args(["create-admin", "--email"])


def test_selected_database_requires_an_existing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    missing = tmp_path / "absent.db"

    with pytest.raises(CliError, match="database file not found"):
        _selected_database(missing)

    try:
        _selected_database(missing)
    except CliError as error:
        assert str(missing) in str(error)

    present = tmp_path / "present.db"
    present.write_bytes(b"")
    assert _selected_database(present) == present


def test_prompt_password_needs_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(CliError, match="a terminal is required"):
        _prompt_password()


def test_prompt_password_rejects_empty_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    import freesearch.cli.users as users_module

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(users_module.getpass, "getpass", lambda _prompt="": "")

    with pytest.raises(CliError, match="a password is required"):
        _prompt_password()


def test_prompt_password_returns_masked_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    import freesearch.cli.users as users_module

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(users_module.getpass, "getpass", lambda _prompt="": "StrongPass123!x-Unit")

    assert _prompt_password() == SecretStr("StrongPass123!x-Unit")


def test_report_maps_each_failure_to_a_fixed_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from uuid import uuid4

    assert _report(CliError("usage")) == 1
    assert _report(exceptions.InvalidPasswordException(reason="rule text")) == 1
    assert _report(exceptions.UserAlreadyExists()) == 1
    assert _report(AuthUserNotFound()) == 1
    assert _report(AuthRoleAssignmentFailed(uuid4())) == 1
    assert _report(AuthServiceError("down")) == 1
    assert _report(RuntimeError("boom")) == 1

    captured = capsys.readouterr()
    assert "boom" not in captured.err
    assert "an account with this email address already exists" in captured.err
    assert "no account has this id" in captured.err
    assert "the account database is unavailable" in captured.err
    assert "the account operation failed" in captured.err


def test_report_role_failure_prints_agent_fallback_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from uuid import uuid4

    account = uuid4()
    assert _report(AuthRoleAssignmentFailed(account)) == 1

    captured = capsys.readouterr()
    assert captured.err == ""
    assert f"Account: {account}" in captured.out
    assert "agent" in captured.out


def test_main_returns_the_run_status_as_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    import freesearch.cli.users as users_module

    async def _fake_run(arguments=None):  # type: ignore[no-untyped-def]
        assert arguments == ["create-admin", "--email", "ops@example.com"]
        return 3

    monkeypatch.setattr(users_module, "_run", _fake_run)

    with pytest.raises(SystemExit) as ended:
        main(["create-admin", "--email", "ops@example.com"])

    assert ended.value.code == 3
