"""Command-line migration operations for the FreeSearch SQLite database."""

import argparse
import sys
from pathlib import Path

from freesearch.persistence.database_migrations import (
    DatabaseMigrationError,
    DatabaseResetRequired,
    database_reset_message,
    database_status,
    upgrade_database,
)
from freesearch.services.monitoring import DB_ENV_VAR, DEFAULT_DB_FILENAME, resolve_database_path


def _selected_database(explicit: Path | None) -> Path:
    """Resolve the target database through the shared precedence rule.

    Precedence: the process ``FREESEARCH_DB`` variable, an explicit ``--database``
    argument, the local environment file, then the filename default.
    """

    return resolve_database_path(explicit)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freesearch-db",
        description="Inspect or create the FreeSearch SQLite schema.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help=(
            f"database path; {DB_ENV_VAR} takes precedence when set "
            f"(default: {DEFAULT_DB_FILENAME})"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="inspect revision and schema without changing data")
    subparsers.add_parser(
        "upgrade",
        help="create a missing or empty database at the alpha baseline, or validate it",
    )
    return parser


def _status(database: Path) -> int:
    status = database_status(database)
    revision = status.current_revision or "unversioned"
    print(f"Database: {status.database}")
    print(f"Revision: {revision} (head: {status.head_revision})")
    if status.schema_valid:
        print("Schema: valid")
        return 0
    reset_message = database_reset_message(database)
    if reset_message is not None:
        print("Schema: reset required")
        print(reset_message, file=sys.stderr)
        return 1
    if status.current_revision is None:
        print("Schema: not created (will be created on first start)")
        return 1
    print("Schema: invalid")
    return 1


def _upgrade(database: Path) -> int:
    try:
        result = upgrade_database(database)
    except DatabaseResetRequired as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Database: {result.database}")
    print(f"Revision: {result.current_revision}")
    print("Schema: created" if result.changed else "Schema: already current")
    return 0


def _run(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    database = _selected_database(options.database)
    try:
        if options.command == "status":
            return _status(database)
        return _upgrade(database)
    except DatabaseMigrationError as error:
        print(str(error), file=sys.stderr)
        return 1


def main() -> None:
    """Run the database command and return its status to the shell."""

    raise SystemExit(_run())


if __name__ == "__main__":
    main()
