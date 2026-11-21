"""Recursive JSON shape comparison for the contract tests.

Two values have the same shape when they have the same JSON type and, for
objects, the same keys with values of the same shape. Values may differ.
Lists compare item by item according to ``lists``:

- ``"first"``: every mock item matches the first recorded item;
- ``"pairwise"``: lists of the same length compare item ``i`` with recorded
  item ``i`` (heterogeneous lists such as the Exa x402 ``accepts`` options or
  the Firecrawl zod union branches); other lengths compare with the first;
- ``"any"``: every mock item matches at least one recorded item.

``null_accepts_str`` lets a recorded ``null`` stand for an optional string.
"""

from typing import Any, Literal

__all__ = ["ListMode", "assert_same_shape", "json_kind"]

ListMode = Literal["first", "pairwise", "any"]


def json_kind(value: Any) -> str:
    """Return the JSON type name of a decoded value."""

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _matches(recorded: Any, mocked: Any, path: str, **options: Any) -> bool:
    try:
        assert_same_shape(recorded, mocked, path, **options)
    except AssertionError:
        return False
    return True


def assert_same_shape(
    recorded: Any,
    mocked: Any,
    path: str = "$",
    *,
    lists: ListMode = "first",
    null_accepts_str: bool = False,
) -> None:
    """Assert that ``mocked`` has the shape of ``recorded``; see the module docstring."""

    options: dict[str, Any] = {"lists": lists, "null_accepts_str": null_accepts_str}
    if null_accepts_str and recorded is None and isinstance(mocked, str):
        return
    assert json_kind(mocked) == json_kind(recorded), (
        f"{path}: {json_kind(mocked)} != {json_kind(recorded)}"
    )
    if isinstance(recorded, dict):
        assert set(mocked) == set(recorded), f"{path}: keys {sorted(mocked)} != {sorted(recorded)}"
        for key, value in recorded.items():
            assert_same_shape(value, mocked[key], f"{path}.{key}", **options)
        return
    if not isinstance(recorded, list) or not recorded:
        return
    assert mocked, f"{path}: the mock returned an empty list"
    pairwise = lists == "pairwise" and len(mocked) == len(recorded)
    for index, item in enumerate(mocked):
        where = f"{path}[{index}]"
        if lists == "any" and any(_matches(other, item, where, **options) for other in recorded):
            continue
        assert_same_shape(recorded[index if pairwise else 0], item, where, **options)
