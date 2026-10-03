"""Offline Behave steps for OpenTelemetry trace observability (search/fetch).

Every scenario runs against stub adapters or an ``httpx.MockTransport``-backed
``KeenableAdapter`` — no live network. Each scenario opens a fresh temporary
SQLite repository (closed and unlinked by ``environment.after_scenario``) and
drives the real FastAPI app through ``TestClient`` inside its lifespan, so the
app-scoped observability runtime exports spans to that scenario's database.
"""

import json
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FAKE_API_KEY = "sk-test-obs-7f3a9c-not-a-real-secret"

_SEARCH_RESULTS = [
    {
        "title": "Consensus algorithms explained",
        "url": "https://docs.freesearch.dev/consensus",
        "snippet": "Raft, Paxos, and where each applies.",
    },
    {
        "title": "Raft vs Paxos",
        "url": "https://docs.freesearch.dev/raft-vs-paxos",
        "snippet": "A practical comparison.",
    },
]
_FETCH_CONTENT = "Extracted article body used only for trace verification."
_FETCH_TITLE = "Example Article"

_LIST_ITEM_KEYS = {
    "trace_id",
    "operation",
    "started_at",
    "duration_ms",
    "provider",
    "outcome",
    "result_count",
    "error",
}


class _TraceStubAdapter(ProviderAdapter):
    """Deterministic stub that returns fixed payloads or raises on demand."""

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        search_urls: tuple[str, ...] = ("https://example.com/stub-result",),
    ) -> None:
        self._name = name
        self._fail = fail
        self._search_urls = search_urls

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail:
            raise RuntimeError(f"Provider {self._name} simulated failure")
        results = [
            SearchResult(
                title=f"{self._name} hit {index}",
                url=url,  # type: ignore[arg-type]
                snippet=f"Snippet {index} from {self._name} with enough detail.",
            )
            for index, url in enumerate(self._search_urls, start=1)
        ]
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=results,
            total_results=len(results),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        if self._fail:
            raise RuntimeError(f"Provider {self._name} simulated failure")
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} document",
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=0)


def _reset_otel_state(context: Any) -> None:
    """Clear scenario-local observability state for isolation."""
    context.otel_app = None
    context.otel_response = None
    context.otel_trace_id = None
    context.otel_wire_requests = []
    context.otel_dashboard_status = None
    context.otel_stats_status = None


def _open_trace_repository(context: Any) -> None:
    """Open a fresh temp repository; ``environment.after_scenario`` cleans it up."""
    _reset_otel_state(context)
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-otel-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = Path(temporary_file.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )


def _mock_search_client(context: Any) -> httpx.AsyncClient:
    """Return a MockTransport client serving two canned search results."""

    def handler(request: httpx.Request) -> httpx.Response:
        context.otel_wire_requests.append(request)
        return httpx.Response(200, json={"results": _SEARCH_RESULTS})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_fetch_client(context: Any) -> httpx.AsyncClient:
    """Return a MockTransport client serving one canned fetch document."""

    def handler(request: httpx.Request) -> httpx.Response:
        context.otel_wire_requests.append(request)
        return httpx.Response(200, json={"content": _FETCH_CONTENT, "title": _FETCH_TITLE})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _keenable_adapter(client: httpx.AsyncClient) -> KeenableAdapter:
    """Build a keyed Keenable adapter so the no-secret assertion is meaningful."""
    return KeenableAdapter(client, api_key=SecretStr(_FAKE_API_KEY))


def _client_for(context: Any) -> TestClient:
    """Open a TestClient that captures handled and unhandled error responses."""
    return TestClient(context.otel_app, raise_server_exceptions=False)


def _post_search(context: Any, query: str, limit: int, *, fanout: bool = False) -> None:
    payload: dict[str, Any] = {"query": query, "limit": limit}
    if fanout:
        payload["fanout"] = True
    with _client_for(context) as client:
        context.otel_response = client.post("/search", json=payload)
    _capture_trace_header(context)


def _post_fetch(context: Any, url: str) -> None:
    with _client_for(context) as client:
        context.otel_response = client.post("/fetch", json={"url": url})
    _capture_trace_header(context)


def _capture_trace_header(context: Any) -> None:
    """Store a well-formed X-Trace-Id for later steps; error responses carry none."""
    trace_id = context.otel_response.headers.get("x-trace-id")
    if trace_id is not None and _TRACE_ID_RE.fullmatch(trace_id) is not None:
        context.otel_trace_id = trace_id


