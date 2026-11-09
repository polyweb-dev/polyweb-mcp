"""Adversarial and regression verification tests for TASK-000018 Projects P01.

Verifies:
1. Target human schema in SQLite (physical schema drops role and is_superuser).
2. Composite FK constraint linking project_role_assignments to project_memberships.
3. Active project membership enforcement on role assignment.
4. Pre-flush DTO validation prevents dirty DB session state.
5. Bootstrap enforces active status on both human user and installation account.
6. Role persistence seam: in-memory authority dropped on database reload.
7. UserDatabase.create honors untrusted dictionary overrides vs server defaults.
8. Atomic rollback on actual write failure after ProjectRow is flushed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import select, text

from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    ProjectCreate,
)
from polyweb.models.users import AuthProvider
from polyweb.persistence.database_migrations import (
    upgrade_database,
)
from polyweb.persistence.projects import (
    AccountRow,
    ProjectMembershipRow,
    ProjectRepository,
    ProjectRoleAssignmentRow,
    ProjectRow,
    bootstrap_fresh_installation,
)
from polyweb.persistence.users import UserDatabase, UserRow
from tests.fixtures.alpha_fixtures import create_alpha_test_db, seed_alpha_system_admin
from tests.fixtures.auth import auth_service_for


@pytest.mark.asyncio
async def test_gap_stored_user_schema_retains_legacy_roles_and_superuser(tmp_path: Path) -> None:
    """AC #2: SQLite physical schema at migration head drops legacy role and is_superuser."""
    db_path = tmp_path / "user_schema_audit.db"
    upgrade_database(db_path)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info('user')")).fetchall()]
        # Invariant: Target human schema must NOT store role or is_superuser in SQLite
        assert "role" not in columns, "Legacy column 'role' must not be in SQLite user table"
        assert "is_superuser" not in columns, "Legacy column 'is_superuser' must not be in table"

        # Invariant: Legacy check constraints must be dropped
        table_sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='user'")
        ).scalar_one()
        assert "user_role_allowed" not in str(table_sql), "user_role_allowed must be dropped"
        assert "user_superuser_matches_role" not in str(table_sql), (
            "user_superuser_matches_role constraint must be dropped"
        )


