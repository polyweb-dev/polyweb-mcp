"""Mocked contract tests for :class:`ParallelAdapter` - no network, no real key.

Stage 3 Parallel provider slice against the shared contracts (direct HTTPX, no
SDK). All responses are served from fixture JSON through a shared
``httpx.MockTransport``; the suite is Green against the implemented adapter.

Maps the acceptance criteria to tests:

- AC-1 (scoped auth + shared runner): search/fetch POST only
  ``https://api.parallel.ai/v1/search`` / ``/v1/extract`` through the shared
  runner; the constructor-injected ``api_key`` travels as a per-request
  ``x-api-key`` header; the caller client is never mutated and caller
  ``Authorization`` / ``X-API-Key`` never reach the wire.
- AC-2 (normalization): documented Parallel payloads (fixture JSON under
  ``tests/fixtures/parallel/``) normalize to ``SearchResponse`` with query /
  provider / results (url, title, excerpts joined with a blank line, optional
  ``publish_date``) and ``FetchResponse`` with the matching extracted
  ``full_content`` and deterministic ``max_chars`` truncation; usage sums the
  vendor ``usage: [{name, count}]`` counts with ``search_id`` / ``extract_id``
  as the request id.
- AC-3 (error normalization): missing credentials fail closed as
  ``configuration_error``; malformed payloads surface as redaction-safe,
  non-retryable ``invalid_response`` with suppressed cause chains; HTTP
  400/401/403/422 map to typed non-retryable errors; 429/500/502/503/504 are
  retryable; two concurrent 429 public calls each enter the shared runner once
  (no adapter-local retry loop).
- AC-4 (cost/quota): ``estimate_cost`` is network-free (no runner entry, no
  wire request) and quota is unsupported (capability off, ``quota()`` None).
- AC-5 (mocked fixtures): all responses are served from fixture JSON through
  a shared ``httpx.MockTransport``; fakes follow the conventions in
  ``tests/test_resilience.py`` (plain injected objects, no sleeping, no HTTP).

The key seam is explicit constructor injection (``api_key=SecretStr(...)``),
mirroring ``tests/unit/adapters/test_tavily.py``: the adapter must never consult
a global resolver or ambient environment fallback.
"""

import asyncio
import json
import traceback
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.models.contracts import FetchRequest, SearchRequest, UsageOperation

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parallel"


def _load_fixture(name: str) -> dict[str, object]:
    with (_FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class _RecordingRunner:
    """Records every shared-runner entry and executes the operation as-is."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await operation()


class _CountingRunner:
    """Wraps a real ``ResilientRunner`` while recording every entry."""

    def __init__(self, inner: ResilientRunner) -> None:
        self.inner = inner
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await self.inner.run(provider, operation)


class _UnreachableWire:
    """MockTransport handler proving no request ever hits the wire."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call: {request.method} {request.url}")


class _Wire:
    """Shared ``httpx.MockTransport`` handler serving fixture payloads.

    Serves a canned queue when provided, otherwise the documented Parallel
    payload per path, and records every wire request for URL/auth assertions.
    """

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) if responses else []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        if request.url.path == "/v1/extract":
            return httpx.Response(200, json=_load_fixture("extract.json"))
        return httpx.Response(200, json=_load_fixture("search.json"))


def make_client(wire: object | None = None) -> httpx.AsyncClient:
    """A caller-owned client over ``MockTransport``; any unexpected request fails."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(wire or _UnreachableWire()),
        timeout=httpx.Timeout(15.0),
    )


def make_authed_client(wire: object) -> httpx.AsyncClient:
    """A caller client carrying its own auth headers that must never leak."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(wire),
        timeout=httpx.Timeout(15.0),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )


def make_adapter(
    client: httpx.AsyncClient,
    *,
    runner=None,
    key: str = "sk-parallel-test-1",
) -> ParallelAdapter:
    """Build an adapter with an explicitly injected key (no network, no env)."""
    return ParallelAdapter(client, runner=runner, api_key=SecretStr(key))


def _assert_no_secret_leak(error: ProviderOperationError, secret: str) -> None:
    """Assert the public error surfaces nothing containing the secret value."""
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert secret not in text


def _assert_no_records_leak(response: object, secret: str) -> None:
    """Assert skipped-item records carry no secret or raw payload text."""
    usage = response.usage  # type: ignore[union-attr]
    assert usage is not None
    assert secret not in repr(usage.metadata.get("parse_errors"))
    assert secret not in repr(response.results)  # type: ignore[union-attr]


# --- construction ---------------------------------------------------------


