"""Retention deletes only the explicitly selected project's data class."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from polyweb.models.contracts import UsageEvent, UsageOperation
from polyweb.models.observability import (
    ActorType,
    ExecutionAttribution,
    TraceOperation,
    TraceSpanKind,
    TraceSpanRecord,
)
from polyweb.models.projects import TraceSettings
from polyweb.models.retention import RetentionRunRequest
from polyweb.models.schema_enums import (
    AuditActorType,
    AuditCategory,
    AuditOutcome,
    RetentionDataClass,
)
from polyweb.models.settings import ProjectSettingsUpdate
from polyweb.persistence.audit import AuditRepository
from polyweb.persistence.otel_exporter import write_trace_spans
from polyweb.services.retention import ProjectRetentionService
from polyweb.services.settings import SettingsService
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
from tests.fixtures.auth import temp_principal
from tests.fixtures.execution import seed_execution_project


@pytest.mark.asyncio
@pytest.mark.parametrize("data_class", list(RetentionDataClass))
async def test_project_retention_isolates_other_project_system_audit_and_other_data_classes(
    tmp_path: Path, data_class: RetentionDataClass
) -> None:
    import sqlite3

    boot = await bootstrap_fresh_alpha(tmp_path / "retention-service.db")
    try:
        admin = temp_principal(boot.admin_user)
        a = boot.default_project.id
        b = (await seed_execution_project(boot.repository, user_id=admin.id, name="B")).project_id
        await SettingsService(boot.repository).update_project_settings(
            admin,
            a,
            ProjectSettingsUpdate(expected_revision=0, trace=TraceSettings(retention_days=30)),
        )
        now = datetime.now(UTC)
        old = now - timedelta(days=60)
        cutoff = now - timedelta(days=1)
        for index, project_id in enumerate((a, b), 1):
            attr = ExecutionAttribution(
                project_id=project_id, actor_type=ActorType.HUMAN, actor_id=admin.id
            )
            for timestamp in (old, now):
                await boot.repository.record_usage(
                    UsageEvent(
                        provider="tavily",
                        operation=UsageOperation.SEARCH,
                        units=index,
                        observed_at=timestamp,
                    ),
                    attribution=attr,
                )
                async with boot.repository.session() as session:
                    await AuditRepository(session).append_project_event(
                        project_id=project_id,
                        action="test.retention",
                        actor_type=AuditActorType.HUMAN,
                        actor_id=admin.id,
                        outcome=AuditOutcome.SUCCESS,
                        occurred_at=timestamp,
                    )
                    await session.commit()
            for offset, timestamp in enumerate((old, now)):
                trace_id = f"{index * 10 + offset:032x}"
                root = TraceSpanRecord(
                    project_id=project_id,
                    actor_type=ActorType.HUMAN,
                    actor_id=admin.id,
                    span_id=f"root-{index}-{offset}",
                    trace_id=trace_id,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=timestamp,
                    ended_at=timestamp,
                    duration_ms=0,
                    operation=TraceOperation.SEARCH,
                )
                # A child ending later must not survive deletion of its old root.
                child = root.model_copy(
                    update={
                        "span_id": f"child-{index}-{offset}",
                        "parent_span_id": root.span_id,
                        "started_at": now,
                        "ended_at": now,
                        "operation": None,
                    }
                )
                write_trace_spans(boot.repository.database_path, [root, child])
        async with boot.repository.session() as session:
            system = await AuditRepository(session).append_system_event(
                account_id=boot.account_id,
                category=AuditCategory.AUDIT,
                action="test.system",
                actor_type=AuditActorType.HUMAN,
                actor_id=admin.id,
                outcome=AuditOutcome.SUCCESS,
                occurred_at=old,
            )
            await session.commit()
        tables = {
            RetentionDataClass.TRACES: "trace_spans",
            RetentionDataClass.USAGE: "usage_events",
            RetentionDataClass.AUDIT: "project_audit_events",
        }

        def rows(table, project):
            with sqlite3.connect(boot.repository.database_path) as connection:
                return connection.execute(
                    f"SELECT * FROM {table} WHERE project_id=? ORDER BY 1", (str(project),)
                ).fetchall()

        before_b = {table: rows(table, b) for table in tables.values()}
        before_a = {table: rows(table, a) for table in tables.values()}
        result = await ProjectRetentionService(boot.repository).run(
            admin, a, RetentionRunRequest(data_class=data_class, cutoff=cutoff)
        )
        assert result.deleted_rows == (2 if data_class is RetentionDataClass.TRACES else 1)
        assert {table: rows(table, b) for table in tables.values()} == before_b
        for kind, table in tables.items():
            after = rows(table, a)
            if kind is data_class:
                remaining = [
                    row
                    for row in after
                    if kind is not RetentionDataClass.AUDIT or row[3] == "test.retention"
                ]
                assert len(remaining) == (2 if kind is RetentionDataClass.TRACES else 1)
                assert all(row in before_a[table] for row in remaining)
                assert len(remaining) < len(before_a[table])
            elif kind is RetentionDataClass.AUDIT:
                assert all(row in after for row in before_a[table])
                assert len(after) == len(before_a[table]) + 1
            else:
                assert after == before_a[table]
        async with boot.repository.session() as session:
            events = await AuditRepository(session).list_system_events(account_id=boot.account_id)
        assert system.id in {event.id for event in events}
    finally:
        await boot.repository.close()
