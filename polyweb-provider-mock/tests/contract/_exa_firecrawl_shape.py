"""Recursive JSON shape comparison for the Exa and Firecrawl contract tests.

Unlike the Tavily helper, a list compares item by item when both lists have
the same length: the Exa x402 ``accepts`` options and the Firecrawl zod
union branches are lists of differently shaped objects. Lists of another
length compare every mock item with the first recorded item.
"""

from typing import Any

__all__ = ["assert_same_shape"]


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def assert_same_shape(recorded: Any, mocked: Any, path: str = "$") -> None:
    """Assert equal keys and value types recursively."""

    assert _kind(mocked) == _kind(recorded), f"{path}: {_kind(mocked)} != {_kind(recorded)}"
    if isinstance(recorded, dict):
        assert set(mocked) == set(recorded), f"{path}: keys {sorted(mocked)} != {sorted(recorded)}"
        for key, value in recorded.items():
            assert_same_shape(value, mocked[key], f"{path}.{key}")
    elif isinstance(recorded, list) and recorded:
        assert mocked, f"{path}: the mock returned an empty list"
        pairwise = len(mocked) == len(recorded)
        for index, item in enumerate(mocked):
            assert_same_shape(recorded[index if pairwise else 0], item, f"{path}[{index}]")
