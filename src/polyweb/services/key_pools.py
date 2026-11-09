"""Validation and conversions shared by vault pool operations."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from importlib import import_module
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationDecision,
    PermissionAction,
    ScopeType,
)
from polyweb.models.users import UserPrincipal
from polyweb.models.vault import (
    KeyPoolCreate,
    KeyPoolRead,
    KeyPoolUpdate,
    OperationLimit,
    OperationRate,
    PoolBudget,
    PoolRate,
    VaultProject,
)
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues, StoredKeyPool
from polyweb.persistence.projects import ProjectRepository, ProjectRow
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.audit_events import record_system_event
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_access import run_control_read, run_control_write
from polyweb.services.control_errors import ResourceConflict, ResourceInvalid, ResourceNotFound
from polyweb.services.pool_materializer import detach_pool_allocations, materialize_pools
from polyweb.services.project_routing import ProjectRoutingService
from polyweb.services.provider_bindings import provider_capability
from polyweb.services.vault_keys import _owned, _require_vault

_MICRODOLLARS = Decimal(1_000_000)
_PERIOD_SECONDS: dict[str, Literal[86400, 604800, 2592000]] = {
    "day": 86400,
    "week": 604800,
    "month": 2592000,
}
_SECONDS_PERIOD: dict[int, Literal["day", "week", "month"]] = {
    86400: "day",
    604800: "week",
    2592000: "month",
}


def validate_operations(
    provider_type: str,
    operations: frozenset[str] | None,
    operation_limits: dict[str, OperationLimit] | None = None,
    *,
    supported: frozenset[CredentialOperation] | None = None,
) -> frozenset[Literal["search", "fetch"]]:
    """Default to provider capability; reject empty and unsupported operations."""

    capability = provider_capability(provider_type) if supported is None else supported
    allowed = frozenset(operation.value for operation in capability)
    requested = allowed if operations is None else operations
    if not requested:
        raise ResourceInvalid("OPERATIONS_REQUIRED", "at least one operation is required")
    if not requested <= allowed:
        raise ResourceInvalid(
            "OPERATION_NOT_SUPPORTED", "the provider does not support an operation"
        )
    if operation_limits is not None and (
        not operation_limits.keys() <= requested
        or any(
            isinstance(limit, bool) or (isinstance(limit, int) and limit < 0)
            for limit in operation_limits.values()
        )
    ):
        raise ResourceInvalid("OPERATION_NOT_SUPPORTED", "operation limits must match the pool")
    return frozenset(CredentialOperation(item).value for item in requested)


def pool_values(
    provider_type: str,
    body: KeyPoolCreate,
    *,
    supported: frozenset[CredentialOperation] | None = None,
) -> KeyPoolValues:
    """Convert a create request to the repository's micro-dollar representation."""

    operations = validate_operations(
        provider_type, body.operations, body.operation_limits, supported=supported
    )
    return KeyPoolValues(
        label=body.label,
        rate_limit=body.rate.limit,
        rate_window_seconds=body.rate.window_seconds,
        budget_limit=int(body.budget.limit * _MICRODOLLARS) if body.budget else None,
        budget_window_seconds=_PERIOD_SECONDS[body.budget.period] if body.budget else None,
        operations=operations,
        operation_limits=(
            None
            if body.operation_limits is None
            else {
                key: value.model_dump() if isinstance(value, OperationRate) else value
                for key, value in body.operation_limits.items()
            }
        ),
    )


def pool_budget(limit: int | None, window_seconds: int | None) -> PoolBudget | None:
    """Restore a stored budget without converting through binary floating point."""

    if limit is None:
        return None
    if window_seconds not in _SECONDS_PERIOD:
        raise ValueError("unrecognized budget window")
    return PoolBudget(limit=Decimal(limit) / _MICRODOLLARS, period=_SECONDS_PERIOD[window_seconds])


def pool_rate(limit: int | None, window_seconds: int) -> PoolRate:
    return PoolRate(limit=limit, window_seconds=window_seconds)


async def unassign_owner_pools(
    session: AsyncSession, project_id: UUID, owner_id: UUID
) -> list[StoredKeyPool]:
    """Unassign only this owner's pools and rebuild runtime in the same transaction."""
    pools = KeyPoolRepository(session)
    before = await pools.list_for_project(project_id)
    ids = set(await pools.unassign_owner_pools(project_id, owner_id))
    removed = [pool for pool in before if pool.id in ids]
    if removed:
        await materialize_pools(session, project_id=project_id)
    return removed


