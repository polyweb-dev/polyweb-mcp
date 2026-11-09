"""Provider-neutral trace contracts for persisted OpenTelemetry spans.

Pure data: no OpenTelemetry, database, or transport imports. The vocabulary
here is shared by the instrumentation facade
(:mod:`polyweb.infrastructure.observability`), the SQLite span exporter
(:mod:`polyweb.persistence.otel_exporter`), and the read API
(:mod:`polyweb.services.observability`), so call sites never depend on the
SDK or on a vendor exporter.

``TraceOperation`` is the operation seam: a future Answer operation is added
as one more member (plus its own read shape) without touching the exporter or
the storage schema.
"""

from enum import StrEnum
from re import Pattern, compile
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, TypeAdapter, ValidationError

from polyweb.models.contracts import ContractModel


class ActorType(StrEnum):
    """Execution principal class recorded on usage and trace rows."""

    HUMAN = "human"
    PROJECT_API_KEY = "project_api_key"


class ExecutionAttribution(ContractModel):
    """Trusted project and actor identity stamped on execution telemetry.

    Built only by the execution boundary from a verified principal and an
    authorized project context; callers can never supply it through span
    attributes or request payloads.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    actor_type: ActorType
    actor_id: UUID


class AttemptBinding(ContractModel):
    """The project binding, credential instance, and pool one attempt used.

    Built only by the execution service after the binding and credential
    checks pass, so telemetry can attribute every usage row, health
    observation, quota snapshot, admission, and rate attempt to the exact
    credential that served it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID
    credential_id: UUID
    pool_id: UUID | None = None


class TraceOperation(StrEnum):
    """Operation that produced a trace (the future-Answer expansion seam)."""

    SEARCH = "search"
    FETCH = "fetch"


class TraceOutcome(StrEnum):
    """Coarse trace result used by the Activity list and its filters."""

    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


class TraceSpanKind(StrEnum):
    """Span kind, stored as a stable lowercase label."""

    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"


class TraceStatusCode(StrEnum):
    """Projected OpenTelemetry span status."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class TraceAttribute:
    """Attribute key vocabulary shared with the exporter's root projection.

    Keys follow the OpenTelemetry HTTP semantic conventions where they apply
    and are provider-neutral ``polyweb.*`` keys otherwise, so another
    exporter (OTLP/Langfuse/LangSmith) can consume the same spans unchanged.
    """

    SCHEMA_VERSION: Final[str] = "polyweb.trace.schema_version"
    OPERATION: Final[str] = "polyweb.operation.name"
    USER_ID: Final[str] = "polyweb.user.id"
    PROJECT_ID: Final[str] = "polyweb.project.id"
    ACTOR_TYPE: Final[str] = "polyweb.actor.type"
    ACTOR_ID: Final[str] = "polyweb.actor.id"
    PROVIDER: Final[str] = "polyweb.provider.name"
    ROUTING_MODE: Final[str] = "polyweb.routing.mode"
    ROUTING_CANDIDATE_COUNT: Final[str] = "polyweb.routing.candidate_count"
    REQUEST_QUERY: Final[str] = "polyweb.request.query"
    REQUEST_URL: Final[str] = "polyweb.request.url"
    REQUEST_LIMIT: Final[str] = "polyweb.request.limit"
    RESPONSE_RESULT_COUNT: Final[str] = "polyweb.response.result_count"
    RESPONSE_CONTENT_LENGTH: Final[str] = "polyweb.response.content_length"
    RESPONSE_PARTIAL: Final[str] = "polyweb.response.partial"
    RESPONSE_OUTPUT_JSON: Final[str] = "polyweb.response.output_json"
    ERROR_TYPE: Final[str] = "error.type"
    HTTP_REQUEST_METHOD: Final[str] = "http.request.method"
    HTTP_ROUTE: Final[str] = "http.route"
    HTTP_RESPONSE_STATUS_CODE: Final[str] = "http.response.status_code"
    URL_PATH: Final[str] = "url.path"
    SERVER_ADDRESS: Final[str] = "server.address"
    SERVER_PORT: Final[str] = "server.port"
    #: Internal capture decision stamped by the trusted execution boundary.
    CAPTURE_PAYLOAD: Final[str] = "polyweb.trace.capture_payload"
    #: Reserved legacy key; untrusted callers cannot inject it.
    SAMPLED: Final[str] = "polyweb.trace.sampled"


OWNERSHIP_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        TraceAttribute.PROJECT_ID,
        TraceAttribute.ACTOR_TYPE,
        TraceAttribute.ACTOR_ID,
    }
)
"""Ownership keys only the trusted attribution binder may stamp on a span."""

INTERNAL_ATTRIBUTES: Final[frozenset[str]] = OWNERSHIP_ATTRIBUTES | frozenset(
    {
        TraceAttribute.CAPTURE_PAYLOAD,
        TraceAttribute.SAMPLED,
    }
)
"""Keys owned by the trusted binders: callers cannot set them and they are never stored."""

TRACE_CONTENT_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        TraceAttribute.REQUEST_QUERY,
        TraceAttribute.REQUEST_URL,
        TraceAttribute.RESPONSE_OUTPUT_JSON,
    }
)
"""Span attributes that carry request/response payload content."""

TRACE_SAFE_EVENT_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "content_length",
        "country_code",
        "enhanced",
        "exception.type",
        "language",
        "limit",
        "max_chars",
        "mode",
        "pdf_pages",
        "result_count",
    }
)
"""Event attributes kept under metadata-only capture.

