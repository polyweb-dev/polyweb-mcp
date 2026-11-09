"""Trace read API integration tests: list/detail contracts over seeded traces.

Drives the real FastAPI app (with a real SQLite repository and lifespan, so
the trace exporter is active) using only the checked-in observability
fixtures. No provider keys, no live network.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from fastapi.testclient import TestClient

from polyweb.models.observability import (
    ActorType,
    TraceEventDetail,
    TraceOperation,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
)
from polyweb.models.observability import TraceOutcome as _Outcome
from polyweb.persistence.otel_exporter import write_trace_spans
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "observability"
_SUCCESS_ID = "e1c2d3a4b5c6d7e8f9012345678abcde"
_ERROR_ID = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "observability-api.db")
    yield repo
    await repo.close()


async def _seed(repository: SQLiteRepository, owner: UUID, *names: str) -> UUID:
    attribution = await seed_execution_project(repository, user_id=owner)
    for name in names:
        document = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
        records = []
        for span in document["spans"]:
            is_root = span["parent_span_id"] is None
            error = span.get("error") or {}
            output = document.get("output")
            records.append(
                TraceSpanRecord(
                    project_id=attribution.project_id,
                    actor_type=ActorType.HUMAN,
                    actor_id=owner,
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
                    # Fixture loader contract (PLAN §6.1 item 6 loader half):
                    # the document provider seeds only the root summary row;
                    # every child span reads its own span-level `provider`
                    # field (None when the fixture records no identity).
                    provider=(document.get("provider") if is_root else span.get("provider")),
                    input_text=document.get("input_text") if is_root else None,
                    output_json=(json.dumps(output) if is_root and output is not None else None),
                    result_count=document.get("result_count") if is_root else None,
                    user_id=str(owner) if is_root else None,
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
    return attribution.project_id


def _client(repository: SQLiteRepository) -> TestClient:
    return TestClient(create_app([], repository=repository))


def _trace_ids(client: TestClient, headers: dict[str, str], pid: UUID) -> list[str]:
    return [
        item["trace_id"]
        for item in client.get(f"/api/v1/projects/{pid}/traces", headers=headers).json()["items"]
    ]


async def test_list_returns_newest_first_summary_only(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for trace reads. Seed rows carry its UUID.
    with _client(repository) as client:
        anonymous = client.get(f"/api/v1/projects/{UUID(int=1)}/traces")
        assert anonymous.status_code == 401

        pair = register_and_login(client, temp_email("obs-list"))
        headers = raw_auth_headers(pair["access_token"])
        owner = account_id_from_pair(pair)
        pid = await _seed(repository, owner, "search_success.json", "provider_error.json")
        response = client.get(f"/api/v1/projects/{pid}/traces", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert [item["trace_id"] for item in payload["items"]] == [_ERROR_ID, _SUCCESS_ID]
    for item in payload["items"]:
        assert item["user_id"] == str(owner)
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
            "user_id",
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
    auth_secret: str,
) -> None:
    # Use one Agent account for trace reads. Seed rows carry its UUID.
    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-filter"))
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(
            repository, account_id_from_pair(pair), "search_success.json", "provider_error.json"
        )
        fetched = client.get(
            f"/api/v1/projects/{pid}/traces", params={"operation": "fetch"}, headers=headers
        )
        errored = client.get(
            f"/api/v1/projects/{pid}/traces", params={"outcome": "error"}, headers=headers
        )
        mismatch = client.get(
            f"/api/v1/projects/{pid}/traces",
            params={"operation": "search", "outcome": "error"},
            headers=headers,
        )
        invalid = client.get(
            f"/api/v1/projects/{pid}/traces", params={"operation": "bogus"}, headers=headers
        )

    assert [item["trace_id"] for item in fetched.json()["items"]] == [_ERROR_ID]
    assert [item["trace_id"] for item in errored.json()["items"]] == [_ERROR_ID]
    assert mismatch.json()["items"] == []
    assert invalid.status_code == 422


async def test_list_limit_clamps_to_1_and_100(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for trace reads. Seed rows carry its UUID.
    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-limit"))
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(
            repository, account_id_from_pair(pair), "search_success.json", "provider_error.json"
        )
        assert (
            len(
                client.get(
                    f"/api/v1/projects/{pid}/traces", params={"limit": 0}, headers=headers
                ).json()["items"]
            )
            == 1
        )
        assert (
            len(client.get(f"/api/v1/projects/{pid}/traces", headers=headers).json()["items"]) == 2
        )
        assert (
            len(
                client.get(
                    f"/api/v1/projects/{pid}/traces", params={"limit": 5000}, headers=headers
                ).json()["items"]
            )
            == 2
        )


async def test_list_is_empty_without_traces(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for the read. No seed rows exist.
    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-empty"))
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(repository, account_id_from_pair(pair))
        response = client.get(f"/api/v1/projects/{pid}/traces", headers=headers)

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_detail_returns_full_input_output_and_spans(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for the read. Seed rows carry its UUID.
    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-detail"))
        headers = raw_auth_headers(pair["access_token"])
        owner = account_id_from_pair(pair)
        pid = await _seed(repository, owner, "search_success.json")
        response = client.get(f"/api/v1/projects/{pid}/traces/{_SUCCESS_ID}", headers=headers)

    assert response.status_code == 200
    detail = response.json()
    assert detail["trace_id"] == _SUCCESS_ID
    assert detail["user_id"] == str(owner)
    assert detail["operation"] == "search"
    assert detail["input"] == "distributed consensus algorithms"
    assert detail["output"]["kind"] == "search_results"
    assert [item["url"] for item in detail["output"]["results"]] == [
        "https://docs.polyweb.dev/consensus",
        "https://docs.polyweb.dev/raft-vs-paxos",
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
            # RED (PLAN §6.1 item 4, additive): the API exposes the
            # per-span provider identity. Fails because there is no API field.
            "provider",
            "started_at",
            "ended_at",
            "duration_ms",
            "outcome",
            "error",
            "events",
        }
        assert span["duration_ms"] >= 0
    # RED: the provider child preserves its span-level identity while
    # non-provider spans stay null; the root span keeps the document provider.
    # (Assumes the span fixture carries a span-level `provider` field per
    # PLAN §6.1 item 6; `provider_error.json` already does.)
    by_name = {span["name"]: span for span in detail["spans"]}
    assert by_name["polyweb.provider"]["provider"] == "keenable"
    assert by_name["polyweb.backend"]["provider"] is None
    assert root["provider"] == "keenable"


async def test_detail_error_trace_has_error_without_output(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for the read. Seed rows carry its UUID.
    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-err"))
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(repository, account_id_from_pair(pair), "provider_error.json")
        response = client.get(f"/api/v1/projects/{pid}/traces/{_ERROR_ID}", headers=headers)

    assert response.status_code == 200
    detail = response.json()
    assert detail["outcome"] == "error"
    assert detail["error"] == {"type": "http_error", "message": "HTTP 502"}
    assert detail["input"] == "https://docs.polyweb.dev/getting-started"
    assert detail["output"] is None
    assert detail["result_count"] is None


async def test_detail_404_for_absent_and_malformed_ids(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account. Auth runs first, then the 404 logic.
    with _client(repository) as client:
        assert client.get(f"/api/v1/projects/{UUID(int=1)}/traces/{'0' * 32}").status_code == 401
        pair = register_and_login(client, temp_email("obs-404"))
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(repository, account_id_from_pair(pair), "search_success.json")
        assert (
            client.get(f"/api/v1/projects/{pid}/traces/{_SUCCESS_ID}", headers=headers).status_code
            == 200
        )
        absent = client.get(f"/api/v1/projects/{pid}/traces/{'0' * 32}", headers=headers)
        malformed = client.get(f"/api/v1/projects/{pid}/traces/not-a-trace", headers=headers)
        short = client.get(f"/api/v1/projects/{pid}/traces/abc123", headers=headers)

    assert absent.status_code == 404
    assert malformed.status_code == 404
    assert short.status_code == 404


async def test_trace_reads_and_monitoring_add_no_traces(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for traces and one Developer account for stats.
    # Seed rows carry the Agent UUID. The Developer reads stats only.
    with _client(repository) as client:
        agent = register_and_login(client, temp_email("obs-agent"))
        agent_headers = raw_auth_headers(agent["access_token"])
        pid = await _seed(
            repository,
            account_id_from_pair(agent),
            "search_success.json",
            "provider_error.json",
        )
        dev_pair = await register_system_admin_login(client, repository, temp_email("obs-dev"))
        dev_headers = raw_auth_headers(dev_pair["access_token"])
        before = _trace_ids(client, agent_headers, pid)
        assert (
            client.get(f"/api/v1/projects/{pid}/traces", headers=agent_headers).status_code == 200
        )
        assert (
            client.get(
                f"/api/v1/projects/{pid}/traces/{_SUCCESS_ID}", headers=agent_headers
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/v1/projects/{pid}/traces", params={"limit": 1}, headers=agent_headers
            ).status_code
            == 200
        )
        assert client.get("/stats", headers=dev_headers).status_code == 200
        assert client.get("/dashboard", headers=dev_headers).status_code == 200
        after = _trace_ids(client, agent_headers, pid)

    assert before == [_ERROR_ID, _SUCCESS_ID]
    assert after == before


async def test_hundred_row_page_looks_ahead_and_cursor_replay_cannot_cross_projects(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    from datetime import UTC

    with _client(repository) as client:
        pair = register_and_login(client, temp_email("obs-page"))
        owner = account_id_from_pair(pair)
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(repository, owner)
        other = await _seed(repository, owner)
        now = datetime.now(UTC)
        write_trace_spans(
            repository.database_path,
            [
                TraceSpanRecord(
                    project_id=pid,
                    actor_type=ActorType.HUMAN,
                    actor_id=owner,
                    span_id=f"{index:016x}",
                    trace_id=f"{index:032x}",
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=now,
                    ended_at=now,
                    duration_ms=0,
                    operation=TraceOperation.SEARCH,
                    user_id=str(owner),
                )
                for index in range(1, 102)
            ],
        )
        first = client.get(f"/api/v1/projects/{pid}/traces", params={"limit": 100}, headers=headers)
        assert first.status_code == 200
        assert len(first.json()["items"]) == 100
        cursor = first.json()["next_cursor"]
        assert cursor is not None
        second = client.get(
            f"/api/v1/projects/{pid}/traces",
            params={"limit": 100, "cursor": cursor},
            headers=headers,
        )
        assert second.status_code == 200
        assert len(second.json()["items"]) == 1
        assert second.json()["next_cursor"] is None
        ids = [row["trace_id"] for row in first.json()["items"] + second.json()["items"]]
        assert len(set(ids)) == 101
        assert ids == [f"{index:032x}" for index in range(101, 0, -1)]
        replay = client.get(
            f"/api/v1/projects/{other}/traces", params={"cursor": cursor}, headers=headers
        )
        assert replay.status_code == 422
        assert replay.json()["detail"]["code"] == "INVALID_CURSOR"


async def test_project_dashboard_omits_other_private_credentials_quota_and_health(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    from datetime import UTC

    from polyweb.models.contracts import QuotaSnapshot, QuotaSource, UsageEvent, UsageOperation
    from polyweb.models.observability import ExecutionAttribution

    with _client(repository) as client:
        pair = register_and_login(client, temp_email("dashboard-scope"))
        owner = account_id_from_pair(pair)
        headers = raw_auth_headers(pair["access_token"])
        pid = await _seed(repository, owner)
        other = await _seed(repository, owner)
        await repository.record_quota(
            QuotaSnapshot(
                provider="other-private-provider",
                source=QuotaSource.AUTHORITATIVE,
                remaining=98765,
                limit=99999,
                observed_at=datetime.now(UTC),
            )
        )
        for project, provider, units in [
            (pid, "own-provider", 2),
            (other, "other-private-provider", 98765),
        ]:
            await repository.record_usage(
                UsageEvent(
                    provider=provider,
                    operation=UsageOperation.SEARCH,
                    units=units,
                    observed_at=datetime.now(UTC),
                ),
                attribution=ExecutionAttribution(
                    project_id=project, actor_type=ActorType.HUMAN, actor_id=owner
                ),
            )
        dashboard = client.get(f"/api/v1/projects/{pid}/dashboard", headers=headers)
        usage = client.get(f"/api/v1/projects/{pid}/usage", headers=headers)
        assert dashboard.status_code == usage.status_code == 200
        assert set(dashboard.json()) == {"project_id", "totals", "recent_usage", "generated_at"}
        assert dashboard.json()["totals"] == usage.json()["totals"]
        assert dashboard.json()["totals"][0]["provider"] == "own-provider"
        assert dashboard.json()["totals"][0]["event_count"] == 1
        assert "other-private-provider" not in dashboard.text
        assert "98765" not in dashboard.text
        assert "quota" not in dashboard.text
        assert "health" not in dashboard.text
        foreign = client.get(f"/api/v1/projects/{other}/usage", headers=headers)
        assert foreign.status_code == 200
        assert foreign.json()["totals"][0]["provider"] == "other-private-provider"
