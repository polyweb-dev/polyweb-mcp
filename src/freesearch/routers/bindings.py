"""Read-only project provider and owner-filtered binding projections."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request

from freesearch.configuration.provider_config import ProviderConfig
from freesearch.models.projects import ProjectBindingRead
from freesearch.models.providers import ProjectProvidersRead
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


__all__ = ["register_binding_routes"]
