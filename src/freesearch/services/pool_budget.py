"""Atomic calendar-window budget reservations for vault pools."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DAY = 86400
_WEEK = 604800
_MONTH = 2592000


def window_start(now: datetime, period_seconds: int | None) -> str:
    """Return the UTC calendar day, Monday week, or month start as an ISO date."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("budget time must be timezone-aware")
    date = now.astimezone(UTC).date()
    if period_seconds == _DAY:
        pass
    elif period_seconds == _WEEK:
        date -= timedelta(days=date.weekday())
    elif period_seconds in (_MONTH, None):
        date = date.replace(day=1)
    else:
        raise ValueError("invalid budget window")
    return date.isoformat()


async def reserve_with_window(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Reserve against the current cap atomically; return its actual window for refunds."""
    if cost_micros < 0:
        raise ValueError("cost must be nonnegative")
    instant = now or datetime.now(UTC)
    params = {
        "pool": str(pool_id),
        "cost": cost_micros,
        "day": window_start(instant, _DAY),
        "week": window_start(instant, _WEEK),
        "month": window_start(instant, _MONTH),
        "updated": instant.astimezone(UTC).isoformat(),
    }
    result = await session.execute(
        text(
            "INSERT INTO pool_budget_usage (pool_id,window_start,spent_micros,updated_at) "
            "SELECT id, CASE budget_window_seconds WHEN 86400 THEN :day "
            "WHEN 604800 THEN :week ELSE :month END, :cost, :updated FROM key_pools "
            "WHERE id=:pool AND budget_limit IS NOT NULL AND :cost <= budget_limit "
            "ON CONFLICT(pool_id,window_start) DO UPDATE SET "
            "spent_micros=pool_budget_usage.spent_micros + excluded.spent_micros, "
            "updated_at=excluded.updated_at WHERE pool_budget_usage.spent_micros <= "
            "(SELECT budget_limit FROM key_pools WHERE id=:pool) - excluded.spent_micros "
            "RETURNING window_start"
        ),
        params,
    )
    row = result.first()
    if row is not None:
        return True, str(row[0])
    cap = await session.execute(text("SELECT budget_limit FROM key_pools WHERE id=:pool"), params)
    row = cap.first()
    if row is None:
        raise ValueError("vault pool no longer exists")
    return row[0] is None, None


async def reserve(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, now: datetime | None = None
) -> bool:
    """Reserve cost in the caller's transaction, or refuse an exhausted budget."""
    allowed, _ = await reserve_with_window(session, pool_id, cost_micros, now=now)
    return allowed


async def release(
    session: AsyncSession, pool_id: UUID, cost_micros: int, *, window_start: str
) -> None:
    """Refund an unsent call in its original window."""
    if cost_micros < 0:
        raise ValueError("cost must be nonnegative")
    await session.execute(
        text(
            "UPDATE pool_budget_usage SET spent_micros=spent_micros-:cost, updated_at=:updated "
            "WHERE pool_id=:pool AND window_start=:window AND spent_micros >= :cost"
        ),
        {
            "pool": str(pool_id),
            "window": window_start,
            "cost": cost_micros,
            "updated": datetime.now(UTC).isoformat(),
        },
    )


async def pool_budget_used_micros(
    session: AsyncSession, pool_id: UUID, *, now: datetime | None = None
) -> int:
    """Return spend in the pool's currently configured calendar window."""
    instant = now or datetime.now(UTC)
    result = await session.execute(
        text(
            "SELECT COALESCE(u.spent_micros, 0) FROM key_pools p "
            "LEFT JOIN pool_budget_usage u ON u.pool_id=p.id AND u.window_start="
            "CASE p.budget_window_seconds WHEN 86400 THEN :day WHEN 604800 THEN :week "
            "ELSE :month END WHERE p.id=:pool"
        ),
        {
            "pool": str(pool_id),
            "day": window_start(instant, _DAY),
            "week": window_start(instant, _WEEK),
            "month": window_start(instant, _MONTH),
        },
    )
    return int(result.scalar_one_or_none() or 0)