def _get_json(context: Any, path: str, **params: Any) -> Any:
    with _client_for(context) as client:
        response = client.get(path, params=params or None)
    assert response.status_code == 200, f"GET {path} -> {response.status_code}: {response.text}"
    return response.json()


def _get_status(context: Any, path: str) -> Any:
    with _client_for(context) as client:
        return client.get(path)


def _trace_list(context: Any, **params: Any) -> Any:
    return _get_json(context, "/api/v1/traces", **params)


def _trace_detail(context: Any, trace_id: str) -> Any:
    return _get_json(context, f"/api/v1/traces/{trace_id}")


def _spans_by_name(detail: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for span in detail["spans"]:
        grouped.setdefault(span["name"], []).append(span)
    return grouped


def _assert_hierarchy(context: Any, root_name: str, *, expect_adapter_children: bool) -> Any:
    """Assert the required span tree, kinds, parentage, and durations."""
    assert context.otel_trace_id is not None, "no trace id captured for this scenario"
    detail = _trace_detail(context, context.otel_trace_id)
    assert detail["trace_id"] == context.otel_trace_id
    assert re.fullmatch(r"[0-9a-f]{32}", detail["trace_id"]) is not None

    spans = detail["spans"]
    assert len(spans) >= 7, f"expected at least 7 spans, got {len(spans)}"
    by_id = {span["span_id"]: span for span in spans}
    assert len(by_id) == len(spans), "span ids must be unique"

    roots = [span for span in spans if span["parent_span_id"] is None]
    assert len(roots) == 1, f"expected exactly one root span, got {len(roots)}"
    root = roots[0]
    assert root["name"] == root_name
    assert root["kind"] == "server"

    root_children = [span for span in spans if span["parent_span_id"] == root["span_id"]]
    assert {span["name"] for span in root_children} == {
        "freesearch.backend",
        "freesearch.response",
    }
    backend = next(span for span in root_children if span["name"] == "freesearch.backend")

    backend_children = [span for span in spans if span["parent_span_id"] == backend["span_id"]]
    assert {span["name"] for span in backend_children} == {
        "freesearch.route",
        "freesearch.provider",
        "freesearch.results",
    }
    provider = next(span for span in backend_children if span["name"] == "freesearch.provider")
    assert provider["kind"] == "client"

    if expect_adapter_children:
        provider_children = [
            span for span in spans if span["parent_span_id"] == provider["span_id"]
        ]
        assert {span["name"] for span in provider_children} == {
            "freesearch.provider.http",
            "freesearch.provider.parse",
        }
        http_child = next(
            span for span in provider_children if span["name"] == "freesearch.provider.http"
        )
        assert http_child["kind"] == "client"

    for span in spans:
        assert isinstance(span["duration_ms"], int), f"{span['name']} duration not an int"
        assert span["duration_ms"] >= 0, f"{span['name']} has negative duration"
    return detail


@given("an offline trace repository with a mock-transport Keenable search")
def step_given_trace_repo_keenable_search(context: Any) -> None:
    """Open a temp repository and serve search through a MockTransport Keenable adapter."""
    _open_trace_repository(context)
    context.otel_app = create_app(
        [_keenable_adapter(_mock_search_client(context))],
        repository=context.repository,
    )


@given("an offline trace repository with a mock-transport Keenable fetch")
def step_given_trace_repo_keenable_fetch(context: Any) -> None:
    """Open a temp repository and serve fetch through a MockTransport Keenable adapter."""
    _open_trace_repository(context)
    context.otel_app = create_app(
        [_keenable_adapter(_mock_fetch_client(context))],
        repository=context.repository,
    )


@given("an offline trace repository with a failing search provider")
def step_given_trace_repo_failing_search(context: Any) -> None:
    """Open a temp repository with a stub whose search always raises."""
    _open_trace_repository(context)
    context.otel_app = create_app(
        [_TraceStubAdapter("exploding-search", fail=True)],
        repository=context.repository,
    )


@given("an offline trace repository with one failing and one succeeding fanout provider")
def step_given_trace_repo_fanout(context: Any) -> None:
    """Open a temp repository with one failing and one succeeding stub provider."""
    _open_trace_repository(context)
    context.otel_app = create_app(
        [
            _TraceStubAdapter("flaky", fail=True),
            _TraceStubAdapter("reliable", search_urls=("https://example.com/reliable",)),
        ],
        repository=context.repository,
    )


@when('I submit a traced search for "{query}" with limit {limit:d}')
def step_when_traced_search(context: Any, query: str, limit: int) -> None:
    """POST a search through the traced app."""
    _post_search(context, query, limit)


@when('I submit a traced fanout search for "{query}" with limit {limit:d}')
def step_when_traced_fanout_search(context: Any, query: str, limit: int) -> None:
    """POST a fanout search through the traced app."""
    _post_search(context, query, limit, fanout=True)


@when('I submit a traced fetch for "{url}"')
def step_when_traced_fetch(context: Any, url: str) -> None:
    """POST a fetch through the traced app."""
    _post_fetch(context, url)


@when('I submit a traced fetch for "{url}" against a failing provider')
def step_when_traced_fetch_failing(context: Any, url: str) -> None:
    """Rebuild the app with a failing stub and POST a fetch through it."""
    context.otel_app = create_app(
        [_TraceStubAdapter("exploding-fetch", fail=True)],
        repository=context.repository,
    )
    _post_fetch(context, url)


@when("I read the dashboard, stats, and trace endpoints")
def step_when_read_monitoring(context: Any) -> None:
    """Read every own-backend surface that must never create traces."""
    assert context.otel_trace_id is not None, "no traced request happened yet"
    context.otel_dashboard_status = _get_status(context, "/dashboard").status_code
    context.otel_stats_status = _get_status(context, "/stats").status_code
    _trace_list(context)
    _trace_detail(context, context.otel_trace_id)
    assert context.otel_dashboard_status == 200
    assert context.otel_stats_status == 200


@then('the traced search should succeed with provider "{provider}" and {count:d} results')
def step_then_traced_search_success(context: Any, provider: str, count: int) -> None:
    """Verify the search response body carries the stubbed normalized results."""
    response = context.otel_response
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["provider"] == provider
    assert len(body["results"]) == count
    for result in body["results"]:
        assert result["title"], "result title is empty"
        assert str(result["url"]).startswith(("http://", "https://"))
        assert result["snippet"], "result snippet is empty"
    assert body["total_results"] == count


@then("the traced response should carry a trace header matching 32 lowercase hex chars")
def step_then_trace_header(context: Any) -> None:
    """Verify X-Trace-Id is present, well-formed, and stored for later steps."""
    trace_id = context.otel_response.headers.get("x-trace-id")
    assert trace_id is not None, "response is missing the X-Trace-Id header"
    assert _TRACE_ID_RE.fullmatch(trace_id) is not None, f"malformed trace id: {trace_id!r}"
    context.otel_trace_id = trace_id


@then("the trace list should contain exactly {count:d} trace matching the trace header")
@then("the trace list should contain exactly {count:d} traces matching the trace header")
def step_then_trace_list_matches_header(context: Any, count: int) -> None:
    """Verify the list holds one summary row for the traced request, header-matched."""
    body = _trace_list(context)
    assert len(body["items"]) == count, f"expected {count} traces: {body['items']}"
    assert body["items"][0]["trace_id"] == context.otel_trace_id


@then('the trace list should contain exactly {count:d} trace with outcome "{outcome}"')
@then('the trace list should contain exactly {count:d} traces with outcome "{outcome}"')
def step_then_trace_list_outcome(context: Any, count: int, outcome: str) -> None:
    """Verify the list holds one summary row with the expected outcome."""
    body = _trace_list(context, outcome=outcome)
    assert len(body["items"]) == count, f"expected {count} traces: {body['items']}"
    assert body["items"][0]["outcome"] == outcome
    context.otel_trace_id = body["items"][0]["trace_id"]


@then("the trace list should still contain exactly {count:d} trace")
@then("the trace list should still contain exactly {count:d} traces")
def step_then_trace_list_still(context: Any, count: int) -> None:
    """Verify untraced reads did not add traces."""
    body = _trace_list(context)
    assert len(body["items"]) == count, f"expected {count} traces: {body['items']}"


@then('the trace detail should show the full query "{query}" with {count:d} normalized results')
def step_then_trace_detail_query(context: Any, query: str, count: int) -> None:
    """Verify the detail carries the full query and normalized results, list does not."""
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    assert detail["operation"] == "search"
    assert detail["outcome"] == "success"
    assert detail["provider"] == "keenable"
    assert detail["result_count"] == count
    assert detail["input"] == query
    assert detail["output"]["kind"] == "search_results"
    assert detail["output"]["query"] == query
    assert len(detail["output"]["results"]) == count
    for actual, expected in zip(detail["output"]["results"], _SEARCH_RESULTS, strict=True):
        assert actual["title"] == expected["title"]
        assert actual["url"] == expected["url"]
        assert actual["snippet"] == expected["snippet"]

    listing = _trace_list(context)
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert set(item) == _LIST_ITEM_KEYS, f"list row is not summary-only: {sorted(item)}"
    list_text = json.dumps(listing)
    assert query not in list_text, "full query leaked into the trace list"
    for expected in _SEARCH_RESULTS:
        assert expected["url"] not in list_text, "result URL leaked into the trace list"


@then(
    "the search trace detail should show the required search span hierarchy "
    "with non-negative durations"
)
def step_then_search_hierarchy(context: Any) -> None:
    """Verify the full search span tree including Keenable HTTP/parse children."""
    _assert_hierarchy(context, "POST /search", expect_adapter_children=True)


@then(
    "the fetch trace detail should show the required fetch span hierarchy "
    "with non-negative durations"
)
def step_then_fetch_hierarchy(context: Any) -> None:
    """Verify the full fetch span tree including Keenable HTTP/parse children."""
    detail = _assert_hierarchy(context, "POST /fetch", expect_adapter_children=True)
    assert detail["operation"] == "fetch"
    assert detail["outcome"] == "success"
    assert detail["output"]["kind"] == "fetch_document"


@then("the stored trace should contain no secret values")
def step_then_no_secrets(context: Any) -> None:
    """Verify the fake key rode the wire but never reached the stored trace."""
    assert context.otel_wire_requests, "mock transport saw no request"
    assert any(
        request.headers.get("X-API-Key") == _FAKE_API_KEY for request in context.otel_wire_requests
    ), "fake API key was not sent on the wire; the redaction check is vacuous"
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    dump = json.dumps(detail)
    assert _FAKE_API_KEY not in dump, "API key leaked into the stored trace"
    assert "X-API-Key" not in dump, "credential header name leaked into the stored trace"
    assert "Authorization" not in dump, "auth header name leaked into the stored trace"


@then("the traced search should fail with status {code:d} and no fabricated results")
def step_then_traced_search_failure(context: Any, code: int) -> None:
    """Verify the existing HTTP failure behavior is preserved (no invented results)."""
    response = context.otel_response
    assert response.status_code == code, (
        f"expected {code}, got {response.status_code}: {response.text}"
    )
    assert "results" not in response.text, "failure response fabricates results"


@then('the error trace detail should show root and provider ERROR with error type "{error_type}"')
def step_then_error_trace_type(context: Any, error_type: str) -> None:
    """Verify root and provider spans are ERROR with a low-cardinality type."""
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    assert detail["outcome"] == "error"
    assert detail["error"] is not None
    assert detail["error"]["type"] == error_type
    assert detail["output"] is None, "error trace fabricates output"
    assert detail["result_count"] is None, "error trace fabricates a result count"

    grouped = _spans_by_name(detail)
    roots = [span for span in detail["spans"] if span["parent_span_id"] is None]
    assert len(roots) == 1
    assert roots[0]["outcome"] == "error"
    providers = grouped.get("freesearch.provider", [])
    assert len(providers) == 1
    assert providers[0]["outcome"] == "error"
    assert providers[0]["error"] is not None
    assert providers[0]["error"]["type"] == error_type
    assert " " not in error_type, "error.type must be low-cardinality (no spaces)"


@then("the error trace detail should contain exactly one exception event")
def step_then_single_exception_event(context: Any) -> None:
    """Verify exactly one standard exception event sits on the failing provider span."""
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    exception_holders = [
        span
        for span in detail["spans"]
        if any(event["name"] == "exception" for event in span["events"])
    ]
    assert len(exception_holders) == 1, (
        f"expected exactly one span with an exception event: "
        f"{[span['name'] for span in exception_holders]}"
    )
    assert exception_holders[0]["name"] == "freesearch.provider"


@then("the traced fanout search should succeed with the surviving provider results")
def step_then_fanout_success(context: Any) -> None:
    """Verify the fanout request succeeds off the surviving provider."""
    response = context.otel_response
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["provider"] == "reliable"
    assert body["participating_providers"] == ["reliable"]
    assert len(body["results"]) == 1
    assert body["results"][0]["url"] == "https://example.com/reliable"
    trace_id = response.headers.get("x-trace-id")
    assert trace_id is not None, "fanout response is missing the X-Trace-Id header"
    assert _TRACE_ID_RE.fullmatch(trace_id) is not None
    context.otel_trace_id = trace_id


@then("the fanout trace detail should show one root with {count:d} sibling provider spans")
def step_then_fanout_siblings(context: Any, count: int) -> None:
    """Verify one root, N sibling provider spans, and a single assembly span."""
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    spans = detail["spans"]
    roots = [span for span in spans if span["parent_span_id"] is None]
    assert len(roots) == 1, "fanout must produce a single root, never one trace per provider"
    assert roots[0]["name"] == "POST /search"
    grouped = _spans_by_name(detail)
    assert len(grouped.get("freesearch.provider", [])) == count
    assert len(grouped.get("freesearch.results", [])) == 1, "expected one assembly span"
    providers = grouped["freesearch.provider"]
    parents = {span["parent_span_id"] for span in providers}
    assert len(parents) == 1, "provider spans must be siblings under one parent"
    backend = next(span for span in spans if span["span_id"] in parents)
    assert backend["name"] == "freesearch.backend"


@then('the fanout trace detail should show outcome "{outcome}" with the failed provider in ERROR')
def step_then_fanout_partial(context: Any, outcome: str) -> None:
    """Verify partial outcome: failed child ERROR, request-level success."""
    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    assert detail["outcome"] == outcome
    assert detail["error"] is None, "a partial request must not carry a request-level error"
    grouped = _spans_by_name(detail)
    outcomes = sorted(span["outcome"] for span in grouped["freesearch.provider"])
    assert outcomes == ["error", "success"], f"expected one failed child: {outcomes}"
    failed = next(span for span in grouped["freesearch.provider"] if span["outcome"] == "error")
    assert failed["error"] is not None
    exception_total = sum(
        1 for span in detail["spans"] for event in span["events"] if event["name"] == "exception"
    )
    assert exception_total == 1, f"expected one exception event, got {exception_total}"


@then("an unknown trace id should return 404 without creating a trace")
def step_then_unknown_trace_404(context: Any) -> None:
    """Verify absent/invalid ids 404 and do not create traces."""
    for bad_id in ("not-a-trace-id", "0" * 32):
        response = _get_status(context, f"/api/v1/traces/{bad_id}")
        assert response.status_code == 404, f"{bad_id} -> {response.status_code}"
    body = _trace_list(context)
    assert len(body["items"]) == 1


@then("the traced fetch should succeed with the stubbed document content")
def step_then_traced_fetch_success(context: Any) -> None:
    """Verify the fetch response body carries the stubbed document."""
    response = context.otel_response
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["provider"] == "keenable"
    assert body["document"]["content"] == _FETCH_CONTENT
    trace_id = response.headers.get("x-trace-id")
    assert trace_id is not None, "fetch response is missing the X-Trace-Id header"
    assert _TRACE_ID_RE.fullmatch(trace_id) is not None
    context.otel_trace_id = trace_id

    assert context.otel_trace_id is not None
    detail = _trace_detail(context, context.otel_trace_id)
    assert detail["operation"] == "fetch"
    assert detail["result_count"] == 1
    assert detail["input"] == "https://example.com/article"
    assert detail["output"]["kind"] == "fetch_document"
    assert detail["output"]["content"] == _FETCH_CONTENT


@then(
    "the traced fetch should fail with status {code:d} "
    'and an error trace with error type "{error_type}"'
)
def step_then_traced_fetch_failure(context: Any, code: int, error_type: str) -> None:
    """Verify fetch errors mirror the search error contract."""
    response = context.otel_response
    assert response.status_code == code, (
        f"expected {code}, got {response.status_code}: {response.text}"
    )
    assert "content" not in response.text, "failure response fabricates content"
    body = _trace_list(context, operation="fetch", outcome="error")
    assert len(body["items"]) == 1, f"expected one fetch error trace: {body['items']}"
    detail = _trace_detail(context, body["items"][0]["trace_id"])
    assert detail["outcome"] == "error"
    assert detail["error"] is not None
    assert detail["error"]["type"] == error_type
    assert detail["output"] is None
