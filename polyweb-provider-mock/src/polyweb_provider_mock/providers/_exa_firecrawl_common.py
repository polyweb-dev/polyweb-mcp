"""Helpers shared by the Exa and Firecrawl plugins.

Discovery skips modules whose name starts with ``_``, so this module exports
no ``PLUGIN``. Both helpers are candidates for the core plugin interface.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from polyweb_provider_mock import content
from polyweb_provider_mock.providers.base import OperationContext
from polyweb_provider_mock.store import Charge, QuotaExhausted

__all__ = ["charge_all", "iso_ms", "schema_value"]


def iso_ms(value: datetime) -> str:
    """Render a UTC timestamp with milliseconds and ``Z``, as JavaScript does."""

    value = value.astimezone(UTC)
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 1000:03d}Z"


def charge_all(context: OperationContext, parts: Sequence[tuple[str, int]]) -> list[Charge]:
    """Debit the priced parts of one request, all or nothing.

    The store checks funds per debit, so a request billed in several parts
    could otherwise be half debited. The whole cost is checked first, then
    every part with a non-zero count is charged. Keyless principals have no
    account and are never refused here.
    """

    merged: dict[str, int] = {}
    for operation, units in parts:
        if units > 0:
            merged[operation] = merged.get(operation, 0) + units
    total = Decimal(0)
    for operation, units in merged.items():
        rule = context.store.price(context.plugin.name, operation)
        total += Decimal(0) if rule is None else rule.credits_per_unit * units
    account, key = context.principal.account, context.principal.key
    if account is not None and account.credit_limit is not None:
        left = account.credit_limit - account.credits_used
        if left <= 0 or total > left:
            raise QuotaExhausted("account")
    if key is not None and key.credit_limit is not None:
        left = key.credit_limit - key.credits_used
        if left <= 0 or total > left:
            raise QuotaExhausted("key")
    return [context.charge(operation, units) for operation, units in merged.items()]


def schema_value(schema: Any, label: str, depth: int = 0) -> Any:
    """Return a deterministic value that satisfies a small JSON Schema."""

    kind = schema.get("type") if isinstance(schema, dict) else None
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "string")
    if isinstance(schema, dict) and isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if kind == "object" and depth < 4:
        properties = schema.get("properties") or {}
        return {
            name: schema_value(child, f"{label} {name}", depth + 1)
            for name, child in properties.items()
        }
    if kind == "array" and depth < 4:
        return [schema_value(schema.get("items") or {}, label, depth + 1)]
    if kind in {"number", "integer"}:
        return int(content.hex_id(4, label), 16) % 1000
    if kind == "boolean":
        return True
    return content.answer(label).split(". ")[0].rstrip(".") + "."
