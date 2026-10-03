"""Trace read API integration tests: list/detail contracts over seeded traces.

Drives the real FastAPI app (with a real SQLite repository and lifespan, so
the trace exporter is active) using only the checked-in observability
fixtures. No provider keys, no live network.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.models.observability import (
    TraceEventDetail,
    TraceOperation,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
)
from freesearch.models.observability import TraceOutcome as _Outcome
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "observability"
_SUCCESS_ID = "e1c2d3a4b5c6d7e8f9012345678abcde"
_ERROR_ID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "observability-api.db")
    yield repo
    await repo.close()


def _seed(repository: SQLiteRepository, *names: str) -> None:
    for name in names:
        document = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
        records = []
        for span in document["spans"]:
            is_root = span["parent_span_id"] is None
            error = span.get("error") or {}
            output = document.get("output")
            records.append(
                TraceSpanRecord(
                    span_id=span["span_id"],
                    trace_id=str(document["trace_id"]),
                    parent_span_id=span["parent_span_id"],
                    name=span["name"],
                    kind=TraceSpanKind(span["kind"]),
                    started_at=datetime.fromisoformat(span["started_at"]),
                    ended_at=datetime.fromisoformat(span["ended_at"]),
                    duration_ms=span["duration_ms"],
                    status_code=TraceStatusCode(span["status_code"]),
                    status_message=error.get("message"),
                    outcome=_Outcome(span["outcome"]),
                    error_type=span.get("error_type"),
                    operation=(TraceOperation(document["operation"]) if is_root else None),
                    provider=document.get("provider") if is_root else None,
                    input_text=document.get("input_text") if is_root else None,
                    output_json=(json.dumps(output) if is_root and output is not None else None),
                    result_count=document.get("result_count") if is_root else None,
                    events=[
                        TraceEventDetail(
                            name=event["name"],
                            timestamp=datetime.fromisoformat(event["timestamp"]),
                            attributes=dict(event.get("attributes") or {}),
                        )
                        for event in span.get("events", [])
                    ],
                )
            )
        write_trace_spans(repository.database_path, records)


def _client(repository: SQLiteRepository) -> TestClient:
    return TestClient(create_app([], repository=repository))


def _trace_ids(client: TestClient) -> list[str]:
    return [item["trace_id"] for item in client.get("/api/v1/traces").json()["items"]]


async def test_list_returns_newest_first_summary_only(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "search_success.json", "provider_error.json")

    with _client(repository) as client:
        response = client.get("/api/v1/traces")

    assert response.status_code == 200
    payload = response.json()
    assert [item["trace_id"] for item in payload["items"]] == [_ERROR_ID, _SUCCESS_ID]
    first, second = payload["items"]
    assert (first["operation"], first["outcome"], first["result_count"]) == (
        "fetch",
        "error",
        None,
    )
    assert (second["operation"], second["outcome"], second["result_count"]) == (
        "search",
        "success",
        2,
    )
    assert first["error"] == {"type": "http_error", "message": "HTTP 502"}
    assert second["error"] is None
    for item in payload["items"]:
        assert set(item) == {
            "trace_id",
            "operation",
            "started_at",
            "duration_ms",
            "provider",
            "outcome",
            "result_count",
            "error",
        }
    assert datetime.fromisoformat(payload["generated_at"]).tzinfo is not None


async def test_list_filters_by_operation_and_outcome(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "search_success.json", "provider_error.json")

    with _client(repository) as client:
        fetched = client.get("/api/v1/traces", params={"operation": "fetch"})
        errored = client.get("/api/v1/traces", params={"outcome": "error"})
        mismatch = client.get("/api/v1/traces", params={"operation": "search", "outcome": "error"})
        invalid = client.get("/api/v1/traces", params={"operation": "bogus"})

    assert [item["trace_id"] for item in fetched.json()["items"]] == [_ERROR_ID]
    assert [item["trace_id"] for item in errored.json()["items"]] == [_ERROR_ID]
    assert mismatch.json()["items"] == []
    assert invalid.status_code == 422


async def test_list_limit_clamps_to_1_and_100(repository: SQLiteRepository) -> None:
    _seed(repository, "search_success.json", "provider_error.json")

    with _client(repository) as client:
        assert len(client.get("/api/v1/traces", params={"limit": 0}).json()["items"]) == 1
        assert len(client.get("/api/v1/traces").json()["items"]) == 2
        assert len(client.get("/api/v1/traces", params={"limit": 5000}).json()["items"]) == 2


async def test_list_is_empty_without_traces(repository: SQLiteRepository) -> None:
    with _client(repository) as client:
        response = client.get("/api/v1/traces")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_detail_returns_full_input_output_and_spans(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "search_success.json")

    with _client(repository) as client:
        response = client.get(f"/api/v1/traces/{_SUCCESS_ID}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["trace_id"] == _SUCCESS_ID
    assert detail["operation"] == "search"
    assert detail["input"] == "distributed consensus algorithms"
    assert detail["output"]["kind"] == "search_results"
    assert [item["url"] for item in detail["output"]["results"]] == [
        "https://docs.freesearch.dev/consensus",
        "https://docs.freesearch.dev/raft-vs-paxos",
    ]
    first_result = detail["output"]["results"][0]
    assert first_result["title"] == "Consensus algorithms explained"
    assert first_result["snippet"] == "Raft, Paxos, and where each applies."
    assert first_result["source"] == "keenable"
    assert first_result["score"] == 0.94
    assert len(detail["spans"]) == 7
    root = detail["spans"][0]
    assert root["name"] == "POST /search"
    assert root["stage"] == "Search request"
    assert root["kind"] == "server"
    assert root["parent_span_id"] is None
    for span in detail["spans"]:
        assert set(span) == {
            "span_id",
            "parent_span_id",
            "name",
            "stage",
            "kind",
            "started_at",
            "ended_at",
            "duration_ms",
            "outcome",
            "error",
            "events",
        }
        assert span["duration_ms"] >= 0


async def test_detail_error_trace_has_error_without_output(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "provider_error.json")

    with _client(repository) as client:
        response = client.get(f"/api/v1/traces/{_ERROR_ID}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["outcome"] == "error"
    assert detail["error"] == {"type": "http_error", "message": "HTTP 502"}
    assert detail["input"] == "https://docs.freesearch.dev/getting-started"
    assert detail["output"] is None
    assert detail["result_count"] is None


async def test_detail_404_for_absent_and_malformed_ids(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "search_success.json")

    with _client(repository) as client:
        absent = client.get(f"/api/v1/traces/{'0' * 32}")
        malformed = client.get("/api/v1/traces/not-a-trace")
        short = client.get("/api/v1/traces/abc123")

    assert absent.status_code == 404
    assert malformed.status_code == 404
    assert short.status_code == 404


async def test_trace_reads_and_monitoring_add_no_traces(
    repository: SQLiteRepository,
) -> None:
    _seed(repository, "search_success.json", "provider_error.json")

    with _client(repository) as client:
        before = _trace_ids(client)
        assert client.get("/api/v1/traces").status_code == 200
        assert client.get(f"/api/v1/traces/{_SUCCESS_ID}").status_code == 200
        assert client.get("/api/v1/traces", params={"limit": 1}).status_code == 200
        assert client.get("/stats").status_code == 200
        assert client.get("/dashboard").status_code == 200
        after = _trace_ids(client)

    assert before == [_ERROR_ID, _SUCCESS_ID]
    assert after == before