async def sync_pool_changes(
    repository: SQLiteRepository, changes: list[tuple[StoredKeyPool | None, StoredKeyPool | None]]
) -> None:
    routing = ProjectRoutingService(repository)
    for before, after in changes:
        for project_id in {p.project_id for p in (before, after) if p and p.project_id}:
            old = before if before and before.project_id == project_id else None
            new = after if after and after.project_id == project_id else None
            pool = old or new
            assert pool is not None
            await routing.sync(
                project_id,
                pool.provider_type,
                {CredentialOperation(op) for op in old.operations} if old else set(),
                {CredentialOperation(op) for op in new.operations} if new else set(),
            )


async def _require_owner(session: AsyncSession, actor: UserPrincipal, project_id: UUID) -> None:
    projects = await ProjectRepository(session).list_provider_owner_projects(actor.id)
    if project_id not in projects:
        raise AuthorizationDenied(
            AuthorizationDecision(
                allowed=False,
                reason="provider owner required",
                required_permission=PermissionAction.PROVIDERS_SUPPLY,
                scope_type=ScopeType.PROJECT,
                scope_id=project_id,
            )
        )


async def _owned_pool(session: AsyncSession, actor: UserPrincipal, pool_id: UUID) -> StoredKeyPool:
    await _require_vault(session, actor.id)
    pool = await KeyPoolRepository(session).get(pool_id)
    if (
        pool is None
        or await CredentialRepository(session).get_owned(actor.id, pool.credential_id) is None
    ):
        raise ResourceNotFound("pool is not available")
    return pool


async def _view(session: AsyncSession, pool: StoredKeyPool) -> KeyPoolRead:
    try:
        module = import_module("polyweb.services.pool_budget")
    except ImportError:  # pool_budget lands in L2i
        used = 0
    else:
        counter = cast(
            Callable[[AsyncSession, UUID], Awaitable[int]], module.pool_budget_used_micros
        )
        used = await counter(session, pool.id)
    return KeyPoolRead(
        id=pool.id,
        credential_id=pool.credential_id,
        project_id=pool.project_id,
        provider_type=pool.provider_type,
        label=pool.label,
        rate=pool_rate(pool.rate_limit, pool.rate_window_seconds),
        budget=pool_budget(pool.budget_limit, pool.budget_window_seconds),
        budget_used_usd=Decimal(used) / _MICRODOLLARS,
        operations=pool.operations,
        operation_limits=pool.operation_limits,
    )


