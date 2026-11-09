"""Read-only project view of assigned vault pools."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.projects import PermissionAction
from polyweb.models.users import UserPrincipal
from polyweb.models.vault import OperationLimit, PoolBudget, PoolRate
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.users import UserRow
from polyweb.routers.auth import current_principal
from polyweb.routers.control_errors import control_repository
from polyweb.services.authorization import ScopedAuthorizationService
from polyweb.services.control_access import require_project_permission, run_control_read
from polyweb.services.control_errors import ControlStorageUnavailable
from polyweb.services.key_pools import pool_budget, pool_rate
from polyweb.services.pool_budget import pool_budget_used_micros

router = APIRouter(prefix="/api/v1/projects", tags=["project pools"])
Principal = Annotated[UserPrincipal, Depends(current_principal)]


class PoolOwner(BaseModel):
    user_id: UUID
    email: str


class ProjectPoolRead(BaseModel):
    pool_id: UUID
    label: str
    provider_type: str
    key_label: str
    owner: PoolOwner
    rate: PoolRate
    budget: PoolBudget | None
    budget_used: Decimal
    operations: frozenset[str]
    operation_limits: dict[str, OperationLimit] | None
    overcommit: bool

    @field_serializer("budget_used", when_used="json")
    def serialize_used(self, value: Decimal) -> float:
        return float(value)


@router.get("/{project_id}/pools", response_model=list[ProjectPoolRead])
async def list_project_pools(
    request: Request, actor: Principal, project_id: UUID
) -> list[ProjectPoolRead]:
    repository = control_repository(request)
    authorization = ScopedAuthorizationService(repository)

    async def read(session: AsyncSession) -> list[ProjectPoolRead]:
        await require_project_permission(
            session, authorization, actor, project_id, PermissionAction.PROVIDERS_READ
        )
        pools = await KeyPoolRepository(session).list_for_project(project_id)
        if not pools:
            return []
        owner_id = await ProjectRepository(session).get_provider_owner(project_id)
        owner = await session.get(UserRow, owner_id) if owner_id is not None else None
        if owner is None or owner_id is None:
            raise ControlStorageUnavailable("pool owner is unavailable")
        credentials = CredentialRepository(session)
        result = []
        for pool in pools:
            key = await credentials.get_owned(owner_id, pool.credential_id)
            if key is None:
                raise ControlStorageUnavailable("pool credential is unavailable")
            result.append(
                ProjectPoolRead(
                    pool_id=pool.id,
                    label=pool.label,
                    provider_type=pool.provider_type,
                    key_label=key.credential.label,
                    owner=PoolOwner(user_id=owner_id, email=owner.email),
                    rate=pool_rate(pool.rate_limit, pool.rate_window_seconds),
                    budget=pool_budget(pool.budget_limit, pool.budget_window_seconds),
                    budget_used=Decimal(await pool_budget_used_micros(session, pool.id))
                    / Decimal(1_000_000),
                    operations=pool.operations,
                    operation_limits=pool.operation_limits,
                    overcommit=key.overcommit,
                )
            )
        return result

    return await run_control_read(repository, read)
