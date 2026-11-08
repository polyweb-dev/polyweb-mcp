"""Project-scoped provider order storage and membership."""

import json
from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.configuration.provider_config import get_provider_configs
from freesearch.configuration.provider_limits import PROVIDER_IDS
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.credentials import CredentialOperation
from freesearch.models.project_routing import (
    OperationOrder,
    OperationOrderUpdate,
    OrderItem,
    ProjectOrderResponse,
    RoutingOperation,
    RoutingStrategy,
    StoredProjectOrder,
)
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, PermissionAction
from freesearch.models.users import UserPrincipal
from freesearch.persistence.bindings import ProjectBindingRow
from freesearch.persistence.credentials import ProviderCredentialRow
from freesearch.persistence.key_pools import KeyPoolRepository
from freesearch.persistence.projects import ProjectRow
from freesearch.persistence.settings import ProjectSettingsRepository
from freesearch.persistence.storage import RuntimeSettingRow, SQLiteRepository
from freesearch.persistence.transactions import run_serialized
from freesearch.services.audit_events import record_project_event
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.control_access import (
    require_active_project,
    require_project_permission,
    run_control_read,
    run_control_write,
)
from freesearch.services.control_errors import ResourceConflict
from freesearch.services.pool_materializer import provider_enabled
from freesearch.services.provider_bindings import provider_capability
from freesearch.services.routing_order import call_cost_usd, merge_order, order_for

NAMESPACE = "provider_order"
_SEED_FLAG = "routing.orders_seeded"
_NAMES = {"you": "You.com", "exa": "Exa"}


class ProjectPoolOperations:
    """Project routing membership from assigned vault pools."""

    async def for_project(
        self, session: AsyncSession, project_id: UUID
    ) -> Mapping[str, frozenset[CredentialOperation]]:
        operations: dict[str, set[CredentialOperation]] = {}
        for pool in await KeyPoolRepository(session).list_for_project(project_id):
            operations.setdefault(pool.provider_type, set()).update(
                CredentialOperation(operation) for operation in pool.operations
            )
        for provider in await _keyless_members(session, project_id):
            operations[provider] = {CredentialOperation.SEARCH, CredentialOperation.FETCH}
        return {
            provider: frozenset(ops)
            for provider, ops in operations.items()
            if await provider_enabled(session, provider)
        }


async def _keyless_members(session: AsyncSession, project_id: UUID) -> set[str]:
    rows = await session.scalars(
        select(ProviderCredentialRow.provider_type)
        .join(ProjectBindingRow, ProjectBindingRow.credential_id == ProviderCredentialRow.id)
        .where(
            ProjectBindingRow.project_id == str(project_id),
            ProviderCredentialRow.auth_mode == "keyless",
            ProviderCredentialRow.status == "active",
        )
    )
    return set(rows)


async def _document(session: AsyncSession, project_id: UUID) -> tuple[StoredProjectOrder, int]:
    row = await ProjectSettingsRepository(session).get(project_id=project_id, namespace=NAMESPACE)
    return (
        StoredProjectOrder.model_validate({} if row is None else row.document),
        0 if row is None else row.revision,
    )


def _order(
    document: StoredProjectOrder,
    operation: RoutingOperation,
    members: Collection[str],
    keyless: Collection[str] = (),
) -> list[str]:
    stored = getattr(document, operation.value)
    costs = {
        provider: call_cost_usd(provider, operation, keyless=provider in keyless)
        for provider in members
    }
    return order_for(stored.strategy, members, stored.custom_order, costs)


async def effective_order(
    session: AsyncSession, project_id: UUID, operation: RoutingOperation, members: Collection[str]
) -> list[str]:
    """Resolve a runtime order within the caller's existing read session."""

    document, _ = await _document(session, project_id)
    return _order(document, operation, members, await _keyless_members(session, project_id))


async def seed_legacy_orders(repository: SQLiteRepository) -> None:
    """Atomically seed existing projects once before legacy priorities disappear."""

    async def seed(session: AsyncSession) -> None:
        flag = await session.get(RuntimeSettingRow, _SEED_FLAG)
        if flag is not None and json.loads(flag.value_json) is True:
            return
        legacy = await session.get(RuntimeSettingRow, "routing")
        policy = {} if legacy is None else json.loads(legacy.value_json)
        strategy = (
            RoutingStrategy.FREE_FIRST
            if isinstance(policy, dict) and policy.get("cost_optimization_preset") == "free_first"
            else RoutingStrategy.CUSTOM
        )
        configs = get_provider_configs()
        priorities: dict[str, int] = {}
        for provider in ProviderName:
            row = await session.get(RuntimeSettingRow, f"provider.{provider.value}")
            data = {} if row is None else json.loads(row.value_json)
            if isinstance(data, dict) and isinstance(data.get("config"), dict):
                data = data["config"]
            value = data.get("priority") if isinstance(data, dict) else None
            priorities[provider.value] = (
                value if isinstance(value, int) else configs[provider].priority
            )
        order = sorted(priorities, key=lambda provider: (priorities[provider], provider))
        settings = ProjectSettingsRepository(session)
        for project_id in (await session.execute(select(ProjectRow.id))).scalars():
            identifier = UUID(project_id)
            existing = await settings.get(project_id=identifier, namespace=NAMESPACE)
            if existing is not None:
                continue
            entry = {"strategy": strategy.value, "custom_order": order}
            await settings.compare_and_set(
                project_id=identifier,
                namespace=NAMESPACE,
                schema_version=1,
                overrides={"search": entry, "fetch": entry},
                expected_revision=0,
            )
        if flag is None:
            session.add(RuntimeSettingRow(key=_SEED_FLAG, value_json="true"))
        else:
            flag.value_json = "true"

    await run_serialized(repository, seed)


