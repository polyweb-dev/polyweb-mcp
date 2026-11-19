"""Helpers shared by the Exa and Firecrawl plugins.

Discovery skips modules whose name starts with ``_``, so this module exports
no ``PLUGIN``. Multi-part billing lives in the core:
:meth:`~polyweb_provider_mock.providers.base.OperationContext.charge_all`.
"""

from datetime import UTC, datetime
from typing import Any

from polyweb_provider_mock import content

__all__ = ["iso_ms", "schema_value"]


def iso_ms(value: datetime) -> str:
    """Render a UTC timestamp with milliseconds and ``Z``, as JavaScript does."""

    value = value.astimezone(UTC)
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 1000:03d}Z"


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
