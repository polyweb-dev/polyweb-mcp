"""Project runtime capacity derived from assigned vault pools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.infrastructure.secrets import KEYLESS_PROVIDER_TYPES, ProviderName
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.persistence.bindings import ProjectBindingRow
from polyweb.persistence.credentials import CredentialProjectGrantRow
from polyweb.persistence.key_pools import KeyPoolRepository, StoredKeyPool
from polyweb.persistence.pools import ProjectPoolAllocationRow
from polyweb.persistence.projects import ProjectRow
from polyweb.persistence.storage import RuntimeSettingRow

_POOL_PREFIX = "vault-key:"
KEYLESS_PROVIDERS = KEYLESS_PROVIDER_TYPES


@dataclass(frozen=True)
class MaterializeResult:
    """Projects and assigned pools rebuilt within the caller's transaction."""

    projects: int
    pools: int


def _runtime_id(kind: str, identifier: UUID) -> str:
    return str(uuid5(NAMESPACE_URL, f"polyweb:{kind}:{identifier}"))


def keyless_credential_id(provider: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"polyweb:keyless-credential:{provider}"))


async def ensure_keyless_credentials(session: AsyncSession) -> None:
    """Create the installation's non-vault public credentials, without secrets."""

    await session.execute(
        text("INSERT INTO accounts (id,status) VALUES (:id,'active') ON CONFLICT(id) DO NOTHING"),
        {"id": str(DEFAULT_INSTALLATION_ACCOUNT_ID)},
    )
    now = datetime.now(UTC).isoformat()
    for provider in sorted(KEYLESS_PROVIDERS):
        await session.execute(
            text(
                "INSERT INTO provider_credentials "
                "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
                "generation,status,created_by,created_at,updated_at,version,owner_user_id) "
                "VALUES (:id,:account,:provider,'system',NULL,'public','keyless',"
                "1,'active',NULL,:now,:now,1,NULL) ON CONFLICT(id) DO NOTHING"
            ),
            {
                "id": keyless_credential_id(provider),
                "account": str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                "provider": provider,
                "now": now,
            },
        )


async def provider_enabled(session: AsyncSession, provider: str) -> bool:
    from polyweb.services.provider_runtime import (
        _config_payload,
        _current_config,
        _provider_base,
    )

    name = ProviderName(provider)
    row = await session.get(RuntimeSettingRow, f"provider.{provider}")
    payload = _config_payload(None if row is None else json.loads(row.value_json))
    base = _provider_base(name)
    return (base if payload is None else _current_config(name, base, payload)).enabled


def _rate(pool: StoredKeyPool, operation: str) -> int | None:
    if pool.operation_limits is None or operation not in pool.operation_limits:
        return pool.rate_limit
    value = pool.operation_limits[operation]
    if isinstance(value, dict):
        value = value.get("rate_limit")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError("invalid operation rate limit")
    return value


def _rate_window(pool: StoredKeyPool, operation: str) -> int:
    value = (pool.operation_limits or {}).get(operation)
    if isinstance(value, dict):
        window = value.get("rate_window_seconds", pool.rate_window_seconds)
        if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
            raise ValueError("invalid operation rate window")
        return int(window)
    return pool.rate_window_seconds


async def _insert_pool(session: AsyncSession, account_id: str, pool: StoredKeyPool) -> None:
    pool_id = _runtime_id("credential-pool", pool.credential_id)
    operations = json.dumps(sorted(pool.operations))
    args = {
        "pool_id": pool_id,
        "account": account_id,
        "provider": pool.provider_type,
        "pool_key": f"{_POOL_PREFIX}{pool.credential_id}",
        "label": pool.label,
        "credential": str(pool.credential_id),
        "project": str(pool.project_id),
        "key_pool": str(pool.id),
        "creator": str(pool.created_by),
        "now": pool.created_at,
        "updated": pool.updated_at,
        "operations": operations,
        "binding": _runtime_id("binding", pool.id),
        "budget": pool.budget_limit,
        "budget_window": pool.budget_window_seconds,
        "rate_window": pool.rate_window_seconds,
        "limit_scope": "operation" if pool.operation_limits is not None else "pool",
    }
    await session.execute(
        text(
            "INSERT INTO upstream_quota_pools "
            "(id,account_id,provider_type,upstream_scope,pool_key,label,constraints,status,"
            "created_at,updated_at,version) "
            "VALUES (:pool_id,:account,:provider,'credential',:pool_key,:label,'[]','active',"
            ":now,:now,1) ON CONFLICT(id) DO NOTHING"
        ),
        args,
    )
    await session.execute(
        text(
            "INSERT INTO credential_project_grants "
            "(credential_id,owner_scope,project_id,permitted_operations,granted_by,created_at,version)"
            " VALUES (:credential,'system',:project,:operations,:creator,:now,1) "
            "ON CONFLICT(credential_id,project_id) DO UPDATE SET "
            "permitted_operations=excluded.permitted_operations"
        ),
        args,
    )
    await session.execute(
        text(
            "INSERT INTO project_provider_bindings "
            "(id,project_id,credential_id,credential_scope,granted_project_id,route_label,"
            "enabled_operations,priority,overrides,created_by,created_at,updated_at,version) "
            "VALUES (:binding,:project,:credential,'system',:project,:provider,:operations,"
            "100,'{}',:creator,:now,:updated,1) ON CONFLICT(id) DO UPDATE SET "
            "enabled_operations=excluded.enabled_operations,updated_at=excluded.updated_at"
        ),
        args,
    )
    for operation in sorted(pool.operations):
        rate = _rate(pool, operation)
        params = {
            **args,
            "operation": operation,
            "rate": rate,
            "rate_window": _rate_window(pool, operation),
            "best_effort": int(rate == 0),
        }
        await session.execute(
            text(
                "INSERT INTO credential_pool_links "
                "(credential_id,operation_scope,pool_id,provider_type,created_at,version) "
                "VALUES (:credential,:operation,:pool_id,:provider,:now,1) "
                "ON CONFLICT(credential_id,operation_scope) DO UPDATE SET "
                "pool_id=excluded.pool_id,provider_type=excluded.provider_type"
            ),
            params,
        )
        await session.execute(
            text(
                "INSERT INTO project_pool_allocations "
                "(project_id,pool_id,operation_scope,base_rate,rate_window_seconds,"
                "borrow_enabled,max_rate,weight,best_effort,granted_by,created_at,updated_at,"
                "version,key_pool_id,limit_scope,budget_limit,budget_window_seconds) "
                "VALUES (:project,:pool_id,:operation,:rate,:rate_window,0,NULL,1,:best_effort,"
                ":creator,:now,:updated,1,:key_pool,:limit_scope,:budget,:budget_window) "
                "ON CONFLICT(project_id,pool_id,operation_scope) DO UPDATE SET "
                "base_rate=excluded.base_rate,rate_window_seconds=excluded.rate_window_seconds,"
                "borrow_enabled=excluded.borrow_enabled,max_rate=excluded.max_rate,"
                "weight=excluded.weight,best_effort=excluded.best_effort,"
                "key_pool_id=excluded.key_pool_id,limit_scope=excluded.limit_scope,"
                "budget_limit=excluded.budget_limit,"
                "budget_window_seconds=excluded.budget_window_seconds,updated_at=excluded.updated_at"
            ),
            params,
        )


