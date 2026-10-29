"""Project provider bindings and provider view HTTP surface (A4).

Thin transport over :class:`~freesearch.services.provider_bindings.ProviderBindingService`::

    GET    /api/v1/projects/{project_id}/providers               providers.read
    GET    /api/v1/projects/{project_id}/bindings                providers.read
    POST   /api/v1/projects/{project_id}/bindings                providers.configure (201)
    PATCH  /api/v1/projects/{project_id}/bindings/{binding_id}   providers.configure
    DELETE /api/v1/projects/{project_id}/bindings/{binding_id}   providers.configure (204)

Human session principals only. An unknown project, or one the caller is not
an active member of, is HTTP 404; a member without the permission is 403. A
new binding always starts with no enabled operations; sending
``enabled_operations`` on create is rejected with 422.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response, status

from freesearch.configuration.provider_config import ProviderConfig
from freesearch.models.projects import ProjectBindingRead
from freesearch.models.providers import BindingCreate, BindingUpdate, ProjectProvidersRead
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.routers.control_errors import control_repository, register_control_error_handlers
from freesearch.services.provider_bindings import ProviderBindingService
from freesearch.services.provider_runtime import effective_config_for_name

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _binding_service(request: Request) -> ProviderBindingService:
    repository = control_repository(request)

    async def provider_config(provider_type: str) -> ProviderConfig:
        return await effective_config_for_name(repository, provider_type)

    return ProviderBindingService(repository, provider_config=provider_config)


def register_binding_routes(app: FastAPI) -> None:
    """Register the project binding and provider view routes on ``app``."""

    register_control_error_handlers(app)

    @app.get(
        "/api/v1/projects/{project_id}/providers",
        response_model=ProjectProvidersRead,
    )
    async def get_project_providers(
        request: Request, principal: _Principal, project_id: UUID
    ) -> ProjectProvidersRead:
        """Available credentials versus enabled bindings, per provider type."""

        return await _binding_service(request).project_providers(principal, project_id)

    @app.get(
        "/api/v1/projects/{project_id}/bindings",
        response_model=list[ProjectBindingRead],
    )
    async def list_project_bindings(
        request: Request, principal: _Principal, project_id: UUID
    ) -> list[ProjectBindingRead]:
        """List this project's bindings."""

        return await _binding_service(request).list_bindings(principal, project_id)

    @app.post(
        "/api/v1/projects/{project_id}/bindings",
        response_model=ProjectBindingRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_project_binding(
        request: Request, principal: _Principal, project_id: UUID, body: BindingCreate
    ) -> ProjectBindingRead:
        """Bind a private or granted credential; it starts disabled."""

        return await _binding_service(request).create_binding(principal, project_id, body)

    @app.patch(
        "/api/v1/projects/{project_id}/bindings/{binding_id}",
        response_model=ProjectBindingRead,
    )
    async def update_project_binding(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        binding_id: UUID,
        body: BindingUpdate,
    ) -> ProjectBindingRead:
        """Change enabled operations, priority or route label."""

        return await _binding_service(request).update_binding(
            principal, project_id, binding_id, body
        )

    @app.delete(
        "/api/v1/projects/{project_id}/bindings/{binding_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_project_binding(
        request: Request, principal: _Principal, project_id: UUID, binding_id: UUID
    ) -> Response:
        """Remove one binding."""

        await _binding_service(request).delete_binding(principal, project_id, binding_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["register_binding_routes"]
