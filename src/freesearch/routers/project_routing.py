"""Project provider-order API."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request

from freesearch.models.project_routing import (
    OperationOrderUpdate,
    ProjectOrderResponse,
    RoutingOperation,
)
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.routers.control_errors import control_repository, register_control_error_handlers
from freesearch.services.project_routing import ProjectRoutingService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def register_project_routing_routes(app: FastAPI) -> None:
    register_control_error_handlers(app)

    @app.get("/api/v1/projects/{project_id}/routing/order", response_model=ProjectOrderResponse)
    async def get_order(
        request: Request, principal: _Principal, project_id: UUID
    ) -> ProjectOrderResponse:
        return await ProjectRoutingService(control_repository(request)).get(principal, project_id)

    @app.put(
        "/api/v1/projects/{project_id}/routing/order/{operation}",
        response_model=ProjectOrderResponse,
    )
    async def put_order(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        operation: RoutingOperation,
        update: OperationOrderUpdate,
    ) -> ProjectOrderResponse:
        return await ProjectRoutingService(control_repository(request)).set(
            principal, project_id, operation, update
        )
