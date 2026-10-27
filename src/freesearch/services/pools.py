"""System administration of upstream pools, credential links and allocations (A4).

Only system administrators manage shared capacity: pools and links need live
``system.pools.manage``; project allocations need live
``system.allocations.manage``. No project-scoped route reaches this service,
so no project edit can create or raise a pool value or an allocation ceiling.
Projects read their own allocations through the provider view.

Allocations are strict by default (loans off, ``max_rate`` null or equal to
``base_rate``). The base rates promised on one pool must fit every pool rate
constraint of the same window: an allocation or a pool edit that would
overcommit a constraint is rejected with ``ALLOCATION_INFEASIBLE``.

Every mutation appends a system audit event in the same transaction;
allocation changes also append an event in the allocated project.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.credentials import CredentialOperation
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, PermissionAction
from freesearch.models.providers import (
    AllocationPut,
    AllocationRead,
    PoolCreate,
    PoolLinkRead,
    PoolRead,
    PoolUpdate,
    RateConstraint,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    StoredAllocation,
    StoredPool,
    StoredPoolLink,
    UpstreamPoolRepository,
)
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import DEFAULT_WRITE_ATTEMPTS
from freesearch.services.audit_events import record_project_event, record_system_event
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.control_access import (
    require_active_project,
    require_system_permission,
    run_control_read,
    run_control_write,
)
from freesearch.services.control_errors import ResourceConflict, ResourceInvalid, ResourceNotFound
from freesearch.services.provider_bindings import allocation_read

#: Audit actions (system scope; allocation actions also at project scope).
POOL_CREATED: Final[str] = "pool.created"
POOL_UPDATED: Final[str] = "pool.updated"
POOL_LINK_PUT: Final[str] = "pool_link.put"
POOL_LINK_DELETED: Final[str] = "pool_link.deleted"
ALLOCATION_PUT: Final[str] = "allocation.put"
ALLOCATION_DELETED: Final[str] = "allocation.deleted"

#: 409: the promised base rates would exceed a pool rate constraint.
ALLOCATION_INFEASIBLE: Final[str] = "ALLOCATION_INFEASIBLE"
#: 409: an allocation write conflicts with existing data.
ALLOCATION_CONFLICT: Final[str] = "ALLOCATION_CONFLICT"
#: 409: another pool of this provider already uses the pool key.
POOL_CONFLICT: Final[str] = "POOL_CONFLICT"
#: 422: the provider type is not in the catalog.
UNKNOWN_PROVIDER_TYPE: Final[str] = "UNKNOWN_PROVIDER_TYPE"
#: 422: a credential cannot link to another provider's pool.
PROVIDER_TYPE_MISMATCH: Final[str] = "PROVIDER_TYPE_MISMATCH"

_VALID_PROVIDER_TYPES: Final[frozenset[str]] = frozenset(item.value for item in ProviderName)


def _stored_constraints(pool: StoredPool) -> list[RateConstraint]:
    """Decode the stored constraints, skipping entries outside the wire contract."""

    constraints: list[RateConstraint] = []
    for item in pool.constraints:
        try:
            constraints.append(RateConstraint.model_validate(item))
        except ValidationError:
            continue
    return constraints


def _pool_read(pool: StoredPool) -> PoolRead:
    return PoolRead(
        id=pool.id,
        provider_type=pool.provider_type,
        upstream_scope=pool.upstream_scope,
        pool_key=pool.pool_key,
        label=pool.label,
        constraints=_stored_constraints(pool),
        max_concurrency=pool.max_concurrency,
        max_queued_requests=pool.max_queued_requests,
        status=pool.status,
        version=pool.version,
    )


def _link_read(link: StoredPoolLink) -> PoolLinkRead:
    return PoolLinkRead(
        credential_id=link.credential_id,
        pool_id=link.pool_id,
        operation_scope=link.operation,
        provider_type=link.provider_type,
        version=link.version,
    )


def _constraint_payload(constraints: Iterable[RateConstraint]) -> list[dict[str, Any]]:
    return [constraint.model_dump(mode="json") for constraint in constraints]


def _require_feasible(
    constraints: Iterable[RateConstraint], allocations: Iterable[StoredAllocation | AllocationPut]
) -> None:
    """Reject base rates whose sum exceeds a pool constraint of the same window."""

    totals: dict[int, int] = {}
    for allocation in allocations:
        window = allocation.rate_window_seconds
        totals[window] = totals.get(window, 0) + allocation.base_rate
    for constraint in constraints:
        if totals.get(constraint.window_seconds, 0) > constraint.limit:
            raise ResourceConflict(
                ALLOCATION_INFEASIBLE,
                "the promised base rates exceed the pool's rate constraint for this window",
            )


class PoolService:
    """System-admin pool, link and allocation administration."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        max_write_attempts: int = DEFAULT_WRITE_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    # ------------------------------------------------------------------
    # Pools
    # ------------------------------------------------------------------

    async def list_pools(self, actor: UserPrincipal) -> list[PoolRead]:
        """List every pool of the installation."""

        async def operation(session: AsyncSession) -> list[PoolRead]:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            pools = await UpstreamPoolRepository(session).list_pools(account_id=self._account_id)
            return [_pool_read(pool) for pool in pools]

        return await run_control_read(self._repository, operation)

    async def get_pool(self, actor: UserPrincipal, pool_id: UUID) -> PoolRead:
        """Return one pool."""

        async def operation(session: AsyncSession) -> PoolRead:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            return _pool_read(await self._pool(session, pool_id))

        return await run_control_read(self._repository, operation)

    async def create_pool(self, actor: UserPrincipal, body: PoolCreate) -> PoolRead:
        """Create one pool for a catalog provider type."""

        async def operation(session: AsyncSession) -> PoolRead:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            if body.provider_type not in _VALID_PROVIDER_TYPES:
                raise ResourceInvalid(UNKNOWN_PROVIDER_TYPE, "unknown provider type")
            pool = await UpstreamPoolRepository(session).create_pool(
                account_id=self._account_id,
                provider_type=body.provider_type,
                upstream_scope=body.upstream_scope,
                pool_key=body.pool_key,
                label=body.label,
                constraints=_constraint_payload(body.constraints),
                max_concurrency=body.max_concurrency,
                max_queued_requests=body.max_queued_requests,
            )
            await self._audit_pool(session, actor, pool, POOL_CREATED)
            return _pool_read(pool)

        return await self._write(operation, POOL_CONFLICT)

    async def update_pool(self, actor: UserPrincipal, pool_id: UUID, body: PoolUpdate) -> PoolRead:
        """Change one pool; tighter constraints must still fit promised base rates."""

        async def operation(session: AsyncSession) -> PoolRead:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            current = await self._pool(session, pool_id)
            fields = body.model_fields_set
            constraints = (
                body.constraints if body.constraints is not None else _stored_constraints(current)
            )
            _require_feasible(
                constraints,
                await PoolAllocationRepository(session).list_for_pool(pool_id=pool_id),
            )
            updated = await UpstreamPoolRepository(session).update_pool(
                account_id=self._account_id,
                pool_id=pool_id,
                upstream_scope=body.upstream_scope or current.upstream_scope,
                pool_key=body.pool_key or current.pool_key,
                label=body.label or current.label,
                constraints=_constraint_payload(constraints),
                max_concurrency=(
                    body.max_concurrency if "max_concurrency" in fields else current.max_concurrency
                ),
                max_queued_requests=(
                    body.max_queued_requests
                    if "max_queued_requests" in fields
                    else current.max_queued_requests
                ),
                status=body.status or current.status,
            )
            if updated is None:
                raise ResourceNotFound("pool is not available")
            await self._audit_pool(session, actor, updated, POOL_UPDATED)
            return _pool_read(updated)

        return await self._write(operation, POOL_CONFLICT)

    # ------------------------------------------------------------------
    # Credential links
    # ------------------------------------------------------------------

    async def list_links(self, actor: UserPrincipal, pool_id: UUID) -> list[PoolLinkRead]:
        """List every credential link of one pool."""

        async def operation(session: AsyncSession) -> list[PoolLinkRead]:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            await self._pool(session, pool_id)
            links = await UpstreamPoolRepository(session).links_for_pool(pool_id=pool_id)
            return [_link_read(link) for link in links]

        return await run_control_read(self._repository, operation)

    async def put_link(
        self,
        actor: UserPrincipal,
        pool_id: UUID,
        credential_id: UUID,
        operation_scope: CredentialOperation,
    ) -> PoolLinkRead:
        """Link one credential's operation to this pool; relinking replaces the pool."""

        async def operation(session: AsyncSession) -> PoolLinkRead:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            pool = await self._pool(session, pool_id)
            credential = await CredentialRepository(session).get_active_credential(
                account_id=self._account_id, credential_id=credential_id
            )
            if credential is None:
                raise ResourceNotFound("credential is not available")
            if credential.provider_type != pool.provider_type:
                raise ResourceInvalid(
                    PROVIDER_TYPE_MISMATCH,
                    "a credential can only link to a pool of its own provider type",
                )
            link = await UpstreamPoolRepository(session).link_credential(
                credential_id=credential_id,
                operation=operation_scope,
                pool_id=pool_id,
                provider_type=pool.provider_type,
            )
            await self._audit_link(session, actor, link, POOL_LINK_PUT)
            return _link_read(link)

        return await self._write(operation, POOL_CONFLICT)

    async def delete_link(
        self,
        actor: UserPrincipal,
        pool_id: UUID,
        credential_id: UUID,
        operation_scope: CredentialOperation,
    ) -> None:
        """Remove one credential's link to this pool."""

        async def operation(session: AsyncSession) -> None:
            await self._require(session, actor, PermissionAction.SYSTEM_POOLS_MANAGE)
            pools = UpstreamPoolRepository(session)
            link = await pools.pool_for_credential(
                credential_id=credential_id, operation=operation_scope
            )
            if link is None or link.pool_id != pool_id:
                raise ResourceNotFound("pool link is not available")
            await pools.unlink_credential(
                credential_id=credential_id, operation=operation_scope, pool_id=pool_id
            )
            await self._audit_link(session, actor, link, POOL_LINK_DELETED)

        await self._write(operation, POOL_CONFLICT)

    # ------------------------------------------------------------------
    # Project allocations
    # ------------------------------------------------------------------

    async def list_project_allocations(
        self, actor: UserPrincipal, project_id: UUID
    ) -> list[AllocationRead]:
        """List one project's allocations (system view)."""

        async def operation(session: AsyncSession) -> list[AllocationRead]:
            await self._require(session, actor, PermissionAction.SYSTEM_ALLOCATIONS_MANAGE)
            await self._project(session, project_id)
            allocations = await PoolAllocationRepository(session).list_for_project(
                project_id=project_id
            )
            return [allocation_read(allocation) for allocation in allocations]

        return await run_control_read(self._repository, operation)

    async def get_allocation(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: CredentialOperation,
    ) -> AllocationRead:
        """Return one allocation."""

        async def operation(session: AsyncSession) -> AllocationRead:
            await self._require(session, actor, PermissionAction.SYSTEM_ALLOCATIONS_MANAGE)
            allocation = await PoolAllocationRepository(session).get(
                project_id=project_id, pool_id=pool_id, operation=operation_scope
            )
            if allocation is None:
                raise ResourceNotFound("allocation is not available")
            return allocation_read(allocation)

        return await run_control_read(self._repository, operation)

    async def put_allocation(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: CredentialOperation,
        body: AllocationPut,
    ) -> AllocationRead:
        """Create or replace one allocation if the pool can honour every base rate."""

        async def operation(session: AsyncSession) -> AllocationRead:
            await self._require(session, actor, PermissionAction.SYSTEM_ALLOCATIONS_MANAGE)
            await self._project(session, project_id)
            await require_active_project(
                session, account_id=self._account_id, project_id=project_id
            )
            pool = await self._pool(session, pool_id)
            allocations = PoolAllocationRepository(session)
            others = [
                existing
                for existing in await allocations.list_for_pool(pool_id=pool_id)
                if not (existing.project_id == project_id and existing.operation == operation_scope)
            ]
            _require_feasible(
                _stored_constraints(pool),
                [*others, body],
            )
            stored = await self._upsert_allocation(
                allocations, actor, project_id, pool_id, operation_scope, body
            )
            await self._audit_allocation(session, actor, stored, ALLOCATION_PUT)
            return allocation_read(stored)

        return await self._write(operation, ALLOCATION_CONFLICT)

    async def delete_allocation(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: CredentialOperation,
    ) -> None:
        """Remove one allocation."""

        async def operation(session: AsyncSession) -> None:
            await self._require(session, actor, PermissionAction.SYSTEM_ALLOCATIONS_MANAGE)
            allocations = PoolAllocationRepository(session)
            current = await allocations.get(
                project_id=project_id, pool_id=pool_id, operation=operation_scope
            )
            if current is None:
                raise ResourceNotFound("allocation is not available")
            await allocations.delete(
                project_id=project_id, pool_id=pool_id, operation=operation_scope
            )
            await self._audit_allocation(session, actor, current, ALLOCATION_DELETED)

        await self._write(operation, ALLOCATION_CONFLICT)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _require(
        self, session: AsyncSession, actor: UserPrincipal, action: PermissionAction
    ) -> None:
        await require_system_permission(
            session, self._authorization, actor, action, account_id=self._account_id
        )

    async def _pool(self, session: AsyncSession, pool_id: UUID) -> StoredPool:
        pool = await UpstreamPoolRepository(session).get_pool(
            account_id=self._account_id, pool_id=pool_id
        )
        if pool is None:
            raise ResourceNotFound("pool is not available")
        return pool

    async def _project(self, session: AsyncSession, project_id: UUID) -> None:
        project = await ProjectRepository(session).get_project(
            project_id=project_id, account_id=self._account_id
        )
        if project is None:
            raise ResourceNotFound("project is not available")

    @staticmethod
    async def _upsert_allocation(
        allocations: PoolAllocationRepository,
        actor: UserPrincipal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: CredentialOperation,
        body: AllocationPut,
    ) -> StoredAllocation:
        values: dict[str, Any] = {
            "base_rate": body.base_rate,
            "rate_window_seconds": body.rate_window_seconds,
            "borrow_enabled": body.borrow_enabled,
            "max_rate": body.max_rate,
            "weight": body.weight,
            "best_effort": body.best_effort,
            "max_concurrency": body.max_concurrency,
            "max_queued_requests": body.max_queued_requests,
            "max_queued_bytes": body.max_queued_bytes,
            "max_queue_wait_ms": body.max_queue_wait_ms,
        }
        current = await allocations.get(
            project_id=project_id, pool_id=pool_id, operation=operation_scope
        )
        if current is None:
            return await allocations.create(
                project_id=project_id,
                pool_id=pool_id,
                operation=operation_scope,
                granted_by=actor.id,
                **values,
            )
        updated = await allocations.update(
            project_id=project_id,
            pool_id=pool_id,
            operation=operation_scope,
            expected_version=current.version,
            granted_by=actor.id,
            **values,
        )
        if updated is None:
            raise ResourceConflict(ALLOCATION_CONFLICT, "the allocation changed; retry")
        return updated

    async def _audit_pool(
        self, session: AsyncSession, actor: UserPrincipal, pool: StoredPool, action: str
    ) -> None:
        await record_system_event(
            session,
            account_id=self._account_id,
            actor=actor,
            action=action,
            target_type="pool",
            target_id=str(pool.id),
            detail={
                "provider_type": pool.provider_type,
                "upstream_scope": pool.upstream_scope.value,
                "label": pool.label,
                "status": pool.status.value,
                "constraint_count": len(pool.constraints),
            },
        )

    async def _audit_link(
        self, session: AsyncSession, actor: UserPrincipal, link: StoredPoolLink, action: str
    ) -> None:
        await record_system_event(
            session,
            account_id=self._account_id,
            actor=actor,
            action=action,
            target_type="pool_link",
            target_id=f"{link.pool_id}:{link.credential_id}:{link.operation.value}",
            detail={"provider_type": link.provider_type, "operation_scope": link.operation.value},
        )

    async def _audit_allocation(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        allocation: StoredAllocation,
        action: str,
    ) -> None:
        target_id = f"{allocation.project_id}:{allocation.pool_id}:{allocation.operation.value}"
        detail: dict[str, object] = {
            "operation_scope": allocation.operation.value,
            "base_rate": allocation.base_rate,
            "rate_window_seconds": allocation.rate_window_seconds,
            "borrow_enabled": allocation.borrow_enabled,
            "max_rate": allocation.max_rate,
            "weight": allocation.weight,
            "best_effort": allocation.best_effort,
        }
        await record_system_event(
            session,
            account_id=self._account_id,
            actor=actor,
            action=action,
            target_type="allocation",
            target_id=target_id,
            detail=detail,
        )
        await record_project_event(
            session,
            project_id=allocation.project_id,
            actor=actor,
            action=action,
            target_type="allocation",
            target_id=target_id,
            detail=detail,
        )

    async def _write[T](
        self, operation: Callable[[AsyncSession], Awaitable[T]], conflict_code: str
    ) -> T:
        return await run_control_write(
            self._repository,
            operation,
            conflict_code=conflict_code,
            max_attempts=self._max_write_attempts,
        )


__all__ = [
    "ALLOCATION_CONFLICT",
    "ALLOCATION_DELETED",
    "ALLOCATION_INFEASIBLE",
    "ALLOCATION_PUT",
    "POOL_CONFLICT",
    "POOL_CREATED",
    "POOL_LINK_DELETED",
    "POOL_LINK_PUT",
    "POOL_UPDATED",
    "PROVIDER_TYPE_MISMATCH",
    "UNKNOWN_PROVIDER_TYPE",
    "PoolService",
]
