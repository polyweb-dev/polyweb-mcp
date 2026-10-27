"""Project retention HTTP surface (TASK-000044).

Thin transport only. The project id comes from the URL, the service enforces
the live project ``settings.write`` permission, and the response never carries
another project's data. Control-plane error handlers map not-found, denied,
invalid, conflict, and storage failures to the shared safe responses.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status

from freesearch.models.retention import RetentionRunRead, RetentionRunRequest
from freesearch.models.users import UserPrincipal
from freesearch.routers.auth import current_principal
from freesearch.services.retention import ProjectRetentionService
from freesearch.services.users import AuthService

_Principal = Annotated[UserPrincipal, Depends(current_principal)]


def _retention_service(request: Request) -> ProjectRetentionService:
    """Return the retention service over the app's shared repository."""

    account_service = getattr(request.app.state, "auth_service", None)
    if not isinstance(account_service, AuthService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retention is not configured",
        )
    repository = account_service.repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="retention is not configured",
        )
    return ProjectRetentionService(repository)


def register_retention_routes(app: FastAPI) -> None:
    """Register the explicit project retention route on ``app``."""

    @app.post(
        "/api/v1/projects/{project_id}/retention/runs",
        response_model=RetentionRunRead,
    )
    async def run_project_retention(
        request: Request,
        principal: _Principal,
        project_id: UUID,
        body: RetentionRunRequest,
    ) -> RetentionRunRead:
        """Purge one data class of this project older than the cutoff."""

        return await _retention_service(request).run(principal, project_id, body)


__all__ = ["register_retention_routes"]