async def test_adapter_implements_provider_adapter_interface() -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller)

        assert isinstance(adapter, ProviderAdapter)
        assert adapter.name == "parallel"
        capabilities = adapter.capabilities
        assert capabilities.search is True
        assert capabilities.fetch is True
        assert capabilities.cost_estimate is True
    finally:
        await caller.aclose()


async def test_init_missing_resolver_credential_fails_closed() -> None:
    """A missing key fails closed at construction (explicit ``api_key=None``).

    Substitution note: this test previously asserted that the retired global
    ``get_provider_secret_resolver`` seam was asked for exactly the Parallel
    credential (``resolver.requested == [ProviderName.PARALLEL]``). That seam
    no longer exists, so the surviving behavioral guarantees are asserted
    instead: fail-closed non-retryable ``configuration_error`` naming the
    provider and the missing API key, with the caller client left untouched.
    """
    caller = make_client()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ParallelAdapter(caller, api_key=None)

        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        message = excinfo.value.error.message.lower()
        assert "parallel" in message and "api key" in message
        # The failing path must leave the shared client untouched.
        assert "Authorization" not in caller.headers
        assert "x-api-key" not in {key.lower() for key in caller.headers}
    finally:
        await caller.aclose()


async def test_init_missing_credential_never_falls_back_to_ambient_key(monkeypatch) -> None:
    """No ambient ``FREESEARCH_PARALLEL_API_KEY`` fallback.

    Substitution note: the retired resolver's ``requested`` bookkeeping is gone;
    the surviving guarantee is fail-closed construction that leaks neither the
    ambient key into the error nor into the caller's client.
    """
    monkeypatch.setenv("FREESEARCH_PARALLEL_API_KEY", "ambient-pk-leak")
    caller = make_client()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ParallelAdapter(caller, api_key=None)
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        assert "ambient-pk-leak" not in str(excinfo.value)
        assert "ambient-pk-leak" not in str(caller.headers)
        # The ambient key is never adopted into the caller's client.
        assert "x-api-key" not in {key.lower() for key in caller.headers}
        assert "Authorization" not in caller.headers
    finally:
        await caller.aclose()


# --- wire contract (AC-1) --------------------------------------------------


async def test_search_posts_to_v1_search_through_shared_runner_with_scoped_key() -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner, key="sk-parallel-secret-99")
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="python async")
        )
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel"]
    assert [str(request.url) for request in wire.requests] == ["https://api.parallel.ai/v1/search"]
    request = wire.requests[0]
    assert request.method == "POST"
    # The injected api_key is the only auth on the wire.
    assert request.headers["x-api-key"] == "sk-parallel-secret-99"
    assert "authorization" not in request.headers
    assert "caller-token-1" not in request.headers.values()
    assert "caller-xkey-2" not in request.headers.values()
    assert json.loads(request.content)["search_queries"] == ["python async"]
    assert response.query == "python async"


async def test_fetch_posts_to_v1_extract_through_shared_runner_with_scoped_key() -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner, key="sk-parallel-secret-99")
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel"]
    assert [str(request.url) for request in wire.requests] == ["https://api.parallel.ai/v1/extract"]
    request = wire.requests[0]
    assert request.method == "POST"
    assert request.headers["x-api-key"] == "sk-parallel-secret-99"
    assert "authorization" not in request.headers
    assert "caller-token-1" not in request.headers.values()
    assert "caller-xkey-2" not in request.headers.values()
    assert json.loads(request.content)["urls"] == ["https://www.example.com/guide"]


async def test_operations_never_mutate_caller_http_client() -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    headers_before = dict(caller.headers)
    base_url_before = str(caller.base_url)
    try:
        adapter = make_adapter(caller, key="sk-parallel-secret-99")
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="mutate")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )
    finally:
        await caller.aclose()

    assert dict(caller.headers) == headers_before
    assert str(caller.base_url) == base_url_before
    for request in wire.requests:
        # The injected api_key is scoped per request; caller auth never leaks.
        assert request.headers["x-api-key"] == "sk-parallel-secret-99"
        assert "authorization" not in request.headers
        assert "caller-token-1" not in request.headers.values()
        assert "caller-xkey-2" not in request.headers.values()


# --- search normalization (AC-2) -------------------------------------------


