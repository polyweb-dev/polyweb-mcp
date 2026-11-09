"""Unit coverage for pure provider access masks.

No database, transport, or adapter imports: constants, strict mask
validation, effective search/fetch decode over all mask pairs, unsupported
operation rejection, and capability-to-mask conversion.
"""

import pytest

from polyweb.models.provider_access import (
    ALL_BITS,
    FETCH_BIT,
    GLOBAL_BIT,
    SEARCH_BIT,
    is_operation_enabled,
    support_mask_from_capabilities,
    validate_mask,
)


def test_access_bit_constants_match_contract() -> None:
    assert GLOBAL_BIT == 1
    assert SEARCH_BIT == 2
    assert FETCH_BIT == 4
    assert ALL_BITS == 7


@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 5, 6, 7])
def test_validate_mask_accepts_all_values_in_range(value: int) -> None:
    assert validate_mask(value, field="enable_mask") == value


@pytest.mark.parametrize(
    "value",
    [True, False, 1.0, 0.0, "7", "3", None, -1, -7, 8, 9, 255],
)
def test_validate_mask_rejects_non_integer_or_out_of_range(value: object) -> None:
    with pytest.raises(ValueError):
        validate_mask(value, field="enable_mask")


def test_validate_mask_rejects_bool_even_when_value_matches_bit() -> None:
    with pytest.raises(ValueError):
        validate_mask(True, field="support_mask")
    with pytest.raises(ValueError):
        validate_mask(False, field="support_mask")


@pytest.mark.parametrize("enable_mask", range(8))
@pytest.mark.parametrize("support_mask", range(8))
@pytest.mark.parametrize("operation", ["search", "fetch"])
def test_is_operation_enabled_matches_bitwise_contract(
    enable_mask: int, support_mask: int, operation: str
) -> None:
    effective = enable_mask & support_mask
    if operation == "search":
        expected = (effective & (GLOBAL_BIT | SEARCH_BIT)) == (GLOBAL_BIT | SEARCH_BIT)
    else:
        expected = (effective & (GLOBAL_BIT | FETCH_BIT)) == (GLOBAL_BIT | FETCH_BIT)

    assert is_operation_enabled(enable_mask, support_mask, operation) is expected


def test_global_off_blocks_both_tools_despite_tool_bits() -> None:
    assert is_operation_enabled(6, 7, "search") is False
    assert is_operation_enabled(6, 7, "fetch") is False
    assert is_operation_enabled(7, 6, "search") is False


def test_tool_off_affects_only_that_tool() -> None:
    assert is_operation_enabled(5, 7, "search") is False
    assert is_operation_enabled(5, 7, "fetch") is True
    assert is_operation_enabled(3, 7, "search") is True
    assert is_operation_enabled(3, 7, "fetch") is False


def test_unsupported_tool_stays_off_when_admin_bit_is_on() -> None:
    assert is_operation_enabled(7, 3, "fetch") is False
    assert is_operation_enabled(7, 3, "search") is True


@pytest.mark.parametrize("operation", ["", "cost_estimate", "quota", "SEARCH", "Fetch", "unknown"])
@pytest.mark.parametrize("enable_mask", [0, 3, 7])
@pytest.mark.parametrize("support_mask", [0, 3, 7])
def test_unsupported_operation_always_returns_false(
    enable_mask: int, support_mask: int, operation: str
) -> None:
    assert is_operation_enabled(enable_mask, support_mask, operation) is False


def test_support_mask_from_capabilities_brave_mapping() -> None:
    assert support_mask_from_capabilities(search=True, fetch=False) == 3


def test_support_mask_from_capabilities_full_mapping() -> None:
    assert support_mask_from_capabilities(search=True, fetch=True) == 7


def test_support_mask_from_capabilities_partial_and_global_flags() -> None:
    assert support_mask_from_capabilities(search=False, fetch=False) == 1
    assert support_mask_from_capabilities(search=False, fetch=True) == 5
    assert support_mask_from_capabilities(search=True, fetch=True, global_supported=False) == 6
    assert support_mask_from_capabilities(search=False, fetch=False, global_supported=False) == 0
