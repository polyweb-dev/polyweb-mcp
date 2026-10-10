"""Persistent attempt limits for login and public registration.

The counters live in the local SQLite database, so a restart cannot reset an
attacker's budget and two API processes share one allowance. Keys are SHA-256
digests with a purpose prefix, so the stored rows never contain a raw email
address or peer address, and a login key can never collide with a registration
key.

Each helper owns one short transaction and commits it: a reservation must be
durable before password validation or hash work starts, and the transaction must
be released before that expensive work runs.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.users import normalize_email
from freesearch.persistence.users import LoginThrottleRow

#: Q2a limits: five pair attempts and twenty peer-address attempts per window.
LOGIN_WINDOW_SECONDS: int = 900
LOGIN_PAIR_LIMIT: int = 5
LOGIN_PEER_LIMIT: int = 20

#: Q5b limits: five peer attempts and one hundred deployment attempts per window.
REGISTRATION_WINDOW_SECONDS: int = 900
REGISTRATION_PEER_LIMIT: int = 5
REGISTRATION_GLOBAL_LIMIT: int = 100

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def _stamp(value: datetime) -> str:
    """Render one instant as a fixed-width UTC string for lexicographic compare."""

    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _digest(*parts: str) -> str:
    """Return the 64-character SHA-256 key for one counter."""

    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def _pair_key(email: str, peer_address: str) -> str:
    return _digest("login:pair", normalize_email(email), peer_address)


def _peer_key(peer_address: str) -> str:
    return _digest("login:peer", peer_address)


def _registration_peer_key(peer_address: str) -> str:
    return _digest("register:peer", peer_address)


def _registration_global_key() -> str:
    return _digest("register:global", "all")


def _retry_after(expires_at: str, now: datetime) -> int:
    """Return whole seconds until a rejected counter window expires."""

    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return 1
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return max(1, int((expiry - now).total_seconds()) + 1)


async def _reserve(
    session: AsyncSession, key: str, *, limit: int, window_seconds: int, now: datetime
) -> int:
    """Increment one counter atomically; return 0 when accepted, else retry seconds.

    The upsert resets a counter whose window has already expired, so one
    statement both rolls the window and counts the attempt. The conditional update
    plus the re-read count keeps concurrent requests inside one allowance.
    """

    stamp_now = _stamp(now)
    expires_at = _stamp(now + timedelta(seconds=window_seconds))
    statement = sqlite_insert(LoginThrottleRow).values(key=key, attempts=1, expires_at=expires_at)
    statement = statement.on_conflict_do_update(
        index_elements=[LoginThrottleRow.key],
        set_={
            "attempts": case(
                (LoginThrottleRow.expires_at <= stamp_now, 1),
                else_=LoginThrottleRow.attempts + 1,
            ),
            "expires_at": case(
                (LoginThrottleRow.expires_at <= stamp_now, expires_at),
                else_=LoginThrottleRow.expires_at,
            ),
        },
    )
    await session.execute(statement)
    row = await session.get(LoginThrottleRow, key)
    if row is None or row.attempts <= limit:
        return 0
    return _retry_after(row.expires_at, now)


async def reserve_attempt(
    session: AsyncSession, *, email: str, peer_address: str, now: datetime
) -> int | None:
    """Reserve one login attempt; return retry seconds after rejection.

    Both counters count every attempt, including the attempts that later succeed,
    so concurrent requests cannot slip past the failure limit.
    """

    pair_retry = await _reserve(
        session,
        _pair_key(email, peer_address),
        limit=LOGIN_PAIR_LIMIT,
        window_seconds=LOGIN_WINDOW_SECONDS,
        now=now,
    )
    peer_retry = await _reserve(
        session,
        _peer_key(peer_address),
        limit=LOGIN_PEER_LIMIT,
        window_seconds=LOGIN_WINDOW_SECONDS,
        now=now,
    )
    await session.commit()
    return max(pair_retry, peer_retry) or None


async def clear_pair(session: AsyncSession, *, email: str, peer_address: str) -> None:
    """Clear one pair counter after a successful active local login.

    The peer-address counter deliberately survives success: it limits the total
    address volume for the window, not the failures of one account.
    """

    await session.execute(
        delete(LoginThrottleRow).where(LoginThrottleRow.key == _pair_key(email, peer_address))
    )
    await session.commit()


async def reserve_registration_attempt(
    session: AsyncSession, *, peer_address: str, now: datetime
) -> int | None:
    """Reserve one public registration; return retry seconds after rejection.

    The peer counter and the deployment-wide counter are reserved in one
    transaction before any schema validation or password hash work. A successful
    registration clears neither counter.
    """

    peer_retry = await _reserve(
        session,
        _registration_peer_key(peer_address),
        limit=REGISTRATION_PEER_LIMIT,
        window_seconds=REGISTRATION_WINDOW_SECONDS,
        now=now,
    )
    global_retry = await _reserve(
        session,
        _registration_global_key(),
        limit=REGISTRATION_GLOBAL_LIMIT,
        window_seconds=REGISTRATION_WINDOW_SECONDS,
        now=now,
    )
    await session.commit()
    return max(peer_retry, global_retry) or None


async def delete_expired(session: AsyncSession, *, now: datetime, limit: int = 100) -> int:
    """Remove at most ``limit`` expired counters and commit that bounded cleanup."""

    expired = (
        select(LoginThrottleRow.key)
        .where(LoginThrottleRow.expires_at <= _stamp(now))
        .limit(max(1, limit))
    )
    result = await session.execute(
        delete(LoginThrottleRow).where(LoginThrottleRow.key.in_(expired))
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "LOGIN_PAIR_LIMIT",
    "LOGIN_PEER_LIMIT",
    "LOGIN_WINDOW_SECONDS",
    "REGISTRATION_GLOBAL_LIMIT",
    "REGISTRATION_PEER_LIMIT",
    "REGISTRATION_WINDOW_SECONDS",
    "clear_pair",
    "delete_expired",
    "reserve_attempt",
    "reserve_registration_attempt",
]
