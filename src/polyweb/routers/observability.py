"""Project-scoped Activity and usage read API (TASK-000044).

Transport only: validate the request, read the verified account from the
request, call the project read services, and return the contract models. The
project id in the path is the only ownership selector: never a query parameter,
a body, or a header. These routes are never traced themselves (they are
own-backend reads, not provider queries), so paging Activity can never create
traces to page.
"""

from uuid import UUID

from fastapi import FastAPI, HTTPException, Request

from polyweb.models.observability import (
    TraceDetail,
    TraceListResponse,
    TraceOperation,
    TraceOutcome,
)
from polyweb.routers.auth import current_principal
from polyweb.services.monitoring import (
    DEFAULT_RECENT_LIMIT,
    ProjectUsageResponse,
    collect_project_usage,
)
from polyweb.services.observability import (
    DEFAULT_TRACE_LIMIT,
    get_project_trace,
    list_project_traces,
)


def register_observability_routes(app: FastAPI) -> None:
    """Register the project-scoped trace, usage, and dashboard reads on ``app``."""

    @app.get(
        "/api/v1/projects/{project_id}/traces",
        response_model=TraceListResponse,
    )
    async def project_traces(
        project_id: UUID,
        request: Request,
        limit: int = DEFAULT_TRACE_LIMIT,
        operation: TraceOperation | None = None,
        outcome: TraceOutcome | None = None,
        cursor: str | None = None,
    ) -> TraceListResponse:
        """List one authorized project's newest-first trace summaries."""

        principal = current_principal(request)
        return await list_project_traces(
            request.app.state.repository,
            principal,
            project_id,
            limit=limit,
            operation=operation,
            outcome=outcome,
            cursor=cursor,
        )

    @app.get(
        "/api/v1/projects/{project_id}/traces/{trace_id}",
        response_model=TraceDetail,
    )
    async def project_trace_detail(
        project_id: UUID, trace_id: str, request: Request
    ) -> TraceDetail:
        """Return one trace of the authorized project, else a non-revealing 404."""

        principal = current_principal(request)
        detail = await get_project_trace(
            request.app.state.repository,
            principal,
            project_id,
            trace_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no trace for {trace_id!r}")
        return detail

    @app.get(
        "/api/v1/projects/{project_id}/usage",
        response_model=ProjectUsageResponse,
    )
    async def project_usage(
        project_id: UUID,
        request: Request,
        limit: int = DEFAULT_RECENT_LIMIT,
    ) -> ProjectUsageResponse:
        """Return one authorized project's usage totals and recent ledger."""

        principal = current_principal(request)
        return await collect_project_usage(
            request.app.state.repository,
            principal,
            project_id,
            recent_limit=limit,
        )

    @app.get(
        "/api/v1/projects/{project_id}/dashboard",
        response_model=ProjectUsageResponse,
    )
    async def project_dashboard(
        project_id: UUID,
        request: Request,
        limit: int = DEFAULT_RECENT_LIMIT,
    ) -> ProjectUsageResponse:
        """Return one authorized project's dashboard snapshot.

        Provider quota and health are shared, installation-wide observations
        with no project owner, so the project dashboard is its own usage only;
        it never exposes another project's credential state.
        """

        principal = current_principal(request)
        return await collect_project_usage(
            request.app.state.repository,
            principal,
            project_id,
            recent_limit=limit,
        )


__all__ = ["register_observability_routes"]
