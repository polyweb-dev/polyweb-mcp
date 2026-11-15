"""Shared date parsing and calendar-month helpers for provider adapters.

Narrow helper sharing the invalid/non-string → ``None`` policy across adapter
``_parse_published_at`` functions. Naive, offset, and microsecond inputs are
preserved exactly as :meth:`datetime.fromisoformat` returns them; only
unparseable or non-string values become ``None``. Billing-period parsing that
assigns UTC to naive dates (Firecrawl credit snapshots) stays separate.

``month_start`` and ``next_month_start`` give the UTC calendar-month bounds the
monthly-ledger adapters (Brave, Exa, Keenable, Parallel) share.
"""

from datetime import UTC, datetime
from typing import Any

__all__ = ["month_start", "next_month_start", "parse_iso_datetime"]


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string; non-string or unparseable values are ``None``."""
    if not isinstance(value, str):
        return None
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def month_start(value: datetime) -> datetime:
    """Return the first instant of ``value``'s calendar month in UTC."""
    return datetime(value.year, value.month, 1, tzinfo=UTC)


def next_month_start(value: datetime) -> datetime:
    """Return the first instant of the calendar month after ``value`` in UTC."""
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=UTC)
    return datetime(value.year, value.month + 1, 1, tzinfo=UTC)
