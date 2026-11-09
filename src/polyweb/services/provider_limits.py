"""Provider limit service: catalog seeding, dashboard views, and admission.

The service is the only place that combines the documented catalog, the stored
native pools, the operator grants, and the rate windows. Routers stay thin and
never read or write limit rows themselves.

Admission runs after unchanged route selection and before any vendor I/O. A
funds denial is a local 402; a rate denial is a local 429 with ``Retry-After``.
When both apply, the funds denial keeps status precedence and both reasons stay
in the audit trail. An unpriced request against a finite ceiling is a safe
configuration error instead of an invented charge.
"""

import contextlib
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Final, Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.configuration.provider_config import ProviderConfig
from polyweb.configuration.provider_limits import (
    TAVILY_DEFAULT_BUCKET_ID,
    TAVILY_RPM_DEV,
    TAVILY_RPM_PROD,
    documented_keyless_operations,
    provider_limit_defaults,
    provider_tier_defaults,
)
from polyweb.models.contracts import (
    FetchRequest,
    FetchResponse,
    ProviderError,
    SearchRequest,
    SearchResponse,
    UnitKind,
)
from polyweb.models.provider_limits import (
    AuthMode,
    Confidence,
    CRDGrantsSummary,
    CRDGrantUpdate,
    CRDPriceProfile,
    CRDState,
    CRDUsageTotal,
    CRDView,
    FundingMode,
    LimitAdmission,
    LimitAuditEvent,
    LimitCallContext,
    LimitDebit,
    LimitHistoryPage,
    LimitHistoryQuery,
    LimitOperation,
    LimitRecordNotFound,
    LimitRecordUpdate,
    LimitStoreUnavailable,
    LimitVersionConflict,
    NativeDebit,
    NativePool,
    NativeUsageSnapshot,
    ProviderAuthLimits,
    ProviderLimitDetail,
    ProviderLimitRecord,
    ProviderLimitsResponse,
    RateAdmission,
    RateBlock,
    RateProgressView,
    RateScope,
    RateWindow,
    RateWindowName,
    ResetRule,
    TierBalance,
    effective_attempt_deadline,
    local_funds_denial,
    local_rate_denial,
    native_pool_id,
    unpriced_ceiling_error,
)
from polyweb.persistence.limit_repository import (
    AttemptReservation,
    LimitRepository,
    StrictAttemptSpec,
)
from polyweb.services.credit_units import (
    crd_view,
    effective_crd,
    native_to_crd,
    priced_crd_debit,
    request_cost_crd,
    request_native_cost,
)
from polyweb.services.rate_limits import RateLimitService

logger = logging.getLogger(__name__)

_FUNDS_OK = "ok"
_FUNDS_DENIED = "funds"
_FUNDS_UNPRICED = "unpriced"

# Tavily keyed Credits facts. The usage snapshot persists its tier rows with
# those pool IDs, and a vendor 402 publishes the terminal observation source.
_TAVILY_TERMINAL_SOURCE: Final[str] = "vendor_402"
_TAVILY_MONTHLY_RESET_SOURCE: Final[str] = "free_monthly_reset"
_TAVILY_PAYGO_TIER_ID: Final[str] = "tavily:keyed:paygo"
_TAVILY_PLAN_TIER_ID: Final[str] = "tavily:keyed:plan"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _day_start(now: datetime) -> datetime:
    return datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)