async def test_search_normalizes_results_with_joined_excerpts_and_publish_date() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="normalize")
        )
    finally:
        await caller.aclose()

    assert response.query == "normalize"
    assert response.provider == "parallel"
    assert response.total_results == 2

    first = response.results[0]
    assert first.title == "Example Guide"
    assert str(first.url) == "https://www.example.com/guide"
    # The documented ``excerpts`` array is joined into one deterministic
    # snippet (blank line between markdown excerpts).
    assert first.snippet == "First relevant markdown excerpt.\n\nSecond relevant markdown excerpt."
    assert first.published_at is not None
    assert (first.published_at.year, first.published_at.month, first.published_at.day) == (
        2024,
        1,
        15,
    )
    assert first.metadata == {
        "excerpts": [
            "First relevant markdown excerpt.",
            "Second relevant markdown excerpt.",
        ]
    }
    assert response.provider_metadata == {
        "search_id": "search_fcb2b4f3c75e418687bccaa1a8381331",
        "warnings": None,
        "session_id": "session_fcb2b4f3c75e418687bccaa1a8381331",
    }

    second = response.results[1]
    assert second.title == ""
    assert second.snippet == "Single excerpt without a title."
    assert second.published_at is None
    assert second.metadata == {"excerpts": ["Single excerpt without a title."]}


@pytest.mark.parametrize(
    "usage,expected",
    [
        ([{"name": "sku_search", "count": 1}], Decimal("1")),
        (
            [
                {"name": "sku_search", "count": 1},
                {"name": "sku_search_additional_results", "count": 4},
            ],
            Decimal("5"),
        ),
    ],
)
async def test_search_usage_sums_sku_counts_and_maps_search_id(
    usage: object, expected: Decimal
) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
        )
    finally:
        await caller.aclose()

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == expected
    assert response.usage.request_id == "search_fcb2b4f3c75e418687bccaa1a8381331"


async def test_search_drops_absent_usage() -> None:
    payload = _load_fixture("search.json") | {"usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
        )
    finally:
        await caller.aclose()

    assert response.usage is None


