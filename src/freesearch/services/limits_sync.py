"""Scheduled vendor usage sync with a cross-process lease.

One ``asyncio`` task per active runtime generation polls the providers whose
stored next-sync instant has arrived. The task reads the current adapter
registry on each tick and coordinates ownership through a database lease, so an
API process and an MCP process never poll the same provider twice at once.

One provider failure stays independent of the other providers: the last known
balance survives, the pool records a safe error code and a stale state, and the
next attempt uses bounded backoff.

Provider keys live in DB-stored credentials, so the installation-wide service
usually holds no provider-name adapter. A manual sync for such a provider is
delegated to ``credential_sync``, which polls each active system credential
under its own observation scope.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import QuotaSnapshot, QuotaSource
from freesearch.models.credentials import CredentialAuthMode
from freesearch.models.provider_limits import (
    AuthMode,
    LimitOperation,
    NativePool,
    ProviderObservationScope,
    SyncClaim,
    SyncResult,
    UsageSyncRequest,
    VaultKeyUsage,
)
from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.persistence.credentials import ProviderCredentialRow
from freesearch.persistence.limit_repository import LimitRepository
from freesearch.persistence.oauth_grants import CredentialOAuthGrantRow
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SECONDS = 60
# The default claim lease stays valid beyond a 30-second outer usage timeout.
DEFAULT_LEASE_SECONDS = 30
TAVILY_MIN_SECONDS = 60
# Tavily's lease also stays valid beyond the 30-second outer usage timeout.
TAVILY_LEASE_SECONDS = 90
MAX_BACKOFF_SECONDS = 600
# Tavily's usage endpoint is capped at ten requests per ten minutes.
_THROTTLED_PROVIDERS: dict[str, int] = {"tavily": TAVILY_MIN_SECONDS}


async def add_vault_key_auth_status(
    repository: SQLiteRepository, keys: list[VaultKeyUsage]
) -> list[VaultKeyUsage]:
    """Add secret-free authentication state to the admin's key observations."""

    if not keys:
        return []
    async with repository.session() as session:
        rows = await session.execute(
            select(
                ProviderCredentialRow.id,
                ProviderCredentialRow.auth_mode,
                CredentialOAuthGrantRow.status,
            )
            .outerjoin(
                CredentialOAuthGrantRow,
                CredentialOAuthGrantRow.credential_id == ProviderCredentialRow.id,
            )
            .where(ProviderCredentialRow.id.in_([str(key.key_id) for key in keys]))
        )
        states = {key_id: (CredentialAuthMode(mode), status) for key_id, mode, status in rows}
    result = []
    for key in keys:
        state = states.get(str(key.key_id))
        if state is None:
            continue
        mode, status = state
        result.append(
            key.model_copy(
                update={
                    "auth_mode": mode,
                    "oauth_connected": (
                        status == OAuthGrantStatus.CONNECTED.value
                        if mode is CredentialAuthMode.OAUTH
                        else None
                    ),
                }
            )
        )
    return result


def _sync_interval_seconds() -> int:
    raw = os.environ.get("FREESEARCH_LIMIT_SYNC_SECONDS")
    try:
        configured = int(raw) if raw is not None else DEFAULT_SYNC_INTERVAL_SECONDS
    except ValueError:
        configured = DEFAULT_SYNC_INTERVAL_SECONDS
    return max(5, min(3600, configured))


def _utc_now() -> datetime:
    return datetime.now(UTC)


#: Delegate for a provider without a provider-name adapter: sync its active
#: credentials, or return ``None`` when the composition cannot resolve any.
CredentialSync = Callable[[str, datetime], Awaitable[SyncResult | None]]