async def _prune_generated(session: AsyncSession) -> None:
    # Links and upstream pools are global, so keep any used by another project.
    await session.execute(
        text(
            "DELETE FROM credential_pool_links WHERE pool_id IN "
            "(SELECT id FROM upstream_quota_pools WHERE pool_key LIKE :prefix) "
            "AND NOT EXISTS (SELECT 1 FROM project_pool_allocations a "
            "WHERE a.pool_id=credential_pool_links.pool_id "
            "AND a.operation_scope=credential_pool_links.operation_scope)"
        ),
        {"prefix": f"{_POOL_PREFIX}%"},
    )
    await session.execute(
        text(
            "DELETE FROM upstream_quota_pools WHERE pool_key LIKE :prefix "
            "AND NOT EXISTS (SELECT 1 FROM credential_pool_links l "
            "WHERE l.pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM project_pool_allocations a "
            "WHERE a.pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM execution_dispatches d "
            "WHERE d.pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM usage_events u WHERE u.pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM quota_snapshots q "
            "WHERE q.pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM provider_limit_admissions l "
            "WHERE l.upstream_pool_id=upstream_quota_pools.id) "
            "AND NOT EXISTS (SELECT 1 FROM provider_rate_attempts r "
            "WHERE r.upstream_pool_id=upstream_quota_pools.id)"
        ),
        {"prefix": f"{_POOL_PREFIX}%"},
    )


async def detach_pool_allocations(session: AsyncSession, pool_id: UUID) -> None:
    """Remove allocations before deleting a key pool (0004 drops FK cascade)."""

    await session.execute(
        text("DELETE FROM project_pool_allocations WHERE key_pool_id=:pool_id"),
        {"pool_id": str(pool_id)},
    )


async def materialize_pools(
    session: AsyncSession, *, project_id: UUID | None = None
) -> MaterializeResult:
    """Synchronize project capacity in the caller's transaction; never commit.

    Only explicitly assigned key pools materialize bindings, grants, and
    allocations for the selected provider. There is no implicit public
    keyless grant: a project with no assigned pool resolves zero bindings,
    and previously persisted automatic keyless bindings/grants for providers
    with no assigned pool are pruned by the deletes below.
    """

    await ensure_keyless_credentials(session)
    query = select(ProjectRow.id, ProjectRow.account_id)
    if project_id is not None:
        query = query.where(ProjectRow.id == str(project_id))
    projects = (await session.execute(query.order_by(ProjectRow.id))).all()
    count = 0
    for identifier, account_id in projects:
        pools = await KeyPoolRepository(session).list_for_project(UUID(identifier))
        binding_ids = [_runtime_id("binding", pool.id) for pool in pools]
        credential_ids = [str(pool.credential_id) for pool in pools]
        allocation_keys = [
            (_runtime_id("credential-pool", pool.credential_id), operation)
            for pool in pools
            for operation in pool.operations
        ]
        await session.execute(
            delete(ProjectBindingRow).where(
                ProjectBindingRow.project_id == identifier, ProjectBindingRow.id.not_in(binding_ids)
            )
        )
        await session.execute(
            delete(CredentialProjectGrantRow).where(
                CredentialProjectGrantRow.project_id == identifier,
                CredentialProjectGrantRow.credential_id.not_in(credential_ids),
            )
        )
        await session.execute(
            delete(ProjectPoolAllocationRow).where(
                ProjectPoolAllocationRow.project_id == identifier,
                tuple_(
                    ProjectPoolAllocationRow.pool_id, ProjectPoolAllocationRow.operation_scope
                ).not_in(allocation_keys),
            )
        )
        for pool in pools:
            await _insert_pool(session, account_id, pool)
        count += len(pools)
    await _prune_generated(session)
    return MaterializeResult(projects=len(projects), pools=count)
