"""UTC calendar boundaries shared by provider budgets and vault pools."""

from datetime import datetime

import pytest

from freesearch.models.budget_period import window_bounds


@pytest.mark.parametrize(
    "instant,period,expected",
    [
        ("2026-11-09T00:30:00+02:00", "day", ("2026-11-08", "2026-11-08")),
        ("2026-11-09T00:30:00+02:00", "week", ("2026-11-02", "2026-11-08")),
        ("2026-11-09T00:00:00+00:00", "week", ("2026-11-09", "2026-11-15")),
        ("2028-02-29T12:00:00+00:00", "month", ("2028-02-01", "2028-02-29")),
        ("2026-12-31T23:00:00+00:00", "month", ("2026-12-01", "2026-12-31")),
    ],
)
def test_calendar_bounds(instant, period, expected) -> None:
    assert window_bounds(datetime.fromisoformat(instant), period) == expected
