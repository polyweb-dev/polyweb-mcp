"""Operator CLI for master-key rotation of the encrypted secret store.

``status`` reports the primary key id and value-free envelope counts and
exits nonzero while anything still needs rekeying or is undecryptable.
``rekey`` rewrites every legacy or retired-key envelope under the primary key
inside one transaction; ``--dry-run`` reports without writing. No command
ever prints a secret value or key material.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.encrypted_store import (
    RekeyReport,
    load_secret_codec,
    rekey_secrets,
)
from freesearch.persistence.database_migrations import DatabaseResetRequired
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.monitoring import DB_ENV_VAR, DEFAULT_DB_FILENAME, resolve_database_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freesearch-secrets",
        description="Inspect or rotate the master key of the encrypted secret store.",
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
    subparsers.add_parser("status", help="report key id and rekey counts")
    rekey = subparsers.add_parser("rekey", help="re-encrypt stored envelopes under the primary key")
    rekey.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing",
    )
    return parser


def _print_counts(report: RekeyReport, *, primary_key_id: str) -> None:
    print(f"Primary key id: {primary_key_id}")
    print(f"Secret slots: {report.total}")
    print(f"Current envelopes: {report.current}")
    print(f"Rekeyed envelopes: {report.rekeyed}")
    print(f"Legacy v1 upgraded: {report.legacy_upgraded}")
    print(f"Undecryptable rows: {report.undecryptable}")


def _run(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    database = resolve_database_path(options.database)
    codec = load_secret_codec(get_settings())

    async def _status() -> int:
        repository = await SQLiteRepository.open(database)
        try:
            report = await rekey_secrets(repository, codec, dry_run=True)
        finally:
            await repository.close()
        _print_counts(report, primary_key_id=codec.primary_key_id)
        return 0 if report.rekeyed == 0 and report.undecryptable == 0 else 1

    async def _rekey(*, dry_run: bool) -> int:
        repository = await SQLiteRepository.open(database)
        try:
            report = await rekey_secrets(repository, codec, dry_run=dry_run)
        finally:
            await repository.close()
        _print_counts(report, primary_key_id=codec.primary_key_id)
        if dry_run:
            print("Dry run: no envelopes were rewritten")
        return 0 if report.undecryptable == 0 else 1

    try:
        if options.command == "status":
            return asyncio.run(_status())
        return asyncio.run(_rekey(dry_run=options.dry_run))
    except DatabaseResetRequired as error:
        print(str(error), file=sys.stderr)
        return 1


def main() -> None:
    """Run the secrets command and return its status to the shell."""

    raise SystemExit(_run())


if __name__ == "__main__":
    main()