@pytest.mark.parametrize(
    "usage",
    ["not-a-list", [{"name": "sku_search"}], [{"name": "sku_search", "count": "one"}]],
)
async def test_search_malformed_usage_raises_invalid_response(usage: object) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
            )
    finally:
        await caller.aclose()

    assert excinfo.value.error.provider == "parallel"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_item_missing_excerpts_records_redacted_error() -> None:
    payload = {
        "search_id": "search_x",
        "results": [{"url": "https://www.example.com/guide", "api_key": "super-secret"}],
        "usage": [{"name": "sku_search", "count": 1}],
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert response.usage.metadata.get("parse_errors") == [
        {"index": 0, "code": "invalid_response", "message": "malformed search result item"}
    ]
    _assert_no_records_leak(response, "super-secret")


async def test_search_result_missing_url_returns_empty_success() -> None:
    payload = _load_fixture("search.json") | {
        "results": [{"title": "missing url", "excerpts": ["x"]}]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert response.usage.metadata.get("parse_errors") == [
        {"index": 0, "code": "invalid_response", "message": "malformed search result item"}
    ]


_GOOD_PARALLEL_ITEM = {
    "url": "https://www.example.com/guide",
    "title": "Example Guide",
    "publish_date": "2024-01-15",
    "excerpts": ["First relevant markdown excerpt.", "Second relevant markdown excerpt."],
}

_BAD_URL_ITEM = {
    "title": "Bad address",
    "url": "not-a-url",
    "excerpts": ["An excerpt."],
}

_MISSING_URL_ITEM = {"title": "No address here", "excerpts": ["An excerpt."]}

_MISSING_EXCERPTS_ITEM = {"title": "No excerpts", "url": "https://www.example.com/noex"}

_SECOND_GOOD_ITEM = {
    "url": "https://docs.example.org/api",
    "title": "Second Guide",
    "excerpts": ["Single excerpt without a title."],
}

_VALID_SKU_USAGE = [{"name": "sku_search", "count": 1}]

_EXPECTED_RECORD = {
    "code": "invalid_response",
    "message": "malformed search result item",
}

_EXPECTED_GAP = {"reason": "metering-unavailable"}


def _parallel_payload(items: object, usage: object = _VALID_SKU_USAGE) -> dict[str, object]:
    payload: dict[str, object] = {"search_id": "search_test_1", "results": items}
    payload["usage"] = usage
    return payload


def _parallel_records(response: object) -> object:
    usage = response.usage  # type: ignore[union-attr]
    if usage is not None:
        return usage.metadata.get("parse_errors")
    gap = response.usage_gap  # type: ignore[union-attr]
    assert gap is not None
    return gap.get("parse_errors")


@pytest.mark.parametrize("usage", [_VALID_SKU_USAGE, None], ids=["sku-usage", "usage-absent"])
@pytest.mark.parametrize(
    ("items", "expected_urls", "expected_indices"),
    [
        (
            [_GOOD_PARALLEL_ITEM, _BAD_URL_ITEM],
            ["https://www.example.com/guide"],
            [1],
        ),
        (
            [_MISSING_URL_ITEM, _GOOD_PARALLEL_ITEM],
            ["https://www.example.com/guide"],
            [0],
        ),
        (
            [_GOOD_PARALLEL_ITEM, _MISSING_EXCERPTS_ITEM, _SECOND_GOOD_ITEM],
            ["https://www.example.com/guide", "https://docs.example.org/api"],
            [1],
        ),
    ],
)
async def test_search_skips_invalid_items_and_records_errors(
    usage: object, items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    wire = _Wire([httpx.Response(200, json=_parallel_payload(items, usage))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=10
            )
        )
    finally:
        await caller.aclose()

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.query == "shape"
    assert response.provider == "parallel"
    assert response.total_results == len(expected_urls)
    assert _parallel_records(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]
    if usage is None:
        assert response.usage is None
        assert response.usage_gap is not None
        assert response.usage_gap["reason"] == _EXPECTED_GAP["reason"]
    else:
        assert response.usage is not None
        assert response.usage.units == Decimal("1")
        assert response.usage.request_id == "search_test_1"


@pytest.mark.parametrize("usage", [_VALID_SKU_USAGE, None], ids=["sku-usage", "usage-absent"])
@pytest.mark.parametrize(
    ("items", "expected_indices"),
    [
        ([{"title": "No address here", "excerpts": ["x"]}], [0]),
        ([{"title": "Bad", "url": "not-a-url", "excerpts": ["x"]}], [0]),
        ([{"title": "No excerpts", "url": "https://www.example.com/noex"}], [0]),
    ],
)
async def test_search_all_invalid_items_returns_empty_success(
    usage: object, items: list[object], expected_indices: list[int]
) -> None:
    wire = _Wire([httpx.Response(200, json=_parallel_payload(items, usage))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=10
            )
        )
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.query == "shape"
    assert response.provider == "parallel"
    assert _parallel_records(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]
    if usage is None:
        assert response.usage is None
    else:
        assert response.usage is not None
        assert response.usage.units == Decimal("1")


@pytest.mark.parametrize("usage", [_VALID_SKU_USAGE, None], ids=["sku-usage", "usage-absent"])
async def test_search_empty_list_has_no_parse_errors(usage: object) -> None:
    wire = _Wire([httpx.Response(200, json=_parallel_payload([], usage))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=10
            )
        )
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0
    if usage is None:
        assert response.usage is None
        assert response.usage_gap is None
    else:
        assert response.usage is not None
        assert "parse_errors" not in response.usage.metadata


@pytest.mark.parametrize(
    ("limit", "items", "expected_urls", "expected_indices"),
    [
        (
            1,
            [_BAD_URL_ITEM, _GOOD_PARALLEL_ITEM, _SECOND_GOOD_ITEM],
            ["https://www.example.com/guide"],
            [0],
        ),
        (
            2,
            [_GOOD_PARALLEL_ITEM, _MISSING_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://www.example.com/guide", "https://docs.example.org/api"],
            [1],
        ),
    ],
)
async def test_search_limit_applies_after_invalid_item_filter(
    limit: int, items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    wire = _Wire([httpx.Response(200, json=_parallel_payload(items))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=limit
            )
        )
    finally:
        await caller.aclose()

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.total_results == len(expected_urls)
    assert _parallel_records(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


async def test_search_invalid_tail_item_does_not_fail_response() -> None:
    wire = _Wire(
        [
            httpx.Response(
                200,
                json=_parallel_payload([_GOOD_PARALLEL_ITEM, _SECOND_GOOD_ITEM, _BAD_URL_ITEM]),
            )
        ]
    )
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=1)
        )
    finally:
        await caller.aclose()

    assert [str(item.url) for item in response.results] == ["https://www.example.com/guide"]
    assert response.total_results == 1
    assert _parallel_records(response) == [{"index": 2, **_EXPECTED_RECORD}]


async def test_search_parse_errors_do_not_expose_payload_or_key() -> None:
    wire = _Wire(
        [
            httpx.Response(
                200,
                json=_parallel_payload(
                    [
                        _GOOD_PARALLEL_ITEM,
                        {
                            "title": "leak sk-parallel-test-1",
                            "url": "not-a-url",
                            "excerpts": ["leak sk-parallel-test-1"],
                        },
                    ]
                ),
            )
        ]
    )
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, key="sk-parallel-test-1")
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="shape", limit=10
            )
        )
    finally:
        await caller.aclose()

    assert [str(item.url) for item in response.results] == ["https://www.example.com/guide"]
    errors = _parallel_records(response)
    assert errors == [{"index": 1, **_EXPECTED_RECORD}]
    assert "sk-parallel-test-1" not in repr(errors)
    for record in errors:
        assert set(record.keys()) == {"index", "code", "message"}


# --- fetch normalization (AC-2) --------------------------------------------


async def test_fetch_normalizes_full_content_and_usage() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )
    finally:
        await caller.aclose()

    assert response.provider == "parallel"
    assert str(response.document.url) == "https://www.example.com/guide"
    assert response.document.title == "Example Guide"
    assert response.document.content == "Full page content formatted as markdown."
    assert response.document.metadata == {
        "publish_date": "2024-01-15",
        "excerpts": ["Relevant excerpt text ..."],
    }
    assert response.provider_metadata == {
        "extract_id": "extract_8a911eb27c7a4afaa20d0d9dc98d07c0",
        "errors": [],
        "warnings": None,
        "session_id": "session_8a911eb27c7a4afaa20d0d9dc98d07c0",
    }
    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("1")
    assert response.usage.request_id == "extract_8a911eb27c7a4afaa20d0d9dc98d07c0"


