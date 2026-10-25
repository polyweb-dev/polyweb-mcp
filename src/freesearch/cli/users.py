"""Operator-only account CLI: Admin bootstrap and role assignment.

These commands replace the absent HTTP role-management surface (PLAN P1a/Q5b).
They run under operator filesystem privileges, so they are the only trusted path
that can create an Admin account or change a role. No first-registration rule
and no email match grants Admin.

Safety rules:

* A password never arrives through a command line argument. The command refuses
  a password-shaped flag with a fixed message and never echoes the raw value.
* The bootstrap password comes from a masked terminal prompt. A missing secure
  prompt is an error, not an echo-prone fallback.
* The target database must exist as an absolute file path, so a mistyped path
  cannot create an empty database with an Admin account.
* A successful privileged operation prints only the account UUID and its role.
  Passwords, token pairs, hashes, and argument namespaces never reach the
  output, and every failure uses one fixed message.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never
from uuid import UUID

from fastapi_users import exceptions
from pydantic import SecretStr

from freesearch.configuration.config import get_settings
from freesearch.models.users import UserRole
from freesearch.persistence.database_migrations import absolute_database_path
from freesearch.services.monitoring import resolve_database_path
from freesearch.services.projects import (
    LAST_PROJECT_ADMIN,
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
    ProjectServiceError,
    ProjectStorageUnavailable,
    ProjectValidationError,
)
from freesearch.services.users import (
    AuthRoleAssignmentFailed,
    AuthService,
    AuthServiceError,
    AuthUnsupportedRole,
    AuthUserNotFound,
)

#: One fixed message for every usage failure: raw argument text never appears.
_USAGE_ERROR: str = "invalid command arguments"

#: One fixed message for a password-shaped command-line argument.
_PASSWORD_ARGUMENT_ERROR: str = (
    "do not pass a password on the command line: the command reads it from a masked prompt"
)

#: One fixed message for every unexpected failure.
_OPERATION_ERROR: str = "the account operation failed"

#: Flags that could carry a password value.
_PASSWORD_FLAGS: frozenset[str] = frozenset({"-p", "--pass", "--passwd", "--password", "--secret"})


class CliError(RuntimeError):
    """Raised for a safe, fixed command failure."""


class _SafeParser(argparse.ArgumentParser):
    """Argument parser that never echoes the raw argument text."""

    def error(self, message: str) -> Never:
        del message
        raise CliError(_USAGE_ERROR)


def _is_password_argument(argument: str) -> bool:
    """Return whether one raw argument tries to carry a password."""

    name = argument.split("=", 1)[0].strip().lower()
    return name in _PASSWORD_FLAGS or name.startswith("--pass")


def _parser() -> argparse.ArgumentParser:
    """Return the parser for the two privileged account commands."""

    parser = _SafeParser(
        prog="freesearch-users",
        description=(
            "Create an Admin account, assign an account role, or deactivate "
            "accounts with the project administrator guard (operator only)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser(
        "create-admin", help="create one local Admin account through a masked prompt"
    )
    create.add_argument("--email", required=True, help="email address of the new Admin account")
    create.add_argument(
        "--database",
        type=Path,
        default=None,
        help="existing database file; the shared FREESEARCH_DB precedence applies",
    )
    role = subparsers.add_parser("set-role", help="assign one role to an explicit account UUID")
    role.add_argument("--user-id", required=True, help="account UUID to change")
    role.add_argument(
        "--role",
        required=True,
        choices=[member.value for member in UserRole],
        help="role to assign: admin, developer, or agent",
    )
    role.add_argument(
        "--database",
        type=Path,
        default=None,
        help="existing database file; the shared FREESEARCH_DB precedence applies",
    )
    deactivate = subparsers.add_parser(
        "deactivate",
        help="deactivate one or more accounts after the last-project-admin guard",
    )
    deactivate.add_argument(
        "--user-id",
        action="append",
        required=True,
        dest="user_ids",
        help="account UUID to deactivate; repeat to apply one guarded bulk change",
    )
    deactivate.add_argument(
        "--database",
        type=Path,
        default=None,
        help="existing database file; the shared FREESEARCH_DB precedence applies",
    )
    return parser


def _selected_database(explicit: Path | None) -> Path:
    """Return the absolute path of an existing database file.

    The shared resolver decides the target. The resolved path must name an
    existing file, so the command never creates a fresh database by accident.
    """

    resolved = absolute_database_path(resolve_database_path(explicit))
    if not resolved.is_file():
        raise CliError(f"database file not found: {resolved}")
    return resolved


def _prompt_password() -> SecretStr:
    """Read the bootstrap password from a masked terminal prompt."""

    if not sys.stdin.isatty():
        raise CliError("a terminal is required for the masked password prompt")
    try:
        entered = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise CliError("password entry was cancelled") from error
    if not entered:
        raise CliError("a password is required")
    return SecretStr(entered)


def _report(error: Exception) -> int:
    """Print one fixed, secret-free message for a failed operation."""

    if isinstance(error, CliError):
        print(str(error), file=sys.stderr)
        return 1
    if isinstance(error, exceptions.InvalidPasswordException):
        print(error.reason, file=sys.stderr)
        return 1
    if isinstance(error, exceptions.UserAlreadyExists):
        print("an account with this email address already exists", file=sys.stderr)
        return 1
    if isinstance(error, AuthUserNotFound):
        print("no account has this id", file=sys.stderr)
        return 1
    if isinstance(error, AuthRoleAssignmentFailed):
        print(f"Account: {error.user_id}")
        print("Role: agent (the admin role was not applied)")
        return 1
    if isinstance(error, AuthUnsupportedRole):
        print(str(error), file=sys.stderr)
        return 1
    if isinstance(error, ProjectConflict) and error.code == LAST_PROJECT_ADMIN:
        print(
            "cannot deactivate: a project would lose its last active administrator",
            file=sys.stderr,
        )
        return 1
    if isinstance(error, ProjectNotFound):
        print("no account has this id", file=sys.stderr)
        return 1
    if isinstance(error, ProjectValidationError):
        print(str(error), file=sys.stderr)
        return 1
    if isinstance(error, ProjectStorageUnavailable):
        print("the account database is unavailable", file=sys.stderr)
        return 1
    if isinstance(error, ProjectServiceError):
        print(_OPERATION_ERROR, file=sys.stderr)
        return 1
    if isinstance(error, AuthServiceError):
        print("the account database is unavailable", file=sys.stderr)
        return 1
    print(_OPERATION_ERROR, file=sys.stderr)
    return 1


async def _execute(options: argparse.Namespace) -> int:
    """Run one privileged command against the resolved database."""

    database = _selected_database(options.database)
    service = AuthService(get_settings(), database=database)
    try:
        # The shared opener applies pending migrations through the same runner
        # the API and MCP transports use, so a privileged write never meets an
        # old schema.
        await service.open()
        if options.command == "create-admin":
            account = await service.create_admin(options.email, _prompt_password())
            print(f"Account: {account}")
            print(f"Role: {UserRole.ADMIN.value}")
            return 0
        if options.command == "deactivate":
            repository = service.repository
            if repository is None:
                raise CliError("the account database is unavailable")
            target_ids = [UUID(str(value)) for value in options.user_ids]
            accounts = await ProjectService(
                repository,
                rollout_state=service.settings.projects_rollout_state,
            ).deactivate_accounts(target_ids, trusted=True)
            for deactivated in accounts:
                print(f"Account: {deactivated.id}")
                print("Active: false")
            return 0
        user_id = UUID(str(options.user_id))
        target_role = UserRole(str(options.role))
        await service.change_role(user_id, target_role)
        print(f"Account: {user_id}")
        print(f"Role: {options.role}")
        return 0
    finally:
        await service.close()


async def _run(arguments: Sequence[str] | None = None) -> int:
    """Run the account command and return its exit status."""

    raw = list(arguments) if arguments is not None else sys.argv[1:]
    if any(_is_password_argument(item) for item in raw):
        print(_PASSWORD_ARGUMENT_ERROR, file=sys.stderr)
        return 2
    try:
        options = _parser().parse_args(raw)
    except CliError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        return await _execute(options)
    except ValueError:
        print("the account id must be a UUID", file=sys.stderr)
        return 1
    except Exception as error:
        # One fixed message for anything else, so no raw value can reach output.
        return _report(error)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the account command and return its status to the shell."""

    raise SystemExit(asyncio.run(_run(argv)))


__all__ = ["CliError", "main"]
