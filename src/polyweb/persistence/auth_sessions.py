"""Session-family and refresh-digest persistence.

One family row is an absolute lifetime shared by every access JWT and every
rotated refresh digest issued under it. One refresh row holds the SHA-256 digest
of a single opaque token; the raw token never reaches the database.

The security boundaries are here:

* rotation consumes the presented digest and writes exactly one successor inside
  one transaction, so two concurrent requests cannot both succeed;
* a consumed digest that reappears revokes its whole family before the caller
  returns ``None``;
* a family check always resolves the owning account, so a foreign family id
  cannot authorize an access JWT.

Times are stored as fixed-width UTC ISO-8601 text so the columns compare
lexicographically. Rotation never extends the absolute family expiry.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey, Index, String, Text, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.users import AuthFamily
from polyweb.persistence.storage import Base
from polyweb.persistence.timestamps import parse_timestamp

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def stored_timestamp(value: datetime) -> str:
    """Render one instant as the fixed-width UTC string the columns store."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("auth timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _affected(result: object) -> int:
    """Return the affected-row count of a DML statement result."""

    return int(getattr(result, "rowcount", 0) or 0)


def _is_live(expires_at: str, revoked_at: str | None, now: datetime) -> bool:
    """Return whether a family row is neither revoked nor expired."""

    if revoked_at is not None:
        return False
    return parse_timestamp(expires_at) > now


def _family(row: "AuthSessionRow") -> AuthFamily:
    return AuthFamily(
        id=row.id,
        user_id=row.user_id,
        expires_at=parse_timestamp(row.expires_at),
        revoked_at=parse_timestamp(row.revoked_at) if row.revoked_at else None,
    )


