"""Fixed-width UTC timestamp text shared by the settled-schema repositories.

Every timestamp column stores ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00`` so values
compare lexicographically in SQL, including the database check constraints
that order two timestamps of one row.
"""

from datetime import UTC, datetime

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def resolve_now(now: datetime | None) -> datetime:
    """Return ``now`` (validated aware) or the current UTC instant."""

    if now is None:
        return datetime.now(UTC)
    require_aware(now)
    return now


def require_aware(value: datetime) -> None:
    """Raise ``ValueError`` for a naive datetime."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


def stored_timestamp(value: datetime) -> str:
    """Render one aware instant as fixed-width UTC text."""

    require_aware(value)
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def optional_timestamp(value: datetime | None) -> str | None:
    """Render an optional aware instant, keeping ``None`` as SQL ``NULL``."""

    return None if value is None else stored_timestamp(value)


def parse_timestamp(value: str) -> datetime:
    """Decode stored timestamp text into an aware UTC datetime."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_optional_timestamp(value: str | None) -> datetime | None:
    """Decode optional stored timestamp text."""

    return None if value is None else parse_timestamp(value)


__all__ = [
    "optional_timestamp",
    "parse_optional_timestamp",
    "parse_timestamp",
    "require_aware",
    "resolve_now",
    "stored_timestamp",
]
