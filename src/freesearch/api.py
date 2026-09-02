"""REST API for the FreeSearch providers: FastAPI app with OpenAPI docs.

Thin HTTP layer over the same composition root as the MCP server: adapters are
built in configured priority order and every request is routed through
:func:`freesearch.routing.select_route`. Responses are the provider-neutral
contract models, so the OpenAPI schema at ``/docs`` documents them directly.
"""

from collections.abc import Sequence

from fastapi import FastAPI, HTTPException

from freesearch.adapters.base import ProviderAdapter
from freesearch.contracts import FetchRequest, FetchResponse, SearchRequest, SearchResponse
from freesearch.routing import RoutingError, select_route
from freesearch.server import build_adapters


def create_app(adapters: Sequence[ProviderAdapter] | None = None) -> FastAPI:
    """Create the FastAPI app routing every operation to a configured adapter."""

    app = FastAPI(title="FreeSearch", version="0.1.0")
    routes = list(adapters) if adapters is not None else build_adapters()

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
        return await _route(request).search(request)

    @app.post("/fetch", response_model=FetchResponse)
    async def fetch(request: FetchRequest) -> FetchResponse:
        """Fetch a URL's content through the best available provider."""
        return await _route(request).fetch(request)

    return app


def main() -> None:
    """Serve the API with uvicorn on loopback:8001 (Swagger at /docs)."""
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
