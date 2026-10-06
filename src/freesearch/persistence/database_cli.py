"""Command-line migration operations for the FreeSearch SQLite database."""

import argparse
from pathlib import Path

from freesearch.persistence.database_migrations import database_status, upgrade_database
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
        description="Inspect or upgrade the FreeSearch SQLite schema.",
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
        "upgrade", help="back up an existing database and upgrade it to Alembic head"
    )
    return parser


def _run(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    database = _selected_database(options.database)
    if options.command == "status":
        status = database_status(database)
        revision = status.current_revision or "unversioned"
        validity = "valid" if status.schema_valid else "upgrade required"
        print(f"Database: {status.database}")
        print(f"Revision: {revision} (head: {status.head_revision})")
        print(f"Schema: {validity}")
        return 0 if status.schema_valid else 1

    result = upgrade_database(database)
    print(f"Database: {result.database}")
    print(f"Revision: {result.current_revision}")
    if result.backup is not None:
        print(f"Backup: {result.backup}")
    print("Schema: upgraded" if result.changed else "Schema: already current")
    return 0


def main() -> None:
    """Run the database command and return its status to the shell."""

    raise SystemExit(_run())


if __name__ == "__main__":
    main()
