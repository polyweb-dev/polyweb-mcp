"""Unit tests for the account-creation transaction of ``UserDatabase``.

TASK-000065 signup extension: ``UserDatabase`` accepts an optional
``on_created(session, user)`` callback. It runs after the new row is flushed and
before the single commit, so everything it writes shares the account's
transaction. Only a failure of the user flush means "account already exists";
a failure of the callback or of the commit must roll back and surface unchanged.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi_users import exceptions
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.user_store import user_count, user_store

from polyweb.persistence.users import UserDatabase, UserRow


def _payload(email: str = "new@example.com") -> dict[str, Any]:
    return {"email": email, "hashed_password": "hashed-by-the-manager"}


async def test_on_created_sees_the_flushed_uncommitted_account() -> None:
    seen: list[tuple[bool, bool, str]] = []

    async def on_created(session: AsyncSession, user: UserRow) -> None:
        # ``id`` is assigned by the flush; nothing is left pending; and the hook
        # still shares the open transaction of the creating session.
        seen.append((user.id is not None, not session.new, user.email))
        assert session.in_transaction()
        assert user in session

    async with user_store() as maker:
        async with maker() as session:
            created = await UserDatabase(session, UserRow, on_created=on_created).create(
                _payload("Mixed.Case@Example.com")
            )
        assert seen == [(True, True, "mixed.case@example.com")]
        assert await user_count(maker) == 1
        async with maker() as session:
            stored = (await session.execute(select(UserRow))).scalar_one()
        assert stored.id == created.id


async def test_on_created_failure_rolls_back_the_account_without_relabeling() -> None:
    async def on_created(session: AsyncSession, user: UserRow) -> None:
        raise RuntimeError("workspace provisioning failed")

    async with user_store() as maker:
        async with maker() as session:
            database = UserDatabase(session, UserRow, on_created=on_created)
            with pytest.raises(RuntimeError, match="workspace provisioning failed"):
                await database.create(_payload())
        assert await user_count(maker) == 0


async def test_unique_conflict_raised_by_on_created_is_not_a_duplicate_account() -> None:
    """A late uniqueness failure belongs to the callback, not to the email."""

    async def on_created(session: AsyncSession, user: UserRow) -> None:
        # A genuine database uniqueness failure raised from inside the callback.
        session.add(UserRow(id=uuid4(), email=user.email.upper(), hashed_password="x"))
        await session.flush()

    async with user_store() as maker:
        async with maker() as session:
            database = UserDatabase(session, UserRow, on_created=on_created)
            with pytest.raises(IntegrityError) as caught:
                await database.create(_payload())
        assert not isinstance(caught.value, exceptions.UserAlreadyExists)
        assert await user_count(maker) == 0


async def test_unique_conflict_on_the_user_flush_is_a_duplicate_and_skips_on_created() -> None:
    created_ids: list[object] = []

    async def on_created(session: AsyncSession, user: UserRow) -> None:
        created_ids.append(user.id)

    async with user_store() as maker:
        async with maker() as session:
            first = await UserDatabase(session, UserRow, on_created=on_created).create(
                _payload("dup@example.com")
            )
        async with maker() as session:
            database = UserDatabase(session, UserRow, on_created=on_created)
            with pytest.raises(exceptions.UserAlreadyExists):
                await database.create(_payload("DUP@example.com"))
        # The rejected duplicate provisions nothing and leaves the first account intact.
        assert created_ids == [first.id]
        assert await user_count(maker) == 1


async def test_commit_failure_is_rolled_back_and_not_relabeled_as_duplicate() -> None:
    class _DriverUniqueError(Exception):
        """Driver error whose text looks like a uniqueness conflict."""

    async def on_created(session: AsyncSession, user: UserRow) -> None:
        return None

    async with user_store() as maker:
        async with maker() as session:

            async def failing_commit() -> None:
                raise IntegrityError(
                    "COMMIT", {}, _DriverUniqueError("UNIQUE constraint failed: late.slug")
                )

            session.commit = failing_commit  # type: ignore[method-assign]
            database = UserDatabase(session, UserRow, on_created=on_created)
            with pytest.raises(IntegrityError) as caught:
                await database.create(_payload())
        assert not isinstance(caught.value, exceptions.UserAlreadyExists)
        assert await user_count(maker) == 0


async def test_create_trusted_never_runs_on_created() -> None:
    """Trusted seeding and raw fixtures stay bare even on a provisioning database."""

    calls: list[object] = []

    async def on_created(session: AsyncSession, user: UserRow) -> None:
        calls.append(user.id)

    async with user_store() as maker:
        async with maker() as session:
            await UserDatabase(session, UserRow, on_created=on_created).create_trusted(
                email="seed@example.com", hashed_password="hashed"
            )
        assert calls == []
        assert await user_count(maker) == 1
