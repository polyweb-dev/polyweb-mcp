"""Shared manual native-anchor read and pure response builder.

The existing manual-quota feature already stores one native allowance, its
current use, a billing window, and an update time per provider in
``runtime_settings``. This module owns that read and its response projection so
both the control routes and the provider-limits service can reuse it without
importing router code.

The anchor is an operator estimate, not vendor funds. Its projected capacity
stays ``estimated`` and its source stays ``Manual entry``.

A record can also name one key or one shared pool (TASK-000070). Such a
record replaces that balance owner's stored denial, becomes the newest routing
observation of the owner, and retires the cached adapters of its keys, so the
rebuilt adapters restore their state from the record instead of a 402.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.contracts import (
    ManualQuota,
    ManualQuotaResponse,
    ManualQuotaUpdate,
    QuotaSnapshot,
    QuotaSource,
    manual_quota_remaining,
    manual_quota_remaining_percent,
)
from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialInstanceRead
from polyweb.models.provider_limits import ProviderObservationScope
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.pools import UpstreamPoolRepository
from polyweb.persistence.storage import SQLiteRepository

MANUAL_QUOTA_PREFIX = "manual_quota:"
MANUAL_ANCHOR_SOURCE = "manual_anchor"


class ManualQuotaScopeError(ValueError):
    """The requested key or pool scope does not belong to the provider."""


@dataclass(frozen=True)
class ManualQuotaScope:
    """The balance owner one manual record applies to: one key or one shared pool."""

    observation: ProviderObservationScope
    credential_ids: frozenset[UUID]

    @property
    def credential_id(self) -> UUID | None:
        """The named key, or ``None`` for a shared pool."""

        return None if self.observation.upstream_pool_id else self.observation.credential_id

    @property
    def pool_id(self) -> UUID | None:
        """The named shared pool, or ``None`` for one key."""

        return self.observation.upstream_pool_id

    def suffix(self) -> str:
        """Return the scope part of the settings key, matching the native pool id."""

        return self.observation.native_pool_id("").lstrip("#")


def manual_quota_key(provider: ProviderName, scope: ManualQuotaScope | None = None) -> str:
    """Return the runtime-settings key for a provider or key-scoped billing anchor."""

    base = f"{MANUAL_QUOTA_PREFIX}{provider.value}"
    return base if scope is None else f"{base}#{scope.suffix()}"


def manual_quota_response(
    provider: ProviderName,
    quota: ManualQuota,
    updated_at: datetime,
    scope: ManualQuotaScope | None = None,
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
        credential_id=scope.credential_id if scope is not None else None,
        pool_id=scope.pool_id if scope is not None else None,
    )


async def load_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    scope: ManualQuotaScope | None = None,
) -> ManualQuotaResponse | None:
    """Return the stored billing anchor view, or ``None`` when absent or corrupt."""

    payload = await _safe_runtime_setting(repository, manual_quota_key(provider, scope))
    if not isinstance(payload, dict):
        return None
    return _anchor_from_payload(provider, payload)


def manual_quota_payload(
    quota: ManualQuota, updated_at: datetime, scope: ManualQuotaScope | None = None
) -> dict[str, str | None]:
    """Return the stored runtime-settings payload for one anchor."""

    payload: dict[str, str | None] = {
        "billing_start": quota.billing_start.isoformat(),
        "billing_end": quota.billing_end.isoformat(),
        "allowance": str(quota.allowance),
        "current_usage": str(quota.current_usage),
        "note": quota.note,
        "updated_at": updated_at.isoformat(),
    }
    if scope is not None and scope.credential_id is not None:
        payload["credential_id"] = str(scope.credential_id)
    if scope is not None and scope.pool_id is not None:
        payload["pool_id"] = str(scope.pool_id)
    return payload


async def persist_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    update: ManualQuotaUpdate,
    now: datetime,
    scope: ManualQuotaScope | None = None,
    *,
    explicit: bool = False,
) -> ManualQuotaResponse:
    """Persist the billing anchor and return its ESTIMATED capacity view.

    An explicitly scoped record has its own settings key. An unscoped record
    keeps the provider key, so the existing dialog reads it back, and it
    remembers the one key it was applied to.
    """

    quota = ManualQuota.model_validate(update.model_dump(mode="json"))
    if repository is not None:
        await repository.set_runtime_setting(
            manual_quota_key(provider, scope if explicit else None),
            manual_quota_payload(quota, now, scope),
        )
    return manual_quota_response(provider, quota, now, scope)


async def clear_manual_quota(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    scope: ManualQuotaScope | None = None,
) -> None:
    """Clear the billing anchor idempotently; unknown providers never reach here."""

    if repository is None:
        return
    await repository.set_runtime_setting(manual_quota_key(provider, scope), None)


async def resolve_manual_quota_scope(
    repository: SQLiteRepository | None,
    provider: ProviderName,
    *,
    credential_id: UUID | None = None,
    pool_id: UUID | None = None,
) -> ManualQuotaScope | None:
    """Return the balance owner a manual record applies to, or ``None`` for the provider.

    The eligible keys are the provider's active credentials that carry a key
    (keyless credentials have no balance). Keys linked to one shared pool share
    one balance owner. A named key resolves to its balance owner, a named pool
    must hold an eligible key, and without a name the provider's only balance
    owner applies. With several owners and no name the record stays
    provider-level, because the caller did not say which balance it describes.
    """

    if credential_id is not None and pool_id is not None:
        raise ManualQuotaScopeError("name either a key or a pool, not both")
    if repository is None:
        if credential_id is not None or pool_id is not None:
            raise ManualQuotaScopeError("no credential store is available")
        return None
    async with repository.session() as session:
        credentials = [
            credential
            for credential in await CredentialRepository(session).list_active_for_provider(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, provider_type=provider.value
            )
            if credential.auth_mode != "keyless"
        ]
        links = await UpstreamPoolRepository(session).links_for_credentials(
            credential_ids={credential.id for credential in credentials}
        )
    owner_pool = _balance_pools(links)
    owners: dict[UUID, list[CredentialInstanceRead]] = {}
    for credential in credentials:
        owners.setdefault(owner_pool.get(credential.id, credential.id), []).append(credential)
    if credential_id is not None:
        match = next((item for item in credentials if item.id == credential_id), None)
        if match is None:
            raise ManualQuotaScopeError("the key is not an active key of this provider")
        shared = owner_pool.get(match.id)
        return _scope(owners[shared] if shared is not None else [match], shared)
    if pool_id is not None:
        members = owners.get(pool_id)
        if not members or owner_pool.get(members[0].id) != pool_id:
            raise ManualQuotaScopeError("the pool holds no active key of this provider")
        return _scope(members, pool_id)
    if len(owners) != 1:
        return None
    owner, members = next(iter(owners.items()))
    return _scope(members, owner if owner_pool.get(members[0].id) == owner else None)


async def project_manual_record(
    repository: SQLiteRepository | None,
    limits: Any,
    provider: ProviderName,
    anchor: ManualQuotaResponse | None,
    scope: ManualQuotaScope | None,
    *,
    retire: Callable[[set[UUID]], None] | None = None,
) -> None:
    """Apply one manual record, or its deletion, to the limit store and adapters.

    The native anchor goes to the provider's pool, or to the scoped pool of a
    key or shared pool, where it replaces a stored 402 or zero. A scoped record
    is also stored as the owner's newest routing observation, so routing and
    rebuilt adapters read it instead of the older denial, and the owner's
    cached adapters are retired so their in-memory blocks are dropped.
    """

    if limits is None:
        return
    pool = await limits.apply_manual_anchor(
        provider.value, anchor, scope.observation if scope is not None else None
    )
    if scope is None:
        return
    if repository is not None and pool is not None:
        await repository.record_quota(
            QuotaSnapshot(
                provider=provider.value,
                source=QuotaSource.ESTIMATED,
                remaining=pool.remaining,
                limit=pool.allowance,
                unit_kind=pool.native_unit,
                observed_at=pool.observed_at or datetime.now(UTC),
                reset_at=pool.reset_at,
                metadata={"manual_anchor": anchor is not None, "window": "monthly"},
            ),
            credential_id=scope.observation.credential_id,
            pool_id=scope.pool_id,
            credential_generation=scope.observation.credential_generation,
        )
    if retire is not None:
        retire(set(scope.credential_ids))


def _balance_pools(links: list[Any]) -> dict[UUID, UUID]:
    """Map each linked credential to its shared pool, preferring the search link."""

    pools: dict[UUID, UUID] = {}
    for operation in (CredentialOperation.SEARCH, CredentialOperation.FETCH):
        for link in links:
            if link.operation is operation:
                pools.setdefault(link.credential_id, link.pool_id)
    return pools


def _scope(members: list[CredentialInstanceRead], pool_id: UUID | None) -> ManualQuotaScope:
    first = members[0]
    return ManualQuotaScope(
        observation=ProviderObservationScope(
            credential_id=first.id,
            upstream_pool_id=pool_id,
            credential_generation=first.generation,
        ),
        credential_ids=frozenset(member.id for member in members),
    )


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
        credential_id = _uuid(payload.get("credential_id"))
        pool_id = _uuid(payload.get("pool_id"))
    except (ValidationError, ValueError):
        return None
    if updated_at is None:
        return None
    return manual_quota_response(provider, quota, updated_at).model_copy(
        update={"credential_id": credential_id, "pool_id": pool_id}
    )


def _uuid(value: object) -> UUID | None:
    return UUID(value) if isinstance(value, str) else None


async def _safe_runtime_setting(repository: SQLiteRepository | None, key: str) -> object:
    """Read a runtime setting, degrading repository failures to ``None``."""

    if repository is None:
        return None
    try:
        return await repository.get_runtime_setting(key)
    except Exception:
        return None