@pytest.mark.parametrize(
    "content,max_chars,expected,metadata",
    [
        ("x" * 500, 100, "x" * 100, {"truncated": True}),
        ("short", 1000, "short", {}),
    ],
)
async def test_fetch_truncates_content_at_max_chars_deterministically(
    content: str, max_chars: int, expected: str, metadata: dict[str, object]
) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": content,
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
                max_chars=max_chars,
            )
        )
    finally:
        await caller.aclose()

    assert response.document.content == expected
    assert response.document.metadata == metadata


async def test_fetch_missing_matching_result_raises_fetch_failed() -> None:
    payload = _load_fixture("extract.json") | {
        "results": [{"url": "https://other.example/x", "excerpts": [], "full_content": "no"}]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    assert excinfo.value.error.provider == "parallel"
    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize("full_content", [None, 123])
async def test_fetch_null_or_non_string_full_content_raises_invalid_response(
    full_content: object,
) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": full_content,
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


# --- shared runner and error normalization (AC-3) ---------------------------


async def test_two_concurrent_rate_limited_calls_each_enter_shared_runner() -> None:
    wire = _Wire([httpx.Response(429)] * 2)
    caller = make_client(wire)
    runner = _CountingRunner(ResilientRunner(caller, max_attempts=1))
    try:
        adapter = make_adapter(caller, runner=runner)
        request = SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", query="concurrent"
        )
        outcomes = await asyncio.gather(
            adapter.search(request), adapter.search(request), return_exceptions=True
        )
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel", "parallel"]  # one runner entry per public call
    assert len(wire.requests) == 2  # no adapter-local retry loop
    errors = [outcome for outcome in outcomes if isinstance(outcome, ProviderOperationError)]
    assert len(errors) == 2
    assert {error.error.code for error in errors} == {"http_error"}
    assert {error.error.status_code for error in errors} == {429}
    assert all(error.error.retryable for error in errors)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_http_statuses_surface_as_retryable_errors(status: int) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="retry")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "http_error"
    assert error.retryable is True
    assert error.status_code == status


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "bad_request"),
        (401, "invalid_api_key"),
        (403, "forbidden"),
        (422, "invalid_response"),
    ],
)
async def test_client_error_statuses_map_to_typed_nonretryable_errors(
    status: int, code: str
) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == code
    assert error.retryable is False
    assert error.status_code == status


async def test_normalized_error_redacts_secrets() -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller)

        error = adapter._error("bad_request", "query rejected: api_key=sk-leak-123")

        assert error.error.code == "bad_request"
        assert "sk-leak-123" not in str(error)
        assert "sk-leak-123" not in error.error.message
        assert "sk-leak-123" not in error.error.model_dump_json()
    finally:
        await caller.aclose()


# --- cost estimation and quota (AC-4) --------------------------------------


async def test_estimate_cost_search_is_network_free() -> None:
    caller = make_client()  # any wire request raises AssertionError
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner)

        estimate = await adapter.estimate_cost(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cost")
        )

        assert estimate.provider == "parallel"
        assert estimate.operation is UsageOperation.SEARCH
        assert isinstance(estimate.units, Decimal)
        assert runner.entries == []
    finally:
        await caller.aclose()


