"""Calendar UTC budget window boundaries."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from freesearch.services.pool_budget import window_start


@pytest.mark.parametrize(
    ("instant", "period", "expected"),
    [
        (datetime(2024, 3, 1, tzinfo=UTC), 86400, "2024-03-01"),
        (datetime(2024, 3, 1, 1, tzinfo=timezone(timedelta(hours=2))), 86400, "2024-02-29"),
        (datetime(2024, 3, 3, 23, 59, tzinfo=UTC), 604800, "2024-02-26"),
        (datetime(2024, 3, 4, tzinfo=UTC), 604800, "2024-03-04"),
        (datetime(2024, 2, 29, 23, 59, tzinfo=UTC), 2592000, "2024-02-01"),
        (datetime(2024, 3, 1, tzinfo=UTC), None, "2024-03-01"),
    ],
)
def test_calendar_window_start(instant: datetime, period: int | None, expected: str) -> None:
    assert window_start(instant, period) == expected


def test_window_rejects_naive_time_and_unknown_period() -> None:
    with pytest.raises(ValueError):
        window_start(datetime(2024, 1, 1), 86400)
    with pytest.raises(ValueError):
        window_start(datetime(2024, 1, 1, tzinfo=UTC), 1)
