"""Transport-neutral trace payload helpers shared by the API and the MCP tools.

These helpers are pure projections between the request/response contracts and
the root-span attributes the exporter turns into the Activity summary. They live
in infrastructure rather than in a router module, so both transports record the
same summary shape and neither transport imports the other.

The root span is the summary source: operation, provider, input text, result
count, partial flag, and the tagged output payload the trace read API serves
back. Child spans keep their own low-cardinality attributes.
"""

from typing import Any

from freesearch.infrastructure.observability import ObservabilityRuntime, error_type_of
from freesearch.models.contracts import (
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
)
from freesearch.models.observability import (
    TraceAttribute,
    TraceFetchOutput,
    TraceOperation,
    TraceSearchOutput,
    TraceSearchResult,
)


def _operation_name(request: SearchRequest | FetchRequest) -> TraceOperation:
    """Return the trace operation for a provider-querying request."""

    return TraceOperation.SEARCH if isinstance(request, SearchRequest) else TraceOperation.FETCH


def _request_attributes(request: SearchRequest | FetchRequest) -> dict[str, Any]:
    """Provider-neutral request shape for backend/route span attributes."""

    attributes: dict[str, Any] = {
        TraceAttribute.OPERATION: _operation_name(request).value,
        TraceAttribute.ROUTING_MODE: request.routing.mode.value,
    }
    attributes[TraceAttribute.REQUEST_LIMIT] = (
        request.limit if isinstance(request, SearchRequest) else request.max_chars
    )
    return attributes


def _search_results_payload(response: SearchResponse) -> list[TraceSearchResult]:
    """Normalized results out, in the one shape the trace read API serves."""

    return [
        TraceSearchResult(
            title=result.title,
            url=str(result.url),
            snippet=result.snippet,
            source=result.source,
            score=result.score,
        )
        for result in response.results
    ]


def _annotate_root_error(observability: ObservabilityRuntime, error: BaseException) -> None:
    """Mark the root span as failed with a low-cardinality type and message.

    FastAPI turns an unhandled handler failure into a response inside the app, so
    the root span would otherwise look successful; annotating the error keeps
    the Activity row honest (and the failing child keeps the exception event).
    """

    observability.annotate_root(
        {
            TraceAttribute.ERROR_TYPE: error_type_of(error),
            TraceAttribute.ERROR_MESSAGE: str(error),
        }
    )


def _annotate_root(
    observability: ObservabilityRuntime,
    request: SearchRequest | FetchRequest,
    response: SearchResponse | FetchResponse,
) -> None:
    """Project the request/response onto the root span (the exporter's summary).

    Root attributes are the single source of the Activity summary row: the
    operation, provider, input text, result count, partial flag, and the tagged
    output payload the trace read API serves back.
    """

    if isinstance(request, SearchRequest) and isinstance(response, SearchResponse):
        _annotate_search_root(observability, request, response)
    elif isinstance(request, FetchRequest) and isinstance(response, FetchResponse):
        _annotate_fetch_root(observability, request, response)


def _annotate_search_root(
    observability: ObservabilityRuntime, request: SearchRequest, response: SearchResponse
) -> None:
    """Annotate the root span of a search request."""

    output = TraceSearchOutput(query=response.query, results=_search_results_payload(response))
    observability.annotate_root(
        {
            TraceAttribute.OPERATION: TraceOperation.SEARCH.value,
            TraceAttribute.PROVIDER: response.provider,
            TraceAttribute.REQUEST_QUERY: request.query,
            TraceAttribute.REQUEST_LIMIT: request.limit,
            TraceAttribute.RESPONSE_RESULT_COUNT: len(response.results),
            TraceAttribute.RESPONSE_PARTIAL: any(item.error for item in response.waterfall),
            TraceAttribute.RESPONSE_OUTPUT_JSON: output.model_dump_json(),
        }
    )


def _annotate_fetch_root(
    observability: ObservabilityRuntime, request: FetchRequest, response: FetchResponse
) -> None:
    """Annotate the root span of a fetch request."""

    document = response.document
    output = TraceFetchOutput(
        url=str(document.url),
        title=document.title,
        content=document.content,
        content_length=len(document.content),
        truncated=bool(document.metadata.get("truncated")),
    )
    observability.annotate_root(
        {
            TraceAttribute.OPERATION: TraceOperation.FETCH.value,
            TraceAttribute.PROVIDER: response.provider,
            TraceAttribute.REQUEST_URL: str(request.url),
            TraceAttribute.REQUEST_LIMIT: request.max_chars,
            TraceAttribute.RESPONSE_RESULT_COUNT: 1,
            TraceAttribute.RESPONSE_PARTIAL: False,
            TraceAttribute.RESPONSE_OUTPUT_JSON: output.model_dump_json(),
        }
    )


__all__ = [
    "_annotate_root",
    "_annotate_root_error",
    "_operation_name",
    "_request_attributes",
    "_search_results_payload",
]