async def test_estimate_cost_fetch_is_network_free() -> None:
    caller = make_client()  # any wire request raises AssertionError
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner)

        estimate = await adapter.estimate_cost(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )

        assert estimate.provider == "parallel"
        assert estimate.operation is UsageOperation.FETCH
        assert isinstance(estimate.units, Decimal)
        assert runner.entries == []
    finally:
        await caller.aclose()


async def test_quota_is_unsupported() -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller)

        assert adapter.capabilities.quota is False
        assert await adapter.quota() is None
    finally:
        await caller.aclose()


# --- refine-phase granular edge matrix (non-duplicative boundaries) --------


def _fetch_payload_with_content(content: str) -> dict[str, object]:
    """A documented extract payload whose only result carries ``content``."""
    return _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": content,
            }
        ]
    }


@pytest.mark.parametrize(
    "content,max_chars,expected,metadata",
    [
        # Exact boundary: content of length == max_chars is NOT truncated.
        ("x" * 100, 100, "x" * 100, {}),
        # Boundary + 1: truncates to exactly max_chars and flags truncation.
        ("x" * 101, 100, "x" * 100, {"truncated": True}),
        # Empty content is a valid document (never truncated, no metadata).
        ("", 100, "", {}),
        # max_chars unset disables truncation even for long content.
        ("y" * 500, None, "y" * 500, {}),
    ],
)
async def test_fetch_truncation_boundary_equality_and_empty_content(
    content: str, max_chars: int | None, expected: str, metadata: dict[str, object]
) -> None:
    payload = _fetch_payload_with_content(content)
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
                max_chars=max_chars,
            )
        )
    finally:
        await caller.aclose()

    assert response.document.content == expected
    assert response.document.metadata == metadata


async def test_fetch_float_usage_count_sums_exactly() -> None:
    payload = _load_fixture("extract.json") | {"usage": [{"name": "sku_extract", "count": 1.5}]}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )
    finally:
        await caller.aclose()

    assert response.usage is not None
    assert response.usage.units == Decimal("1.5")


@pytest.mark.parametrize(
    "usage",
    [
        {"name": "sku_search", "count": 1},  # mapping, not a list
        [["sku_search", 1]],  # entry is a list, not a mapping
        ["sku_search"],  # entry is a string, not a mapping
        [{"name": "sku_search", "count": True}],  # bool count is not numeric
        [{"name": "sku_search", "count": False}],
    ],
)
async def test_search_usage_bool_or_nonmapping_shapes_raise_invalid_response(usage: object) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "raw_body",
    [
        # JSON literals NaN / Infinity reach ``json.loads`` via the raw body and
        # must not be summed into an infinite/NaN usage total.
        '{"search_id": "x", "results": [], "usage": [{"name": "s", "count": NaN}]}',
        '{"search_id": "x", "results": [], "usage": [{"name": "s", "count": Infinity}]}',
    ],
)
async def test_search_nonfinite_usage_counts_raise_invalid_response(raw_body: str) -> None:
    wire = _Wire([httpx.Response(200, text=raw_body)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>definitely not json</html>"),
        httpx.Response(200, json=[1, 2, 3]),  # a JSON array is not a payload object
    ],
)
async def test_search_malformed_json_body_raises_invalid_response(response: httpx.Response) -> None:
    wire = _Wire([response])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None  # a raw JSON/parse failure never escapes


async def test_fetch_malformed_json_body_raises_invalid_response() -> None:
    wire = _Wire([httpx.Response(200, text="not json at all")])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize("status", [400, 401, 500])
async def test_http_error_body_secret_never_leaks_and_cause_is_suppressed(status: int) -> None:
    secret = "sk-body-secret-7"
    wire = _Wire([httpx.Response(status, json={"error": {"message": f"denied api_key={secret}"}})])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.__cause__ is None
    assert error.error.retryable is (status == 500)
    assert error.error.status_code == status
    # The vendor error body is never echoed into the normalized message.
    assert "denied" not in error.error.message
    _assert_no_secret_leak(error, secret)


async def test_retryable_status_retries_through_runner_then_succeeds() -> None:
    wire = _Wire(
        [
            httpx.Response(503),
            httpx.Response(200, json=_load_fixture("search.json")),
        ]
    )
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=2, base_delay=0.0, random_source=lambda: 0.0)
    try:
        adapter = make_adapter(caller, runner=runner)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="retry")
        )
    finally:
        await caller.aclose()

    # The retry happened inside the shared runner (two wire calls), never in an
    # adapter-local loop, and the second attempt normalized normally.
    assert len(wire.requests) == 2
    assert response.query == "retry"
    assert response.provider == "parallel"
    assert response.total_results == 2


