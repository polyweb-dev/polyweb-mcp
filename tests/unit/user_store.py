"""In-memory account store shared by the account-creation unit tests.

Only the ``user`` table exists. A real SQLite engine is used so uniqueness and
rollback behavior come from the database, not from a hand-built constraint
error. Nothing here touches a file, a server, or a provider.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from polyweb.persistence.users import UserRow


class MemoryRepository:
    """Stand-in for ``SQLiteRepository`` exposing only ``session()``."""

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._maker() as session:
            yield session


@asynccontextmanager
async def user_store() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory over a fresh in-memory ``user`` table."""

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(UserRow.__table__.create)  # type: ignore[attr-defined]
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def user_count(maker: async_sessionmaker[AsyncSession]) -> int:
    """Return the committed number of accounts, read through a fresh session."""

    async with maker() as session:
        return int((await session.execute(select(func.count()).select_from(UserRow))).scalar_one())
