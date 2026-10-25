"""Integration tests for project, membership, and scoped RBAC persistence (TASK-000018).

Verifies:
1. Fresh install & expected-schema validation (migration head, tables, columns, indexes, FKs).
2. Presence and status of single internal installation account (DEFAULT_INSTALLATION_ACCOUNT_ID).
3. Foreign key integrity: RESTRICT on parent delete, CASCADE on dependent rows, zero FK violations.
4. Atomic project creation with active initial admin; rollback if admin is inactive/missing.
5. Trusted bootstrap idempotency (repeated bootstrap) and public registration privilege isolation.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    ProjectCreate,
    ProjectStatus,
    ScopeType,
)
from freesearch.persistence.database_migrations import (
    migration_head,
    upgrade_database,
    validate_database_schema,
)
from freesearch.persistence.projects import (
    AccountRow,
    ProjectMembershipRow,
    ProjectRepository,
    ProjectRoleAssignmentRow,
    ProjectRow,
    bootstrap_fresh_installation,
)
from freesearch.persistence.users import UserDatabase, UserRow
from tests.fixtures.alpha_fixtures import (
    bootstrap_fresh_alpha,
    create_alpha_test_db,
    seed_alpha_system_admin,
)


@pytest.mark.asyncio
async def test_fresh_database_schema_validation_and_head_revision(tmp_path: Path) -> None:
    """AC 1 & 5: Fresh install brings database to migration head and passes schema validation."""
    db_path = tmp_path / "fresh_schema_test.db"
    assert not db_path.exists()

    result = upgrade_database(db_path)
    assert result.current_revision == migration_head()
    assert result.current_revision == "0008_project_owned_telemetry"

    # Schema validator asserts tables, columns, indexes, and FKs
    validate_database_schema(db_path)


@pytest.mark.asyncio
async def test_single_internal_installation_account_present_in_fresh_db(tmp_path: Path) -> None:
    """AC 1: Fresh databases contain exactly one internal installation account."""
    db_path = tmp_path / "install_account_test.db"
    repo = await create_alpha_test_db(db_path)
    try:
        async with repo.session() as session:
            stmt = select(AccountRow)
            accounts = (await session.execute(stmt)).scalars().all()
            assert len(accounts) == 1
            account = accounts[0]
            assert UUID(account.id) == DEFAULT_INSTALLATION_ACCOUNT_ID
            assert account.status == "active"
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_foreign_key_integrity_and_cascade_restrict_rules(tmp_path: Path) -> None:
    """AC 5: Verify foreign key integrity, RESTRICT on parent delete, and CASCADE on dependents."""
    db_path = tmp_path / "fk_integrity_test.db"
    repo = await create_alpha_test_db(db_path)
    try:
        # Seed admin user
        admin_user, _ = await seed_alpha_system_admin(repo)

        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            project, _member, _role = await project_repo.create_project_with_admin(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                created_by=admin_user.id,
                project_create=ProjectCreate(
                    name="FK Verification Project",
                    slug="fk-proj",
                    initial_admin_user_id=admin_user.id,
                ),
            )
            await session.commit()

        # 1. Deleting installation account while project exists must fail (RESTRICT)
        async with repo.session() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    delete(AccountRow).where(AccountRow.id == str(DEFAULT_INSTALLATION_ACCOUNT_ID))
                )
            await session.commit()
            await session.rollback()

        # 2. Deleting user who created project must fail (RESTRICT)
        async with repo.session() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    delete(UserRow).where(UserRow.id == admin_user.id)  # type: ignore[arg-type]
                )
                await session.commit()
            await session.rollback()

        # 3. Deleting project CASCADE deletes its memberships and role assignments
        async with repo.session() as session:
            await session.execute(delete(ProjectRow).where(ProjectRow.id == str(project.id)))
            await session.commit()

            # Verify memberships deleted
            m_stmt = select(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == str(project.id)
            )
            assert (await session.execute(m_stmt)).scalars().all() == []

            # Verify project role assignments deleted
            r_stmt = select(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.project_id == str(project.id)
            )
            assert (await session.execute(r_stmt)).scalars().all() == []
    finally:
        await repo.close()

    # 4. PRAGMA foreign_key_check passes with 0 violations
    validate_database_schema(db_path)


@pytest.mark.asyncio
async def test_atomic_project_and_initial_admin_creation(tmp_path: Path) -> None:
    """AC 4: A project and its first active project_admin assignment are created atomically."""
    db_path = tmp_path / "atomic_proj_test.db"
    repo = await create_alpha_test_db(db_path)
    try:
        admin_user, _ = await seed_alpha_system_admin(repo)

        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            project, member, role = await project_repo.create_project_with_admin(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                created_by=admin_user.id,
                project_create=ProjectCreate(
                    name="Team Alpha",
                    slug="team-alpha",
                    initial_admin_user_id=admin_user.id,
                ),
            )
            await session.commit()

            assert project.name == "Team Alpha"
            assert project.slug == "team-alpha"
            assert project.status == ProjectStatus.ACTIVE
            assert member.user_id == admin_user.id
            assert member.status == MembershipStatus.ACTIVE
            assert BuiltinRole.PROJECT_ADMIN.value in member.roles
            assert role.scope_type == ScopeType.PROJECT
            assert role.scope_id == project.id
            assert role.role_key == BuiltinRole.PROJECT_ADMIN.value

        # Verify rows exist in physical tables
        async with repo.session() as session:
            p_row = (
                await session.execute(select(ProjectRow).where(ProjectRow.id == str(project.id)))
            ).scalar_one_or_none()
            assert p_row is not None
            assert p_row.name == "Team Alpha"

            m_row = (
                await session.execute(
                    select(ProjectMembershipRow).where(
                        ProjectMembershipRow.project_id == str(project.id)
                    )
                )
            ).scalar_one_or_none()
            assert m_row is not None
            assert m_row.user_id == str(admin_user.id)

            r_row = (
                await session.execute(
                    select(ProjectRoleAssignmentRow).where(
                        ProjectRoleAssignmentRow.project_id == str(project.id)
                    )
                )
            ).scalar_one_or_none()
            assert r_row is not None
            assert r_row.role_key == BuiltinRole.PROJECT_ADMIN.value
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_atomic_project_creation_rollback_on_inactive_or_missing_user(tmp_path: Path) -> None:
    """AC 4: Inactive or missing admin user aborts project creation without persisting any rows."""
    db_path = tmp_path / "atomic_rollback_test.db"
    repo = await create_alpha_test_db(db_path)
    try:
        # 1. Create an inactive user
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            inactive_user = await user_db.create(
                {
                    "email": "inactive@freesearch.local",
                    "hashed_password": "hash",
                    "is_active": True,
                    "is_superuser": False,
                    "is_verified": True,
                }
            )
            await user_db.update(inactive_user, {"is_active": False})
            await session.commit()
            inactive_id = inactive_user.id

        # 2. Attempt project creation with inactive user -> raises ValueError
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            with pytest.raises(ValueError, match="is not active"):
                await project_repo.create_project_with_admin(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    created_by=inactive_id,
                    project_create=ProjectCreate(
                        name="Failed Project",
                        slug="failed-slug",
                        initial_admin_user_id=inactive_id,
                    ),
                )
            await session.rollback()

        # 3. Attempt project creation with non-existent user -> raises ValueError
        non_existent_id = uuid4()
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            with pytest.raises(ValueError, match="does not exist"):
                await project_repo.create_project_with_admin(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    created_by=non_existent_id,
                    project_create=ProjectCreate(
                        name="Ghost Project",
                        slug="ghost-slug",
                        initial_admin_user_id=non_existent_id,
                    ),
                )
            await session.rollback()

        # 4. Verify no project, membership, or role assignment rows were created
        async with repo.session() as session:
            projects = (await session.execute(select(ProjectRow))).scalars().all()
            assert len(projects) == 0

            members = (await session.execute(select(ProjectMembershipRow))).scalars().all()
            assert len(members) == 0

            roles = (await session.execute(select(ProjectRoleAssignmentRow))).scalars().all()
            assert len(roles) == 0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_trusted_bootstrap_idempotency_and_public_registration_privilege_isolation(
    tmp_path: Path,
) -> None:
    """AC 3: Idempotent trusted bootstrap and public role isolation."""
    db_path = tmp_path / "bootstrap_isolation_test.db"
    repo = await create_alpha_test_db(db_path)
    try:
        # 1. Trusted bootstrap assigns system_admin
        admin_user, _ = await seed_alpha_system_admin(repo, email="super@freesearch.local")
        async with repo.session() as session:
            role1 = await bootstrap_fresh_installation(session, admin_user.id)
            await session.commit()
            assert role1.role_key == BuiltinRole.SYSTEM_ADMIN.value

        # 2. Repeated bootstrap is idempotent
        async with repo.session() as session:
            role2 = await bootstrap_fresh_installation(session, admin_user.id)
            await session.commit()
            assert role2.role_key == BuiltinRole.SYSTEM_ADMIN.value

        # Verify exactly 1 system role assignment for admin
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            sys_roles = await project_repo.get_system_role_assignments(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                user_id=admin_user.id,
            )
            assert len(sys_roles) == 1
            assert sys_roles[0].role_key == BuiltinRole.SYSTEM_ADMIN.value

        # 3. Public registration path: ordinary user signs up
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            public_user = await user_db.create(
                {
                    "email": "public_registrant@example.com",
                    "hashed_password": "public_password_hash",
                    "is_active": True,
                    "is_superuser": False,
                    "is_verified": False,
                }
            )
            await session.commit()
            public_id = public_user.id

        # Verify public registration user has ZERO system roles and ZERO project roles
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            public_sys_roles = await project_repo.get_system_role_assignments(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                user_id=public_id,
            )
            assert len(public_sys_roles) == 0

            public_proj_roles_stmt = select(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.user_id == str(public_id)
            )
            public_proj_roles = (await session.execute(public_proj_roles_stmt)).scalars().all()
            assert len(public_proj_roles) == 0

            public_memberships_stmt = select(ProjectMembershipRow).where(
                ProjectMembershipRow.user_id == str(public_id)
            )
            public_memberships = (await session.execute(public_memberships_stmt)).scalars().all()
            assert len(public_memberships) == 0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_full_project_member_addition_and_role_management(tmp_path: Path) -> None:
    """AC 1 & 4: Adding project members and managing project-scoped roles."""
    db_path = tmp_path / "project_membership_flow.db"
    result = await bootstrap_fresh_alpha(
        db_path,
        admin_email="org_admin@freesearch.local",
        project_name="Workspace Delta",
    )
    try:
        repo = result.repository
        project = result.default_project

        # Register a new team member
        async with repo.session() as session:
            user_db = UserDatabase(session, UserRow)
            member_user = await user_db.create(
                {
                    "email": "teammate@freesearch.local",
                    "hashed_password": "teammate_hash",
                    "is_active": True,
                    "is_superuser": False,
                    "is_verified": True,
                }
            )
            await session.commit()
            member_id = member_user.id

        # Add member to project with PROJECT_MEMBER role
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            member_read, role_read = await project_repo.add_project_member(
                project_id=project.id,
                user_id=member_id,
                role_key=BuiltinRole.PROJECT_MEMBER.value,
                granted_by=result.admin_user.id,
            )
            await session.commit()

            assert member_read.user_id == member_id
            assert member_read.status == MembershipStatus.ACTIVE
            assert BuiltinRole.PROJECT_MEMBER.value in member_read.roles
            assert role_read.role_key == BuiltinRole.PROJECT_MEMBER.value

        # Assign extra role (ROUTING_EDITOR)
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            extra_role = await project_repo.assign_project_role(
                project_id=project.id,
                user_id=member_id,
                role_key=BuiltinRole.ROUTING_EDITOR.value,
                granted_by=result.admin_user.id,
            )
            await session.commit()
            assert extra_role.role_key == BuiltinRole.ROUTING_EDITOR.value

        # Inspect members
        async with repo.session() as session:
            project_repo = ProjectRepository(session)
            members = await project_repo.get_project_members(project_id=project.id)
            assert len(members) == 2
            member_map = {m.user_id: m for m in members}
            assert BuiltinRole.PROJECT_ADMIN.value in member_map[result.admin_user.id].roles
            teammate_roles = member_map[member_id].roles
            assert BuiltinRole.PROJECT_MEMBER.value in teammate_roles
            assert BuiltinRole.ROUTING_EDITOR.value in teammate_roles
    finally:
        await result.repository.close()