@pytest.mark.parametrize(
    "result_url",
    [
        "https://www.example.com/GUIDE",  # case differs from the request URL
        "https://www.example.com/guide/",  # trailing slash differs
    ],
)
async def test_fetch_url_match_is_exact_and_case_sensitive(result_url: str) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": result_url,
                "excerpts": [],
                "full_content": "content for the mismatched URL",
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "fetch_failed"
    assert error.error.retryable is False
    assert error.__cause__ is None


async def test_search_sends_advanced_settings_and_never_emits_language() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                query="geo",
                limit=7,
                domains=("example.com", "docs.example.org"),
                country_code="US",
                language="fr",
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    # Domains and a lowercased country code are emitted; the request language
    # is intentionally ignored and never appears on the wire.
    assert body["advanced_settings"] == {
        "max_results": 7,
        "source_policy": {"include_domains": ["example.com", "docs.example.org"]},
        "location": "us",
    }
    assert "language" not in body
    assert "language" not in body["advanced_settings"]


async def test_search_default_limit_maps_to_max_results_ten() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="defaults")
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["advanced_settings"] == {"max_results": 10}


async def test_nested_search_options_override_common_defaults_and_price_by_mode() -> None:
    wire = _Wire()
    caller = make_client(wire)
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner)
        response = await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                query="common query",
                limit=12,
                mode="advanced",
                extra_bundles=0,
                domains=("common.example",),
                country_code="US",
                provider_options={
                    "parallel": {
                        "objective": "nested objective",
                        "search_queries": ["first query", "second query"],
                        "mode": "turbo",
                        "max_chars_total": 8000,
                        "session_id": "session-1",
                        "client_model": "model-1",
                        "advanced_settings": {
                            "source_policy": {
                                "include_domains": ["nested.example"],
                                "exclude_domains": ["excluded.example"],
                                "after_date": "2025-03-01",
                            },
                            "fetch_policy": {
                                "max_age_seconds": 3600,
                                "timeout_seconds": 30,
                                "disable_cache_fallback": True,
                            },
                            "excerpt_settings": {"max_chars_per_result": 1200},
                            "location": "ca",
                            "max_results": 5,
                        },
                    }
                },
            )
        )
        estimate = await adapter.estimate_cost(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                query="common query",
                mode="advanced",
                provider_options={"parallel": {"mode": "turbo"}},
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body == {
        "objective": "nested objective",
        "search_queries": ["first query", "second query"],
        "mode": "turbo",
        "max_chars_total": 8000,
        "session_id": "session-1",
        "client_model": "model-1",
        "advanced_settings": {
            "max_results": 5,
            "source_policy": {
                "include_domains": ["nested.example"],
                "exclude_domains": ["excluded.example"],
                "after_date": "2025-03-01",
            },
            "fetch_policy": {
                "max_age_seconds": 3600,
                "timeout_seconds": 30,
                "disable_cache_fallback": True,
            },
            "excerpt_settings": {"max_chars_per_result": 1200},
            "location": "ca",
        },
    }
    assert "extra_bundles" not in body
    assert len(response.results) == 2
    assert estimate.units == Decimal("0.001")
    assert runner.entries == ["parallel"]


async def test_fetch_forwards_nested_parallel_extract_options() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
                provider_options={
                    "parallel": {
                        "objective": "extract objective",
                        "search_queries": ["extract query"],
                        "max_chars_total": 5000,
                        "session_id": "extract-session",
                        "client_model": "extract-model",
                        "advanced_settings": {
                            "fetch_policy": {
                                "max_age_seconds": 3600,
                                "timeout_seconds": 30,
                                "disable_cache_fallback": True,
                            },
                            "excerpt_settings": {"max_chars_per_result": 700},
                            "full_content": {"max_chars_per_result": 6000},
                        },
                    }
                },
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body == {
        "urls": ["https://www.example.com/guide"],
        "objective": "extract objective",
        "search_queries": ["extract query"],
        "max_chars_total": 5000,
        "session_id": "extract-session",
        "client_model": "extract-model",
        "advanced_settings": {
            "full_content": {"max_chars_per_result": 6000},
            "fetch_policy": {
                "max_age_seconds": 3600,
                "timeout_seconds": 30,
                "disable_cache_fallback": True,
            },
            "excerpt_settings": {"max_chars_per_result": 700},
        },
    }


async def test_search_rejects_unsupported_extra_bundles_before_runner_or_wire() -> None:
    caller = make_client(_UnreachableWire())
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    query="legacy expansion",
                    extra_bundles=1,
                )
            )
    finally:
        await caller.aclose()

    assert excinfo.value.error.code == "bad_request"
    assert "extra_bundles" in excinfo.value.error.message
    assert runner.entries == []