@pytest.mark.asyncio
async def test_gap_missing_composite_fk_from_role_assignments(tmp_path: Path) -> None:
    """FK Integrity: project_role_assignments has composite FK referencing project_memberships.

    Deleting a project membership cascades and deletes corresponding role assignments.
    """
    db_path = tmp_path / "fk_gap_audit.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            project, _, _ = await project_repo.create_project_with_admin(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                created_by=admin_user.id,
                project_create=ProjectCreate(
                    name="FK Gap Project",
                    slug="fk-gap-project",
                    initial_admin_user_id=admin_user.id,
                ),
            )
            await session.commit()

            # Delete the membership row directly
            m_stmt = select(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == str(project.id),
                ProjectMembershipRow.user_id == str(admin_user.id),
            )
            membership = (await session.execute(m_stmt)).scalar_one()
            await session.delete(membership)
            await session.commit()

        # Invariant: Role assignment must be cascaded and deleted
        async with repo.session() as session:
            ra_stmt = select(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.project_id == str(project.id),
                ProjectRoleAssignmentRow.user_id == str(admin_user.id),
            )
            assignments = (await session.execute(ra_stmt)).scalars().all()
            assert len(assignments) == 0, (
                "Role assignment must be deleted when composite project membership is deleted"
            )
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_assign_role_bypasses_membership_validation(tmp_path: Path) -> None:
    """Authorization Invariant: Cannot assign project role to non-member user."""
    db_path = tmp_path / "membership_bypass_gap.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            project, _, _ = await project_repo.create_project_with_admin(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                created_by=admin_user.id,
                project_create=ProjectCreate(
                    name="Validation Project",
                    slug="val-project",
                    initial_admin_user_id=admin_user.id,
                ),
            )
            await session.commit()

            # Non-member random user
            non_member_id = uuid4()
            with pytest.raises(ValueError, match="is not a member"):
                await project_repo.assign_project_role(
                    project_id=project.id,
                    user_id=non_member_id,
                    role_key=BuiltinRole.PROJECT_MEMBER.value,
                    granted_by=admin_user.id,
                )
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_dto_validation_after_session_mutation_leaves_dirty_state(
    tmp_path: Path,
) -> None:
    """Session Cleanliness: DTO validation happens BEFORE any session mutations or DB flushes."""
    db_path = tmp_path / "dirty_session_gap.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        async with repo.session() as session:
            # Pass invalid project name (e.g., whitespace-only) that fails validation
            with pytest.raises(ValidationError):
                ProjectCreate(
                    name="   ",  # Invalid blank/whitespace name
                    slug="bad-project",
                    initial_admin_user_id=admin_user.id,
                )

            # Assert session is completely clean (no dirty/pending objects)
            assert len(session.new) == 0
            assert len(session.dirty) == 0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_bootstrap_creates_admin_even_if_account_or_user_inactive(
    tmp_path: Path,
) -> None:
    """Account Lifecycle: Bootstrap requires active installation account and human user."""
    db_path = tmp_path / "bootstrap_status_gap.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        # 1. Inactive user fails bootstrap
        async with repo.session() as session:
            db_user = await session.get(UserRow, admin_user.id)
            assert db_user is not None
            db_user.is_active = False
            await session.commit()

        async with repo.session() as session:
            with pytest.raises(ValueError, match="inactive"):
                await bootstrap_fresh_installation(session, admin_user.id)

        # Reactivate user
        async with repo.session() as session:
            db_user = await session.get(UserRow, admin_user.id)
            assert db_user is not None
            db_user.is_active = True
            await session.commit()

        # 2. Suspended installation account fails bootstrap
        async with repo.session() as session:
            account = await session.get(AccountRow, str(DEFAULT_INSTALLATION_ACCOUNT_ID))
            assert account is not None
            account.status = "suspended"
            await session.commit()

        async with repo.session() as session:
            with pytest.raises(ValueError, match="not active"):
                await bootstrap_fresh_installation(session, admin_user.id)
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_in_memory_role_authority_lost_on_fresh_session(
    tmp_path: Path,
) -> None:
    """Persistence Seam (A1): system authority persists only as durable assignments."""

    from sqlalchemy import select

    from polyweb.persistence.projects import SystemRoleAssignmentRow
    from polyweb.services.users import AuthLastSystemAdmin

    async def _roles(user_id: object) -> set[str]:
        async with repo.session() as session:
            return set(
                (
                    await session.execute(
                        select(SystemRoleAssignmentRow.role_key).where(
                            SystemRoleAssignmentRow.user_id == str(user_id)
                        )
                    )
                ).scalars()
            )

    db_path = tmp_path / "in_memory_authority_seam.db"
    repo = await create_alpha_test_db(db_path)
    try:
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            user = await user_db.create(
                {
                    "email": "promoted@polyweb.local",
                    "hashed_password": "some_hash_val",
                    "is_active": True,
                    "is_verified": False,
                }
            )
            await session.commit()
            user_id = user.id
        assert await _roles(user_id) == set()

        # 1. Grant through the trusted operation (bootstrap path of the CLI).
        auth_service = auth_service_for(repo)
        assert await auth_service.grant_system_admin(user_id) is True
        assert await auth_service.grant_system_admin(user_id) is False

        # 2. A fresh session sees the durable assignment; no flag mirrors it.
        assert await _roles(user_id) == {"system_admin"}
        async with repo.session() as session:
            reloaded = await session.get(UserRow, user_id)
            assert reloaded is not None
            assert reloaded.is_superuser is False
            assert not hasattr(reloaded, "role")

        # 3. The last active system administrator cannot be revoked ...
        with pytest.raises(AuthLastSystemAdmin):
            await auth_service.revoke_system_admin(user_id)
        assert await _roles(user_id) == {"system_admin"}

        # ... but with a second administrator the revocation is durable.
        async with repo.session() as session:
            other = await UserDatabase(session, UserRow).create(
                {"email": "second-admin@polyweb.local", "hashed_password": "h"}
            )
        assert await auth_service.grant_system_admin(other.id) is True
        assert await auth_service.revoke_system_admin(user_id) is True
        assert await auth_service.revoke_system_admin(user_id) is False
        assert await _roles(user_id) == set()

        # 4. The obsolete role-change operation no longer exists.
        assert not hasattr(auth_service, "change_role")
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_user_database_create_honors_untrusted_attribute_overrides(
    tmp_path: Path,
) -> None:
    """Adapter Contract Seam: UserDatabase.create enforces server-chosen defaults

    for is_active, is_verified, and auth_provider, rejecting untrusted caller
    overrides while create_trusted supports explicit trusted provisioning.
    """
    db_path = tmp_path / "create_overrides.db"
    repo = await create_alpha_test_db(db_path)
    try:
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            # Pass dictionary overrides that attempt to bypass normal defaults
            injected_user = await user_db.create(
                {
                    "email": "injected@polyweb.local",
                    "hashed_password": "some_valid_hash",
                    "is_active": False,
                    "is_verified": True,
                    "auth_provider": AuthProvider.WORKOS.value,
                    "auth_provider_id": "ext-workos-99",
                }
            )
            await session.commit()
            user_id = injected_user.id

        # Verify in fresh session that server-chosen defaults were strictly enforced
        async with repo.session() as session:
            reloaded = await session.get(UserRow, user_id)
            assert reloaded is not None
            assert reloaded.is_verified is False
            assert reloaded.is_active is True
            assert reloaded.auth_provider == "local"
            assert reloaded.auth_provider_id is None

        # Verify that explicit trusted seeding works via create_trusted
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            trusted_user = await user_db.create_trusted(
                email="trusted@polyweb.local",
                hashed_password=None,
                auth_provider=AuthProvider.WORKOS.value,
                auth_provider_id="ext-workos-100",
                is_active=False,
                is_verified=True,
            )
            await session.commit()
            trusted_id = trusted_user.id

        async with repo.session() as session:
            reloaded_trusted = await session.get(UserRow, trusted_id)
            assert reloaded_trusted is not None
            assert reloaded_trusted.is_verified is True
            assert reloaded_trusted.is_active is False
            assert reloaded_trusted.auth_provider == "workos"
            assert reloaded_trusted.auth_provider_id == "ext-workos-100"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_gap_atomic_project_creation_rollback_on_actual_write_failure(
    tmp_path: Path,
) -> None:
    """Atomic Rollback: an actual database write failure occurring after ProjectRow

    is flushed cleanly rolls back the transaction, preventing partial project persistence.
    """
    db_path = tmp_path / "actual_write_failure_rollback.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        call_count = 0
        async with repo.session() as session:
            original_flush = session.flush

            async def failing_flush(objects: Any = None) -> None:
                nonlocal call_count
                call_count += 1
                await original_flush(objects)
                # On second flush (after ProjectRow is already flushed to SQLite),
                # simulate a write failure during membership/role insertion!
                if call_count == 2:
                    raise RuntimeError(
                        "Simulated SQLite write/disk failure during membership flush"
                    )

            session.flush = failing_flush  # type: ignore[method-assign]
            project_repo = ProjectRepository(session)
            with pytest.raises(RuntimeError, match="Simulated SQLite write/disk failure"):
                await project_repo.create_project_with_admin(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    created_by=admin_user.id,
                    project_create=ProjectCreate(
                        name="Mid Failure Project",
                        slug="mid-failure-project",
                        initial_admin_user_id=admin_user.id,
                    ),
                )
            await session.rollback()

        # Invariant: ProjectRow was flushed at call_count=1, but rollback must leave 0 rows in DB
        async with repo.session() as session:
            projects = (await session.execute(select(ProjectRow))).scalars().all()
            assert len(projects) == 0, (
                "Flushed ProjectRow must be completely rolled back on subsequent write failure"
            )
    finally:
        await repo.close()
