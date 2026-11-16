"""Pure value helpers of the limit repository: no database."""

from decimal import Decimal

import pytest

from polyweb.persistence.limit_repository import _decimal, _decode_detail


@pytest.mark.parametrize("text", ["NaN", "-NaN", "sNaN", "Infinity", "-Infinity", "inf"])
def test_stored_non_finite_decimal_reads_as_absent(text: str) -> None:
    """A12: a legacy event value that is not a finite number is treated as absent."""

    assert _decimal(text) is None


@pytest.mark.parametrize(("text", "value"), [("960", Decimal("960")), ("0.25", Decimal("0.25"))])
def test_stored_exact_decimal_reads_back(text: str, value: Decimal) -> None:
    assert _decimal(text) == value


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '"text"', ""])
def test_unreadable_event_detail_reads_as_empty(text: str) -> None:
    """A12: a malformed legacy detail payload is absent, never an error."""

    assert _decode_detail(text) == {}