class ProviderLimitsService:
    """Serve provider limit views and gate every metered provider call."""

    def __init__(
        self,
        repository: LimitRepository | None,
        *,
        records: Sequence[ProviderLimitRecord] | None = None,
        tier_defaults: dict[str, list[TierBalance]] | None = None,
        rate_limits: RateLimitService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._records = list(records if records is not None else provider_limit_defaults())
        self._tiers = dict(tier_defaults if tier_defaults is not None else provider_tier_defaults())
        self._clock = clock or _utc_now
        self._rates = rate_limits or RateLimitService(repository, self._records, clock=self._clock)
        # Runtime Tavily facts stored by apply_tavily_config: the rail the
        # current adapter executes with, the operator key environment, and the
        # PAYGO overage confirmation. Catalog defaults keep the pre-seed state.
        self._tavily_auth_mode: AuthMode | None = None
        self._keenable_auth_mode: AuthMode | None = None
        self._tavily_key_environment: Literal["dev", "prod"] = "dev"
        self._tavily_paygo_enabled: bool = False

    # ------------------------------------------------------------- lifecycle

    @property
    def records(self) -> list[ProviderLimitRecord]:
        """Return the catalog this service serves."""

        return list(self._records)

    @property
    def rate_limits(self) -> RateLimitService:
        """Return the rate service that shares this catalog and repository."""

        return self._rates

    async def initialize(self) -> None:
        """Seed the catalog and the declared pools idempotently."""

        if self._repository is None:
            return
        await self._repository.seed_records(self._records)
        stored = await self._repository.list_records()
        if stored:
            self._records = stored
            self._rates.replace_records(stored)
        await self._reconcile_tavily_versions()
        for pool in self._declared_pools():
            await self._repository.ensure_pool(pool)

    async def _reconcile_tavily_versions(self) -> None:
        """Re-sync stored Tavily rows whose catalog version is newer.

        Seeding is insert-only, so an existing database still holds a
        version-1 Tavily row after the version-2 catalog arrives. The stored
        record's own version satisfies the update precondition, and a
        conflicting later operator edit keeps its row and is logged instead
        of raised. Catalog defaults come from ``provider_limit_defaults``.
        """

        defaults = {
            record.key: record
            for record in provider_limit_defaults()
            if record.provider == "tavily"
        }
        for stored in list(self._records):
            default = defaults.get(stored.key)
            if default is None or stored.version >= default.version:
                continue
            repository = self._require_repository(stored.provider)
            try:
                refreshed = await repository.update_record(
                    LimitRecordUpdate(
                        provider=stored.provider,
                        operation=stored.operation,
                        auth_mode=stored.auth_mode,
                        version=stored.version,
                        rate=default.rate,
                        budget=default.budget,
                        conversion_profile=default.conversion_profile,
                        plan_name=default.plan_name,
                        usage_url=default.usage_url,
                        transport_available=default.transport_available,
                    )
                )
            except LimitVersionConflict:
                logger.warning("tavily catalog row could not be reconciled")
                continue
            self._refresh_record(refreshed)

    async def credential_changed(self, provider: str) -> None:
        """Invalidate stale credential generations after a secret change."""

        if self._repository is None:
            return
        for pool in await self._repository.list_pools(provider):
            await self._repository.apply_snapshot(
                NativeUsageSnapshot(
                    pool_id=pool.pool_id,
                    provider=pool.provider,
                    auth_mode=pool.auth_mode,
                    native_unit=pool.native_unit,
                    observed_at=self._clock(),
                    source=pool.source,
                    confidence=Confidence.UNKNOWN,
                    remaining=pool.remaining,
                    allowance=pool.allowance,
                    reset_at=pool.reset_at,
                    credential_generation=pool.credential_generation + 1,
                    stale=True,
                    error_code="credential_changed",
                )
            )

    async def apply_tavily_config(self, config: ProviderConfig, *, auth_mode: AuthMode) -> None:
        """Store the runtime Tavily facts and apply the keyed minute limit.

        ``auth_mode`` is the rail the runtime adapter currently executes with,
        so the dashboard reports the active rail instead of deriving one from
        the catalog record order, and the funds gate reads the operator key
        environment and PAYGO choices. The documented minute limit (development
        100, production 1000 rpm) applies to the shared bucket of BOTH keyed
        operation records together. Keyless records and every other provider
        stay untouched.
        """

        self._tavily_auth_mode = auth_mode
        self._tavily_key_environment = config.tavily_key_environment
        self._tavily_paygo_enabled = bool(config.tavily_paygo_enabled)
        rate = _tavily_minute_rate(config.tavily_key_environment)
        for record in self._tavily_keyed_records():
            await self._apply_tavily_rate(record, rate)

    def apply_keenable_auth_mode(self, auth_mode: AuthMode) -> None:
        """Store the auth rail selected by the active Keenable adapter."""

        self._keenable_auth_mode = auth_mode

    async def _apply_tavily_rate(self, record: ProviderLimitRecord, rate: RateBlock) -> None:
        """Apply one rate limit to a record's shared minute bucket, when it moves."""

        stored = _minute_window(record)
        incoming = _minute_window(rate)
        if stored is not None and incoming is not None and stored.limit == incoming.limit:
            return
        if self._repository is None:
            self._refresh_record(record.model_copy(update={"rate": rate}))
            return
        try:
            updated = await self._repository.update_record(
                LimitRecordUpdate(
                    provider=record.provider,
                    operation=record.operation,
                    auth_mode=record.auth_mode,
                    version=record.version,
                    rate=rate,
                )
            )
        except LimitVersionConflict:
            logger.warning("tavily rate reconfiguration hit a version conflict")
            return
        self._refresh_record(updated)

    def _tavily_keyed_records(self) -> list[ProviderLimitRecord]:
        """Return the keyed Tavily operation records that share the limits."""

        return [
            record
            for record in self._records
            if record.provider == "tavily" and record.auth_mode is AuthMode.KEYED
        ]

    async def apply_manual_anchor(self, provider: str, anchor: object | None) -> None:
        """Project an operator manual native anchor into the matching pool.

        The anchor supplies an estimated native allowance for a provider whose
        usage API is unavailable. A fresh authoritative observation is never
        replaced silently, and a rate-only free provider stays unmetered. A
        deleted anchor restores an unknown state rather than a zero balance.
        """

        if self._repository is None:
            return
        pool = self._manual_anchor_pool(provider)
        if pool is None:
            return
        stored = await self._repository.get_pool(pool.pool_id)
        if stored is not None and _is_fresh_vendor_value(stored):
            # A fresh vendor observation stands. It is never replaced silently by
            # an operator estimate, and it is never cleared by an operator delete.
            return
        if anchor is None:
            # The explicit clear path bypasses the preserve rule, so a deleted
            # anchor restores the unknown state rather than the old estimate.
            await self._repository.clear_pool_values(
                pool.pool_id,
                observed_at=self._clock(),
                source="manual_anchor",
            )
            return
        await self._repository.record_manual_anchor(
            pool,
            remaining=_anchor_decimal(anchor, "remaining"),
            allowance=_anchor_decimal(anchor, "allowance"),
            reset_at=_anchor_instant(anchor, "billing_end"),
            observed_at=_anchor_instant(anchor, "updated_at") or self._clock(),
        )

    def _manual_anchor_pool(self, provider: str) -> NativePool | None:
        """Return the finite paid pool a manual anchor may fill, if any."""

        for record in self._records:
            if (
                record.provider == provider
                and record.auth_mode is AuthMode.KEYED
                and record.budget is not None
                and record.native_pool_id is not None
                and record.native_unit is not None
            ):
                return NativePool(
                    pool_id=record.native_pool_id,
                    provider=provider,
                    auth_mode=AuthMode.KEYED,
                    native_unit=record.native_unit,
                    source="manual_anchor",
                    confidence=Confidence.ESTIMATED,
                    manual_anchor=True,
                )
        return None

    # ------------------------------------------------------------ admission

    def supports(self, provider: str, operation: LimitOperation, auth_mode: AuthMode) -> bool:
        """Return whether the catalog covers one provider rail.

        A synthetic adapter without a catalog record is never gated, so the
        unchanged execution contract of injected test doubles holds.
        """

        return any(
            record.provider == provider
            and record.operation is operation
            and record.auth_mode is auth_mode
            for record in self._records
        )

    async def admit(self, context: LimitCallContext) -> LimitAdmission:
        """Reserve funds and rate units, or raise a local denial.

        The vendor is never called when the funds gate or a known enforced rate
        window has no capacity, and a local denial consumes no reservation.
        """

        record, admission = await self._admission_candidate(context)
        if self._repository is None:
            return admission.model_copy(update={"local_only": True})
        # The repository rechecks rate capacity inside its transaction and may
        # raise LimitDeniedError from the atomic recheck; it propagates
        # unchanged to the router transport.
        return await self._repository.reserve(admission, record=record, clock=self._clock)

    async def _admission_candidate(
        self, context: LimitCallContext
    ) -> tuple[ProviderLimitRecord, LimitAdmission]:
        """Resolve the catalog record, funds/rate decision, and reservation."""

        record = self._record(context.provider, context.operation, context.auth_mode)
        rate_admission = await self._rates.admit(context)
        # The scoped pool row may be created here, so the pool is chosen before
        # the funds reads open their shared snapshot. These reads are only a
        # fast pre-check: the repository reservation rechecks Tavily capacity
        # under its own write lock, so this snapshot is never the authority.
        pool_id = await self._selected_pool_id(record, _as_request(context), context=context)
        if self._repository is None:
            decision, reasons = await self._funds_decision(record, context, pool_id=pool_id)
        else:
            async with self._repository.session() as session:
                decision, reasons = await self._funds_decision(
                    record, context, pool_id=pool_id, session=session
                )
        if decision is _FUNDS_UNPRICED:
            raise unpriced_ceiling_error(context.provider, context.operation)
        if decision is _FUNDS_DENIED:
            await self._audit_denial(
                context,
                [*reasons, *[denial.bucket_id for denial in rate_admission.denials]],
                refusal="funds",
            )
            raise local_funds_denial(
                context.provider,
                operation=context.operation,
                reasons=reasons,
                detail={"rate_denied": not rate_admission.admitted},
            )
        if not rate_admission.admitted:
            rate_reasons = [denial.bucket_id for denial in rate_admission.denials]
            await self._audit_denial(
                context,
                rate_reasons,
                refusal="rate",
                retry_after=rate_admission.retry_after_seconds,
            )
            raise local_rate_denial(
                context.provider,
                operation=context.operation,
                reasons=rate_reasons,
                retry_after_seconds=rate_admission.retry_after_seconds,
            )
        return record, self._reservation(record, context, rate_admission, pool_id)

    async def admit_attempt(
        self, context: LimitCallContext, spec: StrictAttemptSpec | None
    ) -> AttemptReservation:
        """Reserve native funds and strict capacity in one transaction.

        The execution service calls this once per actual dispatch. The native
        admission and the strict pool/project reservation share the context's
        attempt id, so a strict denial rolls back the native reservation
        instead of leaking it and the concurrency check never counts a sibling
        row of the same attempt.
        """

        record, admission = await self._admission_candidate(context)
        if self._repository is None:
            return AttemptReservation(
                attempt_id=context.attempt_id,
                admission=admission.model_copy(update={"local_only": True}),
            )
        return await self._repository.reserve_attempt(
            attempt_id=context.attempt_id,
            provider=context.provider,
            operation=context.operation,
            auth_mode=context.auth_mode,
            admission=admission,
            spec=spec,
            record=record,
        )

    def observation_pool_id(self, provider: str, auth_mode: AuthMode) -> str | None:
        """Return the catalog funds pool used by authoritative usage polling."""
        return next(
            (
                record.native_pool_id
                for record in self._records
                if record.provider == provider
                and record.auth_mode is auth_mode
                and record.native_pool_id is not None
            ),
            None,
        )

    async def record_uncertain(
        self, admission: LimitAdmission, *, reason: str, upstream_complete: bool = False
    ) -> None:
        """Finalize one dispatched attempt whose upstream receipt is unknown.

        A cancellation after dispatch cannot prove the vendor skipped the
        call, so the reservation is not refunded: it finalizes with the
        reserved native and credit amounts (and keeps its rate units). Vendor
        truth reconciles a later usage poll; the local books stay conservative.
        """

        if self._repository is None:
            return
        await self._repository.finalize(
            LimitDebit(
                attempt_id=admission.attempt_id,
                provider=admission.provider,
                operation=admission.operation,
                auth_mode=admission.auth_mode,
                pool_id=admission.pool_id,
                outcome="failure",
                native_units=admission.reserved_native,
                successful_urls=0,
                crd_debit=admission.reserved_crd,
                native_unit=self._record(
                    admission.provider, admission.operation, admission.auth_mode
                ).native_unit,
                reason="local_unknown_charge" if upstream_complete else "local_uncertain",
                audit_source="local",
            )
        )

    async def release_admission(self, admission: LimitAdmission) -> None:
        """Refund a reservation whose vendor call provably never started."""

        if self._repository is None:
            return
        await self._repository.release(admission.attempt_id, "cancelled", refund_rate=True)

    async def record_success(
        self,
        admission: LimitAdmission,
        response: SearchResponse | FetchResponse,
        *,
        request: SearchRequest | FetchRequest | None = None,
    ) -> None:
        """Finalize one successful attempt with its actual native and CRD debit.

        An attempt that drew on the estimated daily free pool records one query
        from that pool and its priced allowance value in credit units, so the
        daily count and the daily credit-unit value stay one counter and one
        debit.
        """

        record = self._record(admission.provider, admission.operation, admission.auth_mode)
        daily_tier = self._daily_tier(record)
        # A credential/pool-scoped daily pool (``<daily>#cred:...``) is the
        # same declared tier for this one credential instance.
        daily = (
            daily_tier is not None
            and admission.pool_id is not None
            and (
                admission.pool_id == daily_tier.pool_id
                or admission.pool_id.startswith(f"{daily_tier.pool_id}#")
            )
        )
        if daily:
            native_units: Decimal | None = Decimal("1")
            crd_debit = request_cost_crd(record, request)
        else:
            native_units = _reported_native(response, record)
            if native_units is None:
                native_units = request_native_cost(record, request)
            crd_debit = _debit_crd(record, native_units)
        if self._repository is None:
            return
        await self._repository.finalize(
            LimitDebit(
                attempt_id=admission.attempt_id,
                provider=admission.provider,
                operation=admission.operation,
                auth_mode=admission.auth_mode,
                pool_id=admission.pool_id,
                outcome="success",
                native_units=native_units,
                successful_urls=_successful_urls(response),
                actual_usd=_reported_usd(response),
                crd_debit=crd_debit,
                # The admission already chose the pool, and finalize reads that
                # pool row inside its own transaction; the unit therefore comes
                # from the same catalog tier that declared the pool, not from a
                # separate pre-read connection.
                native_unit=(
                    daily_tier.native_unit
                    if daily and daily_tier is not None
                    else record.native_unit
                ),
                reason="local_success",
            )
        )

    async def record_failure(
        self,
        admission: LimitAdmission,
        error: ProviderError,
        *,
        charged_native: Decimal | None = None,
        charged_document: bool = False,
    ) -> None:
        """Finalize one failed attempt.

        A definite failure with no confirmed charge records zero credit units and
        releases the reservation. A confirmed native charge, including the
        Firecrawl returned-document exception, still records its priced debit.
        """

        if self._repository is None:
            return
        record = self._record(admission.provider, admission.operation, admission.auth_mode)
        if not charged_document or charged_native is None:
            await self._repository.release(admission.attempt_id, error.code)
            return
        await self._repository.finalize(
            LimitDebit(
                attempt_id=admission.attempt_id,
                provider=admission.provider,
                operation=admission.operation,
                auth_mode=admission.auth_mode,
                pool_id=admission.pool_id,
                outcome="failure",
                native_units=charged_native,
                successful_urls=1,
                actual_usd=_reported_usd_or_none(error),
                charged_document=True,
                crd_debit=_debit_crd(record, charged_native),
                native_unit=record.native_unit,
                reason="local_failure",
            )
        )

    async def record_terminal_402(
        self,
        provider: str,
        auth_mode: AuthMode,
        *,
        credential_id: UUID | None = None,
        upstream_pool_id: UUID | None = None,
    ) -> None:
        """Write one terminal out-of-Credits observation after a vendor 402.

        A credential-scoped or shared-pool attempt records its zero against the
        exact resolved pool and credential instance, so an unrelated credential
        of the same provider stays usable. Only an unattributed provider-wide
        call keeps the legacy catalog-pool behavior. The same terminal fact is
        also stored as a credential-scoped quota observation, which the routing
        plan reads per credential. A missing pool, credential store, or failed
        write stays silent: the next usage poll or monthly refill restores pool
        truth.
        """

        record = next(
            (
                candidate
                for candidate in self._records
                if candidate.provider == provider
                and candidate.auth_mode is auth_mode
                and candidate.native_pool_id is not None
            ),
            None,
        )
        if record is None or self._repository is None:
            return
        base_pool_id = record.native_pool_id
        if base_pool_id is None:
            return
        if upstream_pool_id is not None:
            pool_id = f"{base_pool_id}#pool:{upstream_pool_id}"
        elif credential_id is not None:
            pool_id = f"{base_pool_id}#cred:{credential_id}"
        else:
            pool_id = base_pool_id
        pool = await self._repository.get_pool(pool_id)
        if pool is None and pool_id != base_pool_id:
            pool = await self._repository.ensure_pool(
                NativePool(
                    pool_id=pool_id,
                    provider=provider,
                    auth_mode=auth_mode,
                    native_unit=record.native_unit or UnitKind.REQUEST,
                    source="credential_scope",
                    confidence=Confidence.UNKNOWN,
                )
            )
        if pool is None:
            return
        now = self._clock()
        with contextlib.suppress(Exception):
            await self._repository.apply_snapshot(
                NativeUsageSnapshot(
                    pool_id=pool_id,
                    provider=provider,
                    auth_mode=auth_mode,
                    native_unit=pool.native_unit,
                    observed_at=now,
                    source=_TAVILY_TERMINAL_SOURCE,
                    confidence=Confidence.OBSERVED,
                    remaining=Decimal("0"),
                    allowance=pool.allowance,
                    reset_at=pool.reset_at or _next_month_start(now),
                    credential_generation=pool.credential_generation,
                    plan_name=record.plan_name,
                )
            )

    def _reservation(
        self,
        record: ProviderLimitRecord,
        context: LimitCallContext,
        rate_admission: RateAdmission,
        pool_id: str | None,
    ) -> LimitAdmission:
        created = context.requested_at
        request = _as_request(context)
        return LimitAdmission(
            attempt_id=context.attempt_id,
            provider=context.provider,
            operation=context.operation,
            auth_mode=context.auth_mode,
            pool_id=pool_id,
            reserved_crd=request_cost_crd(record, request) or Decimal("0"),
            reserved_native=request_native_cost(record, request),
            state="reserved",
            created_at=created,
            expires_at=effective_attempt_deadline(created),
            rate_reservations=rate_admission.reservations,
            project_id=context.project_id,
            credential_id=context.credential_id,
            binding_id=context.binding_id,
            upstream_pool_id=context.upstream_pool_id,
            request_id=context.request_id,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
        )

    async def _selected_pool_id(
        self,
        record: ProviderLimitRecord,
        request: SearchRequest | FetchRequest | None,
        *,
        context: LimitCallContext | None = None,
    ) -> str | None:
        """Return the pool an attempt draws on, preferring a covering daily pool.

        A project credential's private vendor balance is keyed to that
        credential, and a credential linked to a shared upstream pool draws on
        the pool's one balance; only an unattributed/system attempt keeps the
        provider-wide catalog pool. A scoped pool row is created without a
        balance first, so an unknown balance stays eligible until a vendor
        observation or terminal 402 records the truth.
        """

        base = record.native_pool_id
        scoped = self._scoped_pool_id(base, record, context)
        if scoped is None or self._repository is None:
            return scoped
        if scoped != base:
            await self._repository.ensure_pool(
                NativePool(
                    pool_id=scoped,
                    provider=record.provider,
                    auth_mode=record.auth_mode,
                    native_unit=record.native_unit or UnitKind.REQUEST,
                    source="credential_scope",
                    confidence=Confidence.UNKNOWN,
                )
            )
        daily_id = self._daily_pool_id(record)
        if daily_id is None:
            return scoped
        scoped_daily = self._scoped_pool_id(daily_id, record, context)
        if scoped_daily is None:
            return scoped
        if scoped_daily == daily_id or self._repository is None:
            daily = await self._repository.get_pool(daily_id) if self._repository else None
        else:
            base_daily = await self._repository.get_pool(daily_id)
            daily = await self._repository.ensure_pool(
                NativePool(
                    pool_id=scoped_daily,
                    provider=record.provider,
                    auth_mode=record.auth_mode,
                    native_unit=(
                        base_daily.native_unit
                        if base_daily is not None
                        else record.native_unit or UnitKind.REQUEST
                    ),
                    remaining=base_daily.remaining if base_daily is not None else None,
                    allowance=base_daily.allowance if base_daily is not None else None,
                    source=base_daily.source if base_daily is not None else "credential_scope",
                    confidence=(
                        base_daily.confidence if base_daily is not None else Confidence.UNKNOWN
                    ),
                    reset_at=base_daily.reset_at if base_daily is not None else None,
                )
            )
        cost = request_cost_crd(record, request)
        remaining = native_to_crd(daily, record.conversion_profile) if daily is not None else None
        if remaining is not None and cost is not None and remaining >= cost:
            return scoped_daily
        return scoped

    @staticmethod
    def _scoped_pool_id(
        base: str | None,
        record: ProviderLimitRecord,
        context: LimitCallContext | None,
    ) -> str | None:
        """Return the credential/pool-scoped native pool id of one attempt.

        The scope suffix keeps two project credentials of one provider, or two
        independent upstream pools, from sharing a funds balance. A shared
        upstream pool uses one suffix for every credential attached to it, so
        a terminal 402 on the pool correctly affects the pool's members and an
        unrelated credential stays clean.
        """

        if context is None:
            return base
        if context.upstream_pool_id is not None:
            scope = f"pool:{context.upstream_pool_id}"
        elif context.credential_id is not None:
            scope = f"cred:{context.credential_id}"
        else:
            return base
        root = base or (
            native_pool_id(record.provider, record.auth_mode, record.native_unit)
            if record.native_unit is not None
            else f"{record.provider}:{record.auth_mode.value}:credits"
        )
        return f"{root}#{scope}"

    def _daily_tier(self, record: ProviderLimitRecord) -> TierBalance | None:
        """Return the declared estimated daily tier of one search rail."""

        if record.auth_mode is not AuthMode.KEYED or record.operation is not LimitOperation.SEARCH:
            return None
        for tier in self._tiers.get(f"{record.provider}:{record.auth_mode.value}", []):
            if tier.reset_rule is ResetRule.DAILY_ESTIMATE:
                return tier
        return None

    def _daily_pool_id(self, record: ProviderLimitRecord) -> str | None:
        """Return the estimated daily free pool of one search rail, when declared."""

        tier = self._daily_tier(record)
        return tier.pool_id if tier is not None else None

    async def _funds_decision(
        self,
        record: ProviderLimitRecord,
        context: LimitCallContext,
        *,
        pool_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[str, list[str]]:
        """Return the funds decision and its reasons for one request."""

        view = await self._view_for(
            record, self._clock(), _as_request(context), pool_id=pool_id, session=session
        )
        if record.provider == "tavily":
            precheck = await self._tavily_funds_precheck(
                record, view, pool_id=pool_id, session=session
            )
            if precheck is not None:
                return precheck
        if view.state is CRDState.UNMETERED:
            return (_FUNDS_OK, [])
        if view.state is CRDState.UNAVAILABLE:
            return (_FUNDS_DENIED, ["unavailable"])
        cost = view.request_cost_crd
        if cost is None:
            return (_FUNDS_UNPRICED, ["price_unknown"])
        spendable = view.spendable_crd
        if spendable is None:
            # An unknown paid balance stays eligible unless an explicit local
            # grant of zero forbids it.
            if view.local_remaining_crd is not None and view.local_remaining_crd == 0:
                return (_FUNDS_DENIED, ["grant_exhausted"])
            return (_FUNDS_OK, [])
        if spendable < cost:
            return (_FUNDS_DENIED, ["funds_exhausted"])
        return (_FUNDS_OK, [])

    async def _tavily_funds_precheck(
        self,
        record: ProviderLimitRecord,
        view: CRDView,
        *,
        pool_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[str, list[str]] | None:
        """Return the keyed Credits decision, or None for the generic CRD gate.

        The keyed rail stores its native Credits balance on one durable pool.
        A terminal vendor 402 observation denies the call until the monthly
        refill, unless stored usage tiers or the operator PAYGO choice confirm
        paid overage. A zero aggregate whose stored observed paid-plan tier
        still holds native funds is the vendor KEY ceiling: that denial reason
        is ``key_cap_exhausted`` and PAYGO never lifts it, while a plan-bound
        zero keeps the overage rule. A local grant spend cap keeps the generic
        gate, so its denial reasons stay unchanged for reserved operator
        funds.
        """

        if (
            not record.supported
            or not record.transport_available
            or record.auth_mode is not AuthMode.KEYED
            or record.native_pool_id is None
            or self._repository is None
        ):
            return None
        pool = await self._repository.get_pool(pool_id or record.native_pool_id, session=session)
        if pool is None:
            return None
        if _tavily_key_cap_zero(pool):
            return (_FUNDS_DENIED, ["key_cap_exhausted"])
        confirmed = self._tavily_paygo_confirmed(pool)
        if pool.source == _TAVILY_TERMINAL_SOURCE and not confirmed:
            return (_FUNDS_DENIED, ["credits_exhausted"])
        if confirmed and _tavily_free_exhausted(pool, view) and self._grant_overage_allowed(view):
            return (_FUNDS_OK, [])
        return None

    def _tavily_paygo_confirmed(self, pool: NativePool) -> bool:
        """Return whether configuration or stored usage confirms PAID overage.

        The operator flag is the explicit confirmation. The usage snapshot's
        PAYGO tier confirms overage when the vendor payload reported its
        fields, and an OBSERVED paid-plan tier with a known amount confirms a
        paid plan. A free plan keeps the terminal denial until the monthly
        refill.
        """

        if self._tavily_paygo_enabled:
            return True
        paygo = _stored_tier(pool, _TAVILY_PAYGO_TIER_ID)
        if paygo is not None and paygo.confidence is Confidence.OBSERVED:
            return True
        plan = _stored_tier(pool, _TAVILY_PLAN_TIER_ID)
        return (
            plan is not None
            and plan.confidence is Confidence.OBSERVED
            and (plan.native_remaining is not None or plan.native_allowance is not None)
        )

    @staticmethod
    def _grant_overage_allowed(view: CRDView) -> bool:
        """Return whether a local grant spend cap still permits one call.

        A grant is an operator spend cap, not vendor funds: confirmed overage
        must not bypass it, so the effective grant ceiling must still cover
        the whole request cost.
        """

        cost = view.request_cost_crd
        grant = view.local_remaining_crd
        return cost is not None and (grant is None or grant >= cost)

    async def _audit_denial(
        self,
        context: LimitCallContext,
        reasons: Sequence[str],
        *,
        refusal: str,
        retry_after: int | None = None,
    ) -> None:
        if self._repository is None:
            return
        await self._repository.record_event(
            LimitAuditEvent(
                event_id=uuid4().hex,
                provider=context.provider,
                auth_mode=context.auth_mode,
                operation=context.operation,
                observed_at=datetime.now(UTC),
                source="local",
                reason="soft_402" if refusal == "funds" else "local_rate_denial",
                crd_debit=Decimal("0"),
                local_attempt_id=context.attempt_id,
                detail={
                    "refusal": refusal,
                    "reasons": list(reasons),
                    "retry_after": retry_after,
                },
            )
        )

    # ----------------------------------------------------------------- views

    async def provider_view(self, provider: str) -> ProviderLimitsResponse:
        """Return the dashboard payload for one provider and both auth modes.

        A canonical provider without a catalog record still gets a payload with
        an empty auth list, so a direct read of a registered name never fails.
        The dashboard lists only the providers that hold catalog records.
        """

        now = self._clock()
        records = [record for record in self._records if record.provider == provider]
        pools = {
            pool.pool_id: pool
            for pool in (await self._repository.list_pools(provider) if self._repository else [])
        }
        await self._refresh_daily_pool(provider, pools, now)
        await self._refresh_monthly_pool(provider, pools, now)
        # Project newer credential-scoped observations for display only.
        identities = {}
        if self._repository is not None and any("#" in pool_id for pool_id in pools):
            identities = await self._repository.observation_identities(provider)
        card_pools = _with_scoped_observations(pools, identities)
        return ProviderLimitsResponse(
            provider=provider,
            active_auth_mode=self._active_mode(provider, records),
            auths=[
                await self._auth_limits(provider, auth_mode, records, card_pools, now)
                for auth_mode in _auth_modes(records)
            ],
            documented_keyless_operations=documented_keyless_operations(provider),
            version=max((record.version for record in records), default=1),
            generated_at=now,
        )

    async def dashboard_views(self) -> list[ProviderLimitsResponse]:
        """Return one payload per catalog provider, in stable order.

        PLAN revision 6 section 2 gives the main card count per slice, and the
        core slice S0 holds zero records, so an empty catalog yields no cards.
        """

        views: list[ProviderLimitsResponse] = []
        for provider in sorted({record.provider for record in self._records}):
            try:
                views.append(await self.provider_view(provider))
            except Exception:
                logger.warning("provider limit view could not be built")
        return views

    async def usage_totals(self) -> list[CRDUsageTotal]:
        """Return credit-unit cost and operation volume totals."""

        if self._repository is None:
            return []
        return await self._repository.crd_usage_totals()

    async def sync_provider_once(self, provider: str) -> None:
        """Reserve nothing; exposed for the schedule seam to call a fresh read."""

        return None

    async def save_grant(
        self,
        provider: str,
        update: CRDGrantUpdate,
        auth_mode: AuthMode = AuthMode.KEYED,
    ) -> ProviderLimitsResponse:
        """Store an operator grant and return the refreshed provider payload."""

        repository = self._require_repository(provider)
        await repository.save_grant(provider, update, auth_mode=auth_mode)
        return await self.provider_view(provider)

    async def history(self, query: LimitHistoryQuery) -> LimitHistoryPage:
        """Return one page of a provider's audit history."""

        if self._repository is None:
            return LimitHistoryPage()
        return await self._repository.list_history(query)

    async def update_record(self, change: LimitRecordUpdate) -> ProviderLimitsResponse:
        """Apply a catalog change and return the refreshed provider payload."""

        repository = self._require_repository(change.provider)
        record = await repository.update_record(change)
        self._refresh_record(record)
        return await self.provider_view(change.provider)

    def _refresh_record(self, record: ProviderLimitRecord) -> None:
        """Swap one refreshed record into the in-memory catalog and the rate gate."""

        self._records = [record if item.key == record.key else item for item in self._records]
        self._rates.replace_records(self._records)

    def _require_repository(self, provider: str) -> LimitRepository:
        if self._repository is None:
            raise LimitStoreUnavailable(provider)
        return self._repository

    def _active_mode(self, provider: str, records: Sequence[ProviderLimitRecord]) -> AuthMode:
        """Return the rail the runtime executes with, when the catalog is known.

        Tavily and Keenable adapters decide their rails from credentials, so
        their stored adapter-derived modes win where available. Other providers
        keep the catalog-derived fallback an empty record list has provided so
        far.
        """

        if provider == "tavily" and self._tavily_auth_mode is not None and records:
            return self._tavily_auth_mode
        if provider == "keenable" and self._keenable_auth_mode is not None and records:
            return self._keenable_auth_mode
        return _active_auth_mode(records) if records else AuthMode.KEYED

    # ------------------------------------------------------------- internals

    def _record(
        self, provider: str, operation: LimitOperation, auth_mode: AuthMode
    ) -> ProviderLimitRecord:
        for record in self._records:
            if (
                record.provider == provider
                and record.operation is operation
                and record.auth_mode is auth_mode
            ):
                return record
        raise LimitRecordNotFound(provider, operation.value, auth_mode.value)

    async def _auth_limits(
        self,
        provider: str,
        auth_mode: AuthMode,
        records: Sequence[ProviderLimitRecord],
        pools: dict[str, NativePool],
        now: datetime,
    ) -> ProviderAuthLimits:
        auth_records = [record for record in records if record.auth_mode is auth_mode]
        search = _find(auth_records, LimitOperation.SEARCH)
        fetch = _find(auth_records, LimitOperation.FETCH)
        grants = (
            await self._repository.grants(provider, auth_mode, now=now)
            if self._repository
            else None
        )
        tiers = self._tiers_for(provider, auth_mode, pools, grants)
        free_tiers = [tier for tier in tiers if tier.tier == "free"]
        paid_tiers = [tier for tier in tiers if tier.tier == "paid"]
        unknown_tiers = [tier for tier in tiers if tier.tier == "unknown"]
        # The Tavily rail exposes live minute headroom and its vendor cooldown
        # through the detail windows; the hourly/daily progress contract above
        # stays untouched.
        rate_windows = (
            await self._rates.window_details(provider, auth_mode, now)
            if provider == "tavily"
            else None
        )
        return ProviderAuthLimits(
            auth_mode=auth_mode,
            transport_available=any(record.transport_available for record in auth_records),
            search=search,
            fetch=fetch,
            free_tiers=free_tiers,
            paid_tiers=paid_tiers,
            unknown_tiers=unknown_tiers,
            tier_split_known=any(tier.native_remaining is not None for tier in free_tiers)
            or any(tier.native_remaining is not None for tier in paid_tiers),
            aggregate_pool=_aggregate_pool(pools, auth_records),
            crd_views=[
                self._pool_view(
                    record,
                    pools.get(record.native_pool_id or ""),
                    grants,
                    now,
                    pools.get(self._daily_pool_id_for(provider, auth_mode) or ""),
                )
                for record in auth_records
            ],
            rate_progress=self._daily_bar(
                provider, auth_mode, pools, await self._rates.progress(provider, now)
            ),
            grants=grants,
            detail=_detail(
                search or fetch,
                pools,
                tiers,
                grants,
                rate_windows=rate_windows,
                now=now,
            ),
        )

    def _daily_bar(
        self,
        provider: str,
        auth_mode: AuthMode,
        pools: dict[str, NativePool],
        bars: Sequence[RateProgressView],
    ) -> list[RateProgressView]:
        """Show the estimated daily free allowance from its one stored counter.

        The bar and the credit-unit free tier reference the same subpool, so the
        bar never counts separately from the daily pool.
        """

        daily_id = self._daily_pool_id_for(provider, auth_mode)
        if daily_id is None:
            return list(bars)
        pool = pools.get(daily_id)
        return [
            bar.model_copy(
                update={
                    "kind": "free_daily_allowance",
                    "remaining": pool.remaining if pool is not None else bar.remaining,
                    "reset_at": (pool.reset_at if pool is not None else None) or bar.reset_at,
                    "source": "local_daily_estimate",
                    "confidence": Confidence.ESTIMATED,
                    "enforceable": False,
                }
            )
            if bar.bucket_id == daily_id
            else bar
            for bar in bars
        ]

    def _daily_pool_id_for(self, provider: str, auth_mode: AuthMode) -> str | None:
        for tier in self._tiers.get(f"{provider}:{auth_mode.value}", []):
            if tier.reset_rule is ResetRule.DAILY_ESTIMATE:
                return tier.pool_id
        return None

    def _pool_view(
        self,
        record: ProviderLimitRecord,
        pool: NativePool | None,
        grants: CRDGrantsSummary | None,
        now: datetime,
        daily_pool: NativePool | None = None,
    ) -> CRDView:
        grant_remaining = grants.remaining(record.operation) if grants is not None else None
        daily = self._daily_view(record, grant_remaining, now, daily_pool)
        if daily is not None and _covers(daily):
            return daily
        return crd_view(record, pool, grant_remaining=grant_remaining)

    def _daily_view(
        self,
        record: ProviderLimitRecord,
        grant_remaining: Decimal | None,
        now: datetime,
        daily_pool: NativePool | None,
    ) -> CRDView | None:
        """Return the estimated daily free view of one search record, if declared."""

        pool_id = self._daily_pool_id(record)
        if pool_id is None:
            return None
        tier = next(
            (
                item
                for item in self._tiers.get(f"{record.provider}:{record.auth_mode.value}", [])
                if item.pool_id == pool_id
            ),
            None,
        )
        if tier is None or tier.native_allowance is None:
            return None
        native_remaining = (
            daily_pool.remaining
            if daily_pool is not None and daily_pool.remaining is not None
            else tier.native_remaining
        )
        profile = self._profile_for(record.provider, record.auth_mode, tier)
        return CRDView(
            state=CRDState.FINITE,
            operation=record.operation,
            remaining_crd=_tier_crd(tier, native_remaining, profile),
            local_remaining_crd=grant_remaining,
            request_cost_crd=request_cost_crd(record),
            shared_pool_id=pool_id,
            possible_standard_calls=native_remaining,
            price_version=record.conversion_profile.price_version,
            priced=True,
        )

    async def _view_for(
        self,
        record: ProviderLimitRecord,
        now: datetime,
        request: SearchRequest | FetchRequest | None,
        *,
        pool_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> CRDView:
        pool = None
        if self._repository is not None and (pool_id or record.native_pool_id) is not None:
            pool = await self._repository.get_pool(
                pool_id or record.native_pool_id or "", session=session
            )
        grants = (
            await self._repository.grants(
                record.provider, record.auth_mode, now=now, session=session
            )
            if self._repository
            else None
        )
        grant_remaining = grants.remaining(record.operation) if grants is not None else None
        daily_pool = await self._daily_pool(record, session=session)
        daily = (
            self._daily_view(record, grant_remaining, now, daily_pool)
            if daily_pool is not None and (pool_id is None or pool_id == daily_pool.pool_id)
            else None
        )
        if daily is not None and _covers(daily):
            view = daily
        else:
            view = crd_view(record, pool, request=request)
        return effective_crd(view, grant_remaining)

    async def _daily_pool(
        self, record: ProviderLimitRecord, *, session: AsyncSession | None = None
    ) -> NativePool | None:
        """Return the stored estimated daily pool of one record, when declared."""

        pool_id = self._daily_pool_id(record)
        if pool_id is None or self._repository is None:
            return None
        return await self._repository.get_pool(pool_id, session=session)

    def _declared_pools(self) -> list[NativePool]:
        """Return the pool rows the catalog declares, without a balance."""

        pools: dict[str, NativePool] = {}
        for record in self._records:
            if record.native_pool_id is None or record.native_unit is None:
                continue
            pools.setdefault(
                record.native_pool_id,
                NativePool(
                    pool_id=record.native_pool_id,
                    provider=record.provider,
                    auth_mode=record.auth_mode,
                    native_unit=record.native_unit,
                    source="declared",
                    confidence=Confidence.UNKNOWN,
                ),
            )
        for key, tiers in self._tiers.items():
            provider, _, auth_mode = key.partition(":")
            for tier in tiers:
                if tier.reset_rule is not ResetRule.DAILY_ESTIMATE:
                    continue
                if tier.native_allowance is None:
                    continue
                pools.setdefault(
                    tier.pool_id,
                    NativePool(
                        pool_id=tier.pool_id,
                        provider=provider,
                        auth_mode=AuthMode(auth_mode),
                        native_unit=tier.native_unit,
                        allowance=tier.native_allowance,
                        remaining=tier.native_allowance,
                        source="local_daily_estimate",
                        confidence=Confidence.ESTIMATED,
                        reset_at=_day_start(self._clock()) + timedelta(days=1),
                    ),
                )
        return list(pools.values())

    async def _refresh_daily_pool(
        self, provider: str, pools: dict[str, NativePool], now: datetime
    ) -> None:
        """Refill an estimated daily pool at its UTC boundary, and only that pool."""

        if self._repository is None:
            return
        for tier in self._tiers.get(f"{provider}:{AuthMode.KEYED.value}", []):
            if tier.reset_rule is not ResetRule.DAILY_ESTIMATE or tier.native_allowance is None:
                continue
            pool = pools.get(tier.pool_id) or _daily_pool(provider, tier, now)
            reset_at = pool.reset_at or _day_start(now) + timedelta(days=1)
            if pool.remaining is not None and now < reset_at and pool.pool_id in pools:
                continue
            refreshed = await self._repository.record_manual_anchor(
                pool,
                remaining=tier.native_allowance,
                allowance=tier.native_allowance,
                reset_at=_day_start(now) + timedelta(days=1),
                observed_at=now,
                source="local_daily_estimate",
            )
            if refreshed is not None:
                pools[pool.pool_id] = refreshed
                await self._repository.record_event(
                    LimitAuditEvent(
                        event_id=uuid4().hex,
                        provider=provider,
                        auth_mode=AuthMode.KEYED,
                        operation=LimitOperation.SEARCH,
                        pool_id=pool.pool_id,
                        observed_at=now,
                        source="local_daily_estimate",
                        reason="reset",
                        old_native=pool.remaining,
                        new_native=tier.native_allowance,
                        confidence=Confidence.ESTIMATED,
                    )
                )

    async def _refresh_monthly_pool(
        self, provider: str, pools: dict[str, NativePool], now: datetime
    ) -> None:
        """Refill a keyed Credits month whose free exhaustion expired.

        A terminal vendor 402 observation or an exhaustion zero denies keyed
        calls until the documented first-of-month reset. This local path
        expires that state without a request-path vendor read and refills only
        the declared free allowance from the record's budget. A pool whose
        usage snapshot observed the paid plan or PAYGO tier is never refilled
        with the free allowance, because paid funds are not free Credits.
        """

        if self._repository is None or provider not in ("tavily", "exa"):
            return
        processed: set[str] = set()
        keyed_records = [
            r for r in self._records if r.provider == provider and r.auth_mode is AuthMode.KEYED
        ]
        for record in keyed_records:
            allowance = record.budget.free_allowance if record.budget is not None else None
            pool_id = record.native_pool_id
            if pool_id is None or allowance is None or pool_id in processed:
                continue
            processed.add(pool_id)
            pool = pools.get(pool_id)
            if pool is None or not _free_month_expired(pool, now):
                continue
            if _tavily_paygo_observed(pool):
                continue
            refreshed = await self._repository.record_manual_anchor(
                pool,
                remaining=allowance,
                allowance=allowance,
                reset_at=_next_month_start(now),
                observed_at=now,
                source=_TAVILY_MONTHLY_RESET_SOURCE,
            )
            if refreshed is None:
                continue
            pools[pool.pool_id] = refreshed
            await self._repository.record_event(
                LimitAuditEvent(
                    event_id=uuid4().hex,
                    provider=provider,
                    auth_mode=AuthMode.KEYED,
                    operation=LimitOperation.SEARCH,
                    pool_id=pool.pool_id,
                    observed_at=now,
                    source=_TAVILY_MONTHLY_RESET_SOURCE,
                    reason="reset",
                    old_native=pool.remaining,
                    new_native=allowance,
                    confidence=Confidence.ESTIMATED,
                )
            )

    def _tiers_for(
        self,
        provider: str,
        auth_mode: AuthMode,
        pools: dict[str, NativePool],
        grants: CRDGrantsSummary | None,
    ) -> list[TierBalance]:
        """Project declared tiers with observed balances and credit-unit values."""

        tiers: list[TierBalance] = []
        for tier in self._tiers.get(f"{provider}:{auth_mode.value}", []):
            # A usage snapshot persists its tier facts on the aggregate pool.
            # A vendor-observed tier row wins over the catalog-only
            # declaration, and the free and paid tiers stay alternative views
            # of one pool, so the aggregate funds are never duplicated into
            # the tier sums.
            stored = _observed_stored_tier(tier.pool_id, pools)
            if stored is not None:
                tier = _project_stored_tier(tier, stored)
            pool = pools.get(tier.pool_id)
            profile = self._profile_for(provider, auth_mode, tier)
            remaining = pool.remaining if pool is not None else tier.native_remaining
            allowance = pool.allowance if pool is not None else tier.native_allowance
            if remaining is None:
                remaining = tier.native_remaining
            if allowance is None:
                allowance = tier.native_allowance
            updated = tier.model_copy(
                update={
                    "native_remaining": remaining,
                    "native_allowance": allowance,
                    "remaining_crd": _tier_crd(tier, remaining, profile),
                    "allowance_crd": _tier_crd(tier, allowance, profile),
                    "confidence": _tier_confidence(tier, pool),
                    "source": pool.source if pool is not None else tier.source,
                    "reset_at": (pool.reset_at if pool is not None else None) or tier.reset_at,
                }
            )
            tiers.append(_mark_unknown(updated))
        return _with_grant_tiers(tiers, grants, provider, auth_mode)

    def _profile_for(
        self, provider: str, auth_mode: AuthMode, tier: TierBalance
    ) -> CRDPriceProfile:
        """Return the conversion profile that prices one tier's native unit.

        The tier's own unit wins. A subpool measured in a different unit, such
        as the You.com daily query allowance inside a USD account, uses the
        provider's search profile, which carries the documented USD price of one
        standard call.
        """

        candidates = [
            record
            for record in self._records
            if record.provider == provider and record.auth_mode is auth_mode
        ]
        for record in candidates:
            if record.native_unit is tier.native_unit:
                return record.conversion_profile
        for record in candidates:
            if record.operation is LimitOperation.SEARCH:
                return record.conversion_profile
        return CRDPriceProfile()


def _is_fresh_vendor_value(pool: NativePool) -> bool:
    """Return whether a pool holds a fresh, vendor-confirmed value."""

    return pool.confidence is Confidence.AUTHORITATIVE and not pool.stale and not pool.manual_anchor


def _minute_window(block: RateBlock | ProviderLimitRecord) -> RateWindow | None:
    """Return a rate block or record's documented minute window, when declared."""

    rate = block if isinstance(block, RateBlock) else block.rate
    if rate is None:
        return None
    return next(
        (window for window in rate.windows if window.window is RateWindowName.MINUTE),
        None,
    )


def _tavily_minute_rate(environment: Literal["dev", "prod"]) -> RateBlock:
    """Build the documented shared minute bucket for one key environment.

    Search and extract share the keyed default bucket, so both operation
    records receive the same block: one minute window at the configured
    per-key request limit from the provider limit catalog.
    """

    return RateBlock(
        windows=[
            RateWindow(
                bucket_id=TAVILY_DEFAULT_BUCKET_ID,
                limit=TAVILY_RPM_DEV if environment == "dev" else TAVILY_RPM_PROD,
                window=RateWindowName.MINUTE,
                scope=RateScope.KEY,
                source="configured_key_environment",
            )
        ],
        published=True,
    )


def _next_month_start(now: datetime) -> datetime:
    """Return the first instant of the month after ``now`` in UTC."""

    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return datetime(now.year, now.month + 1, 1, tzinfo=UTC)


def _stored_tier(pool: NativePool, tier_pool_id: str) -> TierBalance | None:
    """Return the tier row one pool's usage snapshot persisted, when present."""

    return next((tier for tier in pool.tiers if tier.pool_id == tier_pool_id), None)


def _observed_stored_tier(tier_pool_id: str, pools: Mapping[str, NativePool]) -> TierBalance | None:
    """Return the vendor-observed tier row for one catalog tier, when stored.

    A usage snapshot carries its tier facts on the aggregate native pool, so
    the stored rows surface wherever that pool is held. Only an OBSERVED tier
    outranks the catalog declaration; an unknown row keeps the declaration.
    """

    for pool in pools.values():
        for stored in pool.tiers:
            if stored.pool_id == tier_pool_id and stored.confidence is Confidence.OBSERVED:
                return stored
    return None


def _project_stored_tier(tier: TierBalance, stored: TierBalance) -> TierBalance:
    """Merge one stored tier row over a catalog tier declaration.

    The stored reported values, funding mode, and provenance replace the
    declared placeholders; the reset behavior stays the catalog's because the
    declared monthly rule is what the vendor follows.
    """

    return tier.model_copy(
        update={
            "native_remaining": stored.native_remaining,
            "native_allowance": stored.native_allowance,
            "funding_mode": stored.funding_mode,
            "source": stored.source,
            "confidence": stored.confidence,
        }
    )


def _tavily_paygo_observed(pool: NativePool) -> bool:
    """Return whether the usage snapshot observed a paid plan or PAYGO tier.

    A pool that carries such a tier is paid or unknown, so the free monthly
    allowance must never refill it: paid Credits and pay-as-you-go access are
    not the free plan's development budget.
    """

    return any(
        tier.confidence is Confidence.OBSERVED
        and tier.pool_id in (_TAVILY_PAYGO_TIER_ID, _TAVILY_PLAN_TIER_ID)
        for tier in pool.tiers
    )


def _free_month_expired(pool: NativePool, now: datetime) -> bool:
    """Return whether a keyed Credits pool's exhausted month has ended.

    A terminal vendor 402 observation or an exhaustion zero expires once the
    stored reset instant has passed or once the observation is from a month
    earlier than the current one, so a local refill can replace it without a
    request-path vendor read.
    """

    exhausted = pool.source == _TAVILY_TERMINAL_SOURCE or pool.remaining == Decimal("0")
    if not exhausted:
        return False
    if pool.reset_at is not None and now >= pool.reset_at:
        return True
    observed = pool.observed_at
    if observed is None:
        return False
    return (observed.year, observed.month) < (now.year, now.month)


def _tavily_free_exhausted(pool: NativePool, view: CRDView) -> bool:
    """Return whether the free plan Credits and the spendable view are both zero."""

    return (
        pool.remaining is not None
        and pool.remaining == Decimal("0")
        and view.spendable_crd is not None
        and view.spendable_crd == Decimal("0")
    )


def _tavily_key_cap_zero(pool: NativePool) -> bool:
    """Return whether a zero aggregate proves a KEY ceiling, not a plan bound.

    The stored usage tiers split the collapsed ``min(plan, key)`` balance the
    usage snapshot published. An observed paid-plan tier whose native balance
    is still above zero shows the plan is funded, so the aggregate zero is the
    vendor key ceiling and PAYGO overage never lifts it. A plan-bound zero
    keeps the PAYGO overage rule instead.
    """

    plan = _stored_tier(pool, _TAVILY_PLAN_TIER_ID)
    return (
        pool.remaining == Decimal("0")
        and plan is not None
        and plan.confidence is Confidence.OBSERVED
        and plan.native_remaining is not None
        and plan.native_remaining > 0
    )


def _active_auth_mode(records: Sequence[ProviderLimitRecord]) -> AuthMode:
    """Return the rail the runtime currently executes with."""

    keyless = [
        record
        for record in records
        if record.auth_mode is AuthMode.KEYLESS and record.transport_available
    ]
    if keyless and not any(record.auth_mode is AuthMode.KEYED for record in records):
        return AuthMode.KEYLESS
    return AuthMode.KEYED


def _auth_modes(records: Sequence[ProviderLimitRecord]) -> list[AuthMode]:
    modes = {record.auth_mode for record in records}
    return sorted(modes, key=lambda mode: 0 if mode is AuthMode.KEYED else 1)


def _find(
    records: Sequence[ProviderLimitRecord], operation: LimitOperation
) -> ProviderLimitRecord | None:
    return next((record for record in records if record.operation is operation), None)


def _has_observation(pool: NativePool) -> bool:
    """Return whether a pool holds an observed or anchored balance."""

    return pool.observed_at is not None and pool.remaining is not None


def _with_scoped_observations(
    pools: Mapping[str, NativePool], identities: Mapping[str, tuple[str, set[int]]]
) -> dict[str, NativePool]:
    """Project credential-scoped observations onto their unobserved catalog pools.

    Execution and the manual refresh record vendor truth on scoped rows
    (``<catalog pool>#cred:<id>`` or ``#pool:<id>``), one per funds identity,
    while the provider card reads the catalog pool. A newer scoped observation
    supersedes an older catalog observation without adding the two together.
    The returned mapping is a read-only view and is never written back.
    """

    scoped: dict[str, dict[str, NativePool]] = {}
    for pool_id, pool in pools.items():
        base_id, marker, scope = pool_id.partition("#")
        identity = identities.get(scope)
        if not marker or identity is None or pool.credential_generation not in identity[1]:
            continue
        if _has_observation(pool):
            identity_map = scoped.setdefault(base_id, {})
            previous = identity_map.get(identity[0])
            if previous is None or (
                pool.observed_at is not None
                and (previous.observed_at is None or pool.observed_at > previous.observed_at)
            ):
                identity_map[identity[0]] = pool
    projected = dict(pools)
    for base_id, identity_members in scoped.items():
        members = list(identity_members.values())
        base = pools.get(base_id)
        newest = max(member.observed_at for member in members if member.observed_at is not None)
        if (
            base is not None
            and _has_observation(base)
            and base.observed_at is not None
            and (base.manual_anchor or base.observed_at >= newest)
        ):
            continue
        projected[base_id] = _combined_pool(base_id, members)
    return projected


def _combined_pool(pool_id: str, members: Sequence[NativePool]) -> NativePool:
    """Fold the scoped funds of distinct identities into one catalog-pool view.

    One identity is shown as observed. Several identities sum their balances;
    an allowance any member does not report stays unknown, the earliest reset
    wins, and a stale member marks the view stale.
    """

    latest = max(members, key=lambda pool: pool.observed_at or datetime.min.replace(tzinfo=UTC))
    if len(members) == 1:
        return latest.model_copy(update={"pool_id": pool_id})
    remaining = Decimal("0")
    allowance: Decimal | None = Decimal("0")
    for member in members:
        remaining += member.remaining or Decimal("0")
        allowance = (
            allowance + member.allowance
            if allowance is not None and member.allowance is not None
            else None
        )
    resets = [member.reset_at for member in members if member.reset_at is not None]
    confidences = {member.confidence for member in members}
    return latest.model_copy(
        update={
            "pool_id": pool_id,
            "remaining": remaining,
            "allowance": allowance,
            "actual_spend_usd": None,
            "reset_at": min(resets) if resets else None,
            "confidence": latest.confidence if len(confidences) == 1 else Confidence.ESTIMATED,
            "stale": any(member.stale for member in members),
            "tiers": [],
            "tier_split_known": False,
        }
    )


def _aggregate_pool(
    pools: dict[str, NativePool], records: Sequence[ProviderLimitRecord]
) -> NativePool | None:
    """Return the single known aggregate pool of one auth rail, when it exists."""

    pool_ids = {
        record.native_pool_id
        for record in records
        if record.native_pool_id is not None and record.budget is not None
    }
    if len(pool_ids) != 1:
        return None
    pool = pools.get(next(iter(pool_ids)))
    if pool is None or pool.remaining is None:
        return None
    return pool


def _detail(
    record: ProviderLimitRecord | None,
    pools: dict[str, NativePool],
    tiers: Sequence[TierBalance],
    grants: CRDGrantsSummary | None,
    *,
    rate_windows: list[RateWindow] | None = None,
    now: datetime | None = None,
) -> ProviderLimitDetail | None:
    """Build detail-only native, USD, plan, and rate information.

    ``rate_windows`` replaces the static catalog windows with measured ones
    where the rate service supplies them, and ``now`` derives the seconds
    left of an active vendor cooldown from the returned reset instants.
    """

    if record is None:
        return None
    pool = pools.get(record.native_pool_id or "")
    windows = (
        rate_windows
        if rate_windows is not None
        else (list(record.rate.windows) if record.rate is not None else [])
    )
    return ProviderLimitDetail(
        plan_name=record.plan_name,
        native_unit=record.native_unit,
        native_balance=pool.remaining if pool is not None else None,
        native_allowance=pool.allowance if pool is not None else None,
        usd_per_call=record.budget.usd_per_call if record.budget is not None else None,
        actual_spend_usd=pool.actual_spend_usd if pool is not None else None,
        reset_at=pool.reset_at if pool is not None else None,
        reset_rule=_reset_rule_for(record, tiers),
        usage_url=record.usage_url,
        source=pool.source if pool is not None else "catalog",
        confidence=pool.confidence if pool is not None else Confidence.UNKNOWN,
        last_sync_at=pool.observed_at if pool is not None else None,
        stale=bool(pool.stale) if pool is not None else False,
        price_version=record.conversion_profile.price_version,
        crd_split_note=_split_note(record),
        rate_windows=windows,
        retry_after_seconds=_cooldown_seconds(windows, now) if now is not None else None,
        tier_split_known=grants is not None
        or any(tier.native_remaining is not None for tier in tiers),
        aggregate_pool_id=record.native_pool_id,
    )


def _cooldown_seconds(windows: Sequence[RateWindow], now: datetime) -> int | None:
    """Return the seconds left of the active vendor cooldown, else ``None``.

    Only a window recorded from a vendor ``Retry-After`` cooldown carries
    that state: its observation names ``vendor_retry_after`` as the source.
    A locally measured rolling window always owns its own boundary reset and
    is not a cooldown, so a rail without a vendor cooldown reports ``None``
    instead of an invented delay, and an elapsed one reports zero.
    """

    resets = [
        window.reset_at
        for window in windows
        if window.source == "vendor_retry_after" and window.reset_at is not None
    ]
    if not resets:
        return None
    return max(0, ceil((max(resets) - now).total_seconds()))


def _reset_rule_for(record: ProviderLimitRecord, tiers: Sequence[TierBalance]) -> ResetRule:
    """Return the documented reset rule of the tier that owns the record's pool."""

    for tier in tiers:
        if tier.pool_id == record.native_pool_id:
            return tier.reset_rule
    return ResetRule.UNKNOWN


def _split_note(record: ProviderLimitRecord) -> str | None:
    """Explain an operation whose native cost can exceed its standard cost."""

    if record.provider == "firecrawl":
        return (
            "Add-ons such as JSON extraction consume extra native credits and extra "
            "USD of priced use for the same single fetched URL."
        )
    return None


def _tier_crd(
    tier: TierBalance, native: Decimal | None, profile: CRDPriceProfile
) -> Decimal | None:
    """Return the exact credit-unit value of one tier amount."""

    if native is None:
        return None
    if tier.native_unit is UnitKind.USD:
        return native / profile.reference_usd_per_crd
    if profile.native_usd_per_unit is None:
        return None
    return native * profile.native_usd_per_unit / profile.reference_usd_per_crd


def _tier_confidence(tier: TierBalance, pool: NativePool | None) -> Confidence:
    if pool is not None and pool.remaining is not None:
        return pool.confidence
    return tier.confidence


def _covers(view: CRDView) -> bool:
    """Return whether a view's own capacity covers its whole request cost."""

    cost = view.request_cost_crd
    spendable = view.spendable_crd
    if cost is None or spendable is None:
        return False
    return spendable >= cost


def _with_grant_tiers(
    tiers: list[TierBalance],
    grants: CRDGrantsSummary | None,
    provider: str,
    auth_mode: AuthMode,
) -> list[TierBalance]:
    """Add an operator grant ceiling as its own local, non-vendor bar."""

    if grants is None:
        return tiers
    unit = tiers[0].native_unit if tiers else UnitKind.CREDIT
    additions: list[TierBalance] = []
    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        granted, consumed, reserved = _grant_amounts(grants, operation)
        if granted == 0:
            continue
        remaining = _floored(granted - consumed - reserved)
        additions.append(
            TierBalance(
                pool_id=f"{provider}:{auth_mode.value}:grant:{operation.value}",
                tier="paid",
                native_unit=unit,
                native_allowance=granted,
                native_remaining=remaining,
                allowance_crd=granted,
                remaining_crd=remaining,
                reset_rule=ResetRule.VENDOR_PERIOD,
                funding_mode=FundingMode.PREPAID,
                source="operator_grant",
                confidence=Confidence.AUTHORITATIVE,
                label=f"Operator {operation.value} grant (local ceiling, not vendor funds)",
            )
        )
    return [*tiers, *additions]


def _grant_amounts(
    grants: CRDGrantsSummary, operation: LimitOperation
) -> tuple[Decimal, Decimal, Decimal]:
    if operation is LimitOperation.SEARCH:
        return (grants.search_granted_crd, grants.search_consumed_crd, grants.search_reserved_crd)
    return (grants.fetch_granted_crd, grants.fetch_consumed_crd, grants.fetch_reserved_crd)


def _floored(value: Decimal) -> Decimal:
    return value if value > 0 else Decimal("0")


def _mark_unknown(tier: TierBalance) -> TierBalance:
    """Keep a paid tier with no known value explicit as unknown."""

    if tier.tier == "paid" and tier.native_remaining is None and tier.native_allowance is None:
        return tier.model_copy(update={"tier": "unknown"})
    return tier


def _daily_pool(provider: str, tier: TierBalance, now: datetime) -> NativePool:
    return NativePool(
        pool_id=tier.pool_id,
        provider=provider,
        auth_mode=AuthMode.KEYED,
        native_unit=tier.native_unit,
        allowance=tier.native_allowance,
        remaining=tier.native_allowance,
        source="local_daily_estimate",
        confidence=Confidence.ESTIMATED,
        reset_at=_day_start(now) + timedelta(days=1),
    )


def _debit_crd(record: ProviderLimitRecord, native_units: Decimal | None) -> Decimal | None:
    """Return the exact priced credit-unit debit of a charged native amount."""

    if native_units is None or record.native_unit is None:
        return None
    return priced_crd_debit(
        NativeDebit(
            provider=record.provider,
            operation=record.operation,
            auth_mode=record.auth_mode,
            native_unit=record.native_unit,
            native_units=native_units,
        ),
        record.conversion_profile,
    )


def _reported_native(
    response: SearchResponse | FetchResponse, record: ProviderLimitRecord
) -> Decimal | None:
    """Return a vendor-reported native charge for one response, when present.

    The Keenable keyed catalog pool counts native units as requests, while the
    adapter reports the actual debit as credits. This narrow compatibility rule
    accepts Keenable keyed credit usage on that request pool. Every other
    provider keeps the exact-unit rule, and the keyless rail stays outside the
    native funds debit.
    """

    usage = response.usage
    if usage is None or record.native_unit is None:
        return None
    if usage.unit_kind is record.native_unit:
        return usage.units
    if (
        record.provider == "keenable"
        and record.auth_mode is AuthMode.KEYED
        and record.native_unit is UnitKind.REQUEST
        and usage.unit_kind is UnitKind.CREDIT
    ):
        return usage.units
    return None


def _reported_usd(response: SearchResponse | FetchResponse) -> Decimal | None:
    """Return a vendor-reported USD cost for one response, when present."""

    usage = response.usage
    if usage is None or usage.unit_kind is not UnitKind.USD:
        return None
    return usage.units


def _reported_usd_or_none(error: ProviderError) -> Decimal | None:
    value = error.details.get("actual_usd")
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _successful_urls(response: SearchResponse | FetchResponse) -> int:
    """Return one successful operation count under the single-URL contract."""

    return 1


def _as_request(context: LimitCallContext) -> SearchRequest | FetchRequest | None:
    return context.request


def _anchor_decimal(anchor: object, field: str) -> Decimal | None:
    value = getattr(anchor, field, None)
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _anchor_instant(anchor: object, field: str) -> datetime | None:
    value = getattr(anchor, field, None)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None