class AuthSessionRow(Base):
    """One refresh-token family: a fixed absolute lifetime per login."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("auth_sessions_user_id", "user_id"),
        Index("auth_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class RefreshTokenRow(Base):
    """One rotated refresh credential, stored as its SHA-256 digest only."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("refresh_tokens_family_id", "family_id"),)

    token_hash: Mapped[str] = mapped_column(String(length=64), primary_key=True, nullable=False)
    family_id: Mapped[UUID] = mapped_column(
        GUID, ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    issued_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    consumed_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuthSessionRepository:
    """Family and digest state transitions bound to one caller-owned session.

    Read helpers leave the commit boundary with the caller, except the reuse
    revocation inside :meth:`get_refresh_family`, whose whole purpose is a
    durable security change. :meth:`consume_and_rotate` owns its own transaction
    because it must commit atomically before any credential leaves the process.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_family(
        self, user_id: UUID, *, expires_at: datetime, now: datetime
    ) -> AuthFamily:
        """Insert one new live family for an account and flush it."""

        row = AuthSessionRow(
            id=uuid4(),
            user_id=user_id,
            created_at=stored_timestamp(now),
            expires_at=stored_timestamp(expires_at),
            revoked_at=None,
        )
        self._session.add(row)
        await self._session.flush()
        return _family(row)

    async def add_refresh(
        self, family_id: UUID, digest: str, *, expires_at: datetime, now: datetime
    ) -> None:
        """Store one refresh digest under its family; the family expiry is unchanged."""

        self._session.add(
            RefreshTokenRow(
                token_hash=digest,
                family_id=family_id,
                issued_at=stored_timestamp(now),
                expires_at=stored_timestamp(expires_at),
                consumed_at=None,
            )
        )
        await self._session.flush()

    async def get_family(
        self, family_id: UUID, *, user_id: UUID, now: datetime
    ) -> AuthFamily | None:
        """Return one live family that belongs to ``user_id``, else ``None``."""

        row = await self._session.get(AuthSessionRow, family_id)
        if row is None or row.user_id != user_id:
            return None
        if not _is_live(row.expires_at, row.revoked_at, now):
            return None
        return _family(row)

    async def get_refresh_family(self, digest: str, *, now: datetime) -> AuthFamily | None:
        """Resolve a refresh digest to its live family, revoking on reuse.

        A consumed digest that reappears is a replay: its whole family is revoked
        before this method returns ``None``, and the revocation is committed here
        so no later auth exception can roll it back. An unknown, expired, or
        already revoked digest also returns ``None`` and stays indistinguishable
        to the caller.
        """

        row = await self._session.get(RefreshTokenRow, digest)
        if row is None:
            return None
        family_row = await self._session.get(AuthSessionRow, row.family_id)
        if family_row is None:
            return None
        if row.consumed_at is not None:
            if family_row.revoked_at is None:
                family_row.revoked_at = stored_timestamp(now)
                await self._session.commit()
            return None
        if not _is_live(family_row.expires_at, family_row.revoked_at, now):
            return None
        return _family(family_row)

    async def consume_and_rotate(
        self, old_digest: str, new_digest: str, *, now: datetime
    ) -> AuthFamily | None:
        """Consume one digest and persist exactly one successor in one transaction.

        The conditional update requires ``consumed_at IS NULL`` and the affected
        row count must be one, so a concurrent rotation of the same digest loses
        here instead of issuing a second credential. The successor keeps the
        family's absolute expiry: rotation never extends a session.
        """

        stamp = stored_timestamp(now)
        row = await self._session.get(RefreshTokenRow, old_digest)
        if row is None:
            await self._session.rollback()
            return None
        family_row = await self._session.get(AuthSessionRow, row.family_id)
        if family_row is None or not _is_live(family_row.expires_at, family_row.revoked_at, now):
            await self._session.rollback()
            return None
        result = await self._session.execute(
            update(RefreshTokenRow)
            .where(RefreshTokenRow.token_hash == old_digest)
            .where(RefreshTokenRow.consumed_at.is_(None))
            .values(consumed_at=stamp)
        )
        if _affected(result) != 1:
            await self._session.rollback()
            return None
        self._session.add(
            RefreshTokenRow(
                token_hash=new_digest,
                family_id=family_row.id,
                issued_at=stamp,
                expires_at=family_row.expires_at,
                consumed_at=None,
            )
        )
        await self._session.commit()
        return _family(family_row)

    async def revoke_family(self, family_id: UUID, *, user_id: UUID, now: datetime) -> None:
        """Revoke one family that belongs to ``user_id``; the caller commits."""

        await self._session.execute(
            update(AuthSessionRow)
            .where(AuthSessionRow.id == family_id)
            .where(AuthSessionRow.user_id == user_id)
            .where(AuthSessionRow.revoked_at.is_(None))
            .values(revoked_at=stored_timestamp(now))
        )

    async def revoke_user_families(self, user_id: UUID, *, now: datetime) -> None:
        """Revoke every live family of one account; the caller commits."""

        await self._session.execute(
            update(AuthSessionRow)
            .where(AuthSessionRow.user_id == user_id)
            .where(AuthSessionRow.revoked_at.is_(None))
            .values(revoked_at=stored_timestamp(now))
        )

    async def delete_expired(self, *, now: datetime, limit: int = 100) -> int:
        """Remove at most ``limit`` expired families and their token rows.

        Consumed digests of a live family are never removed: reuse detection
        depends on them until the family's absolute expiry.
        """

        expired = (
            select(AuthSessionRow.id)
            .where(AuthSessionRow.expires_at <= stored_timestamp(now))
            .limit(max(1, limit))
        )
        family_ids = list((await self._session.scalars(expired)).all())
        if not family_ids:
            return 0
        await self._session.execute(
            delete(RefreshTokenRow).where(RefreshTokenRow.family_id.in_(family_ids))
        )
        result = await self._session.execute(
            delete(AuthSessionRow).where(AuthSessionRow.id.in_(family_ids))
        )
        await self._session.commit()
        return _affected(result)


__all__ = [
    "AuthSessionRepository",
    "AuthSessionRow",
    "RefreshTokenRow",
    "stored_timestamp",
]
