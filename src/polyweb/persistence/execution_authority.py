"""Execution-authority lease and dispatch recovery persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    execution_authority_leases(authority_key, holder_id, fencing_token, state,
        acquired_at, renewed_at, expires_at, recovery_until, version)
    execution_dispatches(attempt_id, request_id, project_id, pool_id,
        credential_id, binding_id, operation, actor_type, actor_id,
        authority_key, fencing_token, state, dispatched_at, resolved_at)

One lease row per authority decides which process may dispatch provider
attempts. ``fencing_token`` increases on every acquisition; a dispatch is
recorded only under the current token of a live, active lease, in one
``INSERT ... SELECT`` statement so the fence check and the write cannot be
separated. After a takeover, still-dispatched rows of an older token become
``uncertain`` and keep holding pool concurrency until resolved, and the new
holder starts in ``recovering`` until ``recovery_until``. A project with
dispatch records cannot be deleted (``ON DELETE RESTRICT``): uncertain
concurrency is never dropped, and projects are archived rather than deleted.

Queue contents, scheduler deficits, and wait timers are kept in memory by
design and are not persisted here. The caller owns the transaction; methods
flush and never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    case,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ActorType
from polyweb.models.schema_enums import AuthorityState, DispatchState
from polyweb.persistence.storage import TELEMETRY_ACTOR_CHECK, Base
from polyweb.persistence.timestamps import (
    parse_optional_timestamp,
    parse_timestamp,
    require_aware,
    stored_timestamp,
)

_OPEN_STATES = (DispatchState.DISPATCHED.value, DispatchState.UNCERTAIN.value)
_FINAL_STATES = frozenset({DispatchState.COMPLETED, DispatchState.FAILED})


class ExecutionAuthorityLeaseRow(Base):
    """The single lease of one execution authority."""

    __tablename__ = "execution_authority_leases"
    __table_args__ = (
        CheckConstraint(
            "state IN ('vacant', 'active', 'recovering')",
            name="execution_authority_leases_state_allowed",
        ),
        CheckConstraint(
            "(state = 'vacant' AND holder_id IS NULL AND expires_at IS NULL) "
            "OR (state <> 'vacant' AND holder_id IS NOT NULL AND expires_at IS NOT NULL)",
            name="execution_authority_leases_holder_consistent",
        ),
        CheckConstraint(
            "state <> 'recovering' OR recovery_until IS NOT NULL",
            name="execution_authority_leases_recovery_consistent",
        ),
        CheckConstraint(
            "fencing_token >= 0", name="execution_authority_leases_fencing_token_nonnegative"
        ),
        CheckConstraint("version >= 1", name="execution_authority_leases_version_positive"),
    )

    authority_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="vacant")
    acquired_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    renewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_until: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class ExecutionDispatchRow(Base):
    """Recovery record of one dispatched provider attempt."""

    __tablename__ = "execution_dispatches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="execution_dispatches_project_id_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="execution_dispatches_pool_id_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="execution_dispatches_credential_id_fkey",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["binding_id"],
            ["project_provider_bindings.id"],
            name="execution_dispatches_binding_id_fkey",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["authority_key"],
            ["execution_authority_leases.authority_key"],
            name="execution_dispatches_authority_key_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "operation IN ('search', 'fetch')", name="execution_dispatches_operation_allowed"
        ),
        CheckConstraint(TELEMETRY_ACTOR_CHECK, name="execution_dispatches_actor_type_allowed"),
        CheckConstraint(
            "state IN ('dispatched', 'completed', 'failed', 'uncertain')",
            name="execution_dispatches_state_allowed",
        ),
        CheckConstraint(
            "(state IN ('dispatched', 'uncertain') AND resolved_at IS NULL) "
            "OR (state IN ('completed', 'failed') AND resolved_at IS NOT NULL)",
            name="execution_dispatches_resolution_consistent",
        ),
        CheckConstraint("fencing_token >= 1", name="execution_dispatches_fencing_token_positive"),
        Index("execution_dispatches_pool_state", "pool_id", "state"),
        Index("execution_dispatches_project_dispatched", "project_id", "dispatched_at"),
        Index("execution_dispatches_authority_state", "authority_key", "state", "fencing_token"),
    )

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    pool_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    credential_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    binding_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(CHAR(36), nullable=False)
    authority_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="dispatched")
    dispatched_at: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(Text, nullable=True)


@dataclass(frozen=True)
class StoredLease:
    """One stored execution-authority lease."""

    authority_key: str
    holder_id: str | None
    fencing_token: int
    state: AuthorityState
    acquired_at: datetime | None
    renewed_at: datetime | None
    expires_at: datetime | None
    recovery_until: datetime | None
    version: int
    #: Dispatch attempts this acquisition fenced into uncertainty.
    uncertain_attempt_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredDispatch:
    """One stored dispatch recovery record."""

    attempt_id: str
    request_id: str
    project_id: UUID
    pool_id: UUID
    credential_id: UUID | None
    binding_id: UUID | None
    operation: CredentialOperation
    actor_type: ActorType
    actor_id: UUID
    authority_key: str
    fencing_token: int
    state: DispatchState
    dispatched_at: datetime
    resolved_at: datetime | None


def _stored_lease(
    row: ExecutionAuthorityLeaseRow, uncertain_attempt_ids: tuple[str, ...] = ()
) -> StoredLease:
    return StoredLease(
        authority_key=row.authority_key,
        holder_id=row.holder_id,
        fencing_token=row.fencing_token,
        state=AuthorityState(row.state),
        acquired_at=parse_optional_timestamp(row.acquired_at),
        renewed_at=parse_optional_timestamp(row.renewed_at),
        expires_at=parse_optional_timestamp(row.expires_at),
        recovery_until=parse_optional_timestamp(row.recovery_until),
        version=row.version,
        uncertain_attempt_ids=uncertain_attempt_ids,
    )


def _stored_dispatch(row: ExecutionDispatchRow) -> StoredDispatch:
    return StoredDispatch(
        attempt_id=row.attempt_id,
        request_id=row.request_id,
        project_id=UUID(row.project_id),
        pool_id=UUID(row.pool_id),
        credential_id=UUID(row.credential_id) if row.credential_id else None,
        binding_id=UUID(row.binding_id) if row.binding_id else None,
        operation=CredentialOperation(row.operation),
        actor_type=ActorType(row.actor_type),
        actor_id=UUID(row.actor_id),
        authority_key=row.authority_key,
        fencing_token=row.fencing_token,
        state=DispatchState(row.state),
        dispatched_at=parse_timestamp(row.dispatched_at),
        resolved_at=parse_optional_timestamp(row.resolved_at),
    )


def _optional_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


class ExecutionAuthorityRepository:
    """Fenced lease transitions and dispatch recovery records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire(
        self,
        *,
        authority_key: str,
        holder_id: str,
        now: datetime,
        ttl: timedelta,
        recovery: timedelta,
        pool_id: UUID | None = None,
    ) -> StoredLease | None:
        """Take the authority when it is absent, vacant, expired, or already ours.

        The fencing token advances by one. Every still-dispatched row of an
        older token becomes ``uncertain``; when any did, the lease starts in
        ``recovering`` until ``now + recovery``. ``pool_id`` lets the caller
        identify open dispatch rows by the shared pool they were recorded for:
        the quiet ledger identity may differ from the pool-scoped fence key, so
        recovery follows the pool row rather than guessing a key namespace.
        Returns ``None`` while another holder's lease is live. Re-acquiring by
        the same holder starts a new incarnation and fences the old one: its
        open dispatches become ``uncertain`` and its token can no longer record
        dispatches.
        """

        stamp = stored_timestamp(now)
        await self._session.execute(
            sqlite_insert(ExecutionAuthorityLeaseRow)
            .values(
                authority_key=authority_key,
                fencing_token=0,
                state=AuthorityState.VACANT.value,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=[ExecutionAuthorityLeaseRow.authority_key])
        )
        lease = ExecutionAuthorityLeaseRow
        # A repeated acquisition during the same recovering incarnation keeps
        # that incarnation and its persisted recovery deadline. Resetting the
        # lease to ACTIVE here would let an immediate second request bypass the
        # conservative pause while the predecessor's dispatches are uncertain.
        existing = await self._session.scalar(
            select(lease)
            .where(lease.authority_key == authority_key)
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            recovery_until = parse_optional_timestamp(existing.recovery_until)
            expires_at = parse_optional_timestamp(existing.expires_at)
            if (
                existing.state == AuthorityState.RECOVERING.value
                and existing.holder_id == holder_id
                and recovery_until is not None
                and recovery_until > now
                and expires_at is not None
                and expires_at > now
            ):
                kept = await self._session.scalar(
                    update(lease)
                    .where(
                        lease.authority_key == authority_key,
                        lease.holder_id == holder_id,
                        lease.fencing_token == existing.fencing_token,
                    )
                    .values(
                        renewed_at=stamp,
                        expires_at=stored_timestamp(now + ttl),
                        version=lease.version + 1,
                    )
                    .returning(lease)
                    .execution_options(populate_existing=True)
                )
                kept_uncertain = (
                    await self._list_uncertain_attempt_ids(pool_id=pool_id)
                    if pool_id is not None
                    else ()
                )
                await self._session.flush()
                return None if kept is None else _stored_lease(kept, kept_uncertain)
        row = await self._session.scalar(
            update(lease)
            .where(
                lease.authority_key == authority_key,
                or_(
                    lease.state == AuthorityState.VACANT.value,
                    lease.expires_at <= stamp,
                    lease.holder_id == holder_id,
                ),
            )
            .values(
                holder_id=holder_id,
                fencing_token=lease.fencing_token + 1,
                state=AuthorityState.ACTIVE.value,
                acquired_at=stamp,
                renewed_at=stamp,
                expires_at=stored_timestamp(now + ttl),
                recovery_until=None,
                version=lease.version + 1,
            )
            .returning(lease)
            .execution_options(populate_existing=True)
        )
        if row is None:
            await self._session.flush()
            return None
        uncertain_ids: tuple[str, ...] = ()
        if pool_id is not None:
            uncertain_ids = await self._mark_pool_uncertain(
                pool_id=pool_id, token=row.fencing_token
            )
        uncertain = bool(uncertain_ids) or await self._mark_uncertain(
            authority_key=authority_key, token=row.fencing_token
        )
        if pool_id is not None:
            # Include rows an earlier takeover already fenced: their funds
            # settlement is idempotent, so a crash between the fence commit
            # and the debit retention cannot leave a reserved admission behind
            # forever.
            existing_uncertain = await self._list_uncertain_attempt_ids(pool_id=pool_id)
            uncertain_ids = tuple(dict.fromkeys((*uncertain_ids, *existing_uncertain)))
        if uncertain:
            row = await self._session.scalar(
                update(lease)
                .where(lease.authority_key == authority_key)
                .values(
                    state=AuthorityState.RECOVERING.value,
                    recovery_until=stored_timestamp(now + recovery),
                )
                .returning(lease)
                .execution_options(populate_existing=True)
            )
        await self._session.flush()
        return None if row is None else _stored_lease(row, uncertain_ids)

    async def renew(
        self,
        *,
        authority_key: str,
        holder_id: str,
        fencing_token: int,
        now: datetime,
        ttl: timedelta,
    ) -> StoredLease | None:
        """Extend a live lease of this holder and token; finish recovery when due."""

        stamp = stored_timestamp(now)
        lease = ExecutionAuthorityLeaseRow
        recovered = (lease.state == AuthorityState.RECOVERING.value) & (
            lease.recovery_until <= stamp
        )
        row = await self._session.scalar(
            update(lease)
            .where(
                lease.authority_key == authority_key,
                lease.holder_id == holder_id,
                lease.fencing_token == fencing_token,
                lease.state != AuthorityState.VACANT.value,
                lease.expires_at > stamp,
            )
            .values(
                renewed_at=stamp,
                expires_at=stored_timestamp(now + ttl),
                state=case((recovered, AuthorityState.ACTIVE.value), else_=lease.state),
                recovery_until=case((recovered, None), else_=lease.recovery_until),
                version=lease.version + 1,
            )
            .returning(lease)
            .execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored_lease(row)

    async def release(
        self, *, authority_key: str, holder_id: str, fencing_token: int, now: datetime
    ) -> bool:
        """Vacate the lease of this holder and token; dispatch rows stay unresolved."""

        require_aware(now)
        lease = ExecutionAuthorityLeaseRow
        result = await self._session.execute(
            update(lease)
            .where(
                lease.authority_key == authority_key,
                lease.holder_id == holder_id,
                lease.fencing_token == fencing_token,
                lease.state != AuthorityState.VACANT.value,
            )
            .values(
                state=AuthorityState.VACANT.value,
                holder_id=None,
                expires_at=None,
                recovery_until=None,
                version=lease.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def current(self, *, authority_key: str) -> StoredLease | None:
        """Return the lease row of one authority, or ``None`` before first use."""

        row = await self._session.scalar(
            select(ExecutionAuthorityLeaseRow)
            .where(ExecutionAuthorityLeaseRow.authority_key == authority_key)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _stored_lease(row)

    async def _ensure_row(self, *, authority_key: str) -> None:
        """Create an empty lease row for a ledger identity if it is absent."""

        await self._session.execute(
            sqlite_insert(ExecutionAuthorityLeaseRow)
            .values(
                authority_key=authority_key,
                fencing_token=0,
                state=AuthorityState.VACANT.value,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=[ExecutionAuthorityLeaseRow.authority_key])
        )
        await self._session.flush()

    async def _mark_pool_uncertain(self, *, pool_id: UUID, token: int) -> tuple[str, ...]:
        """Mark this pool's still-dispatched rows of older tokens uncertain.

        Returns the attempt ids this takeover fenced, so recovery can retain
        each one's native debit exactly once in the same takeover boundary.
        """

        rows = await self._session.scalars(
            select(ExecutionDispatchRow.attempt_id).where(
                ExecutionDispatchRow.pool_id == str(pool_id),
                ExecutionDispatchRow.state == DispatchState.DISPATCHED.value,
                ExecutionDispatchRow.fencing_token < token,
            )
        )
        attempt_ids = tuple(rows)
        if not attempt_ids:
            return ()
        await self._session.execute(
            update(ExecutionDispatchRow)
            .where(
                ExecutionDispatchRow.pool_id == str(pool_id),
                ExecutionDispatchRow.state == DispatchState.DISPATCHED.value,
                ExecutionDispatchRow.fencing_token < token,
            )
            .values(state=DispatchState.UNCERTAIN.value)
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return attempt_ids

    async def _list_uncertain_attempt_ids(self, *, pool_id: UUID) -> tuple[str, ...]:
        """Return the attempt ids this pool holds in uncertainty."""

        rows = await self._session.scalars(
            select(ExecutionDispatchRow.attempt_id).where(
                ExecutionDispatchRow.pool_id == str(pool_id),
                ExecutionDispatchRow.state == DispatchState.UNCERTAIN.value,
            )
        )
        return tuple(rows)

    async def record_dispatch(
        self,
        *,
        authority_key: str,
        fencing_token: int,
        attempt_id: str,
        request_id: str,
        project_id: UUID,
        pool_id: UUID,
        operation: CredentialOperation,
        actor_type: ActorType,
        actor_id: UUID,
        credential_id: UUID | None = None,
        binding_id: UUID | None = None,
        now: datetime,
        ledger_key: str | None = None,
    ) -> bool:
        """Record one dispatch only under this token of a live, active lease.

        ``ledger_key`` names a stable ledger identity for the row while the
        fence that authorizes the write stays the pool's own lease key.
        """

        stamp = stored_timestamp(now)
        lease = ExecutionAuthorityLeaseRow
        values: dict[str, Any] = {
            "attempt_id": attempt_id,
            "request_id": request_id,
            "project_id": str(project_id),
            "pool_id": str(pool_id),
            "credential_id": _optional_text(credential_id),
            "binding_id": _optional_text(binding_id),
            "operation": CredentialOperation(operation).value,
            "actor_type": ActorType(actor_type).value,
            "actor_id": str(actor_id),
            "authority_key": ledger_key or authority_key,
            "fencing_token": fencing_token,
            "state": DispatchState.DISPATCHED.value,
            "dispatched_at": stamp,
        }
        fenced = select(*(literal(value).label(name) for name, value in values.items())).where(
            lease.authority_key == authority_key,
            lease.fencing_token == fencing_token,
            lease.state == AuthorityState.ACTIVE.value,
            lease.expires_at > stamp,
        )
        table = cast(Table, ExecutionDispatchRow.__table__)
        result = await self._session.execute(insert(table).from_select(list(values), fenced))
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def resolve_dispatch(
        self,
        *,
        project_id: UUID,
        attempt_id: str,
        state: DispatchState,
        now: datetime,
    ) -> bool:
        """Resolve one open dispatch of this project, or mark it uncertain."""

        target = DispatchState(state)
        if target is DispatchState.DISPATCHED:
            raise ValueError("a dispatch resolves as completed, failed, or uncertain")
        dispatch = ExecutionDispatchRow
        if target in _FINAL_STATES:
            sources: tuple[str, ...] = _OPEN_STATES
            resolved_at: str | None = stored_timestamp(now)
        else:
            require_aware(now)
            sources = (DispatchState.DISPATCHED.value,)
            resolved_at = None
        result = await self._session.execute(
            update(dispatch)
            .where(
                dispatch.attempt_id == attempt_id,
                dispatch.project_id == str(project_id),
                dispatch.state.in_(sources),
            )
            .values(state=target.value, resolved_at=resolved_at)
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def open_dispatch_count(self, *, pool_id: UUID) -> int:
        """Count dispatched and uncertain attempts holding one shared pool's concurrency."""

        count = await self._session.scalar(
            select(func.count())
            .select_from(ExecutionDispatchRow)
            .where(
                ExecutionDispatchRow.pool_id == str(pool_id),
                ExecutionDispatchRow.state.in_(_OPEN_STATES),
            )
        )
        return int(count or 0)

    async def list_uncertain(self, *, project_id: UUID) -> list[StoredDispatch]:
        """List this project's uncertain dispatches, oldest first."""

        rows = await self._session.scalars(
            select(ExecutionDispatchRow)
            .where(
                ExecutionDispatchRow.project_id == str(project_id),
                ExecutionDispatchRow.state == DispatchState.UNCERTAIN.value,
            )
            .order_by(ExecutionDispatchRow.dispatched_at, ExecutionDispatchRow.attempt_id)
            .execution_options(populate_existing=True)
        )
        return [_stored_dispatch(row) for row in rows]

    async def _mark_uncertain(self, *, authority_key: str, token: int) -> bool:
        """Turn still-dispatched rows of older tokens uncertain; report whether any did."""

        result = await self._session.execute(
            update(ExecutionDispatchRow)
            .where(
                ExecutionDispatchRow.authority_key == authority_key,
                ExecutionDispatchRow.state == DispatchState.DISPATCHED.value,
                ExecutionDispatchRow.fencing_token < token,
            )
            .values(state=DispatchState.UNCERTAIN.value)
            .execution_options(synchronize_session=False)
        )
        return bool(getattr(result, "rowcount", 0))


__all__ = [
    "ExecutionAuthorityLeaseRow",
    "ExecutionAuthorityRepository",
    "ExecutionDispatchRow",
    "StoredDispatch",
    "StoredLease",
]