class KeyPoolService:
    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    async def list_for_key(self, actor: UserPrincipal, key_id: UUID) -> list[KeyPoolRead]:
        async def read(session: AsyncSession) -> list[KeyPoolRead]:
            await _owned(session, actor.id, key_id)
            return [
                await _view(session, pool)
                for pool in await KeyPoolRepository(session).list_for_key(key_id)
            ]

        return await run_control_read(self._repository, read)

    async def get(self, actor: UserPrincipal, pool_id: UUID) -> KeyPoolRead:
        async def read(session: AsyncSession) -> KeyPoolRead:
            return await _view(session, await _owned_pool(session, actor, pool_id))

        return await run_control_read(self._repository, read)

    async def projects(self, actor: UserPrincipal) -> list[VaultProject]:
        async def read(session: AsyncSession) -> list[VaultProject]:
            await _require_vault(session, actor.id)
            ids = await ProjectRepository(session).list_provider_owner_projects(actor.id)
            keys = await CredentialRepository(session).list_for_owner(actor.id)
            providers = {key.credential.provider_type for key in keys}
            result = []
            for project_id in ids:
                project = await session.get(ProjectRow, str(project_id))
                assert project is not None
                assigned = await KeyPoolRepository(session).list_for_project(project_id)
                result.append(
                    VaultProject(
                        id=project_id,
                        name=project.name,
                        available_providers=sorted(providers - {p.provider_type for p in assigned}),
                    )
                )
            return result

        return await run_control_read(self._repository, read)

    async def _write(
        self,
        actor: UserPrincipal,
        action: str,
        operation: Callable[
            [AsyncSession], Awaitable[tuple[StoredKeyPool | None, StoredKeyPool | None]]
        ],
    ) -> KeyPoolRead | None:
        changes: list[tuple[StoredKeyPool | None, StoredKeyPool | None]] = []

        async def write(session: AsyncSession) -> KeyPoolRead | None:
            changes.clear()
            before, after = await operation(session)
            changes.append((before, after))
            for project_id in {p.project_id for p in (before, after) if p and p.project_id}:
                await materialize_pools(session, project_id=project_id)
            pool = after or before
            assert pool is not None
            await record_system_event(
                session,
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                actor=actor,
                action=f"vault.pool_{action}",
                target_type="key_pool",
                target_id=str(pool.id),
            )
            return await _view(session, after) if after else None

        result = await run_control_write(self._repository, write, conflict_code="POOL_CONFLICT")
        await sync_pool_changes(self._repository, changes)
        return result

    async def create(self, actor: UserPrincipal, key_id: UUID, body: KeyPoolCreate) -> KeyPoolRead:
        async def write(session: AsyncSession) -> tuple[None, StoredKeyPool]:
            key = await _owned(session, actor.id, key_id)
            if body.project_id:
                await _require_owner(session, actor, body.project_id)
            pool = await KeyPoolRepository(session).create(
                credential_id=key_id,
                project_id=body.project_id,
                provider_type=key.credential.provider_type,
                created_by=actor.id,
                values=pool_values(key.credential.provider_type, body),
            )
            return None, pool

        result = await self._write(actor, "created", write)
        assert result is not None
        return result

    async def update(self, actor: UserPrincipal, pool_id: UUID, body: KeyPoolUpdate) -> KeyPoolRead:
        async def write(session: AsyncSession) -> tuple[StoredKeyPool, StoredKeyPool]:
            before = await _owned_pool(session, actor, pool_id)
            if before.project_id:
                await _require_owner(session, actor, before.project_id)
            fields = body.model_fields_set
            if ("label" in fields and body.label is None) or (
                "rate" in fields and body.rate is None
            ):
                raise ResourceInvalid("INVALID_POOL", "label and rate cannot be null")
            merged = KeyPoolCreate(
                label=body.label if body.label is not None else before.label,
                rate=body.rate or pool_rate(before.rate_limit, before.rate_window_seconds),
                budget=body.budget
                if "budget" in fields
                else pool_budget(before.budget_limit, before.budget_window_seconds),
                operations=body.operations if "operations" in fields else before.operations,
                operation_limits=body.operation_limits
                if "operation_limits" in fields
                else before.operation_limits,
            )
            after = await KeyPoolRepository(session).update(
                pool_id, pool_values(before.provider_type, merged)
            )
            assert after is not None
            return before, after

        result = await self._write(actor, "updated", write)
        assert result is not None
        return result

    async def delete(self, actor: UserPrincipal, pool_id: UUID) -> None:
        async def write(session: AsyncSession) -> tuple[StoredKeyPool, None]:
            before = await _owned_pool(session, actor, pool_id)
            if before.project_id:
                await _require_owner(session, actor, before.project_id)
            await detach_pool_allocations(session, pool_id)
            await KeyPoolRepository(session).delete(pool_id)
            return before, None

        await self._write(actor, "deleted", write)

    async def assign(
        self, actor: UserPrincipal, pool_id: UUID, project_id: UUID | None
    ) -> KeyPoolRead:
        async def write(session: AsyncSession) -> tuple[StoredKeyPool, StoredKeyPool]:
            before = await _owned_pool(session, actor, pool_id)
            if before.project_id:
                await _require_owner(session, actor, before.project_id)
            if project_id:
                await _require_owner(session, actor, project_id)
                if before.project_id and before.project_id != project_id:
                    raise ResourceConflict("POOL_ASSIGNED", "unassign the pool first")
            pools = KeyPoolRepository(session)
            after = await (
                pools.assign(pool_id, project_id) if project_id else pools.unassign(pool_id)
            )
            assert after is not None
            return before, after

        result = await self._write(actor, "assigned" if project_id else "unassigned", write)
        assert result is not None
        return result

    async def copy(
        self, actor: UserPrincipal, pool_id: UUID, project_id: UUID, label: str | None
    ) -> KeyPoolRead:
        async def write(session: AsyncSession) -> tuple[None, StoredKeyPool]:
            source = await _owned_pool(session, actor, pool_id)
            await _require_owner(session, actor, project_id)
            after = await KeyPoolRepository(session).duplicate_to_project(
                pool_id, project_id, label or f"{source.label[:95]} copy", actor.id
            )
            assert after is not None
            return None, after

        result = await self._write(actor, "copied", write)
        assert result is not None
        return result
