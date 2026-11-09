"""P03 persistence: revision compare-and-set and strict project scoping."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from polyweb.models.projects import ProjectCreate
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.settings import (
    ProjectSettingsRepository,
    SystemSettingsRepository,
)
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha

_NAMESPACE = "projects"


@pytest.mark.asyncio
async def test_settings_compare_and_set_is_revisioned_and_stale_safe(tmp_path: Path) -> None:
    """Every write is monotonic; a stale expectation never overwrites newer state."""

    boot = await bootstrap_fresh_alpha(tmp_path / "settings-cas.db")
    try:
        async with boot.repository.session() as session:
            system = SystemSettingsRepository(session)
            assert await system.get(_NAMESPACE) is None
            assert await system.revision(_NAMESPACE) == 0
            assert (
                await system.compare_and_set(
                    namespace=_NAMESPACE,
                    schema_version=1,
                    document={"routing": {"max_attempts": 4}},
                    expected_revision=0,
                )
                is True
            )
            await session.commit()

        async with boot.repository.session() as session:
            system = SystemSettingsRepository(session)
            stored = await system.get(_NAMESPACE)
            assert stored is not None
            assert stored.revision == 1
            assert stored.document == {"routing": {"max_attempts": 4}}
            assert (
                await system.compare_and_set(
                    namespace=_NAMESPACE,
                    schema_version=1,
                    document={"routing": {"max_attempts": 9}},
                    expected_revision=0,
                )
                is False
            )
            await session.commit()

        async with boot.repository.session() as session:
            system = SystemSettingsRepository(session)
            assert (
                await system.compare_and_set(
                    namespace=_NAMESPACE,
                    schema_version=1,
                    document={"routing": {"max_attempts": 5}},
                    expected_revision=1,
                )
                is True
            )
            await session.commit()

        async with boot.repository.session() as session:
            system = SystemSettingsRepository(session)
            stored = await system.get(_NAMESPACE)
            assert stored is not None
            assert stored.revision == 2
            assert stored.document == {"routing": {"max_attempts": 5}}
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_project_settings_reads_and_writes_are_strictly_project_scoped(
    tmp_path: Path,
) -> None:
    """Project A's row is invisible to B and vice versa at the repository seam."""

    boot = await bootstrap_fresh_alpha(tmp_path / "settings-project-scope.db")
    try:
        async with boot.repository.session() as session:
            project_b, _, _ = await ProjectRepository(session).create_project_with_admin(
                account_id=boot.account_id,
                created_by=boot.admin_user.id,
                project_create=ProjectCreate(
                    name="Second Project",
                    slug="second",
                    initial_admin_user_id=boot.admin_user.id,
                ),
            )
            await session.commit()

        async with boot.repository.session() as session:
            projects = ProjectSettingsRepository(session)
            assert (
                await projects.get(project_id=boot.default_project.id, namespace=_NAMESPACE) is None
            )
            assert await projects.get(project_id=project_b.id, namespace=_NAMESPACE) is None
            assert (
                await projects.compare_and_set(
                    project_id=boot.default_project.id,
                    namespace=_NAMESPACE,
                    schema_version=1,
                    overrides={"routing": {"max_attempts": 5}},
                    expected_revision=0,
                )
                is True
            )
            assert (
                await projects.compare_and_set(
                    project_id=project_b.id,
                    namespace=_NAMESPACE,
                    schema_version=1,
                    overrides={"routing": {"max_attempts": 7}},
                    expected_revision=0,
                )
                is True
            )
            await session.commit()

        async with boot.repository.session() as session:
            projects = ProjectSettingsRepository(session)
            stored_a = await projects.get(project_id=boot.default_project.id, namespace=_NAMESPACE)
            stored_b = await projects.get(project_id=project_b.id, namespace=_NAMESPACE)
            assert stored_a is not None
            assert stored_b is not None
            assert stored_a.document == {"routing": {"max_attempts": 5}}
            assert stored_b.document == {"routing": {"max_attempts": 7}}

            assert (
                await projects.compare_and_set(
                    project_id=boot.default_project.id,
                    namespace=_NAMESPACE,
                    schema_version=1,
                    overrides={"routing": {"max_attempts": 6}},
                    expected_revision=0,
                )
                is False
            )
            await session.commit()

        async with boot.repository.session() as session:
            projects = ProjectSettingsRepository(session)
            stored_a = await projects.get(project_id=boot.default_project.id, namespace=_NAMESPACE)
            stored_b = await projects.get(project_id=project_b.id, namespace=_NAMESPACE)
            assert stored_a is not None
            assert stored_b is not None
            assert stored_a.revision == 1
            assert stored_a.document == {"routing": {"max_attempts": 5}}
            assert stored_b.revision == 1
            assert stored_b.document == {"routing": {"max_attempts": 7}}

        async with boot.repository.session() as session:
            with pytest.raises(IntegrityError):
                await ProjectSettingsRepository(session).compare_and_set(
                    project_id=uuid4(),
                    namespace=_NAMESPACE,
                    schema_version=1,
                    overrides={},
                    expected_revision=0,
                )
            await session.rollback()
    finally:
        await boot.repository.close()
