"""Shared ISO-8601 date parsing for provider adapters.

Narrow helper sharing the invalid/non-string → ``None`` policy across adapter
``_parse_published_at`` functions. Naive, offset, and microsecond inputs are
preserved exactly as :meth:`datetime.fromisoformat` returns them; only
unparseable or non-string values become ``None``. Billing-period parsing that
assigns UTC to naive dates (Firecrawl credit snapshots) stays separate.
"""

from datetime import datetime
from typing import Any

__all__ = ["parse_iso_datetime"]


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
