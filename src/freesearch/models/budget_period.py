"""UTC calendar windows shared by provider and pool budgets."""

from datetime import UTC, datetime, timedelta
from typing import Literal

BudgetPeriod = Literal["day", "week", "month"]
PERIOD_SECONDS: dict[BudgetPeriod, int] = {"day": 86400, "week": 604800, "month": 2592000}


def window_start(now: datetime, period_seconds: int | None) -> str:
    """Return the UTC calendar day, Monday week, or month start as an ISO date."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("budget time must be timezone-aware")
    date = now.astimezone(UTC).date()
    if period_seconds == 86400:
        pass
    elif period_seconds == 604800:
        date -= timedelta(days=date.weekday())
    elif period_seconds in (2592000, None):
        date = date.replace(day=1)
    else:
        raise ValueError("invalid budget window")
    return date.isoformat()


def window_bounds(now: datetime, period: BudgetPeriod) -> tuple[str, str]:
    """Return inclusive ISO date bounds using the shared calendar start."""
    start = window_start(now, PERIOD_SECONDS[period])
    date = datetime.fromisoformat(start).date()
    if period == "month":
        end = (date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    else:
        end = date + timedelta(days=0 if period == "day" else 6)
    return start, end.isoformat()