async def test_aclose_closes_only_adapter_owned_client() -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)

        assert adapter._http.is_closed is False
        assert caller.is_closed is False

        await adapter.aclose()
        await adapter.aclose()  # closing twice is safe

        # Only the adapter-owned client is closed; the caller's stays open.
        assert adapter._http.is_closed is True
        assert caller.is_closed is False
        assert (await caller.get("https://api.parallel.ai/v1/search")).status_code == 200

        await caller.aclose()
        # The adapter's transport borrows the caller's pools, so it dies with
        # the caller; the adapter cannot outlive its borrowed client.
        with pytest.raises(RuntimeError):
            await adapter._http.get("https://api.parallel.ai/v1/search")
    finally:
        await caller.aclose()


# --- remediation round 1: documented request shape & structural validation ---
#
# Parallel documents ``advanced_settings.full_content`` on Extract (default
# ``false``), caps Search ``max_results`` at 20, requires ``search_id`` /
# ``extract_id`` and a ``results`` array on 200 responses, and any final
# non-2xx status (including 3xx redirects) is a failed HTTP call. Each test
# below is remediation coverage for that documented contract; all are Green
# against the current adapter.


async def test_fetch_posts_advanced_settings_requesting_full_content() -> None:
    """The extract body must explicitly request full content (documented
    ``advanced_settings.full_content``), because the vendor default is False."""
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://www.example.com/guide",
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["urls"] == ["https://www.example.com/guide"]
    assert body["advanced_settings"] == {"full_content": True}


@pytest.mark.parametrize(
    "limit,expected",
    [
        (5, 5),  # values at or below the documented cap pass through unchanged
        (20, 20),  # exact documented cap boundary
        (21, 20),  # one above the documented cap is clamped
        (100, 20),  # contract maximum is clamped
    ],
)
async def test_search_limit_above_documented_cap_is_clamped_to_twenty(
    limit: int, expected: int
) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        await adapter.search(
            SearchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", query="cap", limit=limit
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["advanced_settings"]["max_results"] == expected


def _search_without(key: str) -> dict[str, object]:
    payload = dict(_load_fixture("search.json"))
    payload.pop(key)
    return payload


async def test_search_missing_results_key_raises_invalid_response() -> None:
    wire = _Wire([httpx.Response(200, json=_search_without("results"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="shape")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_missing_search_id_raises_invalid_response() -> None:
    wire = _Wire([httpx.Response(200, json=_search_without("search_id"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="shape")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_non_string_search_id_raises_invalid_response() -> None:
    # Usage is absent so the adapter itself must reject the id shape; a
    # non-string id must never silently reach the usage request_id.
    payload = _load_fixture("search.json") | {"search_id": 123, "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="shape")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("results", ["not-a-list", {"a": 1}])
async def test_search_non_list_results_raises_invalid_response(results: object) -> None:
    payload = _load_fixture("search.json") | {"results": results}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="shape")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_empty_results_list_remains_valid_structure() -> None:
    """An explicitly empty ``results`` array is a valid no-match search."""
    payload = _load_fixture("search.json") | {"results": [], "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="empty")
        )
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0


def _extract_without(key: str) -> dict[str, object]:
    payload = dict(_load_fixture("extract.json"))
    payload.pop(key)
    return payload


async def test_fetch_missing_results_key_raises_invalid_response() -> None:
    # A missing ``results`` array is a structural defect, distinct from a
    # present-but-empty list (which is a valid "no successful extraction").
    wire = _Wire([httpx.Response(200, json=_extract_without("results"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_missing_extract_id_raises_invalid_response() -> None:
    wire = _Wire([httpx.Response(200, json=_extract_without("extract_id"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_non_string_extract_id_raises_invalid_response() -> None:
    # Usage is absent so the adapter itself must reject the id shape.
    payload = _load_fixture("extract.json") | {"extract_id": 456, "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("results", ["not-a-list", {"a": 1}])
async def test_fetch_non_list_results_raises_invalid_response(results: object) -> None:
    payload = _load_fixture("extract.json") | {"results": results}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_empty_results_list_raises_fetch_failed() -> None:
    """A present-but-empty ``results`` array is valid structure: no extraction."""
    payload = _load_fixture("extract.json") | {"results": [], "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://www.example.com/guide",
                )
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "fetch_failed"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("status", [302, 304])
async def test_final_3xx_status_maps_to_nonretryable_http_error(status: int) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="redirect")
            )
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "http_error"
    assert error.retryable is False
    assert error.status_code == status
    assert excinfo.value.__cause__ is None
