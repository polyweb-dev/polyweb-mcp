"""REST API for the FreeSearch providers: FastAPI app with OpenAPI docs.

Thin HTTP layer over the same composition root as the MCP server: adapters are
built in configured priority order and every request is routed through
:func:`freesearch.routing.select_route`. Responses are the provider-neutral
contract models, so the OpenAPI schema at ``/docs`` documents them directly.

Every search/fetch call also records read-only local telemetry (usage and
health observations) through :mod:`freesearch.monitoring`, and the loopback
monitoring reads (``/stats``, ``/dashboard``) expose that telemetry.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import FetchRequest, FetchResponse, SearchRequest, SearchResponse
from freesearch.http import create_async_client
from freesearch.monitoring import (
    MAX_RECENT_LIMIT,
    StatsResponse,
    collect_stats,
    render_dashboard,
    resolve_database_path,
    tracked_call,
)
from freesearch.routing import RoutingError, select_route
from freesearch.server import build_adapters, close_adapters
from freesearch.storage import SQLiteRepository


def create_app(
    adapters: Sequence[ProviderAdapter] | None = None,
    repository: SQLiteRepository | None = None,
    *,
    database: str | Path | None = None,
) -> FastAPI:
    """Create the FastAPI app routing every operation to a configured adapter."""

    owns_client = adapters is None
    client = create_async_client() if owns_client else None
    routes = list(adapters) if adapters is not None else build_adapters(client)
    # The repository is owned only when neither adapters nor a repository was
    # injected: the composition root then opens (and closes) its own database.
    owns_repository = repository is None and adapters is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repo: SQLiteRepository | None = app.state.repository
        try:
            if owns_repository:
                repo = await SQLiteRepository.open(resolve_database_path(database))
                app.state.repository = repo
            yield
        finally:
            if owns_repository and repo is not None:
                app.state.repository = None
                await repo.close()
            await close_adapters(routes, client if owns_client else None)

    app = FastAPI(title="FreeSearch", version="0.1.0", lifespan=lifespan)
    app.state.repository = repository

    def _route(request: SearchRequest | FetchRequest) -> ProviderAdapter:
        if not routes:
            raise HTTPException(
                status_code=503, detail="no provider is configured: set a FREESEARCH_*_API_KEY"
            )
        try:
            return select_route(request, routes, {}, {})[0].adapter
        except RoutingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest) -> SearchResponse:
        """Search the web through the best available provider."""
        adapter = _route(request)
        return await tracked_call(
            app.state.repository, adapter, lambda target: target.search(request)
        )

    @app.post("/fetch", response_model=FetchResponse)
    async def fetch(request: FetchRequest) -> FetchResponse:
        """Fetch a URL's content through the best available provider."""
        adapter = _route(request)
        return await tracked_call(
            app.state.repository, adapter, lambda target: target.fetch(request)
        )

    @app.get("/stats", response_model=StatsResponse)
    async def stats(limit: int = 20) -> StatsResponse:
        """Return the read-only, local-observed monitoring snapshot."""
        return await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(limit: int = 20) -> HTMLResponse:
        """Render the read-only, local-observed monitoring dashboard."""
        snapshot = await collect_stats(
            app.state.repository,
            adapter_names=[adapter.name for adapter in routes],
            recent_limit=_clamped_limit(limit),
        )
        return HTMLResponse(render_dashboard(snapshot), media_type="text/html; charset=utf-8")

    return app


def _clamped_limit(limit: int) -> int:
    """Clamp a requested recent-usage limit into ``[1, MAX_RECENT_LIMIT]``."""

    return min(max(limit, 1), MAX_RECENT_LIMIT)


def main() -> None:
    """Serve the API with uvicorn on loopback:8001 (Swagger at /docs)."""
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
