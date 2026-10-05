"""Durable provider-limit storage: catalog, pools, grants, audit, and rates.

Every read and write goes through one async session. Balance changes, their
audit events, and their admission finalization share one transaction, and no
transaction is held across vendor I/O. Money and native amounts are stored as
exact text, so a fractional credit-unit value survives a restart unchanged.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, cast, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    Confidence,
    CRDGrantsSummary,
    CRDGrantUpdate,
    CRDPriceProfile,
    CRDUsageTotal,
    LimitAdmission,
    LimitAuditEvent,
    LimitDebit,
    LimitHistoryPage,
    LimitHistoryQuery,
    LimitOperation,
    LimitRecordNotFound,
    LimitRecordUpdate,
    LimitVersionConflict,
    NativePool,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateProgressView,
    RateReservation,
    RateUnit,
    RateWindowName,
    SyncClaim,
    SyncResult,
    TierBalance,
)
from freesearch.persistence.limit_rows import (
    CRDGrantRow,
    LimitAdmissionRow,
    LimitEventRow,
    NativePoolRow,
    ProviderLimitRow,
    RateAttemptRow,
    RateWindowObservationRow,
)

_WINDOW_SECONDS: dict[RateWindowName, int] = {
    RateWindowName.SECOND: 1,
    RateWindowName.MINUTE: 60,
    RateWindowName.HOUR: 3600,
    RateWindowName.DAY: 86400,
}
_SLOW_WINDOWS: tuple[str, ...] = ("1h", "1d")
_SUCCESS_REASON = "local_success"
_FAILURE_REASON = "local_failure"
_ATTEMPT_RETENTION_SECONDS = 172_800
_QUANTUM = Numeric(24, 9)


def _timestamp(value: datetime) -> str:
    """Return a timezone-aware UTC instant that SQLite sorts lexicographically."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _instant(text: str | None) -> datetime | None:
    """Parse a stored instant, tolerating a row a newer reader wrote."""

    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _text(value: Decimal | None) -> str | None:
    """Store an exact decimal as plain text without exponent notation."""

    if value is None:
        return None
    return format(value, "f")


def _decimal(text: str | None) -> Decimal | None:
    """Read exact decimal text, ignoring a malformed historical value."""

    if text is None:
        return None
    try:
        return Decimal(text)
    except (ArithmeticError, ValueError):
        return None


def _dump(value: Any) -> str | None:
    """Serialize a contract model or a list of models to JSON text."""

    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps([item.model_dump(mode="json") for item in value])
    return json.dumps(value.model_dump(mode="json"))


def _load(model: Any, text: str | None) -> Any:
    """Decode a stored contract model, returning ``None`` when unusable."""

    if not text:
        return None
    try:
        return model.model_validate_json(text)
    except ValueError:
        return None


def _load_tiers(text: str | None) -> list[TierBalance]:
    """Decode stored tier declarations, ignoring an unreadable value."""

    if not text:
        return []
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    tiers: list[TierBalance] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            tiers.append(TierBalance.model_validate(item))
        except ValueError:
            continue
    return tiers


def _load_reservations(text: str | None) -> list[RateReservation]:
    """Decode stored rate reservations, ignoring an unreadable value."""

    if not text:
        return []
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    reservations: list[RateReservation] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            reservations.append(RateReservation.model_validate(item))
        except ValueError:
            continue
    return reservations


