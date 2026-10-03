"""Trace read API: the Activity page's list and detail endpoints.

Transport only: validate the request, call
:mod:`freesearch.services.observability`, and return the contract models. These
routes are never traced themselves (they are own-backend reads, not provider
queries), so paging Activity can never create traces to page.
"""

from fastapi import FastAPI, HTTPException, Request

from freesearch.models.observability import (
    TraceDetail,
    TraceListResponse,
    TraceOperation,
    TraceOutcome,
)
from freesearch.services.observability import (
    DEFAULT_TRACE_LIMIT,
    get_trace_detail,
    list_traces,
)


def register_observability_routes(app: FastAPI) -> None:
    """Register the read-only trace endpoints on ``app`` under ``/api/v1``."""

    @app.get("/api/v1/traces", response_model=TraceListResponse)
    async def traces(
        request: Request,
        limit: int = DEFAULT_TRACE_LIMIT,
        operation: TraceOperation | None = None,
        outcome: TraceOutcome | None = None,
    ) -> TraceListResponse:
        """List newest-first trace summaries; never includes query or output."""

        return await list_traces(
            request.app.state.repository,
            limit=limit,
            operation=operation,
            outcome=outcome,
        )

    @app.get("/api/v1/traces/{trace_id}", response_model=TraceDetail)
    async def trace_detail(trace_id: str, request: Request) -> TraceDetail:
        """Return one trace's full input, results, and stage timeline."""

        detail = await get_trace_detail(request.app.state.repository, trace_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no trace for {trace_id!r}")
        return detail
