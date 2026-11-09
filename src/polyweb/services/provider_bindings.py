"""Project provider bindings and the available-versus-enabled provider view (A4).

A *binding* is a project's explicit choice to route to one credential: its own
private credential or a system credential granted to it. A binding always
starts with no enabled operations; enabling is a separate update, and the
enabled set must stay inside

    adapter capability ∩ operations the credential supports
                       ∩ the grant's permitted operations (system credentials)

Writes need live ``providers.configure`` in the project and an active
project; reads need ``providers.read``. Every write appends a project audit
event in the same transaction.

The provider view (doc-000001 §4.6) keeps *available* (a credential the
project owns or holds a grant for) separate from *enabled* (a binding with
enabled operations). ``effective_operations`` is capability AND not killed by
system policy AND ownership/grant AND binding enablement. Principal
permission, capacity and live health are dispatch-time checks (A2) and are
not part of the view. The view never carries secrets, slot names, pool
balances or consumption, or another project's bindings or usage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.configuration.provider_config import ProviderConfig, system_support_mask
from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.contracts import UsageOperation
from polyweb.models.credentials import (
    ALL_CREDENTIAL_OPERATIONS,
    CredentialAuthMode,
    CredentialOperation,
)
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialInstanceRead,
    PermissionAction,
    ProjectBindingRead,
)
from polyweb.models.provider_access import ALL_BITS, is_operation_enabled
from polyweb.models.providers import (
    AllocationRead,
    AvailableCredentialRead,
    BindingCreate,
    BindingUpdate,
    ProjectProvidersRead,
    ProviderBindingView,
    ProviderPoolRead,
    ProviderTypeView,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.bindings import ProjectBindingRepository, StoredBinding
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.pools import (
    CredentialPoolLinkRow,
    PoolAllocationRepository,
    ProjectPoolAllocationRow,
    StoredAllocation,
    StoredPool,
    StoredPoolLink,
    UpstreamPoolRepository,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.transactions import DEFAULT_WRITE_ATTEMPTS
from polyweb.services.audit_events import record_project_event
from polyweb.services.authorization import ScopedAuthorizationService
from polyweb.services.control_access import (
    require_active_project,
    require_project_permission,
    run_control_read,
    run_control_write,
)
from polyweb.services.control_errors import ResourceConflict, ResourceInvalid, ResourceNotFound
from polyweb.services.routing_order import catalog_call_costs

#: Audit actions of binding lifecycle events (project scope).
BINDING_CREATED: Final[str] = "binding.created"
BINDING_UPDATED: Final[str] = "binding.updated"
BINDING_DELETED: Final[str] = "binding.deleted"

#: 422 code: the body names a credential the project neither owns nor holds a grant for.
CREDENTIAL_NOT_AVAILABLE: Final[str] = "CREDENTIAL_NOT_AVAILABLE"
#: 422 code: an enabled operation falls outside capability, support or grant.
OPERATION_NOT_PERMITTED: Final[str] = "OPERATION_NOT_PERMITTED"
#: 409 code: the project already routes this credential under this label.
BINDING_ROUTE_CONFLICT: Final[str] = "BINDING_ROUTE_CONFLICT"
#: 409 code: an unclassified binding integrity failure.
BINDING_CONFLICT: Final[str] = "BINDING_CONFLICT"

_TARGET_TYPE: Final[str] = "binding"

#: Operations an OAuth credential supports for execution. The Parallel OAuth
#: grant is scoped to account balance reads, so it serves no search or fetch.
_OAUTH_SUPPORTED_OPERATIONS: Final[frozenset[CredentialOperation]] = frozenset()

ProviderConfigLookup = Callable[[str], Awaitable[ProviderConfig]]


async def _default_provider_config(provider_type: str) -> ProviderConfig:
    del provider_type
    return ProviderConfig()


def provider_capability(provider_type: str) -> frozenset[CredentialOperation]:
    """Return the adapter capability of one provider type (empty when unknown)."""

    try:
        provider = ProviderName(provider_type)
    except ValueError:
        return frozenset()
    mask = system_support_mask(provider)
    return frozenset(
        operation
        for operation in CredentialOperation
        if is_operation_enabled(ALL_BITS, mask, operation.value)
    )


def supported_operations(credential: CredentialInstanceRead) -> frozenset[CredentialOperation]:
    """Return the execution operations one credential can serve."""

    if credential.auth_mode == CredentialAuthMode.OAUTH.value:
        return _OAUTH_SUPPORTED_OPERATIONS
    return provider_capability(credential.provider_type)


def _system_enabled(config: ProviderConfig) -> frozenset[CredentialOperation]:
    return frozenset(
        operation
        for operation in CredentialOperation
        if config.allows(UsageOperation(operation.value))
    )


@dataclass(frozen=True)
class _Available:
    """One credential available to the project and its granted operations."""

    credential: CredentialInstanceRead
    granted: frozenset[CredentialOperation]

    @property
    def permitted(self) -> frozenset[CredentialOperation]:
        """Operations a binding of this credential may enable."""

        return self.granted & supported_operations(self.credential)


def _binding_read(binding: StoredBinding) -> ProjectBindingRead:
    return ProjectBindingRead(
        id=binding.id,
        project_id=binding.project_id,
        credential_id=binding.credential_id,
        route_label=binding.route_label,
        enabled_operations=frozenset(operation.value for operation in binding.enabled_operations),
        priority=binding.priority,
        overrides=binding.overrides,
        version=binding.version,
    )


def allocation_read(allocation: StoredAllocation) -> AllocationRead:
    """Project one stored allocation onto its wire model."""

    # The legacy response schema predates nullable rates. Preserve NULL rather
    # than coercing an unlimited allocation to zero.
    return AllocationRead.model_construct(
        project_id=allocation.project_id,
        pool_id=allocation.pool_id,
        operation_scope=allocation.operation,
        base_rate=allocation.base_rate,
        rate_window_seconds=allocation.rate_window_seconds,
        borrow_enabled=allocation.borrow_enabled,
        max_rate=allocation.max_rate,
        effective_max_rate=allocation.effective_max_rate,
        weight=allocation.weight,
        best_effort=allocation.best_effort,
        max_concurrency=allocation.max_concurrency,
        max_queued_requests=allocation.max_queued_requests,
        max_queued_bytes=allocation.max_queued_bytes,
        max_queue_wait_ms=allocation.max_queue_wait_ms,
        version=allocation.version,
    )


class ProviderBindingService:
    """Authorize and execute project bindings and the project provider view."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        provider_config: ProviderConfigLookup = _default_provider_config,
        max_write_attempts: int = DEFAULT_WRITE_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._provider_config = provider_config
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    # ------------------------------------------------------------------
    # Bindings
    # ------------------------------------------------------------------

    async def list_bindings(
        self, actor: UserPrincipal, project_id: UUID
    ) -> list[ProjectBindingRead]:
        """List this project's bindings with ``providers.read``."""

        async def operation(session: AsyncSession) -> list[ProjectBindingRead]:
            await require_project_permission(
                session, self._authorization, actor, project_id, PermissionAction.PROVIDERS_READ
            )
            bindings = await ProjectBindingRepository(session).list_for_project(
                project_id=project_id
            )
            owned = await CredentialRepository(session).list_for_owner(actor.id)
            owned_ids = {key.credential.id for key in owned}
            return [
                _binding_read(binding) for binding in bindings if binding.credential_id in owned_ids
            ]

        return await run_control_read(self._repository, operation)

    async def create_binding(
        self, actor: UserPrincipal, project_id: UUID, body: BindingCreate
    ) -> ProjectBindingRead:
        """Bind one available credential; the binding starts disabled."""

        async def operation(session: AsyncSession) -> ProjectBindingRead:
            await self._require_configure(session, actor, project_id)
            available = await self._available(session, project_id, body.credential_id)
            if available is None:
                raise ResourceInvalid(
                    CREDENTIAL_NOT_AVAILABLE,
                    "the credential is not available to this project",
                )
            bindings = ProjectBindingRepository(session)
            await self._reject_route_conflict(
                bindings, project_id, body.credential_id, body.route_label, exclude=None
            )
            created = await bindings.create(
                project_id=project_id,
                credential_id=body.credential_id,
                credential_scope=available.credential.owner_scope,
                route_label=body.route_label,
                priority=body.priority,
                created_by=actor.id,
            )
            await self._audit(session, actor, created, BINDING_CREATED)
            return _binding_read(created)

        return await self._write(operation)

    async def update_binding(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        binding_id: UUID,
        body: BindingUpdate,
    ) -> ProjectBindingRead:
        """Change enabled operations, priority or route label of one binding."""

        async def operation(session: AsyncSession) -> ProjectBindingRead:
            await self._require_configure(session, actor, project_id)
            bindings = ProjectBindingRepository(session)
            current = await bindings.get(project_id=project_id, binding_id=binding_id)
            if current is None:
                raise ResourceNotFound("binding is not available")
            enabled = (
                current.enabled_operations
                if body.enabled_operations is None
                else body.enabled_operations
            )
            await self._require_permitted(session, current, enabled)
            route_label = current.route_label if body.route_label is None else body.route_label
            if route_label != current.route_label:
                await self._reject_route_conflict(
                    bindings, project_id, current.credential_id, route_label, exclude=current.id
                )
            updated = await bindings.update(
                project_id=project_id,
                binding_id=binding_id,
                enabled_operations=enabled,
                priority=current.priority if body.priority is None else body.priority,
                route_label=route_label,
            )
            if updated is None:
                raise ResourceNotFound("binding is not available")
            await self._audit(session, actor, updated, BINDING_UPDATED)
            return _binding_read(updated)

        return await self._write(operation)

    async def delete_binding(
        self, actor: UserPrincipal, project_id: UUID, binding_id: UUID
    ) -> None:
        """Remove one binding of this project."""

        async def operation(session: AsyncSession) -> None:
            await self._require_configure(session, actor, project_id)
            bindings = ProjectBindingRepository(session)
            current = await bindings.get(project_id=project_id, binding_id=binding_id)
            if current is None:
                raise ResourceNotFound("binding is not available")
            await bindings.delete(project_id=project_id, binding_id=binding_id)
            await self._audit(session, actor, current, BINDING_DELETED)

        await self._write(operation)

    # ------------------------------------------------------------------
    # Provider view
    # ------------------------------------------------------------------

    async def project_providers(
        self, actor: UserPrincipal, project_id: UUID
    ) -> ProjectProvidersRead:
        """Return available and enabled providers of one project (``providers.read``)."""

        async def operation(session: AsyncSession) -> _ViewState:
            await require_project_permission(
                session, self._authorization, actor, project_id, PermissionAction.PROVIDERS_READ
            )
            return await self._view_state(session, project_id, actor.id)

        state = await run_control_read(self._repository, operation)
        providers = [await self._provider_view(provider.value, state) for provider in ProviderName]
        return ProjectProvidersRead(
            project_id=project_id,
            providers=providers,
            allocations=[allocation_read(allocation) for allocation in state.allocations],
        )

    async def _view_state(
        self, session: AsyncSession, project_id: UUID, owner_id: UUID
    ) -> _ViewState:
        credentials = CredentialRepository(session)
        available = [
            _Available(credential, ALL_CREDENTIAL_OPERATIONS)
            for credential in await credentials.list_private_credentials(
                account_id=self._account_id, project_id=project_id
            )
        ]
        available.extend(
            _Available(credential, granted)
            for credential, granted in await credentials.list_granted_credentials(
                account_id=self._account_id, project_id=project_id
            )
        )
        bindings = await ProjectBindingRepository(session).list_for_project(project_id=project_id)
        assigned_ids = {
            pool.credential_id
            for pool in await KeyPoolRepository(session).list_for_project(project_id)
        }
        owned = await credentials.list_for_owner(owner_id)
        owned_ids = {key.credential.id for key in owned}
        available = [
            item
            for item in available
            if item.credential.id in owned_ids
            or item.credential.id in assigned_ids
            or item.credential.auth_mode == "keyless"
        ]
        credential_ids = {item.credential.id for item in available}
        pools = UpstreamPoolRepository(session)
        permitted = {item.credential.id: item.permitted for item in available}
        rows = (
            await session.scalars(
                select(CredentialPoolLinkRow)
                .join(
                    ProjectPoolAllocationRow,
                    (ProjectPoolAllocationRow.pool_id == CredentialPoolLinkRow.pool_id)
                    & (
                        ProjectPoolAllocationRow.operation_scope
                        == CredentialPoolLinkRow.operation_scope
                    ),
                )
                .where(
                    ProjectPoolAllocationRow.project_id == str(project_id),
                    CredentialPoolLinkRow.credential_id.in_([str(cid) for cid in credential_ids]),
                )
                .order_by(
                    CredentialPoolLinkRow.credential_id, CredentialPoolLinkRow.operation_scope
                )
            )
        ).all()
        links = [
            StoredPoolLink(
                credential_id=UUID(row.credential_id),
                operation=CredentialOperation(row.operation_scope),
                pool_id=UUID(row.pool_id),
                provider_type=row.provider_type,
                version=row.version,
            )
            for row in rows
            if CredentialOperation(row.operation_scope) in permitted[UUID(row.credential_id)]
        ]
        pool_rows = await pools.get_pools(
            account_id=self._account_id, pool_ids={link.pool_id for link in links}
        )
        return _ViewState(
            available=available,
            bindings=bindings,
            links=links,
            pools=pool_rows,
            health=await credentials.latest_health(credential_ids=credential_ids),
            allocations=await PoolAllocationRepository(session).list_for_project(
                project_id=project_id
            ),
        )

    async def _provider_view(self, provider_type: str, state: _ViewState) -> ProviderTypeView:
        capability = provider_capability(provider_type)
        config = await self._provider_config(provider_type)
        system_enabled = _system_enabled(config) & capability
        own = [item for item in state.available if item.credential.provider_type == provider_type]
        by_id = {item.credential.id: item for item in own}
        bindings: list[ProviderBindingView] = []
        for binding in state.bindings:
            item = by_id.get(binding.credential_id)
            if item is None:
                continue
            bindings.append(
                ProviderBindingView(
                    id=binding.id,
                    credential_id=binding.credential_id,
                    route_label=binding.route_label,
                    priority=binding.priority,
                    enabled_operations=binding.enabled_operations,
                    effective_operations=(
                        binding.enabled_operations & system_enabled & item.permitted
                    ),
                )
            )
        effective = frozenset().union(*(binding.effective_operations for binding in bindings))
        observations = [
            state.health[binding.credential_id]
            for binding in bindings
            if binding.enabled_operations and binding.credential_id in state.health
        ]
        health = max(observations, key=lambda observation: observation[1], default=None)
        return ProviderTypeView(
            provider_type=provider_type,
            keyless=bool(catalog_call_costs(provider_type, keyless=True)),
            call_cost_usd=catalog_call_costs(provider_type),
            keyless_call_cost_usd=catalog_call_costs(provider_type, keyless=True),
            capability=capability,
            kill_switch=not config.enabled,
            system_enabled_operations=system_enabled,
            available=bool(own),
            enabled=bool(effective),
            health_status=None if health is None else health[0],
            health_checked_at=None if health is None else health[1],
            credentials=[self._credential_view(item, state) for item in own],
            bindings=bindings,
            effective_operations=effective,
        )

    @staticmethod
    def _credential_view(item: _Available, state: _ViewState) -> AvailableCredentialRead:
        credential = item.credential
        health = state.health.get(credential.id)
        pools: list[ProviderPoolRead] = []
        for link in state.links:
            pool = state.pools.get(link.pool_id)
            if link.credential_id != credential.id or pool is None:
                continue
            pools.append(
                ProviderPoolRead(
                    operation_scope=link.operation,
                    pool_id=pool.id,
                    label=pool.label,
                    upstream_scope=pool.upstream_scope,
                    status=pool.status,
                )
            )
        return AvailableCredentialRead(
            id=credential.id,
            label=credential.label,
            owner_scope=credential.owner_scope,
            auth_mode=credential.auth_mode,
            status=credential.status,
            health_status=None if health is None else health[0],
            health_checked_at=None if health is None else health[1],
            granted_operations=item.granted,
            supported_operations=supported_operations(credential),
            pools=pools,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _require_configure(
        self, session: AsyncSession, actor: UserPrincipal, project_id: UUID
    ) -> None:
        await require_project_permission(
            session, self._authorization, actor, project_id, PermissionAction.PROVIDERS_CONFIGURE
        )
        await require_active_project(session, account_id=self._account_id, project_id=project_id)

    async def _available(
        self, session: AsyncSession, project_id: UUID, credential_id: UUID
    ) -> _Available | None:
        """Return the credential if this project owns it or holds a grant for it."""

        credentials = CredentialRepository(session)
        private = await credentials.get_private_credential(
            account_id=self._account_id, project_id=project_id, credential_id=credential_id
        )
        if private is not None:
            return _Available(private, ALL_CREDENTIAL_OPERATIONS)
        system = await credentials.get_system_credential(
            account_id=self._account_id, credential_id=credential_id
        )
        if system is None:
            return None
        grant = await credentials.get_grant(credential_id=credential_id, project_id=project_id)
        if grant is None:
            return None
        return _Available(
            system, frozenset(CredentialOperation(value) for value in grant.permitted_operations)
        )

    async def _require_permitted(
        self,
        session: AsyncSession,
        binding: StoredBinding,
        enabled: frozenset[CredentialOperation],
    ) -> None:
        if not enabled:
            return
        available = await self._available(session, binding.project_id, binding.credential_id)
        allowed = frozenset() if available is None else available.permitted
        if not enabled <= allowed:
            raise ResourceInvalid(
                OPERATION_NOT_PERMITTED,
                "enabled operations must be within the credential's capability and grant",
            )

    @staticmethod
    async def _reject_route_conflict(
        bindings: ProjectBindingRepository,
        project_id: UUID,
        credential_id: UUID,
        route_label: str,
        *,
        exclude: UUID | None,
    ) -> None:
        for existing in await bindings.list_for_credential(
            project_id=project_id, credential_id=credential_id
        ):
            if existing.route_label == route_label and existing.id != exclude:
                raise ResourceConflict(
                    BINDING_ROUTE_CONFLICT,
                    "this credential is already bound under this route label",
                )

    async def _audit(
        self, session: AsyncSession, actor: UserPrincipal, binding: StoredBinding, action: str
    ) -> None:
        await record_project_event(
            session,
            project_id=binding.project_id,
            actor=actor,
            action=action,
            target_type=_TARGET_TYPE,
            target_id=str(binding.id),
            detail={
                "credential_scope": binding.credential_scope.value,
                "route_label": binding.route_label,
                "priority": binding.priority,
                "enabled_operations": sorted(
                    operation.value for operation in binding.enabled_operations
                ),
            },
        )

    async def _write[T](self, operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
        return await run_control_write(
            self._repository,
            operation,
            conflict_code=BINDING_CONFLICT,
            max_attempts=self._max_write_attempts,
        )


@dataclass(frozen=True)
class _ViewState:
    """Everything the provider view reads in one session."""

    available: list[_Available]
    bindings: list[StoredBinding]
    links: list[StoredPoolLink]
    pools: dict[UUID, StoredPool]
    health: dict[UUID, tuple[str, datetime]]
    allocations: list[StoredAllocation]


__all__ = [
    "BINDING_CONFLICT",
    "BINDING_CREATED",
    "BINDING_DELETED",
    "BINDING_ROUTE_CONFLICT",
    "BINDING_UPDATED",
    "CREDENTIAL_NOT_AVAILABLE",
    "OPERATION_NOT_PERMITTED",
    "ProviderBindingService",
    "ProviderConfigLookup",
    "allocation_read",
    "provider_capability",
    "supported_operations",
]
