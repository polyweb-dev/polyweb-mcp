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

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from freesearch.configuration.provider_limits import (
    documented_keyless_operations,
    provider_limit_defaults,
    provider_tier_defaults,
)
from freesearch.models.contracts import (
    FetchRequest,
    FetchResponse,
    ProviderError,
    SearchRequest,
    SearchResponse,
    UnitKind,
)
from freesearch.models.provider_limits import (
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
    NativeDebit,
    NativePool,
    NativeUsageSnapshot,
    ProviderAuthLimits,
    ProviderLimitDetail,
    ProviderLimitRecord,
    ProviderLimitsResponse,
    RateAdmission,
    RateProgressView,
    ResetRule,
    TierBalance,
    effective_attempt_deadline,
    local_funds_denial,
    local_rate_denial,
    unpriced_ceiling_error,
)
from freesearch.persistence.limit_repository import LimitRepository
from freesearch.services.credit_units import (
    crd_view,
    effective_crd,
    native_to_crd,
    priced_crd_debit,
    request_cost_crd,
    request_native_cost,
)
from freesearch.services.rate_limits import RateLimitService

logger = logging.getLogger(__name__)

_FUNDS_OK = "ok"
_FUNDS_DENIED = "funds"
_FUNDS_UNPRICED = "unpriced"


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
        for pool in self._declared_pools():
            await self._repository.ensure_pool(pool)

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

        record = self._record(context.provider, context.operation, context.auth_mode)
        rate_admission = await self._rates.admit(context)
        decision, reasons = await self._funds_decision(record, context)
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
        admission = self._reservation(
            record,
            context,
            rate_admission,
            await self._selected_pool_id(record, _as_request(context)),
        )
        if self._repository is None:
            return admission.model_copy(update={"local_only": True})
        return await self._repository.reserve(admission)

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
        pool = (
            await self._repository.get_pool(admission.pool_id)
            if self._repository is not None and admission.pool_id is not None
            else None
        )
        daily = pool is not None and pool.pool_id == self._daily_pool_id(record)
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
                native_unit=pool.native_unit if daily and pool is not None else record.native_unit,
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
        )

    async def _selected_pool_id(
        self, record: ProviderLimitRecord, request: SearchRequest | FetchRequest | None
    ) -> str | None:
        """Return the pool an attempt draws on, preferring a covering daily pool.

        The estimated daily free pool covers a search only while it still holds
        the whole request cost, so an exhausted daily pool permits a funded paid
        search instead of denying it.
        """

        daily_id = self._daily_pool_id(record)
        if daily_id is None or self._repository is None:
            return record.native_pool_id
        pool = await self._repository.get_pool(daily_id)
        cost = request_cost_crd(record, request)
        remaining = native_to_crd(pool, record.conversion_profile) if pool is not None else None
        if remaining is not None and cost is not None and remaining >= cost:
            return daily_id
        return record.native_pool_id

    def _daily_pool_id(self, record: ProviderLimitRecord) -> str | None:
        """Return the estimated daily free pool of one search rail, when declared."""

        if record.auth_mode is not AuthMode.KEYED or record.operation is not LimitOperation.SEARCH:
            return None
        for tier in self._tiers.get(f"{record.provider}:{record.auth_mode.value}", []):
            if tier.reset_rule is ResetRule.DAILY_ESTIMATE:
                return tier.pool_id
        return None

    async def _funds_decision(
        self, record: ProviderLimitRecord, context: LimitCallContext
    ) -> tuple[str, list[str]]:
        """Return the funds decision and its reasons for one request."""

        view = await self._view_for(record, self._clock(), _as_request(context))
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
        return ProviderLimitsResponse(
            provider=provider,
            active_auth_mode=_active_auth_mode(records) if records else AuthMode.KEYED,
            auths=[
                await self._auth_limits(provider, auth_mode, records, pools, now)
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
        self._records = [
            record if existing.key == record.key else existing for existing in self._records
        ]
        self._rates.replace_records(self._records)
        return await self.provider_view(change.provider)

    def _require_repository(self, provider: str) -> LimitRepository:
        if self._repository is None:
            raise LimitStoreUnavailable(provider)
        return self._repository

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
            detail=_detail(search or fetch, pools, tiers, grants),
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
    ) -> CRDView:
        pool = None
        if self._repository is not None and record.native_pool_id is not None:
            pool = await self._repository.get_pool(record.native_pool_id)
        grants = (
            await self._repository.grants(record.provider, record.auth_mode, now=now)
            if self._repository
            else None
        )
        grant_remaining = grants.remaining(record.operation) if grants is not None else None
        daily_pool = await self._daily_pool(record)
        daily = self._daily_view(record, grant_remaining, now, daily_pool)
        if daily is not None and _covers(daily):
            view = daily
        else:
            view = crd_view(record, pool, request=request)
        return effective_crd(view, grant_remaining)

    async def _daily_pool(self, record: ProviderLimitRecord) -> NativePool | None:
        """Return the stored estimated daily pool of one record, when declared."""

        pool_id = self._daily_pool_id(record)
        if pool_id is None or self._repository is None:
            return None
        return await self._repository.get_pool(pool_id)

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
) -> ProviderLimitDetail | None:
    """Build detail-only native, USD, plan, and rate information."""

    if record is None:
        return None
    pool = pools.get(record.native_pool_id or "")
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
        rate_windows=list(record.rate.windows) if record.rate is not None else [],
        tier_split_known=grants is not None
        or any(tier.native_remaining is not None for tier in tiers),
        aggregate_pool_id=record.native_pool_id,
    )


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
            "credit units of priced use for the same single fetched URL."
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
    """Return a vendor-reported native charge for one response, when present."""

    usage = response.usage
    if usage is None or record.native_unit is None:
        return None
    if usage.unit_kind is not record.native_unit:
        return None
    return usage.units


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