class LimitRepository:
    """Own the provider-limit tables for one SQLite database."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ---------------------------------------------------------------- catalog

    async def seed_records(self, records: Sequence[ProviderLimitRecord]) -> None:
        """Insert missing catalog records idempotently.

        A stored record keeps the fields an operator edited: seeding never
        overwrites a rate, budget, plan, usage link, or version.
        """

        async with self._session_factory() as session:
            for record in records:
                await session.execute(
                    sqlite_insert(ProviderLimitRow)
                    .values(**_record_values(record))
                    .on_conflict_do_nothing(index_elements=["provider", "operation", "auth_mode"])
                )
            await session.commit()

    async def list_records(self, provider: str | None = None) -> list[ProviderLimitRecord]:
        """Return catalog records ordered by provider, operation, and auth mode."""

        statement = select(ProviderLimitRow).order_by(
            ProviderLimitRow.provider,
            ProviderLimitRow.operation,
            ProviderLimitRow.auth_mode,
        )
        if provider is not None:
            statement = statement.where(ProviderLimitRow.provider == provider)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return [_record_from_row(row) for row in rows]

    async def update_record(self, change: LimitRecordUpdate) -> ProviderLimitRecord:
        """Apply a partial catalog update behind a version precondition."""

        async with self._session_factory() as session:
            row = await _require_record_row(session, change)
            if row.version != change.version:
                raise LimitVersionConflict(change.provider, change.version, row.version)
            values = _update_values(change)
            values["version"] = row.version + 1
            await session.execute(
                update(ProviderLimitRow)
                .where(
                    ProviderLimitRow.provider == change.provider,
                    ProviderLimitRow.operation == change.operation.value,
                    ProviderLimitRow.auth_mode == change.auth_mode.value,
                )
                .values(**values)
            )
            await session.commit()
            refreshed = await _require_record_row(session, change)
            return _record_from_row(refreshed)

    # ------------------------------------------------------------------ pools

    async def list_pools(self, provider: str | None = None) -> list[NativePool]:
        """Return native pools ordered by pool ID."""

        statement = select(NativePoolRow).order_by(NativePoolRow.pool_id)
        if provider is not None:
            statement = statement.where(NativePoolRow.provider == provider)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return [_pool_from_row(row) for row in rows]

    async def get_pool(self, pool_id: str) -> NativePool | None:
        """Return one native pool by ID."""

        async with self._session_factory() as session:
            row = await session.get(NativePoolRow, pool_id)
        return _pool_from_row(row) if row is not None else None

    async def ensure_pool(self, pool: NativePool) -> NativePool:
        """Create a declared pool row without touching a stored balance."""

        async with self._session_factory() as session:
            await session.execute(
                sqlite_insert(NativePoolRow)
                .values(**_pool_values(pool))
                .on_conflict_do_nothing(index_elements=["pool_id"])
            )
            await session.commit()
            row = await session.get(NativePoolRow, pool.pool_id)
        return _pool_from_row(row) if row is not None else pool

    async def apply_snapshot(
        self, snapshot: NativeUsageSnapshot, *, manual_anchor: bool = False
    ) -> bool:
        """Store one vendor observation, rejecting a stale credential generation.

        A failed sync preserves the last known balance and records a safe error
        code plus a stale state. An observation without a numeric balance or
        allowance keeps the stored value instead of erasing it, because an
        absent vendor field is not a zero balance. Returns whether the stored
        balance changed. A manual anchor also marks the pool as an operator
        estimate, so a later delete can find it.
        """

        async with self._session_factory() as session:
            row = await session.get(NativePoolRow, snapshot.pool_id)
            if row is not None and snapshot.credential_generation < row.credential_generation:
                return False
            old_native = _decimal(row.remaining_text) if row is not None else None
            effective = _preserve_known_values(row, snapshot)
            changed = row is None or old_native != effective.remaining
            await _write_pool(session, row, effective, manual_anchor=manual_anchor)
            await _insert_event(
                session,
                LimitAuditEvent(
                    event_id=uuid.uuid4().hex,
                    provider=effective.provider,
                    auth_mode=effective.auth_mode,
                    pool_id=effective.pool_id,
                    observed_at=effective.observed_at,
                    source=effective.source,
                    reason="vendor_sync" if effective.error_code is None else "sync_failed",
                    old_native=old_native,
                    new_native=effective.remaining,
                    confidence=effective.confidence,
                    detail={
                        "error_code": effective.error_code,
                        "stale": effective.stale,
                        "manual_anchor": manual_anchor,
                        "preserved": effective.remaining != snapshot.remaining
                        or effective.allowance != snapshot.allowance,
                    },
                ),
            )
            await session.commit()
        return changed

    async def clear_pool_values(
        self,
        pool_id: str,
        *,
        observed_at: datetime,
        source: str = "manual_anchor",
        reason: str = "reconcile",
    ) -> bool:
        """Return one pool to an unknown balance after an operator delete.

        This path bypasses the preserve rule on purpose. A deleted manual anchor
        restores the unknown state, not zero and not the old estimate, so the
        operator sees that no value is known.
        """

        async with self._session_factory() as session:
            row = await session.get(NativePoolRow, pool_id)
            if row is None:
                return False
            old_native = _decimal(row.remaining_text)
            old_allowance = _decimal(row.allowance_text)
            await session.execute(
                update(NativePoolRow)
                .where(NativePoolRow.pool_id == pool_id)
                .values(
                    remaining_text=None,
                    allowance_text=None,
                    manual_anchor=0,
                    source=source,
                    confidence=Confidence.UNKNOWN.value,
                    stale=0,
                    sync_error_code=None,
                    observed_at=_timestamp(observed_at),
                    version=row.version + 1,
                )
            )
            await _insert_event(
                session,
                LimitAuditEvent(
                    event_id=uuid.uuid4().hex,
                    provider=row.provider,
                    auth_mode=AuthMode(row.auth_mode),
                    pool_id=pool_id,
                    observed_at=observed_at,
                    source=source,
                    reason=reason,
                    old_native=old_native,
                    new_native=None,
                    confidence=Confidence.UNKNOWN,
                    detail={
                        "cleared": True,
                        "old_allowance": _text(old_allowance),
                    },
                ),
            )
            await session.commit()
        return True

    async def apply_tier_snapshot(self, snapshot: NativeUsageSnapshot) -> bool:
        """Store an observed free/paid split without duplicating aggregate funds."""

        async with self._session_factory() as session:
            row = await session.get(NativePoolRow, snapshot.pool_id)
            if row is None:
                return False
            await session.execute(
                update(NativePoolRow)
                .where(NativePoolRow.pool_id == snapshot.pool_id)
                .values(
                    tier_json=_dump(snapshot.tiers) if snapshot.tiers else None,
                    tier_split_known=1 if snapshot.tier_split_known else 0,
                    last_tier_observed_at=_timestamp(snapshot.observed_at),
                )
            )
            await session.commit()
        return True

    async def record_manual_anchor(
        self,
        pool: NativePool,
        *,
        remaining: Decimal | None,
        allowance: Decimal | None,
        reset_at: datetime | None,
        observed_at: datetime,
        source: str = "manual_anchor",
        manual_anchor: bool = True,
    ) -> NativePool | None:
        """Store an operator anchor or a local reset as an estimated observation.

        The operator path also marks the pool as a manual anchor, so a later
        delete can tell an operator estimate from a vendor observation.
        """

        await self.ensure_pool(pool)
        await self.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=pool.pool_id,
                provider=pool.provider,
                auth_mode=pool.auth_mode,
                native_unit=pool.native_unit,
                remaining=remaining,
                allowance=allowance,
                reset_at=reset_at,
                observed_at=observed_at,
                source=source,
                confidence=Confidence.ESTIMATED,
                credential_generation=pool.credential_generation,
            ),
            manual_anchor=manual_anchor,
        )
        return await self.get_pool(pool.pool_id)

    # --------------------------------------------------------- grants and use

    async def save_grant(
        self, provider: str, update: CRDGrantUpdate, *, auth_mode: AuthMode
    ) -> None:
        """Store one period grant and its audit event."""

        async with self._session_factory() as session:
            for operation, granted in update.grants.items():
                await _upsert_grant(session, provider, auth_mode, operation, update, granted)
            await _insert_event(
                session,
                LimitAuditEvent(
                    event_id=uuid.uuid4().hex,
                    provider=provider,
                    auth_mode=auth_mode,
                    observed_at=datetime.now(UTC),
                    source="operator",
                    reason="grant",
                    detail={
                        "period_start": update.period_start.isoformat(),
                        "period_end": update.period_end.isoformat(),
                        "search_crd": _text(update.search_crd),
                        "fetch_crd": _text(update.fetch_crd),
                    },
                ),
            )
            await session.commit()

    async def grants(
        self, provider: str, auth_mode: AuthMode, *, now: datetime
    ) -> CRDGrantsSummary | None:
        """Return the current period grant summary, or ``None`` when none exists."""

        today = now.date().isoformat()
        statement = select(CRDGrantRow).where(
            CRDGrantRow.provider == provider,
            CRDGrantRow.auth_mode == auth_mode.value,
            CRDGrantRow.period_start <= today,
            CRDGrantRow.period_end >= today,
        )
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        if not rows:
            return None
        return _grants_summary(provider, auth_mode, rows)

    async def reserve(self, admission: LimitAdmission) -> LimitAdmission:
        """Reserve funds and rate units in one transaction.

        A repeated attempt ID keeps its first reservation, so a retried call
        cannot reserve twice.
        """

        async with self._session_factory() as session:
            existing = await session.get(LimitAdmissionRow, admission.attempt_id)
            if existing is not None:
                return _admission_from_row(existing)
            await session.execute(
                sqlite_insert(LimitAdmissionRow).values(**_admission_values(admission))
            )
            for reservation in admission.rate_reservations:
                await _insert_rate_attempt(
                    session,
                    attempt_id=admission.attempt_id,
                    bucket_id=reservation.bucket_id,
                    provider=admission.provider,
                    auth_mode=admission.auth_mode,
                    operation=admission.operation,
                    window=reservation.window,
                    units=reservation.units,
                    attempted_at=admission.created_at,
                )
            if admission.reserved_crd > 0:
                await _adjust_grant(
                    session,
                    admission.provider,
                    admission.auth_mode,
                    admission.operation,
                    reserved_delta=admission.reserved_crd,
                )
            await session.commit()
        return admission

    async def finalize(self, debit: LimitDebit) -> bool:
        """Apply the actual debit, mark the attempt finalized, and audit it.

        Returns ``False`` when the attempt was already finished, so a duplicate
        finalization can never debit twice.
        """

        async with self._session_factory() as session:
            row = await session.get(LimitAdmissionRow, debit.attempt_id)
            if row is None or row.state != "reserved":
                return False
            old_native = await _pool_remaining(session, row.pool_id)
            new_native, overspend = _debited(old_native, debit)
            if row.pool_id is not None:
                await _apply_pool_debit(session, row.pool_id, new_native, debit)
            await _adjust_grant(
                session,
                debit.provider,
                debit.auth_mode,
                debit.operation,
                reserved_delta=-(_decimal(row.reserved_crd_text) or Decimal("0")),
                consumed_delta=debit.crd_debit,
            )
            await session.execute(
                update(LimitAdmissionRow)
                .where(LimitAdmissionRow.attempt_id == debit.attempt_id)
                .values(state="finalized")
            )
            await _insert_event(
                session,
                LimitAuditEvent(
                    event_id=uuid.uuid4().hex,
                    provider=debit.provider,
                    auth_mode=debit.auth_mode,
                    operation=debit.operation,
                    pool_id=debit.pool_id or row.pool_id,
                    observed_at=datetime.now(UTC),
                    source=debit.audit_source,
                    reason=debit.reason,
                    old_native=old_native,
                    new_native=new_native,
                    crd_debit=debit.crd_debit,
                    native_debit=debit.native_units,
                    actual_usd=debit.actual_usd,
                    confidence=Confidence.OBSERVED,
                    local_attempt_id=debit.attempt_id,
                    detail={
                        "outcome": debit.outcome,
                        "charged_document": debit.charged_document,
                        "clamped": overspend is not None,
                        "overspend": _text(overspend),
                    },
                ),
            )
            await session.commit()
        return True

    async def release(self, attempt_id: str, reason: str) -> bool:
        """Release a reservation after a definite failure before vendor I/O."""

        async with self._session_factory() as session:
            row = await session.get(LimitAdmissionRow, attempt_id)
            if row is None or row.state != "reserved":
                return False
            await _adjust_grant(
                session,
                row.provider,
                AuthMode(row.auth_mode),
                LimitOperation(row.operation),
                reserved_delta=-(_decimal(row.reserved_crd_text) or Decimal("0")),
            )
            await session.execute(
                update(LimitAdmissionRow)
                .where(LimitAdmissionRow.attempt_id == attempt_id)
                .values(state="released")
            )
            await _insert_event(
                session,
                LimitAuditEvent(
                    event_id=uuid.uuid4().hex,
                    provider=row.provider,
                    auth_mode=AuthMode(row.auth_mode),
                    operation=LimitOperation(row.operation),
                    pool_id=row.pool_id,
                    observed_at=datetime.now(UTC),
                    source="local",
                    reason="release",
                    crd_debit=Decimal("0"),
                    local_attempt_id=attempt_id,
                    detail={"reason": reason},
                ),
            )
            await session.commit()
        return True

    async def get_admission(self, attempt_id: str) -> LimitAdmission | None:
        """Return one stored admission."""

        async with self._session_factory() as session:
            row = await session.get(LimitAdmissionRow, attempt_id)
        return _admission_from_row(row) if row is not None else None

    # ------------------------------------------------------------------ audit

    async def record_event(self, event: LimitAuditEvent) -> None:
        """Append one audit event outside a debit, such as a denial or reset."""

        async with self._session_factory() as session:
            await _insert_event(session, event)
            await session.commit()

    async def list_history(self, query: LimitHistoryQuery) -> LimitHistoryPage:
        """Return one page of audit events, newest first, plus the next cursor."""

        statement = (
            select(LimitEventRow)
            .where(LimitEventRow.provider == query.provider)
            .order_by(LimitEventRow.observed_at.desc(), LimitEventRow.event_id.desc())
            .limit(query.limit + 1)
        )
        if query.auth_mode is not None:
            statement = statement.where(LimitEventRow.auth_mode == query.auth_mode.value)
        cursor = _decode_cursor(query.cursor)
        if cursor is not None:
            statement = statement.where(_before_cursor(cursor))
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        page = rows[: query.limit]
        next_cursor = None
        if len(rows) > query.limit and page:
            next_cursor = f"{page[-1].observed_at}|{page[-1].event_id}"
        return LimitHistoryPage(
            events=[_event_from_row(row) for row in page], next_cursor=next_cursor
        )

    async def crd_usage_totals(self, provider: str | None = None) -> list[CRDUsageTotal]:
        """Aggregate credit-unit cost and operation volume per provider."""

        statement = select(
            LimitEventRow.provider,
            LimitEventRow.operation,
            LimitEventRow.reason,
            LimitEventRow.crd_debit_text,
        ).where(LimitEventRow.reason.in_((_SUCCESS_REASON, _FAILURE_REASON)))
        if provider is not None:
            statement = statement.where(LimitEventRow.provider == provider)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return _usage_totals(rows)

    async def count_events(self, provider: str, reason: str, *, since: datetime) -> int:
        """Count audit events with one reason since an instant."""

        statement = (
            select(func.count())
            .select_from(LimitEventRow)
            .where(
                LimitEventRow.provider == provider,
                LimitEventRow.reason == reason,
                LimitEventRow.observed_at >= _timestamp(since),
            )
        )
        async with self._session_factory() as session:
            total = (await session.execute(statement)).scalar_one()
        return int(total)

    # ------------------------------------------------------------------- sync

    async def claim_sync(self, claim: SyncClaim) -> bool:
        """Claim the sync lease for one provider, or return ``False`` when held."""

        now = _timestamp(claim.now)
        expiry = _timestamp(claim.now + timedelta(seconds=claim.lease_seconds))
        statement = (
            update(NativePoolRow)
            .where(
                NativePoolRow.provider == claim.provider,
                (NativePoolRow.lease_until.is_(None))
                | (NativePoolRow.lease_until < now)
                | (NativePoolRow.lease_owner == claim.owner),
            )
            .values(lease_owner=claim.owner, lease_until=expiry)
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return bool(_rowcount(result))

    async def complete_sync(self, result: SyncResult) -> None:
        """Clear the lease and store the next attempt instant and error state."""

        async with self._session_factory() as session:
            await session.execute(
                update(NativePoolRow)
                .where(NativePoolRow.provider == result.provider)
                .values(
                    lease_owner=None,
                    lease_until=None,
                    next_sync_at=(_timestamp(result.next_sync_at) if result.next_sync_at else None),
                    sync_error_code=result.error_code,
                    stale=1 if (result.stale or result.status == "failed") else 0,
                )
            )
            await session.commit()

    async def next_sync_due(self, now: datetime) -> list[str]:
        """Return providers whose stored next sync instant has arrived."""

        stamp = _timestamp(now)
        statement = select(NativePoolRow.provider).where(
            (NativePoolRow.next_sync_at.is_(None)) | (NativePoolRow.next_sync_at <= stamp)
        )
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return sorted(set(rows))

    # ------------------------------------------------------------------ rates

    async def observe_rate(self, observation: RateObservation) -> None:
        """Store the newest observation of one rate bucket and window."""

        values = {
            "bucket_id": observation.bucket_id,
            "provider": observation.provider,
            "auth_mode": observation.auth_mode.value,
            "window": observation.window.value,
            "unit": observation.unit.value,
            "operation": (
                observation.operation.value if observation.operation is not None else None
            ),
            "limit_text": _text(observation.limit),
            "remaining_text": _text(observation.remaining),
            "reset_at": _timestamp(observation.reset_at) if observation.reset_at else None,
            "observed_at": _timestamp(observation.observed_at),
            "source": observation.source,
            "confidence": observation.confidence.value,
            "stale": 1 if observation.stale else 0,
        }
        async with self._session_factory() as session:
            await session.execute(
                sqlite_insert(RateWindowObservationRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["bucket_id", "provider", "auth_mode", "window", "unit"],
                    set_={key: value for key, value in values.items() if key != "bucket_id"},
                )
            )
            await session.commit()

    async def list_observations(self, provider: str) -> list[RateObservation]:
        """Return stored rate observations for one provider."""

        statement = select(RateWindowObservationRow).where(
            RateWindowObservationRow.provider == provider
        )
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        observations: list[RateObservation] = []
        for row in rows:
            observed_at = _instant(row.observed_at)
            if observed_at is None:
                continue
            observations.append(
                RateObservation(
                    bucket_id=row.bucket_id,
                    provider=row.provider,
                    auth_mode=AuthMode(row.auth_mode),
                    window=RateWindowName(row.window),
                    unit=RateUnit(row.unit),
                    limit=_decimal(row.limit_text),
                    remaining=_decimal(row.remaining_text),
                    reset_at=_instant(row.reset_at),
                    observed_at=observed_at,
                    operation=(
                        LimitOperation(row.operation) if row.operation is not None else None
                    ),
                    source=row.source,
                    confidence=Confidence(row.confidence),
                    stale=bool(row.stale),
                )
            )
        return observations

    async def count_attempts(
        self,
        bucket_id: str,
        *,
        window: RateWindowName,
        now: datetime,
        since: datetime | None = None,
    ) -> Decimal:
        """Count local rate units still inside one window.

        An age-based window expires each attempt by its own age. When a fresh
        vendor observation exists, ``since`` restricts the count to attempts
        after that observation, so a local count is never double counted.
        """

        start = since or (now - timedelta(seconds=_WINDOW_SECONDS[window]))
        statement = select(
            func.coalesce(func.sum(cast(RateAttemptRow.units_text, _QUANTUM)), 0)
        ).where(
            RateAttemptRow.bucket_id == bucket_id,
            RateAttemptRow.attempted_at >= _timestamp(start),
            RateAttemptRow.attempted_at <= _timestamp(now),
        )
        async with self._session_factory() as session:
            total = (await session.execute(statement)).scalar_one()
        return Decimal(str(total))

    async def oldest_attempt(
        self, bucket_id: str, *, window: RateWindowName, now: datetime
    ) -> datetime | None:
        """Return the oldest attempt still inside one age-based window."""

        start = now - timedelta(seconds=_WINDOW_SECONDS[window])
        statement = select(func.min(RateAttemptRow.attempted_at)).where(
            RateAttemptRow.bucket_id == bucket_id,
            RateAttemptRow.attempted_at >= _timestamp(start),
            RateAttemptRow.attempted_at <= _timestamp(now),
        )
        async with self._session_factory() as session:
            oldest = (await session.execute(statement)).scalar_one_or_none()
        return _instant(str(oldest)) if oldest else None

    async def record_rate_attempt(
        self,
        *,
        attempt_id: str,
        bucket_id: str,
        provider: str,
        auth_mode: AuthMode,
        operation: LimitOperation,
        window: RateWindowName,
        units: Decimal,
        attempted_at: datetime,
    ) -> None:
        """Persist one consumed rate unit, ignoring a duplicate attempt ID."""

        async with self._session_factory() as session:
            await _insert_rate_attempt(
                session,
                attempt_id=attempt_id,
                bucket_id=bucket_id,
                provider=provider,
                auth_mode=auth_mode,
                operation=operation,
                window=window,
                units=units,
                attempted_at=attempted_at,
            )
            await session.commit()

    async def purge_expired_attempts(self, now: datetime) -> int:
        """Delete rate attempts older than the longest window plus a margin."""

        cutoff = _timestamp(now - timedelta(seconds=_ATTEMPT_RETENTION_SECONDS))
        async with self._session_factory() as session:
            result = await session.execute(
                delete(RateAttemptRow).where(RateAttemptRow.attempted_at < cutoff)
            )
            await session.commit()
        return _rowcount(result)

    async def list_rate_progress(self, provider: str, now: datetime) -> list[RateProgressView]:
        """Return stored hour and day rate capacity for one provider.

        Only documented hourly and daily buckets become bars. Second and minute
        windows stay detail-only, and an unpublished limit keeps an unknown
        nonnumeric state.
        """

        views: list[RateProgressView] = []
        for observation in await self.list_observations(provider):
            if observation.window.value not in _SLOW_WINDOWS:
                continue
            used = await self.count_attempts(
                observation.bucket_id,
                window=observation.window,
                now=now,
                since=observation.observed_at,
            )
            views.append(_progress_from_observation(observation, used))
        return sorted(views, key=lambda view: (view.bucket_id, view.window))


def _progress_from_observation(observation: RateObservation, used: Decimal) -> RateProgressView:
    return RateProgressView(
        bucket_id=observation.bucket_id,
        operation=observation.operation or LimitOperation.SEARCH,
        window="1h" if observation.window is RateWindowName.HOUR else "1d",
        unit=observation.unit,
        remaining=_remaining_after(observation.remaining, used),
        limit=observation.limit,
        reset_at=observation.reset_at,
        source=observation.source,
        confidence=observation.confidence,
        kind="rate",
        stale=observation.stale,
        enforceable=observation.limit is not None,
    )


def _rowcount(result: Any) -> int:
    """Return the affected row count of a DML result, or zero when unknown."""

    return int(getattr(result, "rowcount", 0) or 0)


def _remaining_after(remaining: Decimal | None, used: Decimal) -> Decimal | None:
    """Return a stored remaining count minus local use, floored at zero."""

    if remaining is None:
        return None
    value = remaining - used
    return value if value > 0 else Decimal("0")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    """Decode the opaque history cursor into its instant and event ID."""

    if not cursor or "|" not in cursor:
        return None
    observed_at, _, event_id = cursor.partition("|")
    return (observed_at, event_id)


def _before_cursor(cursor: tuple[str, str]) -> Any:
    """Return the stable keyset predicate for one history page."""

    observed_at, event_id = cursor
    return (LimitEventRow.observed_at < observed_at) | (
        (LimitEventRow.observed_at == observed_at) & (LimitEventRow.event_id < event_id)
    )


def _usage_totals(rows: Sequence[Any]) -> list[CRDUsageTotal]:
    """Aggregate audit rows into credit-unit cost and operation volume."""

    totals: dict[tuple[str, LimitOperation], CRDUsageTotal] = {}
    attempts: dict[tuple[str, LimitOperation], int] = {}
    for row in rows:
        operation = LimitOperation(row.operation) if row.operation else LimitOperation.SEARCH
        key = (str(row.provider), operation)
        current = totals.get(key)
        debit = _decimal(row.crd_debit_text) or Decimal("0")
        attempts[key] = attempts.get(key, 0) + 1
        totals[key] = CRDUsageTotal(
            provider=key[0],
            operation=operation,
            normalized_crd=(current.normalized_crd if current else Decimal("0")) + debit,
            attempt_count=attempts[key],
            volume_count=(current.volume_count if current else 0)
            + (1 if row.reason == _SUCCESS_REASON else 0),
        )
    return [totals[key] for key in sorted(totals, key=lambda item: (item[0], item[1].value))]


def _record_values(record: ProviderLimitRecord) -> dict[str, Any]:
    return {
        "provider": record.provider,
        "operation": record.operation.value,
        "auth_mode": record.auth_mode.value,
        "supported": 1 if record.supported else 0,
        "transport_available": 1 if record.transport_available else 0,
        "rate_json": _dump(record.rate),
        "budget_json": _dump(record.budget),
        "native_unit": record.native_unit.value if record.native_unit else None,
        "native_pool_id": record.native_pool_id,
        "conversion_profile_json": _dump(record.conversion_profile) or "{}",
        "plan_name": record.plan_name,
        "usage_url": record.usage_url,
        "version": record.version,
    }


def _record_from_row(row: ProviderLimitRow) -> ProviderLimitRecord:
    return ProviderLimitRecord(
        provider=row.provider,
        operation=LimitOperation(row.operation),
        auth_mode=AuthMode(row.auth_mode),
        supported=bool(row.supported),
        transport_available=bool(row.transport_available),
        rate=_load(RateBlock, row.rate_json),
        budget=_load(BudgetBlock, row.budget_json),
        native_unit=UnitKind(row.native_unit) if row.native_unit else None,
        native_pool_id=row.native_pool_id,
        conversion_profile=_load(CRDPriceProfile, row.conversion_profile_json) or CRDPriceProfile(),
        plan_name=row.plan_name,
        usage_url=row.usage_url,
        version=row.version,
    )


async def _require_record_row(session: AsyncSession, change: LimitRecordUpdate) -> ProviderLimitRow:
    row = await session.get(
        ProviderLimitRow,
        (change.provider, change.operation.value, change.auth_mode.value),
    )
    if row is None:
        raise LimitRecordNotFound(change.provider, change.operation.value, change.auth_mode.value)
    return row


def _update_values(change: LimitRecordUpdate) -> dict[str, Any]:
    """Translate a partial update into stored column values."""

    values: dict[str, Any] = {}
    if change.touched("rate"):
        values["rate_json"] = _dump(change.rate)
    if change.touched("budget"):
        values["budget_json"] = _dump(change.budget)
    if change.touched("conversion_profile"):
        values["conversion_profile_json"] = _dump(change.conversion_profile) or "{}"
    if change.touched("plan_name"):
        values["plan_name"] = change.plan_name
    if change.touched("usage_url"):
        values["usage_url"] = change.usage_url
    if change.touched("supported") and change.supported is not None:
        values["supported"] = 1 if change.supported else 0
    if change.touched("transport_available") and change.transport_available is not None:
        values["transport_available"] = 1 if change.transport_available else 0
    return values


def _pool_values(pool: NativePool) -> dict[str, Any]:
    return {
        "pool_id": pool.pool_id,
        "provider": pool.provider,
        "auth_mode": pool.auth_mode.value,
        "native_unit": pool.native_unit.value,
        "remaining_text": _text(pool.remaining),
        "allowance_text": _text(pool.allowance),
        "actual_spend_usd_text": _text(pool.actual_spend_usd),
        "source": pool.source,
        "confidence": pool.confidence.value,
        "reset_at": _timestamp(pool.reset_at) if pool.reset_at else None,
        "observed_at": _timestamp(pool.observed_at) if pool.observed_at else None,
        "version": pool.version,
        "credential_generation": pool.credential_generation,
        "next_sync_at": _timestamp(pool.next_sync_at) if pool.next_sync_at else None,
        "lease_owner": None,
        "lease_until": None,
        "sync_error_code": None,
        "stale": 1 if pool.stale else 0,
        "manual_anchor": 1 if pool.manual_anchor else 0,
        "tier_json": _dump(pool.tiers) if pool.tiers else None,
        "tier_split_known": 1 if pool.tier_split_known else 0,
        "last_tier_observed_at": None,
    }


def _pool_from_row(row: NativePoolRow) -> NativePool:
    return NativePool(
        pool_id=row.pool_id,
        provider=row.provider,
        auth_mode=AuthMode(row.auth_mode),
        native_unit=UnitKind(row.native_unit),
        remaining=_decimal(row.remaining_text),
        allowance=_decimal(row.allowance_text),
        actual_spend_usd=_decimal(row.actual_spend_usd_text),
        source=row.source,
        confidence=Confidence(row.confidence),
        reset_at=_instant(row.reset_at),
        observed_at=_instant(row.observed_at),
        version=row.version,
        credential_generation=row.credential_generation,
        next_sync_at=_instant(row.next_sync_at),
        stale=bool(row.stale),
        manual_anchor=bool(row.manual_anchor),
        tiers=_load_tiers(row.tier_json),
        tier_split_known=bool(row.tier_split_known),
    )


async def _write_pool(
    session: AsyncSession,
    row: NativePoolRow | None,
    snapshot: NativeUsageSnapshot,
    *,
    manual_anchor: bool = False,
) -> None:
    """Insert or update one pool row from a vendor observation."""

    values: dict[str, Any] = {
        "provider": snapshot.provider,
        "auth_mode": snapshot.auth_mode.value,
        "native_unit": snapshot.native_unit.value,
        "remaining_text": _text(snapshot.remaining),
        "allowance_text": _text(snapshot.allowance),
        "actual_spend_usd_text": _text(snapshot.actual_spend_usd),
        "source": snapshot.source,
        "confidence": snapshot.confidence.value,
        "reset_at": _timestamp(snapshot.reset_at) if snapshot.reset_at else None,
        "observed_at": _timestamp(snapshot.observed_at),
        "version": (row.version + 1) if row is not None else 1,
        "credential_generation": snapshot.credential_generation,
        "stale": 1 if snapshot.stale else 0,
        "sync_error_code": snapshot.error_code,
    }
    if manual_anchor:
        values["manual_anchor"] = 1
    if snapshot.tiers:
        values["tier_json"] = _dump(snapshot.tiers)
        values["tier_split_known"] = 1 if snapshot.tier_split_known else 0
        values["last_tier_observed_at"] = _timestamp(snapshot.observed_at)
    if row is None:
        # A first observation creates the row, so every NOT NULL column needs a
        # value: an observed pool is not a manual anchor, it holds no sync lease,
        # and it has no observed tier split unless the snapshot carries one.
        await session.execute(
            sqlite_insert(NativePoolRow).values(
                pool_id=snapshot.pool_id,
                manual_anchor=1 if manual_anchor else 0,
                tier_split_known=1 if snapshot.tier_split_known else 0,
                lease_owner=None,
                lease_until=None,
                next_sync_at=None,
                **values,
            )
        )
        return
    await session.execute(
        update(NativePoolRow).where(NativePoolRow.pool_id == snapshot.pool_id).values(**values)
    )


def _preserve_known_values(
    row: NativePoolRow | None, snapshot: NativeUsageSnapshot
) -> NativeUsageSnapshot:
    """Keep a stored balance or allowance when the observation omits it.

    A vendor field that is absent means "not reported", not "zero". A failed
    sync therefore keeps the last valid balance and marks the pool stale.
    """

    if row is None:
        return snapshot
    stored_remaining = _decimal(row.remaining_text)
    stored_allowance = _decimal(row.allowance_text)
    remaining = snapshot.remaining if snapshot.remaining is not None else stored_remaining
    allowance = snapshot.allowance if snapshot.allowance is not None else stored_allowance
    if remaining == snapshot.remaining and allowance == snapshot.allowance:
        return snapshot
    return snapshot.model_copy(
        update={
            "remaining": remaining,
            "allowance": allowance,
            "stale": snapshot.stale or snapshot.error_code is not None,
        }
    )


async def _pool_remaining(session: AsyncSession, pool_id: str | None) -> Decimal | None:
    if pool_id is None:
        return None
    row = await session.get(NativePoolRow, pool_id)
    return _decimal(row.remaining_text) if row is not None else None


def _debited(
    old_native: Decimal | None, debit: LimitDebit
) -> tuple[Decimal | None, Decimal | None]:
    """Return the pool balance after one debit and any clamped overspend.

    A confirmed vendor charge can exceed the last known balance. The stored
    balance clamps at zero, and the difference stays in the audit detail so the
    clamp never hides real spend. An exact payment that spends the whole balance
    is not an overspend, and an unknown balance stays unknown.
    """

    if old_native is None or debit.native_units is None:
        return old_native, None
    value = old_native - debit.native_units
    if value >= 0:
        return value, None
    return Decimal("0"), -value


async def _apply_pool_debit(
    session: AsyncSession, pool_id: str, new_native: Decimal | None, debit: LimitDebit
) -> None:
    row = await session.get(NativePoolRow, pool_id)
    if row is None:
        return
    values: dict[str, Any] = {
        "remaining_text": _text(new_native),
        "version": row.version + 1,
        "observed_at": _timestamp(datetime.now(UTC)),
    }
    if debit.actual_usd is not None:
        current = _decimal(row.actual_spend_usd_text) or Decimal("0")
        values["actual_spend_usd_text"] = _text(current + debit.actual_usd)
    await session.execute(
        update(NativePoolRow).where(NativePoolRow.pool_id == pool_id).values(**values)
    )


async def _upsert_grant(
    session: AsyncSession,
    provider: str,
    auth_mode: AuthMode,
    operation: LimitOperation,
    update: CRDGrantUpdate,
    granted: Decimal,
) -> None:
    values = {
        "provider": provider,
        "operation": operation.value,
        "auth_mode": auth_mode.value,
        "period_start": update.period_start.isoformat(),
        "period_end": update.period_end.isoformat(),
        "granted_crd_text": _text(granted) or "0",
        "consumed_crd_text": "0",
        "reserved_crd_text": "0",
        "version": update.version + 1,
    }
    await session.execute(
        sqlite_insert(CRDGrantRow)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["provider", "operation", "auth_mode", "period_start"],
            set_={
                "period_end": values["period_end"],
                "granted_crd_text": values["granted_crd_text"],
                "version": values["version"],
            },
        )
    )


async def _adjust_grant(
    session: AsyncSession,
    provider: str,
    auth_mode: AuthMode,
    operation: LimitOperation,
    *,
    reserved_delta: Decimal | None = None,
    consumed_delta: Decimal | None = None,
) -> None:
    """Adjust the reserved or consumed credit units of the current period grant."""

    if reserved_delta in (None, Decimal("0")) and consumed_delta in (None, Decimal("0")):
        return
    row = await _current_grant_row(session, provider, auth_mode, operation)
    if row is None:
        return
    reserved = (_decimal(row.reserved_crd_text) or Decimal("0")) + (reserved_delta or Decimal("0"))
    consumed = (_decimal(row.consumed_crd_text) or Decimal("0")) + (consumed_delta or Decimal("0"))
    await session.execute(
        update(CRDGrantRow)
        .where(
            CRDGrantRow.provider == provider,
            CRDGrantRow.auth_mode == auth_mode.value,
            CRDGrantRow.operation == operation.value,
            CRDGrantRow.period_start == row.period_start,
        )
        .values(
            reserved_crd_text=_text(reserved if reserved > 0 else Decimal("0")),
            consumed_crd_text=_text(consumed if consumed > 0 else Decimal("0")),
        )
    )


async def _current_grant_row(
    session: AsyncSession, provider: str, auth_mode: AuthMode, operation: LimitOperation
) -> CRDGrantRow | None:
    today = datetime.now(UTC).date().isoformat()
    statement = select(CRDGrantRow).where(
        CRDGrantRow.provider == provider,
        CRDGrantRow.auth_mode == auth_mode.value,
        CRDGrantRow.operation == operation.value,
        CRDGrantRow.period_start <= today,
        CRDGrantRow.period_end >= today,
    )
    return (await session.scalars(statement)).first()


def _grants_summary(
    provider: str, auth_mode: AuthMode, rows: Sequence[CRDGrantRow]
) -> CRDGrantsSummary:
    summary = CRDGrantsSummary(
        provider=provider,
        auth_mode=auth_mode,
        period_start=datetime.fromisoformat(rows[0].period_start).date(),
        period_end=datetime.fromisoformat(rows[0].period_end).date(),
        version=rows[0].version,
    )
    for row in rows:
        operation = LimitOperation(row.operation)
        granted = _decimal(row.granted_crd_text) or Decimal("0")
        consumed = _decimal(row.consumed_crd_text) or Decimal("0")
        reserved = _decimal(row.reserved_crd_text) or Decimal("0")
        if operation is LimitOperation.SEARCH:
            summary.search_granted_crd = granted
            summary.search_consumed_crd = consumed
            summary.search_reserved_crd = reserved
        else:
            summary.fetch_granted_crd = granted
            summary.fetch_consumed_crd = consumed
            summary.fetch_reserved_crd = reserved
    return summary


def _admission_values(admission: LimitAdmission) -> dict[str, Any]:
    return {
        "attempt_id": admission.attempt_id,
        "provider": admission.provider,
        "operation": admission.operation.value,
        "auth_mode": admission.auth_mode.value,
        "pool_id": admission.pool_id,
        "reserved_crd_text": _text(admission.reserved_crd) or "0",
        "reserved_native_text": _text(admission.reserved_native),
        "state": admission.state,
        "created_at": _timestamp(admission.created_at),
        "expires_at": _timestamp(admission.expires_at),
        "rate_reservations_json": _dump(list(admission.rate_reservations)),
        "local_only": 1 if admission.local_only else 0,
    }


def _admission_from_row(row: LimitAdmissionRow) -> LimitAdmission:
    created = _instant(row.created_at) or datetime.now(UTC)
    return LimitAdmission(
        attempt_id=row.attempt_id,
        provider=row.provider,
        operation=LimitOperation(row.operation),
        auth_mode=AuthMode(row.auth_mode),
        pool_id=row.pool_id,
        reserved_crd=_decimal(row.reserved_crd_text) or Decimal("0"),
        reserved_native=_decimal(row.reserved_native_text),
        state=row.state,  # type: ignore[arg-type]
        created_at=created,
        expires_at=_instant(row.expires_at) or created,
        rate_reservations=_load_reservations(row.rate_reservations_json),
        local_only=bool(row.local_only),
    )


async def _insert_rate_attempt(
    session: AsyncSession,
    *,
    attempt_id: str,
    bucket_id: str,
    provider: str,
    auth_mode: AuthMode,
    operation: LimitOperation | None,
    window: RateWindowName,
    units: Decimal,
    attempted_at: datetime,
) -> None:
    await session.execute(
        sqlite_insert(RateAttemptRow)
        .values(
            attempt_id=attempt_id,
            bucket_id=bucket_id,
            provider=provider,
            auth_mode=auth_mode.value,
            operation=operation.value if operation is not None else None,
            window=window.value,
            unit=RateUnit.REQUESTS.value,
            units_text=_text(units) or "0",
            attempted_at=_timestamp(attempted_at),
            expires_at=_timestamp(attempted_at + timedelta(seconds=_WINDOW_SECONDS[window])),
        )
        .on_conflict_do_nothing(index_elements=["attempt_id", "bucket_id"])
    )


async def _insert_event(session: AsyncSession, event: LimitAuditEvent) -> None:
    await session.execute(
        sqlite_insert(LimitEventRow)
        .values(
            event_id=event.event_id,
            provider=event.provider,
            operation=event.operation.value if event.operation is not None else None,
            auth_mode=event.auth_mode.value,
            pool_id=event.pool_id,
            observed_at=_timestamp(event.observed_at),
            source=event.source,
            reason=event.reason,
            old_native_text=_text(event.old_native),
            new_native_text=_text(event.new_native),
            old_crd_json=_text(event.old_crd),
            new_crd_json=_text(event.new_crd),
            crd_debit_text=_text(event.crd_debit),
            native_debit_text=_text(event.native_debit),
            actual_usd_text=_text(event.actual_usd),
            confidence=event.confidence.value,
            local_attempt_id=event.local_attempt_id,
            detail_json=json.dumps(event.detail) if event.detail else None,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )


def _event_from_row(row: LimitEventRow) -> LimitAuditEvent:
    return LimitAuditEvent(
        event_id=row.event_id,
        provider=row.provider,
        auth_mode=AuthMode(row.auth_mode),
        operation=LimitOperation(row.operation) if row.operation else None,
        pool_id=row.pool_id,
        observed_at=_instant(row.observed_at) or datetime.now(UTC),
        source=row.source,
        reason=row.reason,
        old_native=_decimal(row.old_native_text),
        new_native=_decimal(row.new_native_text),
        old_crd=_decimal(row.old_crd_json),
        new_crd=_decimal(row.new_crd_json),
        crd_debit=_decimal(row.crd_debit_text),
        native_debit=_decimal(row.native_debit_text),
        actual_usd=_decimal(row.actual_usd_text),
        confidence=Confidence(row.confidence),
        local_attempt_id=row.local_attempt_id,
        detail=_decode_detail(row.detail_json),
    )


def _decode_detail(text: str | None) -> dict[str, Any]:
    """Decode an event's detail payload, ignoring an unreadable value."""

    if not text:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}
