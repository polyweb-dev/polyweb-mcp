"""Serialized SQLite write transactions shared by the control-plane services.

One helper owns the mechanics every mutating service repeated: a fresh
session, ``BEGIN IMMEDIATE`` to take the SQLite write lock before any read,
the caller's operation, then commit. Any error or cancellation rolls back.
Only a SQLite lock/busy failure is retried, a bounded number of times with
the exponential ``0.02 * 2**attempt`` second backoff; every other exception
propagates unchanged so each service keeps its own domain mapping
(last-admin, revision, generation, slot and label conflicts).

The operation may run more than once. It must therefore be a pure database
unit: no vendor or network I/O, and no externally visible one-time delivery,
belongs inside it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.persistence.storage import SQLiteRepository

#: Default number of attempts for one serialized write.
DEFAULT_WRITE_ATTEMPTS: Final[int] = 5
#: Base of the exponential lock backoff, in seconds.
LOCK_BACKOFF_BASE_SECONDS: Final[float] = 0.02

type SerializedOperation[T] = Callable[[AsyncSession], Awaitable[T]]


def is_sqlite_lock_error(error: OperationalError) -> bool:
    """Return whether ``error`` is SQLite reporting a held lock or busy database."""

    message = str(error.orig).lower()
    return "database is locked" in message or "database table is locked" in message


async def run_serialized[T](
    repository: SQLiteRepository,
    operation: SerializedOperation[T],
    *,
    max_attempts: int = DEFAULT_WRITE_ATTEMPTS,
) -> T:
    """Run ``operation`` in one ``BEGIN IMMEDIATE`` transaction and commit it.

    A fresh session serves every attempt. A lock/busy ``OperationalError`` is
    retried until ``max_attempts`` is spent and then re-raised; any other
    exception, including ``asyncio.CancelledError``, rolls back and propagates
    on the first occurrence.
    """

    attempts = max(1, max_attempts)
    for attempt in range(attempts):
        async with repository.session() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                result = await operation(session)
                await session.commit()
                return result
            except OperationalError as error:
                await session.rollback()
                if is_sqlite_lock_error(error) and attempt + 1 < attempts:
                    await asyncio.sleep(LOCK_BACKOFF_BASE_SECONDS * (2**attempt))
                    continue
                raise
            except BaseException:
                await session.rollback()
                raise
    raise AssertionError("unreachable: the final attempt returns or raises")  # pragma: no cover


__all__ = [
    "DEFAULT_WRITE_ATTEMPTS",
    "LOCK_BACKOFF_BASE_SECONDS",
    "SerializedOperation",
    "is_sqlite_lock_error",
    "run_serialized",
]