class LimitSyncService:
    """Run the scheduled usage sync for one runtime generation."""

    def __init__(
        self,
        repository: LimitRepository | None,
        limits: ProviderLimitsService,
        adapters: Callable[[], Sequence[ProviderAdapter]],
        *,
        clock: Callable[[], datetime] | None = None,
        interval_seconds: int | None = None,
        owner: str | None = None,
        enabled: bool = True,
        scope: ProviderObservationScope | None = None,
        quota_repository: SQLiteRepository | None = None,
        credential_sync: CredentialSync | None = None,
    ) -> None:
        self._repository = repository
        self._limits = limits
        self._adapters = adapters
        self._credential_sync = credential_sync
        self._clock = clock or _utc_now
        self._interval = interval_seconds or _sync_interval_seconds()
        self._owner = owner or f"sync-{os.getpid()}"
        self._enabled = enabled
        self._scope = scope
        self._quota_repository = quota_repository
        self._claim_pool_id: str | None = None
        self._failures: dict[str, int] = {}
        self._throttle_until: dict[str, datetime] = {}

    @property
    def interval_seconds(self) -> int:
        """Return the configured tick interval."""

        return self._interval

    async def run(self, stop: asyncio.Event) -> None:
        """Poll due providers until ``stop`` is set, honouring the cadence."""

        if not self._enabled or self._repository is None:
            return
        while not stop.is_set():
            try:
                await self.sync_due(self._clock())
            except Exception:
                logger.warning("limit sync tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    async def sync_due(self, now: datetime) -> list[SyncResult]:
        """Sync every provider whose next attempt instant has arrived."""

        if self._repository is None:
            return []
        due = await self._repository.next_sync_due(now)
        results: list[SyncResult] = []
        for provider in due:
            results.append(await self.sync_provider(provider, now))
        return results

    async def sync_provider(self, provider: str, now: datetime) -> SyncResult:
        """Sync one provider under the database lease.

        The Tavily usage endpoint keeps its documented minimum interval, and
        ``force`` cannot bypass it. For Tavily the repository enforces that
        durable cadence inside the atomic claim anchored on the canonical
        keyed Credits pool row, so a held claim reports ``False`` and this
        service treats it as ``lease_held``.
        """

        if self._repository is None:
            return _skipped(provider, now, "no_repository")
        throttle = self._throttle_until.get(provider)
        if throttle is not None and now < throttle:
            return _skipped(provider, now, "cadence")
        delegated = await self._delegate(provider, now)
        if delegated is not None and not (
            delegated.status == "skipped" and delegated.reason == "no_credential"
        ):
            return delegated
        adapter = self._adapter_for(provider)
        if adapter is None:
            return delegated if delegated is not None else _skipped(provider, now, "no_adapter")
        # The claim lease must outlive the 30-second outer usage timeout the
        # adapter applies to its usage request, so throttled providers keep a
        # lease floor higher than the request timeout.
        lease_floor = (
            TAVILY_LEASE_SECONDS if provider in _THROTTLED_PROVIDERS else DEFAULT_LEASE_SECONDS
        )
        if self._scope is not None:
            self._claim_pool_id = await self._prepare_scoped_pool(provider, adapter)
            if self._claim_pool_id is None:
                return _skipped(provider, now, "no_native_pool")
        claim = SyncClaim(
            pool_id=self._claim_pool_id,
            provider=provider,
            owner=self._owner,
            now=now,
            lease_seconds=max(lease_floor, self._interval),
            credential_generation=await self._credential_generation(provider),
        )
        if not await self._repository.claim_sync(claim):
            return _skipped(provider, now, "lease_held")
        return await self._sync_claimed(provider, adapter, now)

    async def _sync_claimed(
        self, provider: str, adapter: ProviderAdapter, now: datetime
    ) -> SyncResult:
        """Read one provider's usage and store it, keeping failures independent.

        One usage attempt per scheduled poll: this service never retries a
        failed, timed-out, or ``None`` usage request inside the same poll; the
        next attempt waits for the recorded cadence - for Tavily the later of
        the 60-second vendor cadence and Retry-After.
        """

        request = UsageSyncRequest(
            provider=provider,
            auth_mode=_adapter_auth_mode(adapter),
            operations=(LimitOperation.SEARCH, LimitOperation.FETCH),
            observed_at=now,
            credential_generation=await self._credential_generation(provider),
        )
        snapshot_reader = getattr(adapter, "usage_snapshot", None)
        if not callable(snapshot_reader):
            await self._complete(provider, "skipped", now, reason="no_usage_endpoint")
            return SyncResult(
                provider=provider,
                status="skipped",
                observed_at=now,
                next_sync_at=now + timedelta(seconds=self._interval),
                reason="no_usage_endpoint",
            )
        try:
            snapshot = await snapshot_reader(request)
        except Exception as error:
            return await self._record_failure(provider, now, error)
        if snapshot is None:
            await self._complete(provider, "skipped", now, reason="no_usage_endpoint")
            self._failures.pop(provider, None)
            return SyncResult(
                provider=provider,
                status="skipped",
                observed_at=now,
                next_sync_at=now + timedelta(seconds=self._interval),
                reason="no_usage_endpoint",
            )
        if self._scope is not None:
            snapshot = snapshot.model_copy(
                update={
                    "pool_id": self._scope.native_pool_id(snapshot.pool_id),
                    "credential_generation": self._scope.credential_generation,
                    "credential_id": self._scope.credential_id,
                    "upstream_pool_id": self._scope.upstream_pool_id,
                }
            )
        changed = await self._repository.apply_snapshot(snapshot) if self._repository else False
        await self._record_scoped_quota(snapshot.pool_id)
        await self._complete(provider, "synced", now, error_code=snapshot.error_code)
        self._failures.pop(provider, None)
        return SyncResult(
            provider=provider,
            status="synced" if snapshot.error_code is None else "failed",
            observed_at=now,
            next_sync_at=now + timedelta(seconds=self._interval),
            error_code=snapshot.error_code,
            stale=snapshot.stale,
            changed=changed,
        )

    async def _record_failure(self, provider: str, now: datetime, error: Exception) -> SyncResult:
        """Record one failed sync with a safe error code and bounded backoff.

        No immediate usage retry follows a 429 or a transport error: for
        Tavily the next poll waits the later of the 60-second vendor cadence
        and the parsed Retry-After delay after ``now``, and a Retry-After
        larger than 600 seconds caps at 600 for the ``next_sync_at``
        computation.
        """

        failures = self._failures.get(provider, 0) + 1
        self._failures[provider] = failures
        delay = _cadence_delay(
            provider, self._interval, _backoff_seconds(failures, _retry_after(error))
        )
        await self._complete(
            provider, "failed", now, error_code=_error_code(error), backoff_seconds=delay
        )
        logger.warning("limit sync failed for a provider")
        return SyncResult(
            provider=provider,
            status="failed",
            observed_at=now,
            next_sync_at=now + timedelta(seconds=delay),
            error_code=_error_code(error),
            stale=True,
        )

    async def _complete(
        self,
        provider: str,
        status: str,
        now: datetime,
        *,
        error_code: str | None = None,
        reason: str | None = None,
        backoff_seconds: int | None = None,
    ) -> None:
        """Stamp the lease release, error state, and next attempt instant.

        The stored ``next_sync_at`` never schedules an immediate usage retry
        after a failure: for Tavily it never undercuts the vendor's 60-second
        minimum cadence, even when ``interval_seconds`` is configured lower,
        and it honours the failure delay passed in ``backoff_seconds``.
        """

        if self._repository is None:
            return
        delay = _cadence_delay(provider, self._interval, backoff_seconds)
        await self._repository.complete_sync(
            SyncResult(
                provider=provider,
                status=status,  # type: ignore[arg-type]
                observed_at=now,
                next_sync_at=now + timedelta(seconds=delay),
                error_code=error_code,
                stale=status == "failed",
                reason=reason,
            ),
            pool_id=self._claim_pool_id,
        )
        if provider in _THROTTLED_PROVIDERS:
            self._throttle_until[provider] = now + timedelta(seconds=delay)

    async def _prepare_scoped_pool(self, provider: str, adapter: ProviderAdapter) -> str | None:
        """Anchor the cross-process polling lease on the resolved funds identity."""
        assert self._repository is not None and self._scope is not None
        base_id = self._limits.observation_pool_id(provider, _adapter_auth_mode(adapter))
        base = await self._repository.get_pool(base_id) if base_id is not None else None
        if base is None:
            return None
        pool_id = self._scope.native_pool_id(base.pool_id)
        await self._repository.ensure_pool(
            NativePool(
                pool_id=pool_id,
                provider=provider,
                auth_mode=base.auth_mode,
                native_unit=base.native_unit,
                credential_generation=self._scope.credential_generation,
            )
        )
        return pool_id

    async def _record_scoped_quota(self, pool_id: str) -> None:
        """Project accepted native truth onto the same scoped routing snapshot."""
        if self._scope is None or self._quota_repository is None or self._repository is None:
            return
        pool = await self._repository.get_pool(pool_id)
        if pool is None or pool.stale or pool.observed_at is None:
            return
        await self._quota_repository.record_quota(
            QuotaSnapshot(
                provider=pool.provider,
                source=QuotaSource.AUTHORITATIVE,
                remaining=pool.remaining,
                limit=pool.allowance,
                reset_at=pool.reset_at,
                observed_at=pool.observed_at,
                unit_kind=pool.native_unit,
                metadata={"native_sync": True},
            ),
            credential_id=self._scope.credential_id,
            pool_id=self._scope.upstream_pool_id,
            credential_generation=self._scope.credential_generation,
        )

    async def _delegate(self, provider: str, now: datetime) -> SyncResult | None:
        """Sync a provider without a provider-name adapter through its credentials.

        Only the installation-wide service delegates; a credential-scoped
        service already holds the one adapter it was built for.
        """
        if self._scope is not None or self._credential_sync is None:
            return None
        return await self._credential_sync(provider, now)

    def _adapter_for(self, provider: str) -> ProviderAdapter | None:
        for adapter in self._adapters():
            if adapter.name == provider:
                return adapter
        return None

    async def _credential_generation(self, provider: str) -> int:
        """Return the stored credential generation used to reject stale results."""

        if self._scope is not None:
            return self._scope.credential_generation
        if self._repository is None:
            return 0
        pools = await self._repository.list_pools(provider)
        return max(
            (pool.credential_generation for pool in pools if "#" not in pool.pool_id), default=0
        )


def _adapter_auth_mode(adapter: ProviderAdapter) -> AuthMode:
    """Return an adapter's limit rail, defaulting to the keyed rail."""

    mode = getattr(adapter, "limit_auth_mode", None)
    return mode if isinstance(mode, AuthMode) else AuthMode.KEYED


def _cadence_delay(provider: str, interval: int, backoff: int | None) -> int:
    """Return the next-poll delay in seconds for one provider.

    Throttled providers wait at least the later of their vendor cadence and
    the configured interval, plus any failure backoff they are given. The
    resulting delay is bounded by ``MAX_BACKOFF_SECONDS``: a Retry-After
    delay larger than 600 seconds caps at 600 for the ``next_sync_at``
    computation, while non-throttled providers keep their plain interval.
    """

    minimum = _THROTTLED_PROVIDERS.get(provider)
    if minimum is None:
        return interval
    delay = max(interval, minimum)
    if backoff is not None:
        delay = max(delay, backoff)
    return min(delay, MAX_BACKOFF_SECONDS)


def _backoff_seconds(failures: int, retry_after: float | None) -> int:
    """Return the bounded delay before the next attempt.

    A parsed Retry-After delay wins over exponential growth, and a delay
    larger than 600 seconds caps at 600.
    """

    if retry_after is not None:
        return int(max(1, min(MAX_BACKOFF_SECONDS, retry_after)))
    return min(MAX_BACKOFF_SECONDS, 60 * (1 << min(failures - 1, 4)))


def _retry_after(error: Exception) -> float | None:
    """Return the vendor Retry-After delay in seconds when it is a real number.

    ``details["retry_after_seconds"]`` wins over the legacy
    ``details["retry_after"]`` key. Only a real (non-bool) int or float
    greater than or equal to zero is accepted; anything else yields ``None``.
    """

    details = getattr(getattr(error, "error", None), "details", None)
    if not isinstance(details, dict):
        return None
    for key in ("retry_after_seconds", "retry_after"):
        value = details.get(key)
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        if value >= 0:
            return value
    return None


def _error_code(error: Exception) -> str:
    code = getattr(getattr(error, "error", None), "code", None)
    if isinstance(code, str):
        return code
    return type(error).__name__


def _skipped(provider: str, now: datetime, reason: str) -> SyncResult:
    return SyncResult(
        provider=provider,
        status="skipped",
        observed_at=now,
        next_sync_at=now + timedelta(seconds=DEFAULT_SYNC_INTERVAL_SECONDS),
        reason=reason,
    )
