"""Provider access masks shared by configuration, persistence, and transports.

This module is pure: it holds no I/O, no models, and no provider knowledge.

An enable mask stores the administrator choice. A support mask stores the
system tool support. Effective access is the bitwise AND of both masks. Bit 0
is global access, bit 1 is search access, and bit 2 is fetch access. Bits above
bit 2 are reserved.
"""

GLOBAL_BIT: int = 1
SEARCH_BIT: int = 2
FETCH_BIT: int = 4
ALL_BITS: int = GLOBAL_BIT | SEARCH_BIT | FETCH_BIT


def validate_mask(value: object, *, field: str) -> int:
    """Return ``value`` as an access mask.

    The mask must be an integer from 0 through 7. A Boolean, float, string,
    negative, null, or unknown-bit value is not accepted.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer mask")
    if value < 0 or value > ALL_BITS:
        raise ValueError(f"{field} must be an integer mask from 0 through {ALL_BITS}")
    return value


def is_operation_enabled(enable_mask: int, support_mask: int, operation: str) -> bool:
    """Return the effective access for one operation.

    Search needs the global bit and the search bit in both masks. Fetch needs
    the global bit and the fetch bit in both masks. Every other operation
    returns ``False``. Global OFF blocks search and fetch.
    """

    effective = enable_mask & support_mask
    if (effective & GLOBAL_BIT) == 0:
        return False
    if operation == "search":
        return (effective & (GLOBAL_BIT | SEARCH_BIT)) == (GLOBAL_BIT | SEARCH_BIT)
    if operation == "fetch":
        return (effective & (GLOBAL_BIT | FETCH_BIT)) == (GLOBAL_BIT | FETCH_BIT)
    return False


def support_mask_from_capabilities(
    *, search: bool, fetch: bool, global_supported: bool = True
) -> int:
    """Return a support mask built from adapter capabilities."""

    mask = 0
    if global_supported:
        mask |= GLOBAL_BIT
    if search:
        mask |= SEARCH_BIT
    if fetch:
        mask |= FETCH_BIT
    return mask
