"""Project provider bindings and the available-versus-enabled provider view (A4).

A *binding* is a project's explicit choice to route to one credential: its own
private credential or a system credential granted to it. This service lists
bindings and builds the provider view; both reads need ``providers.read``.

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
from polyweb.services.authorization import ScopedAuthorizationService
from polyweb.services.control_access import (
    require_project_permission,
    run_control_read,
)
from polyweb.services.routing_order import catalog_call_costs

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
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._provider_config = provider_config
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)

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
    "ProviderBindingService",
    "ProviderConfigLookup",
    "allocation_read",
    "provider_capability",
    "supported_operations",
]
