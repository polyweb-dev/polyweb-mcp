"""Shared manual native-anchor read and pure response builder.

The existing manual-quota feature already stores one native allowance, its
current use, a billing window, and an update time per provider in
``runtime_settings``. This module owns that read and its response projection so
both the control routes and the provider-limits service can reuse it without
importing router code.

The anchor is an operator estimate, not vendor funds. Its projected capacity
stays ``estimated`` and its source stays ``Manual entry``.
"""

from datetime import datetime

from pydantic import ValidationError

from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import (
    ManualQuota,
    ManualQuotaResponse,
    ManualQuotaUpdate,
    QuotaSource,
    manual_quota_remaining,
    manual_quota_remaining_percent,
)
from freesearch.persistence.storage import SQLiteRepository

MANUAL_QUOTA_PREFIX = "manual_quota:"
MANUAL_ANCHOR_SOURCE = "manual_anchor"


def manual_quota_key(provider: ProviderName) -> str:
    """Return the runtime-settings key for a provider billing anchor."""

    return f"{MANUAL_QUOTA_PREFIX}{provider.value}"


def manual_quota_response(
    provider: ProviderName,
    quota: ManualQuota,
    updated_at: datetime,
) -> ManualQuotaResponse:
    """Build the ESTIMATED capacity view with Decimal-exact derived fields."""

    return ManualQuotaResponse(
        provider=provider.value,
        billing_start=quota.billing_start,
        billing_end=quota.billing_end,
        allowance=quota.allowance,
        current_usage=quota.current_usage,
        remaining=manual_quota_remaining(quota.allowance, quota.current_usage),
        remaining_percent=manual_quota_remaining_percent(quota.allowance, quota.current_usage),
        source=QuotaSource.ESTIMATED,
        updated_at=updated_at,
        note=quota.note,
    )


async def load_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
) -> ManualQuotaResponse | None:
    """Return the stored billing anchor view, or ``None`` when absent or corrupt."""

    payload = await _safe_runtime_setting(repository, manual_quota_key(provider))
    if not isinstance(payload, dict):
        return None
    return _anchor_from_payload(provider, payload)


def manual_quota_payload(quota: ManualQuota, updated_at: datetime) -> dict[str, str | None]:
    """Return the stored runtime-settings payload for one anchor."""

    return {
        "billing_start": quota.billing_start.isoformat(),
        "billing_end": quota.billing_end.isoformat(),
        "allowance": str(quota.allowance),
        "current_usage": str(quota.current_usage),
        "note": quota.note,
        "updated_at": updated_at.isoformat(),
    }


async def persist_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    update: ManualQuotaUpdate,
    now: datetime,
) -> ManualQuotaResponse:
    """Persist the billing anchor and return its ESTIMATED capacity view."""

    quota = ManualQuota.model_validate(update.model_dump(mode="json"))
    if repository is not None:
        await repository.set_runtime_setting(
            manual_quota_key(provider), manual_quota_payload(quota, now)
        )
    return manual_quota_response(provider, quota, now)


async def clear_manual_quota(repository: SQLiteRepository | None, provider: ProviderName) -> None:
    """Clear the billing anchor idempotently; unknown providers never reach here."""

    if repository is None:
        return
    await repository.set_runtime_setting(manual_quota_key(provider), None)


def _anchor_from_payload(
    provider: ProviderName, payload: dict[object, object]
) -> ManualQuotaResponse | None:
    """Decode one stored anchor payload into its response view."""

    raw_updated_at = payload.get("updated_at")
    quota_payload = {
        key: payload.get(key)
        for key in ("billing_start", "billing_end", "allowance", "current_usage", "note")
    }
    try:
        quota = ManualQuota.model_validate(quota_payload)
        updated_at = (
            datetime.fromisoformat(str(raw_updated_at)) if isinstance(raw_updated_at, str) else None
        )
    except (ValidationError, ValueError):
        return None
    if updated_at is None:
        return None
    return manual_quota_response(provider, quota, updated_at)


async def _safe_runtime_setting(repository: SQLiteRepository | None, key: str) -> object:
    """Read a runtime setting, degrading repository failures to ``None``."""

    if repository is None:
        return None
    try:
        return await repository.get_runtime_setting(key)
    except Exception:
        return None
