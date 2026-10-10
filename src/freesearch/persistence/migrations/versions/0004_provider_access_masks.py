"""Convert stored provider enablement into access masks.

Revision ID: 0004_provider_access_masks
Revises: 0003_open_telemetry_spans
Create Date: 2026-10-01

A legacy global Boolean becomes an enable mask for all three bits. The support
mask comes from the frozen capability map below. The map is a historical record
of this revision, so this module imports no live adapter and no live
configuration.
"""

import json
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_provider_access_masks"
down_revision: str | None = "0003_open_telemetry_spans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER_PREFIX = "provider."
_ALL_BITS = 7
_GLOBAL_BIT = 1
_SUPPORT_MASKS: dict[str, int] = {
    "brave": 3,
    "exa": 7,
    "firecrawl": 7,
    "keenable": 7,
    "parallel": 7,
    "tavily": 7,
    "tinyfish": 7,
    "you": 7,
}


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _provider_id(key: object) -> str | None:
    """Return the canonical provider id of a provider settings key."""

    if not isinstance(key, str) or not key.startswith(_PROVIDER_PREFIX):
        return None
    name = key[len(_PROVIDER_PREFIX) :]
    return name if name in _SUPPORT_MASKS else None


def _decode_payload(provider: str, value_json: str) -> dict[str, object]:
    """Return the stored payload mapping, or raise for a malformed record."""

    try:
        payload = json.loads(value_json)
    except (TypeError, ValueError) as error:
        raise ValueError(f"provider {provider} has malformed stored JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"provider {provider} has malformed stored JSON")
    return payload


def _config_of(provider: str, payload: dict[str, object]) -> dict[str, object] | None:
    """Return the provider config mapping, or ``None`` for a foreign record."""

    config = payload.get("config")
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError(f"provider {provider} has malformed stored JSON")
    return config


def _convert_up(provider: str, value_json: str) -> str | None:
    """Return the converted payload.

    A record without an access choice returns ``None`` and stays for runtime
    initialization. A record with a new mask returns ``None`` and stays
    unchanged.
    """

    payload = _decode_payload(provider, value_json)
    config = _config_of(provider, payload)
    if config is None:
        return None
    holds_legacy = "enabled" in config
    holds_mask = "enable_mask" in config or "support_mask" in config
    if holds_legacy and holds_mask:
        raise ValueError(f"provider {provider} has ambiguous stored access values")
    if not holds_legacy:
        return None
    legacy = config["enabled"]
    if not isinstance(legacy, bool):
        raise ValueError(f"provider {provider} has an invalid stored global value")
    converted = dict(config)
    converted.pop("enabled")
    converted["enable_mask"] = _ALL_BITS if legacy else 0
    converted["support_mask"] = _SUPPORT_MASKS[provider]
    return json.dumps({**payload, "config": converted}, separators=(",", ":"))


def _convert_down(provider: str, value_json: str) -> str | None:
    """Return the legacy payload, or ``None`` when the row needs no change."""

    payload = _decode_payload(provider, value_json)
    config = _config_of(provider, payload)
    if config is None or "enable_mask" not in config:
        return None
    enable_mask = config["enable_mask"]
    if isinstance(enable_mask, bool) or not isinstance(enable_mask, int):
        raise ValueError(f"provider {provider} has an invalid enable mask")
    if enable_mask < 0 or enable_mask > _ALL_BITS:
        raise ValueError(f"provider {provider} has an invalid enable mask")
    converted = {
        key: value for key, value in config.items() if key not in ("enable_mask", "support_mask")
    }
    converted["enabled"] = bool(enable_mask & _GLOBAL_BIT)
    return json.dumps({**payload, "config": converted}, separators=(",", ":"))


def _rows() -> list[tuple[str, str]]:
    """Return every canonical provider settings row, key and payload."""

    if "runtime_settings" not in _tables():
        return []
    statement = sa.text(
        "SELECT key, value_json FROM runtime_settings WHERE key LIKE :prefix"
    ).bindparams(prefix=f"{_PROVIDER_PREFIX}%")
    result = op.get_bind().execute(statement).fetchall()
    rows: list[tuple[str, str]] = []
    for key, value_json in result:
        if _provider_id(key) is not None:
            rows.append((str(key), str(value_json)))
    return rows


def _convert(convert_row: Callable[[str, str], str | None]) -> None:
    """Apply one row converter to every canonical provider row."""

    bind = op.get_bind()
    statement = sa.text("UPDATE runtime_settings SET value_json = :payload WHERE key = :key")
    for key, value_json in _rows():
        provider = _provider_id(key)
        if provider is None:
            continue
        payload = convert_row(provider, value_json)
        if payload is None or payload == value_json:
            continue
        bind.execute(statement, {"payload": payload, "key": key})


def upgrade() -> None:
    """Convert each stored legacy global value into an enable mask."""

    _convert(_convert_up)


def downgrade() -> None:
    """Decode the enable Bit 0 into the legacy global Boolean."""

    _convert(_convert_down)
