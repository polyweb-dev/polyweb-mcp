"""Scheduled vendor usage sync with a cross-process lease.

One ``asyncio`` task per active runtime generation polls the providers whose
stored next-sync instant has arrived. The task reads the current adapter
registry on each tick and coordinates ownership through a database lease, so an
API process and an MCP process never poll the same provider twice at once.

One provider failure stays independent of the other providers: the last known
balance survives, the pool records a safe error code and a stale state, and the
next attempt uses bounded backoff.
"""

import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.provider_limits import (
    AuthMode,
    LimitOperation,
    SyncClaim,
    SyncResult,
    UsageSyncRequest,
)
from freesearch.persistence.limit_repository import LimitRepository
from freesearch.services.provider_limits import ProviderLimitsService

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SECONDS = 60
TAVILY_MIN_SECONDS = 60
MAX_BACKOFF_SECONDS = 600
# Tavily's usage endpoint is capped at ten requests per ten minutes.
_THROTTLED_PROVIDERS: dict[str, int] = {"tavily": TAVILY_MIN_SECONDS}


def _sync_interval_seconds() -> int:
    raw = os.environ.get("FREESEARCH_LIMIT_SYNC_SECONDS")
    try:
        configured = int(raw) if raw is not None else DEFAULT_SYNC_INTERVAL_SECONDS
    except ValueError:
        configured = DEFAULT_SYNC_INTERVAL_SECONDS
    return max(5, min(3600, configured))


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    ) -> None:
        self._repository = repository
        self._limits = limits
        self._adapters = adapters
        self._clock = clock or _utc_now
        self._interval = interval_seconds or _sync_interval_seconds()
        self._owner = owner or f"sync-{os.getpid()}"
        self._enabled = enabled
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
        ``force`` cannot bypass it.
        """

        if self._repository is None:
            return _skipped(provider, now, "no_repository")
        throttle = self._throttle_until.get(provider)
        if throttle is not None and now < throttle:
            return _skipped(provider, now, "cadence")
        adapter = self._adapter_for(provider)
        if adapter is None:
            return _skipped(provider, now, "no_adapter")
        claim = SyncClaim(
            provider=provider,
            owner=self._owner,
            now=now,
            lease_seconds=max(30, self._interval),
            credential_generation=await self._credential_generation(provider),
        )
        if not await self._repository.claim_sync(claim):
            return _skipped(provider, now, "lease_held")
        return await self._sync_claimed(provider, adapter, now)

    async def _sync_claimed(
        self, provider: str, adapter: ProviderAdapter, now: datetime
    ) -> SyncResult:
        """Read one provider's usage and store it, keeping failures independent."""

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
        changed = await self._repository.apply_snapshot(snapshot) if self._repository else False
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
        """Record one failed sync with a safe error code and bounded backoff."""

        failures = self._failures.get(provider, 0) + 1
        self._failures[provider] = failures
        delay = _backoff_seconds(failures, _retry_after(error))
        await self._complete(provider, "failed", now, error_code=_error_code(error))
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
    ) -> None:
        if self._repository is None:
            return
        await self._repository.complete_sync(
            SyncResult(
                provider=provider,
                status=status,  # type: ignore[arg-type]
                observed_at=now,
                next_sync_at=now + timedelta(seconds=self._interval),
                error_code=error_code,
                stale=status == "failed",
                reason=reason,
            )
        )
        minimum = _THROTTLED_PROVIDERS.get(provider)
        if minimum is not None:
            self._throttle_until[provider] = now + timedelta(seconds=minimum)

    def _adapter_for(self, provider: str) -> ProviderAdapter | None:
        for adapter in self._adapters():
            if adapter.name == provider:
                return adapter
        return None

    async def _credential_generation(self, provider: str) -> int:
        """Return the stored credential generation used to reject stale results."""

        if self._repository is None:
            return 0
        pools = await self._repository.list_pools(provider)
        return max((pool.credential_generation for pool in pools), default=0)


def _adapter_auth_mode(adapter: ProviderAdapter) -> AuthMode:
    """Return an adapter's limit rail, defaulting to the keyed rail."""

    mode = getattr(adapter, "limit_auth_mode", None)
    return mode if isinstance(mode, AuthMode) else AuthMode.KEYED


def _backoff_seconds(failures: int, retry_after: int | None) -> int:
    """Return the bounded delay before the next attempt."""

    if retry_after is not None:
        return max(1, min(MAX_BACKOFF_SECONDS, retry_after))
    return min(MAX_BACKOFF_SECONDS, 60 * (1 << min(failures - 1, 4)))


def _retry_after(error: Exception) -> int | None:
    details = getattr(getattr(error, "error", None), "details", None)
    if not isinstance(details, dict):
        return None
    value = details.get("retry_after")
    if isinstance(value, int):
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
