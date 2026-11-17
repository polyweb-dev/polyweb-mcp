"""The shared contract shape helper, in each list mode the contract tests use."""

from typing import Any

import pytest

from tests._support.shape import ListMode, assert_same_shape


@pytest.mark.parametrize(
    ("recorded", "mocked"),
    [
        ({"a": 1, "b": None}, {"a": 1}),
        ({"a": 1}, {"a": "1"}),
        ({"a": None}, {"a": "x"}),
        ({"a": [{"x": 1}]}, {"a": [{"y": 1}]}),
        ({"a": [{"x": 1}]}, {"a": []}),
        ({"a": True}, {"a": 1}),
    ],
)
def test_shape_comparison_rejects_mismatches(recorded: Any, mocked: Any) -> None:
    with pytest.raises(AssertionError):
        assert_same_shape(recorded, mocked)


@pytest.mark.parametrize(
    ("recorded", "mocked"),
    [
        ({"a": 1, "b": None}, {"a": 1}),
        ({"a": 1}, {"a": "1"}),
        ({"a": "x"}, {"a": None}),
        ({"a": [{"x": 1}]}, {"a": [{"y": 1}]}),
        ({"a": [{"x": 1}]}, {"a": []}),
        ({"a": True}, {"a": 1}),
    ],
)
def test_nullable_string_mode_still_rejects_mismatches(recorded: Any, mocked: Any) -> None:
    with pytest.raises(AssertionError):
        assert_same_shape(recorded, mocked, null_accepts_str=True)


def test_nullable_string_mode_accepts_a_string_for_a_recorded_null() -> None:
    assert_same_shape({"a": None}, {"a": "x"}, null_accepts_str=True)


@pytest.mark.parametrize(
    ("recorded", "mocked"),
    [
        ({"a": [{"x": 1}, {"y": 1}]}, {"a": [{"z": 1}]}),
        ({"a": [{"x": 1}]}, {"a": []}),
        ({"a": 1.5}, {"a": "1.5"}),
    ],
)
def test_any_mode_rejects_mismatches(recorded: Any, mocked: Any) -> None:
    with pytest.raises(AssertionError):
        assert_same_shape(recorded, mocked, lists="any")


def test_shape_comparison_accepts_any_recorded_item_shape() -> None:
    assert_same_shape({"a": [{"x": 1}, {"y": 1}]}, {"a": [{"y": 2}, {"x": 3}]}, lists="any")


def test_pairwise_mode_compares_heterogeneous_items_by_position() -> None:
    recorded = {"accepts": [{"scheme": "exact", "x": 1}, {"scheme": "upto", "y": [1]}]}

    assert_same_shape(
        recorded,
        {"accepts": [{"scheme": "a", "x": 2}, {"scheme": "b", "y": [3]}]},
        lists="pairwise",
    )
    with pytest.raises(AssertionError, match=r"\$\.accepts\[0\]"):
        assert_same_shape(
            recorded,
            {"accepts": [{"scheme": "b", "y": [3]}, {"scheme": "a", "x": 2}]},
            lists="pairwise",
        )
    assert_same_shape(recorded, {"accepts": [{"scheme": "a", "x": 2}]}, lists="pairwise")


@pytest.mark.parametrize("lists", ["first", "pairwise", "any"])
def test_every_mode_needs_matching_keys_and_types(lists: ListMode) -> None:
    with pytest.raises(AssertionError, match="keys"):
        assert_same_shape({"a": [{"x": 1}]}, {"a": [{"x": 1, "extra": 2}]}, lists=lists)
