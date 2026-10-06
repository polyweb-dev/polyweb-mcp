"""Unit tests for the shared trace payload helpers (P5).

These helpers are pure projections between the provider contracts and the
root-span attributes. No test touches the network or the database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from freesearch.infrastructure.trace_payloads import (
    _annotate_root,
    _annotate_root_error,
    _operation_name,
    _request_attributes,
    _search_results_payload,
)
from freesearch.models.contracts import (
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from freesearch.models.observability import TraceAttribute, TraceOperation


class _RecordingRuntime:
    """Minimal runtime double that captures root annotations."""

    def __init__(self) -> None:
        self.annotations: list[dict[str, Any]] = []

    def annotate_root(self, attributes: dict[str, Any]) -> None:
        self.annotations.append(dict(attributes))


def _search_pair() -> tuple[SearchRequest, SearchResponse]:
    request = SearchRequest(query="consensus")
    response = SearchResponse(
        query="consensus",
        provider="keenable",
        results=[
            SearchResult(
                title="Consensus",
                url="https://example.com/consensus",
                snippet="Raft and Paxos.",
            )
        ],
        total_results=1,
    )
    return request, response


def _fetch_pair() -> tuple[FetchRequest, FetchResponse]:
    request = FetchRequest(url="https://example.com/page")
    response = FetchResponse(
        provider="keenable",
        document=FetchedDocument(
            url="https://example.com/page",
            content="hello world",
            fetched_at=datetime.now(UTC),
        ),
    )
    return request, response


def test_operation_name_follows_request_type() -> None:
    search, _ = _search_pair()
    fetch, _ = _fetch_pair()

    assert _operation_name(search) is TraceOperation.SEARCH
    assert _operation_name(fetch) is TraceOperation.FETCH


def test_request_attributes_carry_operation_routing_and_bound() -> None:
    search, _ = _search_pair()
    fetch, _ = _fetch_pair()

    search_attributes = _request_attributes(search)
    assert search_attributes[TraceAttribute.OPERATION] == "search"
    assert search_attributes[TraceAttribute.REQUEST_LIMIT] == search.limit

    fetch_attributes = _request_attributes(fetch)
    assert fetch_attributes[TraceAttribute.OPERATION] == "fetch"
    assert fetch_attributes[TraceAttribute.REQUEST_LIMIT] == fetch.max_chars


def test_search_results_payload_projects_each_result() -> None:
    _, response = _search_pair()

    (payload,) = _search_results_payload(response)

    assert payload.title == "Consensus"
    assert payload.url == "https://example.com/consensus"
    assert payload.snippet == "Raft and Paxos."


def test_annotate_search_root_writes_summary_attributes() -> None:
    runtime = _RecordingRuntime()
    request, response = _search_pair()

    _annotate_root(runtime, request, response)  # type: ignore[arg-type]

    (attributes,) = runtime.annotations
    assert attributes[TraceAttribute.OPERATION] == "search"
    assert attributes[TraceAttribute.PROVIDER] == "keenable"
    assert attributes[TraceAttribute.REQUEST_QUERY] == "consensus"
    assert attributes[TraceAttribute.RESPONSE_RESULT_COUNT] == 1
    output = json.loads(attributes[TraceAttribute.RESPONSE_OUTPUT_JSON])
    assert output["kind"] == "search_results"
    assert output["results"][0]["title"] == "Consensus"


def test_annotate_fetch_root_writes_summary_attributes() -> None:
    runtime = _RecordingRuntime()
    request, response = _fetch_pair()

    _annotate_root(runtime, request, response)  # type: ignore[arg-type]

    (attributes,) = runtime.annotations
    assert attributes[TraceAttribute.OPERATION] == "fetch"
    assert attributes[TraceAttribute.PROVIDER] == "keenable"
    assert attributes[TraceAttribute.REQUEST_URL] == "https://example.com/page"
    assert attributes[TraceAttribute.RESPONSE_RESULT_COUNT] == 1
    output = json.loads(attributes[TraceAttribute.RESPONSE_OUTPUT_JSON])
    assert output["kind"] == "fetch_document"
    assert output["content"] == "hello world"


def test_annotate_root_ignores_mismatched_pairs() -> None:
    runtime = _RecordingRuntime()
    search, _ = _search_pair()
    _, fetch_response = _fetch_pair()

    _annotate_root(runtime, search, fetch_response)  # type: ignore[arg-type]

    assert runtime.annotations == []


def test_annotate_root_error_marks_type_and_message() -> None:
    runtime = _RecordingRuntime()
    error = RuntimeError("provider exploded")

    _annotate_root_error(runtime, error)  # type: ignore[arg-type]

    (attributes,) = runtime.annotations
    assert attributes[TraceAttribute.ERROR_TYPE] == "RuntimeError"
    assert attributes[TraceAttribute.ERROR_MESSAGE] == "provider exploded"


def test_output_projection_keeps_provider_contracts() -> None:
    _, search_response = _search_pair()
    _, fetch_response = _fetch_pair()

    assert search_response.model_dump(mode="json")["results"][0]["title"] == "Consensus"
    assert fetch_response.model_dump(mode="json")["document"]["content"] == "hello world"
