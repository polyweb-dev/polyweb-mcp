"""System pool, credential link and allocation HTTP surface (A4).

Thin transport over :class:`~freesearch.services.pools.PoolService`. Every
route is system scope; a project role never reaches it::

    GET/POST    /api/v1/system/pools                         system.pools.manage
    GET/PATCH   /api/v1/system/pools/{pool_id}               system.pools.manage
    GET         /api/v1/system/pools/{pool_id}/links         system.pools.manage
    PUT/DELETE  /api/v1/system/pools/{pool_id}/links/{credential_id}?operation_scope=
                                                             system.pools.manage
    GET         /api/v1/system/projects/{project_id}/allocations
                                                             system.allocations.manage
    PUT/GET/DELETE /api/v1/system/projects/{project_id}/allocations/{pool_id}?operation_scope=
                                                             system.allocations.manage
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response, status

from freesearch.models.credentials import CredentialOperation
from freesearch.models.providers import (
    AllocationPut,
    AllocationRead,
    PoolCreate,
    PoolLinkRead,
    PoolRead,
    PoolUpdate,
)
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.routers.control_errors import control_repository, register_control_error_handlers
from freesearch.services.pools import PoolService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]
_OperationScope = Annotated[CredentialOperation, Query()]


def _pool_service(request: Request) -> PoolService:
    return PoolService(control_repository(request))


def register_pool_routes(app: FastAPI) -> None:
    """Register the system pool, link and allocation routes on ``app``."""

    register_control_error_handlers(app)
    _register_pool_routes(app)
    _register_allocation_routes(app)


def _register_pool_routes(app: FastAPI) -> None:
    @app.get("/api/v1/system/pools", response_model=list[PoolRead])
    async def list_pools(request: Request, principal: _Principal) -> list[PoolRead]:
        """List every upstream pool."""

        return await _pool_service(request).list_pools(principal)

    @app.post("/api/v1/system/pools", response_model=PoolRead, status_code=status.HTTP_201_CREATED)
    async def create_pool(request: Request, principal: _Principal, body: PoolCreate) -> PoolRead:
        """Create one upstream pool."""

        return await _pool_service(request).create_pool(principal, body)

    @app.get("/api/v1/system/pools/{pool_id}", response_model=PoolRead)
    async def get_pool(request: Request, principal: _Principal, pool_id: UUID) -> PoolRead:
        """Return one upstream pool."""

        return await _pool_service(request).get_pool(principal, pool_id)

    @app.patch("/api/v1/system/pools/{pool_id}", response_model=PoolRead)
    async def update_pool(
        request: Request, principal: _Principal, pool_id: UUID, body: PoolUpdate
    ) -> PoolRead:
        """Change one upstream pool."""

        return await _pool_service(request).update_pool(principal, pool_id, body)

    @app.get("/api/v1/system/pools/{pool_id}/links", response_model=list[PoolLinkRead])
    async def list_pool_links(
        request: Request, principal: _Principal, pool_id: UUID
    ) -> list[PoolLinkRead]:
        """List the credential links of one pool."""

        return await _pool_service(request).list_links(principal, pool_id)

    @app.put("/api/v1/system/pools/{pool_id}/links/{credential_id}", response_model=PoolLinkRead)
    async def put_pool_link(
        request: Request,
        principal: _Principal,
        pool_id: UUID,
        credential_id: UUID,
        operation_scope: _OperationScope,
    ) -> PoolLinkRead:
        """Link one credential's operation to this pool (same provider type only)."""

        return await _pool_service(request).put_link(
            principal, pool_id, credential_id, operation_scope
        )

    @app.delete(
        "/api/v1/system/pools/{pool_id}/links/{credential_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_pool_link(
        request: Request,
        principal: _Principal,
        pool_id: UUID,
        credential_id: UUID,
        operation_scope: _OperationScope,
    ) -> Response:
        """Remove one credential's link to this pool."""

        await _pool_service(request).delete_link(principal, pool_id, credential_id, operation_scope)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def _register_allocation_routes(app: FastAPI) -> None:
    @app.get(
        "/api/v1/system/projects/{project_id}/allocations",
        response_model=list[AllocationRead],
    )
    async def list_project_allocations(
        request: Request, principal: _Principal, project_id: UUID
    ) -> list[AllocationRead]:
        """List one project's allocations."""

        return await _pool_service(request).list_project_allocations(principal, project_id)

    @app.put(
        "/api/v1/system/projects/{project_id}/allocations/{pool_id}",
        response_model=AllocationRead,
    )
    async def put_allocation(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: _OperationScope,
        body: AllocationPut,
    ) -> AllocationRead:
        """Create or replace one allocation; infeasible base rates are rejected (409)."""

        return await _pool_service(request).put_allocation(
            principal, project_id, pool_id, operation_scope, body
        )

    @app.get(
        "/api/v1/system/projects/{project_id}/allocations/{pool_id}",
        response_model=AllocationRead,
    )
    async def get_allocation(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: _OperationScope,
    ) -> AllocationRead:
        """Return one allocation."""

        return await _pool_service(request).get_allocation(
            principal, project_id, pool_id, operation_scope
        )

    @app.delete(
        "/api/v1/system/projects/{project_id}/allocations/{pool_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_allocation(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        pool_id: UUID,
        operation_scope: _OperationScope,
    ) -> Response:
        """Remove one allocation."""

        await _pool_service(request).delete_allocation(
            principal, project_id, pool_id, operation_scope
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["register_pool_routes"]