def _response(
    document: StoredProjectOrder,
    revision: int,
    membership: Mapping[str, frozenset[CredentialOperation]],
    keyless: Collection[str] = (),
) -> ProjectOrderResponse:
    def operation_view(operation: RoutingOperation) -> OperationOrder:
        allowed = CredentialOperation(operation.value)
        members = [provider for provider, ops in membership.items() if allowed in ops]
        stored = getattr(document, operation.value)
        return OperationOrder(
            strategy=stored.strategy,
            providers=[
                OrderItem(
                    provider=provider,
                    name=_NAMES.get(provider, provider.capitalize()),
                    call_cost_usd=call_cost_usd(provider, operation, keyless=provider in keyless),
                    keyless=provider in keyless,
                )
                for provider in _order(document, operation, members, keyless)
            ],
            has_saved_custom=stored.custom_order is not None,
            not_allowed=sorted(
                provider
                for provider, ops in membership.items()
                if allowed not in ops and allowed in provider_capability(provider)
            ),
        )

    return ProjectOrderResponse(
        revision=revision,
        search=operation_view(RoutingOperation.SEARCH),
        fetch=operation_view(RoutingOperation.FETCH),
    )


class ProjectRoutingService:
    def __init__(
        self, repository: SQLiteRepository, *, pool_operations: ProjectPoolOperations | None = None
    ) -> None:
        self._repository = repository
        self._authorization = ScopedAuthorizationService(repository)
        self._pools = pool_operations or ProjectPoolOperations()

    async def get(self, actor: UserPrincipal, project_id: UUID) -> ProjectOrderResponse:
        async def read(session: AsyncSession) -> ProjectOrderResponse:
            await require_project_permission(
                session, self._authorization, actor, project_id, PermissionAction.PROVIDERS_READ
            )
            document, revision = await _document(session, project_id)
            return _response(
                document,
                revision,
                await self._pools.for_project(session, project_id),
                await _keyless_members(session, project_id),
            )

        return await run_control_read(self._repository, read)

    async def set(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        operation: RoutingOperation,
        update: OperationOrderUpdate,
    ) -> ProjectOrderResponse:
        async def write(session: AsyncSession) -> ProjectOrderResponse:
            await require_project_permission(
                session,
                self._authorization,
                actor,
                project_id,
                PermissionAction.PROVIDERS_CONFIGURE,
            )
            await require_active_project(
                session, account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, project_id=project_id
            )
            membership = await self._pools.for_project(session, project_id)
            keyless = await _keyless_members(session, project_id)
            members = {
                provider
                for provider, ops in membership.items()
                if CredentialOperation(operation.value) in ops
            }
            document, revision = await _document(session, project_id)
            current = getattr(document, operation.value)
            before = _order(document, operation, members, keyless)
            old_strategy = current.strategy
            if current.custom_order is not None:
                current.custom_order = [
                    provider for provider in current.custom_order if provider in PROVIDER_IDS
                ]
            if update.strategy == RoutingStrategy.CUSTOM:
                if update.order is None:
                    if current.custom_order is None:
                        raise ResourceConflict("NO_SAVED_ORDER", "no custom order has been saved")
                else:
                    if len(update.order) != len(members) or set(update.order) != members:
                        raise ResourceConflict("ORDER_STALE", "the provider membership has changed")
                    current.custom_order = merge_order(
                        current.custom_order or [], update.order, members, PROVIDER_IDS
                    )
            current.strategy = update.strategy
            applied = await ProjectSettingsRepository(session).compare_and_set(
                project_id=project_id,
                namespace=NAMESPACE,
                schema_version=1,
                overrides=document.model_dump(mode="json"),
                expected_revision=revision,
            )
            if not applied:
                raise ResourceConflict("ORDER_STALE", "the provider order changed")
            after = _order(document, operation, members, keyless)
            detail: dict[str, Any] = {
                "operation": operation.value,
                "strategy_before": old_strategy.value,
                "strategy_after": update.strategy.value,
                "order_before": before,
                "order_after": after,
            }
            await record_project_event(
                session,
                project_id=project_id,
                actor=actor,
                action="routing.order_changed",
                target_type="provider_order",
                target_id=operation.value,
                detail=detail,
            )
            return _response(document, revision + 1, membership, keyless)

        return await run_control_write(self._repository, write, conflict_code="ORDER_STALE")

    async def sync(
        self,
        project_id: UUID,
        provider_type: str,
        ops_before: Collection[CredentialOperation],
        ops_after: Collection[CredentialOperation],
    ) -> None:
        """Presets are live; custom slots intentionally survive membership changes."""
