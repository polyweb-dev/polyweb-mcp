"""HTTP endpoints for pools in the caller's vault."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from polyweb.models.users import UserPrincipal
from polyweb.models.vault import (
    KeyPoolCreate,
    KeyPoolRead,
    KeyPoolUpdate,
    PoolAssignment,
    VaultProject,
)
from polyweb.routers.auth import current_principal
from polyweb.routers.control_errors import control_repository
from polyweb.services.key_pools import KeyPoolService

router = APIRouter(prefix="/api/v1/account/vault", tags=["vault"])
Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _service(request: Request) -> KeyPoolService:
    return KeyPoolService(control_repository(request))


@router.get("/projects", response_model=list[VaultProject])
async def projects(request: Request, actor: Principal) -> list[VaultProject]:
    return await _service(request).projects(actor)


@router.get("/keys/{key_id}/pools", response_model=list[KeyPoolRead])
async def list_pools(request: Request, actor: Principal, key_id: UUID) -> list[KeyPoolRead]:
    return await _service(request).list_for_key(actor, key_id)


@router.post("/keys/{key_id}/pools", response_model=KeyPoolRead, status_code=201)
async def create_pool(
    request: Request, actor: Principal, key_id: UUID, body: KeyPoolCreate
) -> KeyPoolRead:
    return await _service(request).create(actor, key_id, body)


@router.get("/pools/{pool_id}", response_model=KeyPoolRead)
async def get_pool(request: Request, actor: Principal, pool_id: UUID) -> KeyPoolRead:
    return await _service(request).get(actor, pool_id)


@router.patch("/pools/{pool_id}", response_model=KeyPoolRead)
async def update_pool(
    request: Request, actor: Principal, pool_id: UUID, body: KeyPoolUpdate
) -> KeyPoolRead:
    return await _service(request).update(actor, pool_id, body)


@router.delete("/pools/{pool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pool(request: Request, actor: Principal, pool_id: UUID) -> Response:
    await _service(request).delete(actor, pool_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pools/{pool_id}/assign", response_model=KeyPoolRead)
async def assign_pool(
    request: Request, actor: Principal, pool_id: UUID, body: PoolAssignment
) -> KeyPoolRead:
    return await _service(request).assign(actor, pool_id, body.project_id)


@router.post("/pools/{pool_id}/unassign", response_model=KeyPoolRead)
async def unassign_pool(request: Request, actor: Principal, pool_id: UUID) -> KeyPoolRead:
    return await _service(request).assign(actor, pool_id, None)


@router.post("/pools/{pool_id}/copy", response_model=KeyPoolRead)
async def copy_pool(
    request: Request, actor: Principal, pool_id: UUID, body: PoolAssignment
) -> KeyPoolRead:
    return await _service(request).copy(actor, pool_id, body.project_id, body.label)
