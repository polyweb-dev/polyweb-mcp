"""Operator-only account CLI: system administrator bootstrap and assignment.

These commands are the trusted local path for system authority. They run under
operator filesystem privileges, so they are the only path that can create the
first system administrator or grant and revoke the ``system_admin`` role
assignment. No first-registration rule and no email match grants it, and no
account type or role field exists on an account.

Safety rules:

* A password never arrives through a command line argument. The command refuses
  a password-shaped flag with a fixed message and never echoes the raw value.
* The bootstrap password comes from a masked terminal prompt. A missing secure
  prompt is an error, not an echo-prone fallback.
* The target database must exist as an absolute file path, so a mistyped path
  cannot create an empty database with an Admin account.
* A successful privileged operation prints only the account UUID and the
  system role outcome. Passwords, token pairs, hashes, and argument namespaces
  never reach the output, and every failure uses one fixed message.
* ``revoke-system-admin`` refuses to remove the last active system
  administrator, and ``deactivate`` refuses to leave any project, archived or
  not, without an active project administrator.
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
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    load_existing_secret_codec,
)
from freesearch.persistence.database_migrations import (
    DatabaseResetRequired,
    absolute_database_path,
)
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
    AuthLastSystemAdmin,
    AuthRoleAssignmentFailed,
    AuthService,
    AuthServiceError,
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

#: The one system role the operator CLI manages.
_SYSTEM_ADMIN: str = "system_admin"

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
    """Return the parser for the privileged account commands."""

    parser = _SafeParser(
        prog="freesearch-users",
        description=(
            "Create a system administrator, grant or revoke the system_admin role, "
            "or deactivate accounts with the project administrator guard (operator only)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser(
        "create-admin",
        help="create one local account with the system_admin role through a masked prompt",
    )
    create.add_argument("--email", required=True, help="email address of the new account")
    create.add_argument(
        "--database",
        type=Path,
        default=None,
        help="existing database file; the shared FREESEARCH_DB precedence applies",
    )
    for command, summary in (
        ("grant-system-admin", "grant the system_admin role to an explicit account UUID"),
        ("revoke-system-admin", "revoke the system_admin role from an explicit account UUID"),
    ):
        role = subparsers.add_parser(command, help=summary)
        role.add_argument("--user-id", required=True, help="account UUID to change")
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

    if isinstance(error, DatabaseResetRequired):
        print(str(error), file=sys.stderr)
        return 1
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
        print("System role: none (the system_admin role was not applied)")
        return 1
    if isinstance(error, AuthLastSystemAdmin):
        print(
            "cannot change: the installation would lose its last active system administrator",
            file=sys.stderr,
        )
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
    if type(error) is AuthServiceError:
        print(str(error), file=sys.stderr)
        return 1
    if isinstance(error, AuthServiceError):
        print("the account database is unavailable", file=sys.stderr)
        return 1
    print(_OPERATION_ERROR, file=sys.stderr)
    return 1


def _secret_store(service: AuthService) -> EncryptedDbSecretStore | None:
    """Return the installation's encrypted store so OAuth flow checks can read initiators.

    The existing master key is loaded without ever creating one. A missing or
    unreadable key gives ``None``, and pending OAuth flows in the affected
    scope then end fail-closed.
    """

    repository = service.repository
    if repository is None:
        return None
    try:
        return EncryptedDbSecretStore(repository, load_existing_secret_codec(service.settings))
    except (OSError, ValueError):
        return None


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
            print(f"System role: {_SYSTEM_ADMIN}")
            return 0
        if options.command == "deactivate":
            repository = service.repository
            if repository is None:
                raise CliError("the account database is unavailable")
            target_ids = [UUID(str(value)) for value in options.user_ids]
            accounts = await ProjectService(
                repository,
                rollout_state=service.settings.projects_rollout_state,
                secret_store=_secret_store(service),
            ).deactivate_accounts(target_ids, trusted=True)
            for deactivated in accounts:
                print(f"Account: {deactivated.id}")
                print("Active: false")
            return 0
        user_id = UUID(str(options.user_id))
        if options.command == "grant-system-admin":
            changed = await service.grant_system_admin(user_id)
            print(f"Account: {user_id}")
            print(f"System role: {_SYSTEM_ADMIN} {'granted' if changed else 'already held'}")
            return 0
        changed = await service.revoke_system_admin(user_id, secret_store=_secret_store(service))
        print(f"Account: {user_id}")
        print(f"System role: {_SYSTEM_ADMIN} {'revoked' if changed else 'not held'}")
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