These are provider request shape, counts, and the sanitized error type. Any
other event attribute is treated as request/response content and dropped at
capture time.
"""

TRACE_SCHEMA_VERSION: Final[int] = 1
"""Schema version stamped on every root span."""

TRACE_EVENT_PROVIDER_REQUEST: Final[str] = "polyweb.provider.request"
TRACE_EVENT_PROVIDER_RESPONSE: Final[str] = "polyweb.provider.response"


class TraceSpanName:
    """Stable, low-cardinality child span names (never contain data)."""

    BACKEND: Final[str] = "polyweb.backend"
    ROUTE: Final[str] = "polyweb.route"
    PROVIDER: Final[str] = "polyweb.provider"
    PROVIDER_HTTP: Final[str] = "polyweb.provider.http"
    PROVIDER_PARSE: Final[str] = "polyweb.provider.parse"
    RESULTS: Final[str] = "polyweb.results"
    RESPONSE: Final[str] = "polyweb.response"


class TraceRootSpan(StrEnum):
    """Inbound surfaces that receive a root server span.

    The API values are route templates. The MCP values name one tool call on
    either transport, because a stdio call has no HTTP route.
    """

    SEARCH = "POST /search"
    FETCH = "POST /fetch"
    MCP_SEARCH = "mcp search"
    MCP_FETCH = "mcp fetch"


_ROOT_STAGES: Final[dict[str, str]] = {
    TraceRootSpan.SEARCH.value: "Search request",
    TraceRootSpan.FETCH.value: "Fetch request",
    TraceRootSpan.MCP_SEARCH.value: "MCP search request",
    TraceRootSpan.MCP_FETCH.value: "MCP fetch request",
}

_STAGES: Final[dict[str, str]] = {
    TraceSpanName.BACKEND: "Backend handling",
    TraceSpanName.ROUTE: "Route selection",
    TraceSpanName.PROVIDER: "Provider request",
    TraceSpanName.PROVIDER_HTTP: "Provider HTTP call",
    TraceSpanName.PROVIDER_PARSE: "Provider response parse",
    TraceSpanName.RESULTS: "Results assembly",
    TraceSpanName.RESPONSE: "Response to caller",
}

TRACE_STAGES: Final[dict[str, str]] = {**_ROOT_STAGES, **_STAGES}


def display_stage(name: str) -> str:
    """Return a user-safe stage label for a span name (never a raw payload)."""

    return TRACE_STAGES.get(name, "Stage")


class TraceError(ContractModel):
    """User-facing failure projection: type plus a human-readable message."""

    type: str
    message: str


class TraceSearchResult(ContractModel):
    """One normalized result as returned to the caller."""

    title: str = ""
    url: str
    snippet: str = ""
    source: str | None = None
    score: float | None = None


class TraceSearchOutput(ContractModel):
    """Results-out payload for a search trace."""

    kind: Literal["search_results"] = "search_results"
    query: str
    results: list[TraceSearchResult] = Field(default_factory=list)


class TraceFetchOutput(ContractModel):
    """Results-out payload for a fetch trace (the resolved fetch shape)."""

    kind: Literal["fetch_document"] = "fetch_document"
    url: str
    title: str | None = None
    content: str = ""
    content_length: int = Field(default=0, ge=0)
    truncated: bool = False


TraceOutput = Annotated[
    TraceSearchOutput | TraceFetchOutput,
    Field(discriminator="kind"),
]
"""Tagged union: a new operation contributes one more member and tag."""

_TRACE_ID_PATTERN: Final[Pattern[str]] = compile(r"[0-9a-f]{32}")
"""Canonical trace identifier: exactly 32 lowercase hex characters."""

_TRACE_OUTPUT_ADAPTER: Final[TypeAdapter[TraceOutput]] = TypeAdapter(TraceOutput)


def is_trace_id(value: str) -> bool:
    """Return whether ``value`` is a canonical trace identifier."""

    return _TRACE_ID_PATTERN.fullmatch(value) is not None


def parse_trace_output(output_json: str | None) -> TraceOutput | None:
    """Decode a stored tagged output payload, or ``None`` when absent/legacy."""

    if not output_json:
        return None
    try:
        return _TRACE_OUTPUT_ADAPTER.validate_json(output_json)
    except ValidationError:
        return None


class TraceEventDetail(ContractModel):
    """One span event with its allowlisted attributes."""

    name: str
    timestamp: AwareDatetime
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSpanDetail(ContractModel):
    """One span in the Activity detail timeline."""

    span_id: str
    parent_span_id: str | None = None
    name: str
    stage: str
    provider: str | None = None
    kind: TraceSpanKind
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    outcome: TraceOutcome
    error: TraceError | None = None
    events: list[TraceEventDetail] = Field(default_factory=list)


class TraceSummary(ContractModel):
    """Fast, scannable Activity list row (never carries query or output).

    ``user_id`` is the canonical account UUID of the trace root. A historical
    row without an owner keeps ``None`` and stays outside every account read.
    """

    trace_id: str
    user_id: str | None = None
    operation: TraceOperation | None = None
    started_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    provider: str | None = None
    outcome: TraceOutcome
    result_count: int | None = None
    error: TraceError | None = None


class TraceDetail(TraceSummary):
    """Summary plus the full input, tagged output, and ordered spans."""

    input: str | None = None
    output: TraceOutput | None = None
    spans: list[TraceSpanDetail] = Field(default_factory=list)


class TraceListResponse(ContractModel):
    """Wire payload of ``GET /api/v1/projects/{project_id}/traces``."""

    items: list[TraceSummary] = Field(default_factory=list)
    generated_at: AwareDatetime
    next_cursor: str | None = None


class TraceSpanRecord(ContractModel):
    """One exporter row: the persisted projection of one finished span.

    Root spans additionally carry the summary projection (``user_id`` through
    ``result_count``); child spans leave those at their defaults.
    """

    span_id: str
    trace_id: str
    name: str
    kind: TraceSpanKind
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    status_code: TraceStatusCode = TraceStatusCode.UNSET
    status_message: str | None = None
    outcome: TraceOutcome = TraceOutcome.SUCCESS
    error_type: str | None = None
    parent_span_id: str | None = None
    user_id: str | None = None
    project_id: UUID | None = None
    actor_type: ActorType | None = None
    actor_id: UUID | None = None
    operation: TraceOperation | None = None
    provider: str | None = None
    input_text: str | None = None
    output_json: str | None = None
    result_count: int | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[TraceEventDetail] = Field(default_factory=list)
    resource: dict[str, Any] = Field(default_factory=dict)


def trace_outcome_for(*, status_code: TraceStatusCode, partial: bool = False) -> TraceOutcome:
    """Project a span status (plus the request's partial flag) onto an outcome.

    A handled fanout failure is ``partial``: the request succeeded for the
    caller even though one provider child failed, so the user request must not
    be mislabeled as failed.
    """

    if status_code is TraceStatusCode.ERROR:
        return TraceOutcome.ERROR
    return TraceOutcome.PARTIAL if partial else TraceOutcome.SUCCESS


def trace_error(message: str | None, error_type: str | None) -> TraceError | None:
    """Build the wire error projection, or ``None`` when the span succeeded."""

    if error_type is None:
        return None
    return TraceError(type=error_type, message=message or error_type)
