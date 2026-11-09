"""Durable provider-limit storage: catalog, pools, grants, audit, and rates.

Every read and write goes through one async session. Balance changes, their
audit events, and their admission finalization share one transaction, and no
transaction is held across vendor I/O. Money and native amounts are stored as
exact text, so a fractional credit-unit value survives a restart unchanged.
"""

import asyncio
import json
import math
import sqlite3
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from typing import cast as type_cast
from uuid import UUID

from sqlalchemy import Numeric, cast, delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from freesearch.models.budget_period import BudgetPeriod, window_bounds
from freesearch.models.contracts import ProviderError, UnitKind
from freesearch.models.observability import ActorType
from freesearch.models.provider_limits import (
    DEFAULT_ATTEMPT_LEASE_SECONDS,
    LOCAL_RATE_DENIAL_CODE,
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
    LimitDeniedError,
    LimitHistoryPage,
    LimitHistoryQuery,
    LimitOperation,
    LimitRecordNotFound,
    LimitRecordUpdate,
    LimitStoreUnavailable,
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
    local_funds_denial,
    local_rate_denial,
)
from freesearch.persistence.credentials import ProviderCredentialRow
from freesearch.persistence.limit_rows import (
    CRDGrantRow,
    LimitAdmissionRow,
    LimitEventRow,
    NativePoolRow,
    ProviderBudgetRow,
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


async def _begin_capacity_transaction(session: AsyncSession) -> None:
    """Retry only a SQLite busy/locked BEGIN, before any capacity work occurs.

    No statements or commits after BEGIN are retried: receipt or commit may be
    uncertain. Rolling back each failed BEGIN releases the session transaction
    before the bounded wait and leaves admission identity/debits untouched.
    """

    for retry in range(5):
        try:
            await session.execute(text("BEGIN IMMEDIATE"))
            return
        except OperationalError as error:
            code = getattr(error.orig, "sqlite_errorcode", None)
            if (
                not isinstance(code, int)
                or (code & 0xFF) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                or retry == 4
            ):
                raise
            await session.rollback()
            await asyncio.sleep(0.01 * 2**retry)


@dataclass(frozen=True)
class StrictWindowSpec:
    """One declared strict window the reservation must satisfy.

    The bucket is a pool- or project-scoped unit counter (``project:``,
    ``pool:`` prefix in the bucket id) and ``limit_units`` is a numeric,
    nonnegative strict ceiling; a reservation unit of ``1`` is one provider
    attempt.
    """

    bucket_id: str
    window_seconds: int
    limit_units: int


@dataclass(frozen=True)
class StrictAttemptSpec:
    """Precomputed strict reservation of one attempt against pool and project windows.

    The execution service derives every field from durable binding, pool,
    allocation, and constraint rows before asking the store; this object
    carries no trust: the repository rechecks every window inside its
    ``BEGIN IMMEDIATE`` transaction. ``actor_type``/``actor_id`` name the
    verified principal that owns the attempt; the strict payload and the
    settled capacity rows persist them alongside project, credential, binding,
    pool, and request attribution.
    """

    project_id: UUID
    credential_id: UUID
    binding_id: UUID
    pool_id: UUID | None = None
    request_id: str | None = None
    windows: tuple[StrictWindowSpec, ...] = ()
    pool_max_concurrency: int | None = None
    project_max_concurrency: int | None = None
    units_per_attempt: Decimal = Decimal("1")
    lease_seconds: int = DEFAULT_ATTEMPT_LEASE_SECONDS
    actor_type: ActorType | None = None
    actor_id: UUID | None = None


@dataclass(frozen=True)
class StrictReservation:
    """The stored reservation outcome of one strict attempt.

    ``state`` reports the persisted admission state: only ``reserved`` holds
    dispatchable capacity, ``released``/``completed``/``failed`` name a settled
    attempt whose replay must never grant fresh capacity. ``charge_next_dispatch``
    lets a dispatch path record one more actual upstream send under the same
    attempt (a retry that reused an idempotent reservation) before the send
    happens; it rechecks the strict windows first.
    """

    attempt_id: str
    bucket_ids: tuple[str, ...]
    pool_id: UUID | None
    created_at: datetime
    state: str
    idempotent: bool = False
    charge_next_dispatch: Callable[[], Awaitable["StrictReservation"]] | None = field(
        default=None, compare=False, repr=False
    )
    complete_dispatch: Callable[[], Awaitable[None]] | None = field(
        default=None, compare=False, repr=False
    )


@dataclass(frozen=True)
class AttemptReservation:
    """One atomic admission lifecycle covering native funds and strict caps.

    The native admission carries the rails reservation (funds, rate units,
    audit attribution); the strict reservation carries the pool/project
    windows and concurrency identity. Both share one attempt id and one
    transaction, so a strict denial never leaves a native reservation behind.
    """

    attempt_id: str
    admission: LimitAdmission | None = None
    strict: StrictReservation | None = None

    @property
    def bucket_ids(self) -> tuple[str, ...]:
        return () if self.strict is None else self.strict.bucket_ids

    @property
    def idempotent(self) -> bool:
        return bool(self.strict is not None and self.strict.idempotent)

    @property
    def charge_next_dispatch(self) -> Callable[[], Awaitable["StrictReservation"]] | None:
        return None if self.strict is None else self.strict.charge_next_dispatch


def _strict_spec_payload(spec: StrictAttemptSpec) -> dict[str, Any]:
    """Return the strict spec summary persisted on the admission row.

    The payload rides the existing ``rate_reservations_json`` column (the
    settled capacity tables have no dedicated spec columns); the rails decoder
    skips it, so a strict row never becomes a rails window list.
    """

    return {
        "kind": "strict",
        "units_per_attempt": str(spec.units_per_attempt),
        "lease_seconds": spec.lease_seconds,
        "pool_max_concurrency": spec.pool_max_concurrency,
        "project_max_concurrency": spec.project_max_concurrency,
        "actor_type": spec.actor_type.value if spec.actor_type is not None else None,
        "actor_id": None if spec.actor_id is None else str(spec.actor_id),
        "windows": [
            {
                "bucket_id": window.bucket_id,
                "window_seconds": window.window_seconds,
                "limit_units": window.limit_units,
            }
            for window in spec.windows
        ],
    }


def _strict_spec_matches(stored_json: str | None, spec: StrictAttemptSpec) -> bool:
    """Return whether a stored strict payload equals the replaying spec."""

    try:
        payload = json.loads(stored_json) if stored_json else None
    except ValueError:
        return False
    if not isinstance(payload, dict) or payload.get("kind") != "strict":
        return False
    try:
        stored = _StrictSpecState.model_from_payload(payload)
    except (ArithmeticError, ValueError, TypeError, KeyError):
        return False
    return stored.matches(spec)


class _StrictSpecState:
    """Decoded strict payload used to validate an idempotent replay."""

    __slots__ = (
        "actor_id",
        "actor_type",
        "lease_seconds",
        "pool_max_concurrency",
        "project_max_concurrency",
        "units_per_attempt",
        "windows",
    )

    def __init__(
        self,
        *,
        units_per_attempt: Decimal,
        lease_seconds: int,
        pool_max_concurrency: int | None,
        project_max_concurrency: int | None,
        windows: frozenset[tuple[str, int, int]],
        actor_type: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        self.units_per_attempt = units_per_attempt
        self.lease_seconds = lease_seconds
        self.pool_max_concurrency = pool_max_concurrency
        self.project_max_concurrency = project_max_concurrency
        self.windows = windows
        self.actor_type = actor_type
        self.actor_id = actor_id

    @classmethod
    def model_from_payload(cls, payload: dict[str, Any]) -> "_StrictSpecState":
        units = Decimal(str(payload["units_per_attempt"]))
        lease = int(payload["lease_seconds"])
        pool_cap = payload.get("pool_max_concurrency")
        project_cap = payload.get("project_max_concurrency")
        windows: set[tuple[str, int, int]] = set()
        for item in payload.get("windows", []):
            windows.add(
                (
                    str(item["bucket_id"]),
                    int(item["window_seconds"]),
                    int(item["limit_units"]),
                )
            )
        return cls(
            units_per_attempt=units,
            lease_seconds=lease,
            pool_max_concurrency=None if pool_cap is None else int(pool_cap),
            project_max_concurrency=None if project_cap is None else int(project_cap),
            windows=frozenset(windows),
            actor_type=None if payload.get("actor_type") is None else str(payload["actor_type"]),
            actor_id=None if payload.get("actor_id") is None else str(payload["actor_id"]),
        )

    def matches(self, spec: StrictAttemptSpec) -> bool:
        incoming = frozenset(
            (window.bucket_id, window.window_seconds, window.limit_units) for window in spec.windows
        )
        return (
            self.units_per_attempt == spec.units_per_attempt
            and self.lease_seconds == spec.lease_seconds
            and self.pool_max_concurrency == spec.pool_max_concurrency
            and self.project_max_concurrency == spec.project_max_concurrency
            and self.windows == incoming
            and self.actor_type == (spec.actor_type.value if spec.actor_type is not None else None)
            and self.actor_id == (None if spec.actor_id is None else str(spec.actor_id))
        )


# Tavily persistence guarantees: the keyed rails share one aggregate Credits
# pool, the usage poll runs at most once per 60 seconds, and the durable
# terminal out-of-Credits record carries the ``vendor_402`` source.
_TAVILY_PROVIDER = "tavily"
_TAVILY_KEYED_CREDITS_POOL_ID = "tavily:keyed:credit"
_TAVILY_SYNC_CADENCE_SECONDS = 60
_TAVILY_VENDOR_402_SOURCE = "vendor_402"
_TAVILY_VENDOR_API_SOURCE = "vendor_api"


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

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one caller-owned read session for a multi-value decision.

        Admission reads several pools and grants; the caller holds them on one
        snapshot and closes without writing. Writes keep their own transactions.
        """

        async with self._session_factory() as session:
            yield session

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

    async def get_pool(
        self, pool_id: str, *, session: AsyncSession | None = None
    ) -> NativePool | None:
        """Return one native pool by ID, optionally inside a caller's session.

        The execution admission reads several pools and grants for one decision;
        passing its session keeps those reads on one snapshot instead of opening
        and closing a connection per value.
        """

        if session is not None:
            row = await session.get(NativePoolRow, pool_id)
            return _pool_from_row(row) if row is not None else None
        async with self._session_factory() as own_session:
            row = await own_session.get(NativePoolRow, pool_id)
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

        The Tavily keyed Credits pool also rejects observations that would
        travel backwards from the terminal out-of-Credits record, and it
        subtracts the local debits that finished after the observation
        instant, so debits made while a usage poll ran never resurrect.
        """

        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            if snapshot.credential_id is not None:
                credential = await session.get(ProviderCredentialRow, str(snapshot.credential_id))
                if (
                    credential is None
                    or credential.status != "active"
                    or (
                        credential.generation != snapshot.credential_generation
                        or credential.provider_type != snapshot.provider
                    )
                ):
                    return False
            row = await session.get(NativePoolRow, snapshot.pool_id)
            if (
                row is not None
                and snapshot.upstream_pool_id is None
                and snapshot.credential_generation < row.credential_generation
            ):
                return False
            if (
                row is not None
                and (_instant(row.observed_at) or snapshot.observed_at) > snapshot.observed_at
            ):
                return False
            if _tavily_observation_rejected(row, snapshot):
                return False
            old_native = _decimal(row.remaining_text) if row is not None else None
            effective = _preserve_known_values(row, snapshot)
            if snapshot.source == _TAVILY_VENDOR_API_SOURCE and (
                _is_tavily_credits_pool(snapshot) or "#" in snapshot.pool_id
            ):
                debits = await _native_debits_after(session, snapshot.pool_id, snapshot.observed_at)
                adjusted = _remaining_after(snapshot.remaining, debits)
                if adjusted is not None and adjusted != effective.remaining:
                    effective = effective.model_copy(update={"remaining": adjusted})
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
        self,
        provider: str,
        update: CRDGrantUpdate,
        *,
        auth_mode: AuthMode,
        now: datetime | None = None,
    ) -> None:
        """Store one period grant and its audit event."""

        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            values = dict(
                provider=provider,
                auth_mode=auth_mode.value,
                period=update.period,
                search_crd_text=_text(update.search_crd),
                fetch_crd_text=_text(update.fetch_crd),
                version=update.version + 1,
            )
            await session.execute(
                sqlite_insert(ProviderBudgetRow)
                .values(**values)
                .on_conflict_do_update(index_elements=["provider", "auth_mode"], set_=values)
            )
            await _budget_rows(session, provider, auth_mode, now=now or datetime.now(UTC))
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
                        "period": update.period,
                        "search_crd": _text(update.search_crd),
                        "fetch_crd": _text(update.fetch_crd),
                    },
                ),
            )
            await session.commit()

    async def grants(
        self,
        provider: str,
        auth_mode: AuthMode,
        *,
        now: datetime,
        session: AsyncSession | None = None,
    ) -> CRDGrantsSummary | None:
        """Return the current period grant summary, or ``None`` when none exists.

        Accepts the admission's session so the grant and pool reads that feed one
        decision share a snapshot.
        """

        if session is not None:
            rows, period = await _budget_rows(session, provider, auth_mode, now=now)
        else:
            async with self._session_factory() as own_session:
                rows, period = await _budget_rows(own_session, provider, auth_mode, now=now)
                await own_session.commit()
        if not rows:
            return None
        return _grants_summary(provider, auth_mode, rows).model_copy(update={"period": period})

    async def reserve(
        self,
        admission: LimitAdmission,
        *,
        record: ProviderLimitRecord | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> LimitAdmission:
        """Reserve funds and rate units in one serialized transaction.

        One ``BEGIN IMMEDIATE`` transaction rechecks, inserts, and commits, so
        two processes cannot interleave between a window count and its insert.
        A repeated attempt ID keeps its first reservation, so a retried call
        cannot reserve twice: the replay must carry the same identity
        (provider, operation, auth rail, attribution, and reserved amounts)
        or it is refused instead of silently skipping its obligations. For
        Tavily, the same transaction rechecks before the insert: first the
        documented minute rate window counts unexpired attempts, then the
        known native funds count the active native reservations of other
        admissions. A denial raises before the admission row has funds, and a
        funds denial takes status precedence over a rate denial.
        """

        async with self._session_factory() as session:
            try:
                # The write lock is taken before the first read, so a sibling
                # connection or process can never count the same free unit.
                await _begin_capacity_transaction(session)
                created = _strict_reservation_time(
                    admission.created_at, clock() if clock is not None else datetime.now(UTC)
                )
                admission = _retime_admission(admission, created)
                existing = await session.get(LimitAdmissionRow, admission.attempt_id)
                if existing is not None:
                    stored = _admission_from_row(existing)
                    if existing.state != "reserved":
                        raise _strict_replay_denial(existing, reason="attempt_already_settled")
                    if not _rails_replay_matches(existing, admission):
                        raise _replay_conflict_denial(admission)
                    await session.commit()
                    return stored
                if record is not None:
                    await self._recheck_native(session, admission, record)
                await session.execute(
                    sqlite_insert(LimitAdmissionRow).values(
                        **await _budget_admission_values(session, admission)
                    )
                )
                attribution = _attribution_values(admission)
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
                        attribution=attribution,
                    )
                if admission.reserved_crd > 0:
                    await _adjust_grant(
                        session,
                        admission.provider,
                        admission.auth_mode,
                        admission.operation,
                        reserved_delta=admission.reserved_crd,
                        window_start=await session.scalar(
                            select(LimitAdmissionRow.grant_window_start).where(
                                LimitAdmissionRow.attempt_id == admission.attempt_id
                            )
                        ),
                    )
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                await session.rollback()
                raise LimitStoreUnavailable(admission.provider) from error
            except LimitDeniedError:
                await session.rollback()
                raise
            except BaseException:
                await session.rollback()
                raise
        return admission

    async def finalize(self, debit: LimitDebit) -> bool:
        """Apply the actual debit, mark the attempt finalized, and audit it.

        Returns ``False`` when the attempt was already finished, so a duplicate
        finalization can never debit twice.
        """

        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(LimitAdmissionRow, debit.attempt_id)
            if row is None or row.state != "reserved":
                return False
            payload = _strict_spec_payload_of(row.rate_reservations_json)
            if payload is not None and debit.reason == "local_uncertain":
                payload["outcome"] = "uncertain"
                row.rate_reservations_json = _strict_payload_json(payload)
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
                window_start=row.grant_window_start,
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

    async def release(self, attempt_id: str, reason: str, *, refund_rate: bool = False) -> bool:
        """Release a reservation after a definite failure.

        ``refund_rate`` is the established non-dispatch path: it also deletes
        the attempt's rate rows because no vendor call happened. A definite
        vendor failure keeps its consumed rate units (the call did happen) and
        only refunds the unused funds reservation.
        """

        async with self._session_factory() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(LimitAdmissionRow, attempt_id)
            if row is None or row.state != "reserved":
                return False
            await _adjust_grant(
                session,
                row.provider,
                AuthMode(row.auth_mode),
                LimitOperation(row.operation),
                reserved_delta=-(_decimal(row.reserved_crd_text) or Decimal("0")),
                window_start=row.grant_window_start,
            )
            await session.execute(
                update(LimitAdmissionRow)
                .where(LimitAdmissionRow.attempt_id == attempt_id)
                .values(state="released")
            )
            if refund_rate:
                await session.execute(
                    delete(RateAttemptRow).where(RateAttemptRow.attempt_id == attempt_id)
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

    # ------------------------------------------------- strict pool/project caps

    async def reserve_strict(
        self,
        *,
        attempt_id: str,
        provider: str,
        operation: LimitOperation,
        auth_mode: AuthMode,
        spec: StrictAttemptSpec,
        created_at: datetime | None = None,
    ) -> StrictReservation:
        """Reserve one attempt against strict pool and project windows atomically.

        One ``BEGIN IMMEDIATE`` transaction rechecks each declared window and
        both concurrency caps, and only then inserts the admission row with its
        full attribution plus one rate-attempt row per declared window. The
        reservation instant is read *inside* the serialized transaction, so the
        row order matches the commit order, and every window count admits rows
        stamped slightly ahead of the local clock, so inter-process clock drift
        can never under-count a committed sibling attempt. A repeated attempt
        ID replays only when the stored reservation is still ``reserved`` and
        the spec matches exactly; a terminal or mismatched replay is refused,
        never re-granted capacity. A lacking window or concurrency slot raises
        the local rate denial, and a store failure raises
        :class:`LimitStoreUnavailable`: a failed capacity check means no
        constrained execution, never a smaller window.
        """

        outcome = await self.reserve_attempt(
            attempt_id=attempt_id,
            provider=provider,
            operation=operation,
            auth_mode=auth_mode,
            spec=spec,
            created_at=created_at,
        )
        if outcome.strict is None:  # pragma: no cover - the spec always yields one
            raise AssertionError("a strict reservation must return its strict outcome")
        return outcome.strict

    async def reserve_attempt(
        self,
        *,
        attempt_id: str,
        provider: str,
        operation: LimitOperation,
        auth_mode: AuthMode,
        admission: LimitAdmission | None = None,
        spec: StrictAttemptSpec | None = None,
        record: ProviderLimitRecord | None = None,
        created_at: datetime | None = None,
    ) -> AttemptReservation:
        """Reserve native funds and strict windows in one atomic lifecycle.

        Both obligations share one attempt identity and one transaction: the
        native admission (funds, rate units, audit attribution) and the strict
        pool/project windows and concurrency slot either both commit or both
        roll back. A strict denial therefore never leaves a native reservation
        behind, and no second ``#s`` attempt identity exists to double count
        concurrency. Replays follow the same rules as the native and strict
        single-purpose reservations: only a still-reserved, exactly matching
        attempt is idempotent.
        """

        if admission is None and spec is None:
            raise ValueError("an attempt reservation needs a native admission or a strict spec")
        async with self._session_factory() as session:
            try:
                await _begin_capacity_transaction(session)
                created, core = self._reservation_inputs(
                    attempt_id=attempt_id,
                    provider=provider,
                    operation=operation,
                    auth_mode=auth_mode,
                    admission=admission,
                    spec=spec,
                    created_at=created_at,
                )
                existing = await session.get(LimitAdmissionRow, attempt_id)
                if existing is not None:
                    return await self._replay_existing(
                        session,
                        existing,
                        attempt_id=attempt_id,
                        provider=provider,
                        operation=operation,
                        auth_mode=auth_mode,
                        spec=spec,
                        admission=admission,
                        core=core,
                        created=created,
                    )
                if spec is not None:
                    await _strict_capacity_check(
                        session, spec, operation=operation, created=created
                    )
                if record is not None:
                    await self._recheck_native(session, core, record)
                await self._insert_attempt_rows(
                    session,
                    attempt_id=attempt_id,
                    provider=provider,
                    operation=operation,
                    auth_mode=auth_mode,
                    admission=admission,
                    spec=spec,
                    core=core,
                    created=created,
                )
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                await session.rollback()
                raise LimitStoreUnavailable(f"attempt:{attempt_id}") from error
            except LimitDeniedError:
                await session.rollback()
                raise
            except BaseException:
                await session.rollback()
                raise
            strict = (
                None
                if spec is None
                else StrictReservation(
                    attempt_id=attempt_id,
                    bucket_ids=tuple(window.bucket_id for window in spec.windows),
                    pool_id=spec.pool_id,
                    created_at=created,
                    state="reserved",
                    complete_dispatch=self._dispatch_completion(attempt_id),
                    charge_next_dispatch=(
                        None
                        if admission is not None
                        else self._dispatch_charger(attempt_id=attempt_id, spec=spec)
                    ),
                )
            )
            return AttemptReservation(
                attempt_id=attempt_id,
                admission=core if admission is not None else None,
                strict=strict,
            )

    @staticmethod
    def _reservation_inputs(
        *,
        attempt_id: str,
        provider: str,
        operation: LimitOperation,
        auth_mode: AuthMode,
        admission: LimitAdmission | None,
        spec: StrictAttemptSpec | None,
        created_at: datetime | None,
    ) -> tuple[datetime, LimitAdmission]:
        """Validate and build the shared admission contract of one attempt."""

        if spec is not None:
            _validate_strict_spec(spec)
            created = _strict_reservation_time(created_at, datetime.now(UTC))
            if admission is None:
                core = _strict_admission(
                    attempt_id=attempt_id,
                    provider=provider,
                    operation=operation,
                    auth_mode=auth_mode,
                    spec=spec,
                    created_at=created,
                )
            else:
                core = _retime_admission(admission, created)
        else:
            assert admission is not None
            created = _strict_reservation_time(
                created_at or admission.created_at, datetime.now(UTC)
            )
            core = _retime_admission(admission, created)
        if (
            core.attempt_id != attempt_id
            or core.provider != provider
            or core.operation is not operation
            or core.auth_mode is not auth_mode
        ):
            raise ValueError("the native admission and attempt identity must match")
        if spec is not None and (
            core.project_id,
            core.credential_id,
            core.binding_id,
            core.upstream_pool_id,
            core.request_id,
            core.actor_type,
            core.actor_id,
        ) != (
            spec.project_id,
            spec.credential_id,
            spec.binding_id,
            spec.pool_id,
            spec.request_id,
            spec.actor_type,
            spec.actor_id,
        ):
            raise ValueError("the native and strict ownership must match")
        return created, core

    async def _replay_existing(
        self,
        session: AsyncSession,
        existing: LimitAdmissionRow,
        *,
        attempt_id: str,
        provider: str,
        operation: LimitOperation,
        auth_mode: AuthMode,
        spec: StrictAttemptSpec | None,
        admission: LimitAdmission | None,
        core: LimitAdmission,
        created: datetime,
    ) -> AttemptReservation:
        """Return an idempotent replay or raise its typed conflict denial."""

        if spec is not None:
            replay = _strict_replay(
                existing,
                provider=provider,
                operation=operation,
                auth_mode=auth_mode,
                spec=spec,
                now=created,
                admission=admission,
            )
            stored_admission = _admission_from_row(existing) if admission is not None else None
            await session.rollback()
            if isinstance(replay, LimitDeniedError):
                raise replay
            if replay.charge_next_dispatch is None:
                replay = replace(
                    replay,
                    charge_next_dispatch=self._dispatch_charger(attempt_id=attempt_id, spec=spec),
                    complete_dispatch=self._dispatch_completion(attempt_id),
                )
            return AttemptReservation(
                attempt_id=attempt_id,
                admission=stored_admission,
                strict=replay,
            )
        stored = _admission_from_row(existing)
        if existing.state != "reserved":
            raise _strict_replay_denial(existing, reason="attempt_already_settled")
        if not _rails_replay_matches(existing, core):
            raise _replay_conflict_denial(core)
        await session.commit()
        return AttemptReservation(attempt_id=attempt_id, admission=stored)

    async def _recheck_native(
        self,
        session: AsyncSession,
        core: LimitAdmission,
        record: ProviderLimitRecord,
    ) -> None:
        """Recheck every native funds and rate obligation under the write lock."""

        rate_denial = await _native_rate_denial(session, core, record)
        if await _native_funds_denial(session, core):
            raise local_funds_denial(
                provider=core.provider,
                operation=core.operation,
                reasons=["funds_exhausted"],
            )
        if rate_denial is not None:
            raise rate_denial

    async def _insert_attempt_rows(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        provider: str,
        operation: LimitOperation,
        auth_mode: AuthMode,
        admission: LimitAdmission | None,
        spec: StrictAttemptSpec | None,
        core: LimitAdmission,
        created: datetime,
    ) -> None:
        """Write the admission, native rate rows, strict rows, and grant hold."""

        values = await _budget_admission_values(session, core)
        if spec is not None:
            payload = _strict_spec_payload(spec)
            if admission is not None:
                payload["native"] = _native_payload(admission)
            values["rate_reservations_json"] = _strict_payload_json(payload)
        await session.execute(sqlite_insert(LimitAdmissionRow).values(**values))
        attribution = _attribution_values(core)
        for reservation in core.rate_reservations:
            await _insert_rate_attempt(
                session,
                attempt_id=attempt_id,
                bucket_id=reservation.bucket_id,
                provider=provider,
                auth_mode=auth_mode,
                operation=operation,
                window=reservation.window,
                units=reservation.units,
                attempted_at=created,
                attribution=attribution,
            )
        if spec is not None:
            strict_attribution = _strict_attribution(spec, request_id=core.request_id)
            for window in spec.windows:
                await _insert_attempt_units(
                    session,
                    attempt_id=attempt_id,
                    bucket_id=window.bucket_id,
                    provider=provider,
                    auth_mode=auth_mode,
                    operation=operation,
                    window_text=str(window.window_seconds),
                    window_seconds=window.window_seconds,
                    units=spec.units_per_attempt,
                    attempted_at=created,
                    attribution=strict_attribution,
                )
        if core.reserved_crd > 0:
            await _adjust_grant(
                session,
                core.provider,
                core.auth_mode,
                core.operation,
                reserved_delta=core.reserved_crd,
                window_start=values["grant_window_start"],
            )

    def _dispatch_charger(
        self, *, attempt_id: str, spec: StrictAttemptSpec
    ) -> Callable[[], Awaitable[StrictReservation]]:
        """Return the per-dispatch charger of one standalone strict attempt."""

        async def charge() -> StrictReservation:
            return await self.charge_strict_dispatch(attempt_id=attempt_id, spec=spec)

        return charge

    async def charge_strict_dispatch(
        self, *, attempt_id: str, spec: StrictAttemptSpec
    ) -> StrictReservation:
        """Record one more actual upstream send under a strict reservation.

        The runner may retry inside one adapter call. A retry is a real send
        and consumes another strict unit, but it is the same logical attempt,
        so it keeps the attempt identity's concurrency slot and writes a child
        rate debit with a deterministic ``#d<n>`` id. The strict windows are
        rechecked in the same serialized transaction before the send; at a
        one-unit ceiling the second send is denied before it happens.
        """

        async with self._session_factory() as session:
            try:
                await _begin_capacity_transaction(session)
                created = _strict_reservation_time(None, datetime.now(UTC))
                row = await session.get(LimitAdmissionRow, attempt_id)
                if row is None or row.state != "reserved":
                    raise _strict_replay_denial(row, reason="attempt_already_settled")
                await _strict_capacity_check(
                    session,
                    spec,
                    operation=LimitOperation(row.operation),
                    created=created,
                    check_concurrency=True,
                )
                payload = _strict_spec_payload_of(row.rate_reservations_json)
                if payload is not None:
                    payload["dispatch_completed"] = False
                    row.rate_reservations_json = _strict_payload_json(payload)
                existing_ids = (
                    await session.scalars(
                        select(RateAttemptRow.attempt_id)
                        .where(RateAttemptRow.attempt_id.like(f"{attempt_id}#d%"))
                        .distinct()
                    )
                ).all()
                dispatch = len(set(existing_ids)) + 1
                child_id = f"{attempt_id}#d{dispatch}"
                originals = (
                    await session.scalars(
                        select(RateAttemptRow).where(RateAttemptRow.attempt_id == attempt_id)
                    )
                ).all()
                for original in originals:
                    started = _instant(original.attempted_at)
                    ended = _instant(original.expires_at)
                    seconds = (
                        max(1, int((ended - started).total_seconds()))
                        if started is not None and ended is not None
                        else 1
                    )
                    await _insert_attempt_units(
                        session,
                        attempt_id=child_id,
                        bucket_id=original.bucket_id,
                        provider=original.provider,
                        auth_mode=AuthMode(original.auth_mode),
                        operation=(
                            LimitOperation(original.operation)
                            if original.operation is not None
                            else None
                        ),
                        window_text=original.window,
                        window_seconds=seconds,
                        units=Decimal(original.units_text),
                        attempted_at=created,
                        attribution={
                            "project_id": original.project_id,
                            "credential_id": original.credential_id,
                            "binding_id": original.binding_id,
                            "upstream_pool_id": original.upstream_pool_id,
                            "request_id": original.request_id,
                            "actor_type": original.actor_type,
                            "actor_id": original.actor_id,
                        },
                    )
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                await session.rollback()
                raise LimitStoreUnavailable(f"attempt:{attempt_id}") from error
            except LimitDeniedError:
                await session.rollback()
                raise
            except BaseException:
                await session.rollback()
                raise
            return StrictReservation(
                attempt_id=attempt_id,
                bucket_ids=tuple(window.bucket_id for window in spec.windows),
                pool_id=spec.pool_id,
                created_at=created,
                state="reserved",
                charge_next_dispatch=self._dispatch_charger(attempt_id=attempt_id, spec=spec),
                complete_dispatch=self._dispatch_completion(attempt_id),
            )

    def _dispatch_completion(self, attempt_id: str) -> Callable[[], Awaitable[None]]:
        async def complete() -> None:
            await self.complete_dispatch(attempt_id)

        return complete

    async def complete_dispatch(self, attempt_id: str) -> None:
        """Release concurrency after a known response while retaining rate and funds."""
        async with self._session_factory() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                row = await session.get(LimitAdmissionRow, attempt_id)
                if row is not None and row.state == "reserved":
                    payload = _strict_spec_payload_of(row.rate_reservations_json)
                    if payload is not None:
                        payload["dispatch_completed"] = True
                        row.rate_reservations_json = _strict_payload_json(payload)
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                raise LimitStoreUnavailable(f"attempt:{attempt_id}") from error

    async def release_strict(self, *, attempt_id: str, bucket_ids: Sequence[str]) -> bool:
        """Undo one never-dispatched reservation.

        The admission is marked released only while it is still reserved, and
        in that same transaction the reservation's native grant reservation is
        refunded and every rate row of the attempt (including per-dispatch
        child rows) vanishes: an established non-dispatch never consumes
        funds, rate units, or concurrency. A settled attempt always keeps its
        debit, and a second release reports ``False`` and changes nothing.
        The ``bucket_ids`` argument is retained for the documented strict
        caller contract; deletion is keyed by the attempt id so no obligation
        of the same attempt is left behind.
        """

        del bucket_ids
        async with self._session_factory() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                row = await session.get(LimitAdmissionRow, attempt_id)
                if row is None or row.state != "reserved":
                    await session.commit()
                    return False
                reserved_crd = _decimal(row.reserved_crd_text) or Decimal("0")
                if reserved_crd > 0:
                    await _adjust_grant(
                        session,
                        row.provider,
                        AuthMode(row.auth_mode),
                        LimitOperation(row.operation),
                        reserved_delta=-reserved_crd,
                        window_start=row.grant_window_start,
                    )
                await session.execute(
                    update(LimitAdmissionRow)
                    .where(LimitAdmissionRow.attempt_id == attempt_id)
                    .values(state="released")
                    .execution_options(synchronize_session=False)
                )
                await session.execute(
                    delete(RateAttemptRow).where(RateAttemptRow.attempt_id == attempt_id)
                )
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                await session.rollback()
                raise LimitStoreUnavailable(f"attempt:{attempt_id}") from error
            except BaseException:
                await session.rollback()
                raise
            return True

    async def settle_strict(
        self,
        *,
        attempt_id: str,
        outcome: Literal["completed", "failed", "uncertain"],
    ) -> bool:
        """Mark one strict reservation terminal, retaining its rate debit.

        Every attempt that reached the vendor keeps its window debit whether it
        succeeded or failed, so an uncertain upstream receipt is never refunded,
        and settlement is what frees the attempt's concurrency slot. The row
        lands on the settled ``finalized`` state and records the outcome in its
        strict payload, because the admission contract has exactly the
        ``reserved``/``finalized``/``released`` states. Idempotent: a settled
        attempt reports ``False`` and changes nothing.
        """

        async with self._session_factory() as session:
            try:
                await session.execute(text("BEGIN IMMEDIATE"))
                row = await session.get(LimitAdmissionRow, attempt_id)
                if row is None:
                    return False
                payload = _strict_spec_payload_of(row.rate_reservations_json)
                if row.state != "reserved" and not (
                    row.state == "finalized"
                    and payload is not None
                    and payload.get("outcome") == "uncertain"
                    and outcome != "uncertain"
                ):
                    return False
                if payload is not None:
                    payload["outcome"] = outcome
                    row.rate_reservations_json = _strict_payload_json(payload)
                row.state = "finalized"
                await session.commit()
            except (OperationalError, IntegrityError) as error:
                await session.rollback()
                raise LimitStoreUnavailable(f"attempt:{attempt_id}") from error
            except BaseException:
                await session.rollback()
                raise
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
        """Claim the sync lease for one provider, or return ``False`` when held.

        A Tavily claim anchors on the canonical keyed Credits pool row and is
        one atomic update that requires an expired lease and a due next sync
        instant, so the same owner cannot bypass an active usage poll and no
        other pool of that provider is leased. On success the claim sets the
        next allowed start at least 60 seconds after the request start.
        """

        now = _timestamp(claim.now)
        expiry = _timestamp(claim.now + timedelta(seconds=claim.lease_seconds))
        if claim.pool_id is not None:
            statement = (
                update(NativePoolRow)
                .where(
                    NativePoolRow.provider == claim.provider,
                    NativePoolRow.pool_id == claim.pool_id,
                    (NativePoolRow.lease_until.is_(None)) | (NativePoolRow.lease_until < now),
                    (NativePoolRow.next_sync_at.is_(None)) | (NativePoolRow.next_sync_at <= now),
                )
                .values(
                    lease_owner=claim.owner,
                    lease_until=expiry,
                    next_sync_at=expiry,
                )
            )
        elif claim.provider == _TAVILY_PROVIDER:
            statement = (
                update(NativePoolRow)
                .where(
                    NativePoolRow.provider == claim.provider,
                    NativePoolRow.pool_id == _TAVILY_KEYED_CREDITS_POOL_ID,
                    (NativePoolRow.lease_until.is_(None)) | (NativePoolRow.lease_until < now),
                    (NativePoolRow.next_sync_at.is_(None)) | (NativePoolRow.next_sync_at <= now),
                )
                .values(
                    lease_owner=claim.owner,
                    lease_until=expiry,
                    next_sync_at=_timestamp(
                        claim.now + timedelta(seconds=_TAVILY_SYNC_CADENCE_SECONDS)
                    ),
                )
            )
        else:
            statement = (
                update(NativePoolRow)
                .where(
                    NativePoolRow.provider == claim.provider,
                    ~NativePoolRow.pool_id.contains("#"),
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

    async def complete_sync(self, result: SyncResult, *, pool_id: str | None = None) -> None:
        """Clear the lease and store the next attempt instant and error state."""

        async with self._session_factory() as session:
            await session.execute(
                update(NativePoolRow)
                .where(
                    NativePoolRow.provider == result.provider,
                    NativePoolRow.pool_id == pool_id
                    if pool_id is not None
                    else ~NativePoolRow.pool_id.contains("#"),
                )
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
            (NativePoolRow.next_sync_at.is_(None)) | (NativePoolRow.next_sync_at <= stamp),
            ~NativePoolRow.pool_id.contains("#"),
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

    async def list_observations(
        self, provider: str, *, session: AsyncSession | None = None
    ) -> list[RateObservation]:
        """Return stored rate observations for one provider.

        Accepts the admission's read session so several rate windows share one
        observation query instead of re-reading the provider's history per
        window.
        """

        statement = select(RateWindowObservationRow).where(
            RateWindowObservationRow.provider == provider
        )
        if session is not None:
            rows = (await session.scalars(statement)).all()
        else:
            async with self._session_factory() as own_session:
                rows = (await own_session.scalars(statement)).all()
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
        session: AsyncSession | None = None,
    ) -> Decimal:
        """Count local rate units still inside one window.

        An age-based window expires each attempt by its own age. When a fresh
        vendor observation exists, ``since`` restricts the count to attempts
        after that observation, so a local count is never double counted.
        """

        if session is not None:
            return await _rate_used_in_window(
                session, bucket_id, window_seconds=_WINDOW_SECONDS[window], now=now, since=since
            )
        async with self._session_factory() as own_session:
            return await _rate_used_in_window(
                own_session,
                bucket_id,
                window_seconds=_WINDOW_SECONDS[window],
                now=now,
                since=since,
            )

    async def count_catalog_attempts(
        self,
        provider: str,
        bucket_id: str,
        *,
        window: RateWindowName,
        now: datetime,
        since: datetime | None = None,
    ) -> Decimal:
        """Count a catalog bucket and its credential and pool scopes for display."""

        start = since or (now - timedelta(seconds=_WINDOW_SECONDS[window]))
        prefix = f"{bucket_id}#"
        scope = func.substr(RateAttemptRow.bucket_id, len(prefix) + 1)
        rows = (
            select(
                RateAttemptRow.attempt_id,
                func.max(cast(RateAttemptRow.units_text, _QUANTUM)).label("units"),
            )
            .where(
                RateAttemptRow.provider == provider,
                RateAttemptRow.attempted_at >= _timestamp(start),
                (RateAttemptRow.bucket_id == bucket_id)
                | (
                    (func.substr(RateAttemptRow.bucket_id, 1, len(prefix)) == prefix)
                    & (
                        (func.substr(scope, 1, 5) == "cred:")
                        | (func.substr(scope, 1, 5) == "pool:")
                    )
                ),
            )
            .group_by(RateAttemptRow.attempt_id)
            .subquery()
        )
        async with self._session_factory() as session:
            total = (
                await session.execute(select(func.coalesce(func.sum(rows.c.units), 0)))
            ).scalar_one()
        return Decimal(str(total))

    async def oldest_attempt(
        self, bucket_id: str, *, window: RateWindowName, now: datetime
    ) -> datetime | None:
        """Return the oldest attempt still inside one age-based window."""

        start = now - timedelta(seconds=_WINDOW_SECONDS[window])
        statement = select(func.min(RateAttemptRow.attempted_at)).where(
            RateAttemptRow.bucket_id == bucket_id,
            RateAttemptRow.attempted_at >= _timestamp(start),
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
        actor_type: ActorType,
        actor_id: UUID,
    ) -> None:
        """Persist one consumed rate unit, ignoring a duplicate attempt ID.

        The verified actor that owns the attempt is required on every row.
        """

        _require_actor(actor_type, actor_id)
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
                attribution={"actor_type": actor_type.value, "actor_id": str(actor_id)},
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
            if "#" in observation.bucket_id:
                used = await self.count_attempts(
                    observation.bucket_id,
                    window=observation.window,
                    now=now,
                    since=observation.observed_at,
                )
            else:
                used = await self.count_catalog_attempts(
                    provider,
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


def _strict_attribution(spec: StrictAttemptSpec, *, request_id: str | None) -> dict[str, Any]:
    """Return the attribution column values one strict attempt writes."""

    return {
        "project_id": str(spec.project_id),
        "credential_id": str(spec.credential_id),
        "binding_id": str(spec.binding_id),
        "upstream_pool_id": None if spec.pool_id is None else str(spec.pool_id),
        "request_id": request_id,
        "actor_type": spec.actor_type.value if spec.actor_type is not None else None,
        "actor_id": None if spec.actor_id is None else str(spec.actor_id),
    }


def _require_actor(actor_type: ActorType | None, actor_id: UUID | None) -> None:
    """Refuse a capacity write that does not carry the verified actor."""

    if actor_type is None or actor_id is None:
        raise ValueError("a capacity reservation must carry the verified actor")


def _validate_strict_spec(spec: StrictAttemptSpec) -> None:
    """Reject a malformed strict spec before any transaction starts."""

    if spec.project_id is None or spec.credential_id is None or spec.binding_id is None:
        raise ValueError("a strict attempt spec must name its project, credential, and binding")
    _require_actor(spec.actor_type, spec.actor_id)
    if spec.units_per_attempt < 0:
        raise ValueError("attempt units must not be negative")
    if spec.lease_seconds < 1:
        raise ValueError("the attempt lease must be at least one second")
    for window in spec.windows:
        if not window.bucket_id:
            raise ValueError("a strict window needs a bucket id")
        if window.window_seconds < 1:
            raise ValueError(f"{window.bucket_id}: strict window must be at least one second")
        if window.limit_units < 0:
            raise ValueError(f"{window.bucket_id}: strict limit must not be negative")
    distinct = {window.bucket_id for window in spec.windows}
    if len(distinct) != len(spec.windows):
        raise ValueError("strict windows must not repeat a bucket id")
    if spec.pool_max_concurrency is not None and spec.pool_id is None:
        raise ValueError("pool_concurrent_cap requires an upstream pool id")
    if spec.pool_max_concurrency is not None and spec.pool_max_concurrency < 1:
        raise ValueError("the pool concurrency cap must be positive")
    if spec.project_max_concurrency is not None and spec.project_max_concurrency < 1:
        raise ValueError("the project concurrency cap must be positive")


def _strict_spec_json(spec: StrictAttemptSpec) -> str:
    """Return the strict summary persisted on the admission row."""

    return _strict_payload_json(_strict_spec_payload(spec))


def _is_strict_payload(stored_json: str | None) -> bool:
    try:
        payload = json.loads(stored_json) if stored_json else None
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("kind") == "strict"


def _strict_spec_payload_of(stored_json: str | None) -> dict[str, Any] | None:
    """Return the stored strict payload when it decodes, else ``None``."""

    try:
        payload = json.loads(stored_json) if stored_json else None
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and payload.get("kind") == "strict" else None


def _strict_payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _rails_replay_matches(stored: LimitAdmissionRow, admission: LimitAdmission) -> bool:
    """Return whether a replaying rails admission is the stored reservation.

    Same attempt ID, same identity (provider, operation, auth rail,
    attribution), same reservation amounts, and same rate windows; anything
    else is an unrelated duplicate that must never skip its own checks.
    """

    if _is_strict_payload(stored.rate_reservations_json):
        return False
    if (
        stored.pool_id != admission.pool_id
        or stored.provider != admission.provider
        or stored.operation != admission.operation.value
        or stored.auth_mode != admission.auth_mode.value
    ):
        return False
    if (
        stored.project_id != _optional_text(admission.project_id)
        or stored.credential_id != _optional_text(admission.credential_id)
        or stored.binding_id != _optional_text(admission.binding_id)
        or stored.upstream_pool_id != _optional_text(admission.upstream_pool_id)
        or stored.request_id != admission.request_id
        or stored.actor_type
        != (admission.actor_type.value if admission.actor_type is not None else None)
        or stored.actor_id != _optional_text(admission.actor_id)
    ):
        return False
    if (_decimal(stored.reserved_crd_text) or Decimal("0")) != admission.reserved_crd:
        return False
    if (_decimal(stored.reserved_native_text)) != admission.reserved_native:
        return False
    stored_reservations = _load_reservations(stored.rate_reservations_json)
    stored_windows = frozenset(
        (item.bucket_id, item.window.value, _text(item.units)) for item in stored_reservations
    )
    incoming_windows = frozenset(
        (item.bucket_id, item.window.value, _text(item.units))
        for item in admission.rate_reservations
    )
    return stored_windows == incoming_windows


def _replay_conflict_denial(admission: LimitAdmission) -> LimitDeniedError:
    """Build the typed denial for a mismatched replay of one attempt ID."""

    return LimitDeniedError(
        ProviderError(
            provider=admission.provider,
            code=LOCAL_RATE_DENIAL_CODE,
            message="a reservation replay cannot grant dispatchable capacity",
            retryable=False,
            status_code=429,
            details={
                "origin": "local",
                "refusal": "rate",
                "reasons": ["attempt_identity_conflict"],
            },
        ),
        refusal="rate",
        reasons=["attempt_identity_conflict"],
    )


def _optional_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _strict_replay(
    stored: LimitAdmissionRow,
    *,
    provider: str,
    operation: LimitOperation,
    auth_mode: AuthMode,
    spec: StrictAttemptSpec,
    now: datetime,
    admission: LimitAdmission | None = None,
) -> StrictReservation | LimitDeniedError:
    """Return the usable replay outcome of one strict attempt, or the denial."""

    if stored.state != "reserved":
        return _strict_replay_denial(stored, reason="attempt_already_settled")
    if (
        stored.provider != provider
        or stored.operation != operation.value
        or stored.auth_mode != auth_mode.value
    ):
        return _strict_replay_denial(stored, reason="attempt_identity_conflict")
    if (
        stored.project_id != str(spec.project_id)
        or stored.credential_id != str(spec.credential_id)
        or stored.binding_id != str(spec.binding_id)
        or stored.upstream_pool_id != _optional_text(spec.pool_id)
        or stored.request_id != spec.request_id
    ):
        return _strict_replay_denial(stored, reason="attempt_identity_conflict")
    if not _strict_spec_matches(stored.rate_reservations_json, spec):
        return _strict_replay_denial(stored, reason="attempt_spec_conflict")
    if not _strict_native_matches(stored.rate_reservations_json, admission):
        return _strict_replay_denial(stored, reason="attempt_spec_conflict")
    bucket_ids = tuple(window.bucket_id for window in spec.windows)
    return StrictReservation(
        attempt_id=stored.attempt_id,
        bucket_ids=bucket_ids,
        pool_id=spec.pool_id if stored.upstream_pool_id is None else UUID(stored.upstream_pool_id),
        created_at=_instant(stored.created_at) or now,
        state=stored.state,
        idempotent=True,
    )


def _native_payload(admission: LimitAdmission) -> dict[str, Any]:
    """Return the native obligation summary stored on a unified attempt row."""

    return {
        "pool_id": admission.pool_id,
        "reserved_crd": _text(admission.reserved_crd) or "0",
        "reserved_native": _text(admission.reserved_native),
        "rate_reservations": _dump(list(admission.rate_reservations)),
        "actor_type": (admission.actor_type.value if admission.actor_type is not None else None),
        "actor_id": None if admission.actor_id is None else str(admission.actor_id),
    }


def _strict_native_matches(stored_json: str | None, admission: LimitAdmission | None) -> bool:
    """Return whether a replay's native obligation equals the stored one.

    A strict-only row carries no native obligation; a unified row must be
    replayed only with the same native reservation, so a replay can never skip
    a funds or native rate check it did not originally perform.
    """

    payload = _strict_spec_payload_of(stored_json)
    if payload is None:
        return False
    native = payload.get("native")
    if admission is None:
        return native is None
    if not isinstance(native, dict):
        return False
    stored_reservations = _load_reservations(type_cast(str | None, native.get("rate_reservations")))
    stored_windows = frozenset(
        (item.bucket_id, item.window.value, _text(item.units)) for item in stored_reservations
    )
    incoming_windows = frozenset(
        (item.bucket_id, item.window.value, _text(item.units))
        for item in admission.rate_reservations
    )
    return (
        native.get("pool_id") == admission.pool_id
        and (_decimal(type_cast(str | None, native.get("reserved_crd"))) or Decimal("0"))
        == admission.reserved_crd
        and _decimal(type_cast(str | None, native.get("reserved_native")))
        == admission.reserved_native
        and native.get("actor_type")
        == (admission.actor_type.value if admission.actor_type is not None else None)
        and native.get("actor_id")
        == (None if admission.actor_id is None else str(admission.actor_id))
        and stored_windows == incoming_windows
    )


def _strict_replay_denial(stored: LimitAdmissionRow | None, *, reason: str) -> LimitDeniedError:
    """Build the typed denial for an unusable replay of one attempt ID."""

    label = (
        f"pool:{stored.upstream_pool_id}"
        if stored is not None and stored.upstream_pool_id
        else f"project:{stored.project_id}"
        if stored is not None
        else "attempt"
    )
    error: LimitDeniedError = LimitDeniedError(
        ProviderError(
            provider=label,
            code=LOCAL_RATE_DENIAL_CODE,
            message="a reservation replay cannot grant dispatchable capacity",
            retryable=False,
            status_code=429,
            details={"origin": "local", "refusal": "rate", "reasons": [reason]},
        ),
        refusal="rate",
        reasons=[reason],
    )
    return error


def _strict_admission(
    *,
    attempt_id: str,
    provider: str,
    operation: LimitOperation,
    auth_mode: AuthMode,
    spec: StrictAttemptSpec,
    created_at: datetime,
) -> LimitAdmission:
    """Build the strict admission contract row of one attempt.

    The strict reservation holds no native funds and no credit units: its
    debit is the window units written in the same transaction, and the
    ``strict`` admission row exists so attempt idempotency and in-flight
    concurrency have one durable record.
    """

    return LimitAdmission(
        attempt_id=attempt_id,
        provider=provider,
        operation=operation,
        auth_mode=auth_mode,
        pool_id=None,
        reserved_crd=Decimal("0"),
        reserved_native=None,
        state="reserved",
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=max(1, spec.lease_seconds)),
        rate_reservations=[],
        local_only=False,
        project_id=spec.project_id,
        credential_id=spec.credential_id,
        binding_id=spec.binding_id,
        upstream_pool_id=spec.pool_id,
        request_id=spec.request_id,
        actor_type=spec.actor_type,
        actor_id=spec.actor_id,
    )


async def _strict_capacity_check(
    session: AsyncSession,
    spec: StrictAttemptSpec,
    *,
    operation: LimitOperation,
    created: datetime,
    check_concurrency: bool = True,
) -> None:
    """Recheck every strict window and concurrency cap inside the caller's transaction.

    Each declared window counts its trailing window over attempts stamped
    from ``created - window`` onwards, including committed future rows, so a
    sibling reservation a less-lucky process committed earlier is never
    under-counted and the check cannot interleave with another process's
    reservation. The pool cap counts every still-``reserved`` attempt of the
    same pool and the project cap counts this project's; only settlement or
    an explicit release frees a slot, because an expired-but-unsettled row
    cannot prove the upstream call never happened.
    """

    units = spec.units_per_attempt
    for window in spec.windows:
        limit = Decimal(window.limit_units)
        used = await _rate_used_in_window(
            session,
            window.bucket_id,
            window_seconds=window.window_seconds,
            now=created,
        )
        if used + units > limit:
            raise local_rate_denial(
                provider=_strict_provider_label(spec),
                operation=operation,
                reasons=[window.bucket_id],
                retry_after_seconds=await _window_retry_after_seconds(
                    session,
                    window.bucket_id,
                    window_seconds=window.window_seconds,
                    now=created,
                    over=used + units - limit,
                ),
            )
    if not check_concurrency:
        return
    if spec.pool_max_concurrency is not None and spec.pool_id is not None:
        open_pool = await _open_reserved_count(session, spec.pool_id, project_id=None)
        if open_pool + 1 > spec.pool_max_concurrency:
            raise _strict_concurrency_denial(spec, "pool_concurrent_cap")
    if spec.project_max_concurrency is not None:
        open_project = await _open_reserved_count(session, spec.pool_id, project_id=spec.project_id)
        if open_project + 1 > spec.project_max_concurrency:
            raise _strict_concurrency_denial(spec, "project_concurrent_cap")


def _retime_admission(admission: LimitAdmission, created: datetime) -> LimitAdmission:
    """Preserve a reservation's duration when serialization moves its start."""
    return admission.model_copy(
        update={
            "created_at": created,
            "expires_at": created + (admission.expires_at - admission.created_at),
        }
    )


def _strict_reservation_time(passed: datetime | None, now: datetime) -> datetime:
    """Return the authoritative reservation instant of one strict attempt.

    The post-lock clock is authoritative, so the commit order is the time
    order; a caller-supplied stamp only guards against rollback and can never
    pull the stamp behind the wall clock.
    """

    return passed if passed is not None and passed > now else now


def _strict_provider_label(spec: StrictAttemptSpec) -> str:
    """Return the denial-facing provider label of one strict attempt."""

    return f"pool:{spec.pool_id}" if spec.pool_id is not None else f"project:{spec.project_id}"


def _strict_concurrency_denial(spec: StrictAttemptSpec, bucket: str) -> LimitDeniedError:
    return LimitDeniedError(
        ProviderError(
            provider=_strict_provider_label(spec),
            code=LOCAL_RATE_DENIAL_CODE,
            message="local concurrency cap is full; vendor call skipped",
            retryable=True,
            status_code=429,
            details={
                "origin": "local",
                "refusal": "rate",
                "reasons": [bucket],
            },
        ),
        refusal="rate",
        reasons=[bucket],
    )


async def _open_reserved_count(
    session: AsyncSession, pool_id: UUID | None, *, project_id: UUID | None
) -> int:
    """Count the still-``reserved`` strict reservations of one pool (or project) scope.

    Only strict reservations consume strict concurrency: the sibling rails
    admission of the same attempt is separate funds/rate capacity, so counting
    it here would deny the first attempt with its own row. Strict rows carry
    the ``{"kind": "strict", ...}`` payload; rails rows carry a reservation
    list and never match. Expiry does not free a slot: an unsettled
    reservation cannot prove the upstream call never happened, so only a
    settlement or an explicit release ends its hold (the execution authority's
    recovery reclaims uncertain attempts).
    """

    if pool_id is None and project_id is None:
        return 0
    statement = (
        select(func.count())
        .select_from(LimitAdmissionRow)
        .where(
            (
                (LimitAdmissionRow.state == "reserved")
                & (
                    func.coalesce(
                        func.json_extract(
                            LimitAdmissionRow.rate_reservations_json, "$.dispatch_completed"
                        ),
                        0,
                    )
                    == 0
                )
            )
            | (
                (LimitAdmissionRow.state == "finalized")
                & (
                    func.json_extract(LimitAdmissionRow.rate_reservations_json, "$.outcome")
                    == "uncertain"
                )
            ),
            func.json_extract(LimitAdmissionRow.rate_reservations_json, "$.kind") == "strict",
        )
    )
    if project_id is None:
        statement = statement.where(LimitAdmissionRow.upstream_pool_id == str(pool_id))
    else:
        statement = statement.where(LimitAdmissionRow.project_id == str(project_id))
        if pool_id is not None:
            statement = statement.where(LimitAdmissionRow.upstream_pool_id == str(pool_id))
    total = (await session.execute(statement)).scalar_one()
    return int(total or 0)


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


async def _budget_rows(
    session: AsyncSession, provider: str, auth_mode: AuthMode, *, now: datetime
) -> tuple[Sequence[CRDGrantRow], BudgetPeriod]:
    """Materialize only the active calendar window, preserving earlier holds and spend."""
    config = await session.get(ProviderBudgetRow, (provider, auth_mode.value))
    if config is None:
        return [], "month"
    period = type_cast(BudgetPeriod, config.period)
    start, end = window_bounds(now, period)
    statement = (
        select(CRDGrantRow)
        .where(
            CRDGrantRow.provider == provider,
            CRDGrantRow.auth_mode == auth_mode.value,
            CRDGrantRow.period_start == start,
        )
        .execution_options(populate_existing=True)
    )
    rows = (await session.scalars(statement)).all()
    amounts = {"search": config.search_crd_text, "fetch": config.fetch_crd_text}
    if len(rows) == 2 and all(
        row.version == config.version
        and row.period_end == end
        and row.granted_crd_text == amounts[row.operation]
        for row in rows
    ):
        return rows, period
    for operation, granted in (
        ("search", config.search_crd_text),
        ("fetch", config.fetch_crd_text),
    ):
        await session.execute(
            sqlite_insert(CRDGrantRow)
            .values(
                provider=provider,
                operation=operation,
                auth_mode=auth_mode.value,
                period_start=start,
                period_end=end,
                granted_crd_text=granted,
                consumed_crd_text="0",
                reserved_crd_text="0",
                version=config.version,
            )
            .on_conflict_do_update(
                index_elements=["provider", "operation", "auth_mode", "period_start"],
                set_=dict(period_end=end, granted_crd_text=granted, version=config.version),
            )
        )
    rows = (await session.scalars(statement)).all()
    return rows, period


async def _budget_admission_values(
    session: AsyncSession, admission: LimitAdmission
) -> dict[str, Any]:
    """Persist the actual budget window with the hold, as pool reservations do."""
    values = _admission_values(admission)
    rows, _ = await _budget_rows(
        session, admission.provider, admission.auth_mode, now=admission.created_at
    )
    for row in rows:
        if row.operation != admission.operation.value:
            continue
        available = (
            Decimal(row.granted_crd_text)
            - Decimal(row.consumed_crd_text)
            - Decimal(row.reserved_crd_text)
        )
        if admission.reserved_crd > available:
            raise local_funds_denial(
                provider=admission.provider,
                operation=admission.operation,
                reasons=["budget_exhausted"],
            )
    values["grant_window_start"] = rows[0].period_start if rows else None
    return values


async def _adjust_grant(
    session: AsyncSession,
    provider: str,
    auth_mode: AuthMode,
    operation: LimitOperation,
    *,
    window_start: str | None,
    reserved_delta: Decimal | None = None,
    consumed_delta: Decimal | None = None,
) -> None:
    """Settle a hold in its persisted original window, never the current window."""

    if reserved_delta in (None, Decimal("0")) and consumed_delta in (None, Decimal("0")):
        return
    if window_start is None:
        return
    row = await session.get(CRDGrantRow, (provider, operation.value, auth_mode.value, window_start))
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


def _attribution_values(admission: LimitAdmission) -> dict[str, Any]:
    """Return the consumer-attribution column values of one admission.

    ``None`` for a consumer key stays ``NULL`` in storage, so the capacity
    record survives with attribution missing rather than a wrong project
    claim. The verified actor is required (revision 0002): an admission
    without one is refused before any row is written.
    """

    _require_actor(admission.actor_type, admission.actor_id)

    values: dict[str, Any] = {
        "project_id": None,
        "credential_id": None,
        "binding_id": None,
        "upstream_pool_id": None,
        "request_id": None,
        "actor_type": None,
        "actor_id": None,
    }
    if admission.project_id is not None:
        values["project_id"] = str(admission.project_id)
    if admission.credential_id is not None:
        values["credential_id"] = str(admission.credential_id)
    if admission.binding_id is not None:
        values["binding_id"] = str(admission.binding_id)
    if admission.upstream_pool_id is not None:
        values["upstream_pool_id"] = str(admission.upstream_pool_id)
    if admission.request_id is not None:
        values["request_id"] = admission.request_id
    if admission.actor_type is not None:
        values["actor_type"] = admission.actor_type.value
    if admission.actor_id is not None:
        values["actor_id"] = str(admission.actor_id)
    return values


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
        **_attribution_values(admission),
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
        project_id=_optional_uuid(row.project_id),
        credential_id=_optional_uuid(row.credential_id),
        binding_id=_optional_uuid(row.binding_id),
        upstream_pool_id=_optional_uuid(row.upstream_pool_id),
        request_id=row.request_id,
        actor_type=ActorType(row.actor_type) if row.actor_type else None,
        actor_id=_optional_uuid(row.actor_id),
    )


def _optional_uuid(value: str | None) -> UUID | None:
    """Decode a stored UUID column, ignoring malformed historical values."""

    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _insert_attempt_units(
    session: AsyncSession,
    *,
    attempt_id: str,
    bucket_id: str,
    provider: str,
    auth_mode: AuthMode,
    operation: LimitOperation | None,
    window_text: str,
    window_seconds: int,
    units: Decimal,
    attempted_at: datetime,
    attribution: dict[str, Any] | None = None,
) -> None:
    """Insert one consumed rate unit; a duplicate attempt/bucket pair is a no-op."""

    values: dict[str, Any] = {
        "attempt_id": attempt_id,
        "bucket_id": bucket_id,
        "provider": provider,
        "auth_mode": auth_mode.value,
        "operation": operation.value if operation is not None else None,
        "window": window_text,
        "unit": RateUnit.REQUESTS.value,
        "units_text": _text(units) or "0",
        "attempted_at": _timestamp(attempted_at),
        "expires_at": _timestamp(attempted_at + timedelta(seconds=window_seconds)),
    }
    if attribution is not None:
        values.update(attribution)
    await session.execute(
        sqlite_insert(RateAttemptRow)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["attempt_id", "bucket_id"])
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
    attribution: dict[str, Any] | None = None,
) -> None:
    await _insert_attempt_units(
        session,
        attempt_id=attempt_id,
        bucket_id=bucket_id,
        provider=provider,
        auth_mode=auth_mode,
        operation=operation,
        window_text=window.value,
        window_seconds=_WINDOW_SECONDS[window],
        units=units,
        attempted_at=attempted_at,
        attribution=attribution,
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


def _is_tavily_credits_pool(snapshot: NativeUsageSnapshot) -> bool:
    """Return whether one snapshot describes the Tavily keyed Credits pool."""

    return (
        snapshot.provider == _TAVILY_PROVIDER and snapshot.pool_id == _TAVILY_KEYED_CREDITS_POOL_ID
    )


def _tavily_observation_rejected(row: NativePoolRow | None, snapshot: NativeUsageSnapshot) -> bool:
    """Return whether a vendor_api Tavily observation must not write.

    An observation stamped at or before the stored terminal observation stays
    out. A later observation inside the same calendar month with the same
    credential generation is late vendor data while the stored reset instant
    is still ahead, so there only a numeric zero can refresh the terminal
    state. A later month, a passed reset instant, or a newer credential
    generation supersedes the terminal row normally.
    """

    if row is None or not _is_tavily_credits_pool(snapshot):
        return False
    if row.source != _TAVILY_VENDOR_402_SOURCE or snapshot.source != _TAVILY_VENDOR_API_SOURCE:
        return False
    row_observed = _instant(row.observed_at)
    if row_observed is None:
        return False
    if snapshot.observed_at <= row_observed:
        return True
    reset_at = _instant(row.reset_at)
    if reset_at is not None and reset_at <= snapshot.observed_at:
        return False
    if snapshot.credential_generation > row.credential_generation:
        return False
    row_month = row_observed.astimezone(UTC)
    incoming_month = snapshot.observed_at.astimezone(UTC)
    if (row_month.year, row_month.month) != (incoming_month.year, incoming_month.month):
        return False
    return snapshot.remaining is not None and snapshot.remaining > 0


async def _native_debits_after(
    session: AsyncSession, pool_id: str, observed_at: datetime
) -> Decimal:
    """Sum the native debits one pool recorded after an instant.

    Only the debit events of finished local calls carry their exact native
    amount, and those amounts are already counted while a usage request runs,
    so the caller subtracts them from a numeric vendor balance read. A value
    that carries no readable amount contributes zero.
    """

    statement = select(LimitEventRow.native_debit_text).where(
        LimitEventRow.pool_id == pool_id,
        LimitEventRow.observed_at > _timestamp(observed_at),
        LimitEventRow.reason.in_(
            (_SUCCESS_REASON, _FAILURE_REASON, "local_uncertain", "local_unknown_charge")
        ),
    )
    rows = (await session.scalars(statement)).all()
    return sum((_decimal(text) or Decimal("0") for text in rows), Decimal("0"))


async def _rate_used_in_window(
    session: AsyncSession,
    bucket_id: str,
    *,
    window_seconds: int,
    now: datetime,
    since: datetime | None = None,
) -> Decimal:
    """Count local rate units still inside one window in one session.

    Count committed future rows too: clock rollback must conservatively
    extend a hold rather than hide a debit. Rows age out when the wall clock
    passes their timestamp plus the window.
    """

    start = since or (now - timedelta(seconds=window_seconds))
    statement = select(func.coalesce(func.sum(cast(RateAttemptRow.units_text, _QUANTUM)), 0)).where(
        RateAttemptRow.bucket_id == bucket_id,
        RateAttemptRow.attempted_at >= _timestamp(start),
    )
    total = (await session.execute(statement)).scalar_one()
    return Decimal(str(total))


async def _window_retry_after_seconds(
    session: AsyncSession,
    bucket_id: str,
    *,
    window_seconds: int,
    now: datetime,
    over: Decimal,
) -> int:
    """Return the seconds until one window can admit the next units.

    Attempts leave the window oldest first, so their units come back oldest
    first. The answer is the wait until enough oldest attempts expire, with
    one full window as the answer when the empty window still cannot admit
    the reserved units. Future committed rows count in the same way as the
    strict capacity check.
    """

    start = now - timedelta(seconds=window_seconds)
    statement = (
        select(RateAttemptRow.attempted_at, cast(RateAttemptRow.units_text, _QUANTUM))
        .where(
            RateAttemptRow.bucket_id == bucket_id,
            RateAttemptRow.attempted_at >= _timestamp(start),
        )
        .order_by(RateAttemptRow.attempted_at)
    )
    sufficient: tuple[datetime, Decimal] | None = None
    freed = Decimal("0")
    for row in (await session.execute(statement)).all():
        attempted = _instant(row[0])
        if attempted is None:
            continue
        unit = Decimal(str(row[1]))
        freed += unit
        if freed >= over:
            sufficient = (attempted, unit)
            break
    if sufficient is None or freed < over:
        return window_seconds
    ready_at = sufficient[0] + timedelta(seconds=window_seconds)
    return max(1, math.ceil((ready_at - now).total_seconds()))


async def _native_rate_denial(
    session: AsyncSession, admission: LimitAdmission, record: ProviderLimitRecord
) -> LimitDeniedError | None:
    """Recheck all reserved catalog windows in the serialized transaction.

    Counts use the exact scoped bucket, while the catalog identity excludes
    its credential/pool suffix. Vendor observations replace the prior balance;
    only subsequent local attempts extend them, as in rate preflight.
    """

    if record.rate is None:
        return None
    for reservation in admission.rate_reservations:
        window = next(
            (
                item
                for item in record.rate.windows
                if item.bucket_id == reservation.bucket_id.split("#", 1)[0]
                and item.window is reservation.window
                and item.kind == "rate"
            ),
            None,
        )
        if window is None:
            continue
        observation = await session.scalar(
            select(RateWindowObservationRow)
            .where(
                RateWindowObservationRow.bucket_id == reservation.bucket_id,
                RateWindowObservationRow.provider == admission.provider,
                RateWindowObservationRow.auth_mode == admission.auth_mode.value,
                RateWindowObservationRow.window == reservation.window.value,
            )
            .order_by(RateWindowObservationRow.observed_at.desc())
            .limit(1)
        )
        limit = window.limit
        remaining = None
        since = None
        reset_at = None
        if observation is not None:
            observed_limit = _decimal(observation.limit_text)
            if observed_limit is not None:
                limit = observed_limit
            remaining = _decimal(observation.remaining_text)
            since = _instant(observation.observed_at)
            reset_at = _instant(observation.reset_at)
        available = limit if remaining is None else remaining
        if available is None:
            continue
        seconds = _WINDOW_SECONDS[reservation.window]
        used = await _rate_used_in_window(
            session,
            reservation.bucket_id,
            window_seconds=seconds,
            now=admission.created_at,
            since=since,
        )
        if available - used >= reservation.units:
            continue
        wait = await _window_retry_after_seconds(
            session,
            reservation.bucket_id,
            window_seconds=seconds,
            now=admission.created_at,
            over=used + reservation.units - available,
        )
        if reset_at is not None and reset_at > admission.created_at:
            wait = max(1, math.ceil((reset_at - admission.created_at).total_seconds()))
        return local_rate_denial(
            provider=admission.provider,
            operation=admission.operation,
            reasons=[reservation.bucket_id],
            retry_after_seconds=wait,
        )
    return None


async def _native_funds_denial(session: AsyncSession, admission: LimitAdmission) -> bool:
    """Recheck known native funds against the active native reservations.

    When the admission's pool holds a known remaining value, the still-live
    native reservations of the pool's other reserved admissions plus this
    admission's own reserved amount cannot exceed it. An unknown stored
    balance stays unenforced, because an absent value is not zero.
    """

    pool_id = admission.pool_id
    if pool_id is None:
        return False
    pool_row = await session.get(NativePoolRow, pool_id)
    if pool_row is None:
        return False
    stored = _decimal(pool_row.remaining_text)
    if stored is None:
        return False
    rows = (
        await session.scalars(
            select(LimitAdmissionRow).where(
                LimitAdmissionRow.pool_id == pool_id,
                LimitAdmissionRow.state == "reserved",
                LimitAdmissionRow.expires_at > _timestamp(admission.created_at),
                LimitAdmissionRow.attempt_id != admission.attempt_id,
            )
        )
    ).all()
    reserved = sum(
        (_decimal(row.reserved_native_text) or Decimal("0") for row in rows),
        Decimal("0"),
    )
    own = admission.reserved_native if admission.reserved_native is not None else Decimal("0")
    return stored - reserved - own < 0
