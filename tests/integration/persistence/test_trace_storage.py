"""Trace repository reads: list/detail contracts over seeded fixture traces.

Seeds the checked-in ``tests/fixtures/observability/*.json`` documents through
the public ``write_trace_spans`` path and reads them back through
``SQLiteRepository``. No live network; the only I/O is ``tmp_path`` databases.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest_asyncio

from polyweb.models.observability import (
    ActorType,
    TraceEventDetail,
    TraceFetchOutput,
    TraceOperation,
    TraceOutcome,
    TraceSearchOutput,
    TraceSpanKind,
    TraceSpanRecord,
    TraceStatusCode,
)
from polyweb.persistence.otel_exporter import write_trace_spans
from polyweb.persistence.storage import SQLiteRepository

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "observability"

#: Two fixed account UUIDs for owner-isolation checks.
OWNER_A = UUID("11111111-1111-4111-8111-111111111111")
OWNER_B = UUID("22222222-2222-4222-8222-222222222222")


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "traces.db")
    yield repo
    await repo.close()


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _records_from_fixture(document: dict[str, Any], owner: UUID) -> list[TraceSpanRecord]:
    trace_id = str(document["trace_id"])
    records: list[TraceSpanRecord] = []
    for span in document["spans"]:
        is_root = span["parent_span_id"] is None
        error = span.get("error") or {}
        events = [
            TraceEventDetail(
                name=event["name"],
                timestamp=datetime.fromisoformat(event["timestamp"]),
                attributes=dict(event.get("attributes") or {}),
            )
            for event in span.get("events", [])
        ]
        output = document.get("output")
        records.append(
            TraceSpanRecord(
                project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
                actor_type=ActorType.HUMAN,
                actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
                span_id=span["span_id"],
                trace_id=trace_id,
                parent_span_id=span["parent_span_id"],
                name=span["name"],
                kind=TraceSpanKind(span["kind"]),
                started_at=datetime.fromisoformat(span["started_at"]),
                ended_at=datetime.fromisoformat(span["ended_at"]),
                duration_ms=span["duration_ms"],
                status_code=TraceStatusCode(span["status_code"]),
                status_message=error.get("message"),
                outcome=TraceOutcome(span["outcome"]),
                error_type=span.get("error_type"),
                operation=TraceOperation(document["operation"]) if is_root else None,
                # Fixture loader contract (PLAN §6.1 item 6 loader half):
                # the document provider seeds only the root summary row;
                # every child span reads its own span-level `provider` field
                # (None when the fixture records no identity for that span).
                provider=(document.get("provider") if is_root else span.get("provider")),
                input_text=document.get("input_text") if is_root else None,
                output_json=json.dumps(output) if is_root and output is not None else None,
                result_count=document.get("result_count") if is_root else None,
                events=events,
                # Only the root carries the owner. Child rows keep a null
                # owner because the owned root supplies authorization.
                user_id=str(owner) if is_root else None,
            )
        )
    return records


def _synthetic_root(
    trace_id: str,
    started: datetime,
    owner: UUID,
    *,
    operation: TraceOperation = TraceOperation.SEARCH,
    outcome: TraceOutcome = TraceOutcome.SUCCESS,
    provider: str = "keenable",
    result_count: int | None = 1,
) -> TraceSpanRecord:
    return TraceSpanRecord(
        project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
        actor_type=ActorType.HUMAN,
        actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
        span_id=f"root-{trace_id[-8:]}",
        trace_id=trace_id,
        name="POST /search",
        kind=TraceSpanKind.SERVER,
        started_at=started,
        ended_at=started,
        duration_ms=5,
        operation=operation,
        provider=provider,
        input_text="synthetic",
        result_count=result_count,
        outcome=outcome,
        user_id=str(owner),
    )


async def _seed(repository: SQLiteRepository, owner: UUID, *names: str) -> None:
    for name in names:
        write_trace_spans(
            repository.database_path,
            _records_from_fixture(_load_fixture(name), owner),
        )


async def test_success_fixture_round_trips_summary_and_detail(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json")

    summaries = await repository.list_trace_summaries(user_id=OWNER_A)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.trace_id == "e1c2d3a4b5c6d7e8f9012345678abcde"
    assert summary.operation is TraceOperation.SEARCH
    assert summary.provider == "keenable"
    assert summary.outcome is TraceOutcome.SUCCESS
    assert summary.result_count == 2
    assert summary.duration_ms == 248
    assert summary.error is None

    detail = await repository.get_trace(summary.trace_id, user_id=OWNER_A)
    assert detail is not None
    assert detail.input == "distributed consensus algorithms"
    assert isinstance(detail.output, TraceSearchOutput)
    assert [item.url for item in detail.output.results] == [
        "https://docs.polyweb.dev/consensus",
        "https://docs.polyweb.dev/raft-vs-paxos",
    ]
    assert len(detail.spans) == 7
    assert [(span.started_at, span.span_id) for span in detail.spans] == sorted(
        [(span.started_at, span.span_id) for span in detail.spans]
    )
    provider_span = next(span for span in detail.spans if span.name == "polyweb.provider")
    assert [event.name for event in provider_span.events] == [
        "polyweb.provider.request",
        "polyweb.provider.response",
    ]
    assert all(span.duration_ms >= 0 for span in detail.spans)


async def test_error_fixture_projects_error_without_output(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "provider_error.json")

    summaries = await repository.list_trace_summaries(user_id=OWNER_A)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.operation is TraceOperation.FETCH
    assert summary.outcome is TraceOutcome.ERROR
    assert summary.result_count is None
    assert summary.error is not None
    assert summary.error.type == "http_error"
    assert summary.error.message == "HTTP 502"

    detail = await repository.get_trace(summary.trace_id, user_id=OWNER_A)
    assert detail is not None
    assert detail.input == "https://docs.polyweb.dev/getting-started"
    assert detail.output is None
    exception_events = [
        event for span in detail.spans for event in span.events if event.name == "exception"
    ]
    assert len(exception_events) == 1
    assert exception_events[0].attributes["exception.type"] == "ProviderOperationError"


async def test_list_is_newest_first_with_operation_and_outcome_filters(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json", "provider_error.json")

    summaries = await repository.list_trace_summaries(user_id=OWNER_A)
    assert [item.trace_id for item in summaries] == [
        "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        "e1c2d3a4b5c6d7e8f9012345678abcde",
    ]

    assert [item.operation for item in await repository.list_trace_summaries(user_id=OWNER_A)] == [
        TraceOperation.FETCH,
        TraceOperation.SEARCH,
    ]
    fetched = await repository.list_trace_summaries(user_id=OWNER_A, operation=TraceOperation.FETCH)
    assert [item.trace_id for item in fetched] == ["0f1e2d3c4b5a69788796a5b4c3d2e1f0"]
    searched = await repository.list_trace_summaries(
        user_id=OWNER_A, operation=TraceOperation.SEARCH
    )
    assert [item.trace_id for item in searched] == ["e1c2d3a4b5c6d7e8f9012345678abcde"]
    succeeded = await repository.list_trace_summaries(user_id=OWNER_A, outcome=TraceOutcome.SUCCESS)
    assert [item.trace_id for item in succeeded] == ["e1c2d3a4b5c6d7e8f9012345678abcde"]
    errored = await repository.list_trace_summaries(user_id=OWNER_A, outcome=TraceOutcome.ERROR)
    assert [item.trace_id for item in errored] == ["0f1e2d3c4b5a69788796a5b4c3d2e1f0"]
    assert (
        await repository.list_trace_summaries(user_id=OWNER_A, outcome=TraceOutcome.PARTIAL) == []
    )


async def test_list_limit_clamps_to_1_and_100(repository: SQLiteRepository) -> None:
    base = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    for index in range(5):
        started = datetime.fromtimestamp(base.timestamp() + index * 60, tz=UTC)
        write_trace_spans(
            repository.database_path,
            [_synthetic_root(f"{index:032x}", started, OWNER_A, result_count=index)],
        )

    assert len(await repository.list_trace_summaries(user_id=OWNER_A, limit=0)) == 1
    assert len(await repository.list_trace_summaries(user_id=OWNER_A, limit=-5)) == 1
    assert len(await repository.list_trace_summaries(user_id=OWNER_A, limit=2)) == 2
    assert len(await repository.list_trace_summaries(user_id=OWNER_A, limit=5000)) == 5


async def test_list_rows_are_summary_only(repository: SQLiteRepository) -> None:
    await _seed(repository, OWNER_A, "search_success.json", "provider_error.json")

    summaries = await repository.list_trace_summaries(user_id=OWNER_A)

    assert len(summaries) == 2
    for summary in summaries:
        assert summary.user_id == str(OWNER_A)
        assert summary.actor_type is ActorType.HUMAN
        assert str(summary.actor_id) == "00000000-0000-4000-8000-0000000000bb"
        assert summary.username is None
        assert summary.first_name is None
        assert summary.last_name is None
        assert summary.email is None
        assert set(summary.model_dump(mode="json")) == {
            "trace_id",
            "user_id",
            "actor_type",
            "actor_id",
            "username",
            "first_name",
            "last_name",
            "email",
            "operation",
            "started_at",
            "duration_ms",
            "provider",
            "outcome",
            "result_count",
            "error",
        }


async def test_detail_orders_concurrent_fanout_children_stably(
    repository: SQLiteRepository,
) -> None:
    moment = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
    trace_id = "f" * 32
    root = TraceSpanRecord(
        project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
        actor_type=ActorType.HUMAN,
        actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
        span_id="aa00000000000000",
        trace_id=trace_id,
        name="POST /search",
        kind=TraceSpanKind.SERVER,
        started_at=moment,
        ended_at=moment,
        duration_ms=100,
        operation=TraceOperation.SEARCH,
        provider="aggregated",
        input_text="fanout query",
        result_count=2,
        user_id=str(OWNER_A),
    )
    children = [
        TraceSpanRecord(
            project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
            actor_type=ActorType.HUMAN,
            actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id="aa00000000000000",
            name="polyweb.provider",
            kind=TraceSpanKind.CLIENT,
            started_at=moment,
            ended_at=moment,
            duration_ms=50,
            provider=name,
            # The last child models a failed/zero-result provider attempt:
            # identity must survive even when the call recorded an error.
            status_code=(TraceStatusCode.ERROR if name == "brave" else TraceStatusCode.UNSET),
            outcome=(TraceOutcome.ERROR if name == "brave" else TraceOutcome.SUCCESS),
            error_type="http_error" if name == "brave" else None,
            status_message="HTTP 502" if name == "brave" else None,
        )
        for span_id, name in [
            ("cc00000000000003", "brave"),
            ("aa00000000000001", "exa"),
            ("bb00000000000002", "tavily"),
        ]
    ]
    # Insert out of order; the read must still return a stable timeline.
    write_trace_spans(repository.database_path, [children[0], root, children[2], children[1]])

    detail = await repository.get_trace(trace_id, user_id=OWNER_A)

    assert detail is not None
    assert detail.user_id == str(OWNER_A)
    assert detail.spans[0].span_id == "aa00000000000000"
    assert [span.span_id for span in detail.spans[1:]] == [
        "aa00000000000001",
        "bb00000000000002",
        "cc00000000000003",
    ]
    # RED (PLAN §6.1 item 3): distinct child providers must survive the
    # stable (started_at, span_id) ordering, including the failed span.
    # Fails because storage drops row.provider when projecting the detail.
    assert [span.provider for span in detail.spans[1:]] == [
        "exa",
        "tavily",
        "brave",
    ]
    assert detail.spans[0].provider == "aggregated"
    failed_child = next(span for span in detail.spans if span.span_id == "cc00000000000003")
    assert failed_child.outcome is TraceOutcome.ERROR
    assert failed_child.provider == "brave"


async def test_get_trace_returns_none_for_unknown_id(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json")

    assert await repository.get_trace("0" * 32, user_id=OWNER_A) is None


async def test_fetch_detail_output_shape(repository: SQLiteRepository) -> None:
    moment = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    trace_id = "9" * 32
    output = TraceFetchOutput(
        url="https://docs.polyweb.dev/page",
        title="Page",
        content="hello world",
        content_length=11,
        truncated=False,
    )
    write_trace_spans(
        repository.database_path,
        [
            TraceSpanRecord(
                project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
                actor_type=ActorType.HUMAN,
                actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
                span_id="ab00000000000001",
                trace_id=trace_id,
                name="POST /fetch",
                kind=TraceSpanKind.SERVER,
                started_at=moment,
                ended_at=moment,
                duration_ms=40,
                operation=TraceOperation.FETCH,
                provider="keenable",
                input_text="https://docs.polyweb.dev/page",
                output_json=output.model_dump_json(),
                result_count=1,
                user_id=str(OWNER_A),
            )
        ],
    )

    detail = await repository.get_trace(trace_id, user_id=OWNER_A)

    assert detail is not None
    assert detail.operation is TraceOperation.FETCH
    assert isinstance(detail.output, TraceFetchOutput)
    assert detail.output.content == "hello world"


async def test_each_account_lists_only_its_own_traces(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json")
    await _seed(repository, OWNER_B, "provider_error.json")

    owned_a = await repository.list_trace_summaries(user_id=OWNER_A)
    owned_b = await repository.list_trace_summaries(user_id=OWNER_B)

    assert [item.trace_id for item in owned_a] == ["e1c2d3a4b5c6d7e8f9012345678abcde"]
    assert [item.trace_id for item in owned_b] == ["0f1e2d3c4b5a69788796a5b4c3d2e1f0"]
    assert all(item.user_id == str(OWNER_A) for item in owned_a)
    assert all(item.user_id == str(OWNER_B) for item in owned_b)


async def test_owner_filters_stay_inside_the_owner_predicate(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json")
    await _seed(repository, OWNER_B, "provider_error.json")

    assert (
        await repository.list_trace_summaries(user_id=OWNER_A, operation=TraceOperation.FETCH) == []
    )
    assert (
        await repository.list_trace_summaries(user_id=OWNER_B, operation=TraceOperation.SEARCH)
        == []
    )
    assert [
        item.trace_id
        for item in await repository.list_trace_summaries(
            user_id=OWNER_A, outcome=TraceOutcome.SUCCESS
        )
    ] == ["e1c2d3a4b5c6d7e8f9012345678abcde"]


async def test_foreign_unknown_and_unowned_detail_reads_return_none(
    repository: SQLiteRepository,
) -> None:
    await _seed(repository, OWNER_A, "search_success.json")
    write_trace_spans(
        repository.database_path,
        _records_from_fixture(_load_fixture("provider_error.json"), OWNER_B),
    )
    # One historical row keeps a null owner in the database.
    legacy = TraceSpanRecord(
        project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
        actor_type=ActorType.HUMAN,
        actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
        span_id="legacy-root",
        trace_id="c" * 32,
        name="POST /search",
        kind=TraceSpanKind.SERVER,
        started_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
        ended_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
        duration_ms=5,
        operation=TraceOperation.SEARCH,
        provider="keenable",
    )
    write_trace_spans(repository.database_path, [legacy])

    assert await repository.get_trace("e1c2d3a4b5c6d7e8f9012345678abcde", user_id=OWNER_B) is None
    assert await repository.get_trace("0f1e2d3c4b5a69788796a5b4c3d2e1f0", user_id=OWNER_A) is None
    assert await repository.get_trace("0" * 32, user_id=OWNER_A) is None
    assert await repository.get_trace("c" * 32, user_id=OWNER_A) is None
    assert await repository.get_trace("c" * 32, user_id=OWNER_B) is None
    assert [item.trace_id for item in await repository.list_trace_summaries(user_id=OWNER_A)] == [
        "e1c2d3a4b5c6d7e8f9012345678abcde"
    ]


async def test_limit_applies_after_the_owner_predicate(
    repository: SQLiteRepository,
) -> None:
    base = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    for tag, owner in (("a", OWNER_A), ("b", OWNER_B)):
        for index in range(3):
            started = datetime.fromtimestamp(base.timestamp() + index * 60, tz=UTC)
            trace_id = f"{tag}{index:031x}"
            write_trace_spans(
                repository.database_path,
                [
                    TraceSpanRecord(
                        project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
                        actor_type=ActorType.HUMAN,
                        actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
                        span_id=f"{tag}{index:015x}",
                        trace_id=trace_id,
                        name="POST /search",
                        kind=TraceSpanKind.SERVER,
                        started_at=started,
                        ended_at=started,
                        duration_ms=5,
                        operation=TraceOperation.SEARCH,
                        provider="keenable",
                        user_id=str(owner),
                    )
                ],
            )

    assert len(await repository.list_trace_summaries(user_id=OWNER_A, limit=2)) == 2
    assert len(await repository.list_trace_summaries(user_id=OWNER_B, limit=5000)) == 3
