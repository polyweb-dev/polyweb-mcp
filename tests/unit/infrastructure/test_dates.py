"""Unit tests for the shared ISO-8601 date helper."""

from datetime import UTC, datetime, timedelta

from freesearch.infrastructure.dates import parse_iso_datetime


def test_parse_iso_datetime_accepts_z_as_utc() -> None:
    parsed = parse_iso_datetime("2025-01-02T03:04:05Z")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(0)


def test_parse_iso_datetime_preserves_offset_naive_and_microseconds() -> None:
    offset = parse_iso_datetime("2025-06-07T08:09:10+02:00")
    assert offset is not None
    assert offset.utcoffset() == timedelta(hours=2)

    naive = parse_iso_datetime("2025-06-07T08:09:10")
    assert naive == datetime(2025, 6, 7, 8, 9, 10)
    assert naive is not None and naive.tzinfo is None

    micro = parse_iso_datetime("2025-06-07T08:09:10.123456Z")
    assert micro is not None
    assert micro.microsecond == 123456
    assert micro.tzinfo == UTC


def test_parse_iso_datetime_rejects_invalid_and_non_string() -> None:
    assert parse_iso_datetime("not-a-date") is None
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime(None) is None
    assert parse_iso_datetime(123) is None
    assert parse_iso_datetime(["2025-01-02"]) is None
