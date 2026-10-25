"""Project and membership persistence: rows, repository, and installation bootstrap.

SQLAlchemy rows and SQL operations for:
- accounts (internal installation boundary)
- projects (project workspace metadata and status)
- project_memberships (association of human users to projects)
- system_role_assignments (system-scoped RBAC assignments)
- project_role_assignments (project-scoped RBAC assignments)

Repositories enforce strict project scoping on all queries and mutations.
Project creation with initial administrator is strictly atomic within a single transaction.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    cast,
    delete,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    ProjectCreate,
    ProjectMemberRead,
    ProjectRead,
    ProjectStatus,
    RoleAssignmentRead,
    ScopeType,
)
from freesearch.persistence.storage import Base

if TYPE_CHECKING:
    from freesearch.persistence.users import UserRow


def _get_user_row() -> type[UserRow]:
    from freesearch.persistence.users import UserRow

    return UserRow


def _generate_slug(name: str) -> str:
    """Generate a clean URL-friendly slug from a project name."""
    slug = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug or "project"


def _project_row_to_read(row: ProjectRow) -> ProjectRead:
    """Map a ProjectRow to a ProjectRead model."""
    return ProjectRead(
        id=UUID(row.id),
        account_id=UUID(row.account_id),
        name=row.name,
        slug=row.slug,
        status=ProjectStatus(row.status),
        created_by=UUID(row.created_by),
        created_at=datetime.fromisoformat(row.created_at),
        version=row.version,
    )


class AccountRow(Base):
    """Internal installation account boundary."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="accounts_status_allowed"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class ProjectRow(Base):
    """Project workspace boundary."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="projects_status_allowed"),
        CheckConstraint("version >= 1", name="projects_version_positive"),
        Index("ix_projects_account_id", "account_id"),
        Index("ix_projects_slug", "slug"),
        Index("ix_projects_account_id_slug", "account_id", "slug", unique=True),
        Index("ix_projects_created_by", "created_by"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.ACTIVE.value
    )
    created_by: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectMembershipRow(Base):
    """Association between human user and project workspace."""

    __tablename__ = "project_memberships"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended')", name="project_memberships_status_allowed"
        ),
        CheckConstraint("version >= 1", name="project_memberships_version_positive"),
        Index("ix_project_memberships_user_id", "user_id"),
    )

    project_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MembershipStatus.ACTIVE.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SystemRoleAssignmentRow(Base):
    """System-scoped RBAC role assignment."""

    __tablename__ = "system_role_assignments"
    __table_args__ = (
        CheckConstraint("version >= 1", name="system_role_assignments_version_positive"),
        Index("ix_system_role_assignments_user_id", "user_id"),
    )

    account_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    role_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_by: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectRoleAssignmentRow(Base):
    """Project-scoped RBAC role assignment."""

    __tablename__ = "project_role_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["project_memberships.project_id", "project_memberships.user_id"],
            name="project_role_assignments_membership_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 1", name="project_role_assignments_version_positive"),
        Index("ix_project_role_assignments_user_id", "user_id"),
        Index("ix_project_role_assignments_project_user", "project_id", "user_id"),
    )

    project_id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    role_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_by: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectRepository:
    """Repository enforcing strict project parameters and atomic transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_project_with_admin(
        self,
        *,
        account_id: UUID,
        created_by: UUID,
        project_create: ProjectCreate,
    ) -> tuple[ProjectRead, ProjectMemberRead, RoleAssignmentRead]:
        """Atomically create a project and its first active project_admin assignment.

        Invariants enforced:
        - Target account exists and is active.
        - Initial admin user exists and is active.
        - Project, membership, and project_admin role assignment are created
          in a single atomic transaction.
        - If any check fails or error occurs, transaction rolls back cleanly.
        """
        admin_user_id = project_create.initial_admin_user_id
        if admin_user_id is None:
            raise ValueError("project creation requires a resolved initial_admin_user_id")

        # Validate account exists and is active
        account_stmt = select(AccountRow).where(AccountRow.id == str(account_id))
        account_row = (await self._session.execute(account_stmt)).scalar_one_or_none()
        if account_row is None:
            raise ValueError(f"Target account {account_id} does not exist")
        if account_row.status != "active":
            raise ValueError(f"Target account {account_id} is not active")

        # Validate initial admin exists and is an active human user
        user_cls = _get_user_row()
        user_stmt = select(user_cls).where(
            user_cls.id == admin_user_id  # type: ignore[arg-type]
        )
        admin_user = (await self._session.execute(user_stmt)).scalar_one_or_none()
        if admin_user is None:
            raise ValueError(f"Initial admin user {admin_user_id} does not exist")
        if not admin_user.is_active:
            raise ValueError(f"Initial admin user {admin_user_id} is not active")

        project_id = uuid4()
        slug = project_create.slug or _generate_slug(project_create.name)
        now_utc = datetime.now(UTC)
        now_iso = now_utc.isoformat()

        # Check unique slug for account
        existing_slug_stmt = select(ProjectRow).where(
            ProjectRow.account_id == str(account_id),
            ProjectRow.slug == slug,
        )
        if (await self._session.execute(existing_slug_stmt)).scalar_one_or_none() is not None:
            raise ValueError(f"Project with slug {slug!r} already exists in account")

        # 1. Project record
        project_row = ProjectRow(
            id=str(project_id),
            account_id=str(account_id),
            name=project_create.name,
            slug=slug,
            status=ProjectStatus.ACTIVE.value,
            created_by=str(created_by),
            created_at=now_iso,
            version=1,
        )
        self._session.add(project_row)
        await self._session.flush()

        # 2. Initial membership (ACTIVE)
        membership_row = ProjectMembershipRow(
            project_id=str(project_id),
            user_id=str(admin_user_id),
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        self._session.add(membership_row)
        await self._session.flush()

        # 3. Initial project_admin assignment
        role_row = ProjectRoleAssignmentRow(
            project_id=str(project_id),
            user_id=str(admin_user_id),
            role_key=BuiltinRole.PROJECT_ADMIN.value,
            granted_by=str(created_by),
            version=1,
        )
        self._session.add(role_row)
        await self._session.flush()

        project_read = _project_row_to_read(project_row)
        member_read = ProjectMemberRead(
            project_id=project_id,
            user_id=admin_user_id,
            email=admin_user.email,
            status=MembershipStatus.ACTIVE,
            roles=[BuiltinRole.PROJECT_ADMIN.value],
            version=1,
        )
        role_read = RoleAssignmentRead(
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
            user_id=admin_user_id,
            role_key=BuiltinRole.PROJECT_ADMIN.value,
            granted_by=created_by,
            version=1,
        )
        return project_read, member_read, role_read

    async def get_project(
        self,
        *,
        project_id: UUID,
        account_id: UUID | None = None,
    ) -> ProjectRead | None:
        """Fetch a single project by ID, optionally verifying account boundary."""
        stmt = select(ProjectRow).where(ProjectRow.id == str(project_id))
        if account_id is not None:
            stmt = stmt.where(ProjectRow.account_id == str(account_id))
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return _project_row_to_read(row)

    async def list_projects(
        self,
        *,
        account_id: UUID,
        status: ProjectStatus | None = None,
    ) -> list[ProjectRead]:
        """List all projects in an account, optionally filtered by status."""
        stmt = select(ProjectRow).where(ProjectRow.account_id == str(account_id))
        if status is not None:
            stmt = stmt.where(ProjectRow.status == status.value)
        stmt = stmt.order_by(ProjectRow.created_at.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_project_row_to_read(r) for r in rows]

    async def list_project_members(
        self,
        *,
        project_id: UUID,
    ) -> list[ProjectMemberRead]:
        """List all members and their roles for a project."""
        membership_stmt = select(ProjectMembershipRow).where(
            ProjectMembershipRow.project_id == str(project_id)
        )
        membership_rows = (await self._session.execute(membership_stmt)).scalars().all()

        roles_stmt = select(ProjectRoleAssignmentRow).where(
            ProjectRoleAssignmentRow.project_id == str(project_id)
        )
        role_rows = (await self._session.execute(roles_stmt)).scalars().all()

        roles_by_user: dict[str, list[str]] = {}
        for r in role_rows:
            roles_by_user.setdefault(r.user_id, []).append(r.role_key)

        user_cls = _get_user_row()
        email_by_user: dict[str, str] = {}
        if membership_rows:
            user_stmt = select(user_cls).where(
                cast(user_cls.id, CHAR(36)).in_([m.user_id for m in membership_rows])
            )
            user_rows = (await self._session.execute(user_stmt)).scalars().all()
            email_by_user = {str(user.id): user.email for user in user_rows}

        members: list[ProjectMemberRead] = []
        for m in membership_rows:
            email = email_by_user.get(m.user_id)
            if email is None:
                raise ValueError(f"User {m.user_id} does not exist")
            members.append(
                ProjectMemberRead(
                    project_id=UUID(m.project_id),
                    user_id=UUID(m.user_id),
                    email=email,
                    status=MembershipStatus(m.status),
                    roles=roles_by_user.get(m.user_id, []),
                    version=m.version,
                )
            )
        return members

    async def get_project_members(
        self,
        *,
        project_id: UUID,
    ) -> list[ProjectMemberRead]:
        """Fetch all members and their roles for a project (alias for list_project_members)."""
        return await self.list_project_members(project_id=project_id)

    async def add_project_member(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
        granted_by: UUID,
    ) -> tuple[ProjectMemberRead, RoleAssignmentRead]:
        """Add a member to a project with an initial role atomically."""
        # Pre-validate DTO before making any database writes or flushing
        role_read = RoleAssignmentRead(
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
            user_id=user_id,
            role_key=role_key,
            granted_by=granted_by,
            version=1,
        )

        project = await self.get_project(project_id=project_id)
        if project is None:
            raise ValueError(f"Project {project_id} does not exist")

        user_cls = _get_user_row()
        user_stmt = select(user_cls).where(user_cls.id == user_id)  # type: ignore[arg-type]
        user = (await self._session.execute(user_stmt)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ValueError(f"User {user_id} does not exist or is inactive")

        m_stmt = select(ProjectMembershipRow).where(
            ProjectMembershipRow.project_id == str(project_id),
            ProjectMembershipRow.user_id == str(user_id),
        )
        if (await self._session.execute(m_stmt)).scalar_one_or_none() is not None:
            raise ValueError(f"User {user_id} is already a member of project {project_id}")

        membership_row = ProjectMembershipRow(
            project_id=str(project_id),
            user_id=str(user_id),
            status=MembershipStatus.ACTIVE.value,
            version=1,
        )
        self._session.add(membership_row)
        await self._session.flush()

        role_row = ProjectRoleAssignmentRow(
            project_id=str(project_id),
            user_id=str(user_id),
            role_key=role_key,
            granted_by=str(granted_by),
            version=1,
        )
        self._session.add(role_row)
        await self._session.flush()

        member_read = ProjectMemberRead(
            project_id=project_id,
            user_id=user_id,
            email=user.email,
            status=MembershipStatus.ACTIVE,
            roles=[role_key],
            version=1,
        )
        return member_read, role_read

    async def assign_project_role(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
        granted_by: UUID,
    ) -> RoleAssignmentRead:
        """Assign an additional project-scoped role to an existing active project member."""
        # 1. Pre-validate DTO before making any database writes or flushing
        role_read = RoleAssignmentRead(
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
            user_id=user_id,
            role_key=role_key,
            granted_by=granted_by,
            version=1,
        )

        # 2. Enforce active membership
        m_stmt = select(ProjectMembershipRow).where(
            ProjectMembershipRow.project_id == str(project_id),
            ProjectMembershipRow.user_id == str(user_id),
        )
        membership = (await self._session.execute(m_stmt)).scalar_one_or_none()
        if membership is None:
            raise ValueError(f"User {user_id} is not a member of project {project_id}")
        if membership.status != MembershipStatus.ACTIVE.value:
            raise ValueError(f"User {user_id} is not an active member of project {project_id}")

        stmt = select(ProjectRoleAssignmentRow).where(
            ProjectRoleAssignmentRow.project_id == str(project_id),
            ProjectRoleAssignmentRow.user_id == str(user_id),
            ProjectRoleAssignmentRow.role_key == role_key,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return RoleAssignmentRead(
                scope_type=ScopeType.PROJECT,
                scope_id=project_id,
                user_id=user_id,
                role_key=existing.role_key,
                granted_by=UUID(existing.granted_by),
                version=existing.version,
            )

        row = ProjectRoleAssignmentRow(
            project_id=str(project_id),
            user_id=str(user_id),
            role_key=role_key,
            granted_by=str(granted_by),
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return role_read

    async def assign_system_role(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
        role_key: str,
        granted_by: UUID,
    ) -> RoleAssignmentRead:
        """Assign a system-scoped role to a user."""
        # 1. Pre-validate DTO before making any database writes or flushing
        role_read = RoleAssignmentRead(
            scope_type=ScopeType.SYSTEM,
            scope_id=account_id,
            user_id=user_id,
            role_key=role_key,
            granted_by=granted_by,
            version=1,
        )

        acc_stmt = select(AccountRow).where(AccountRow.id == str(account_id))
        account = (await self._session.execute(acc_stmt)).scalar_one_or_none()
        if account is None or account.status != "active":
            raise ValueError(f"Account {account_id} does not exist or is inactive")

        user_cls = _get_user_row()
        user_stmt = select(user_cls).where(user_cls.id == user_id)  # type: ignore[arg-type]
        user = (await self._session.execute(user_stmt)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ValueError(f"User {user_id} does not exist or is inactive")

        stmt = select(SystemRoleAssignmentRow).where(
            SystemRoleAssignmentRow.account_id == str(account_id),
            SystemRoleAssignmentRow.user_id == str(user_id),
            SystemRoleAssignmentRow.role_key == role_key,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return RoleAssignmentRead(
                scope_type=ScopeType.SYSTEM,
                scope_id=account_id,
                user_id=user_id,
                role_key=existing.role_key,
                granted_by=UUID(existing.granted_by),
                version=existing.version,
            )

        row = SystemRoleAssignmentRow(
            account_id=str(account_id),
            user_id=str(user_id),
            role_key=role_key,
            granted_by=str(granted_by),
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        return role_read

    async def get_system_role_assignments(
        self,
        *,
        account_id: UUID,
        user_id: UUID | None = None,
    ) -> list[RoleAssignmentRead]:
        """Fetch system role assignments for an account and optional user."""
        stmt = select(SystemRoleAssignmentRow).where(
            SystemRoleAssignmentRow.account_id == str(account_id)
        )
        if user_id is not None:
            stmt = stmt.where(SystemRoleAssignmentRow.user_id == str(user_id))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            RoleAssignmentRead(
                scope_type=ScopeType.SYSTEM,
                scope_id=account_id,
                user_id=UUID(r.user_id),
                role_key=r.role_key,
                granted_by=UUID(r.granted_by),
                version=r.version,
            )
            for r in rows
        ]

    async def get_membership(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectMembershipRow | None:
        """Return one membership row with strict project and user parameters."""

        return await self._session.get(ProjectMembershipRow, (str(project_id), str(user_id)))

    async def list_user_project_access(
        self,
        *,
        account_id: UUID,
        user_id: UUID,
    ) -> list[tuple[ProjectRead, MembershipStatus, list[str]]]:
        """List one user's project rows with membership status and role keys.

        Only memberships of the requested account are returned. Project
        authorization still decides whether each role set grants ``project.read``;
        this repository method only supplies current rows.
        """

        stmt = (
            select(ProjectRow, ProjectMembershipRow)
            .join(ProjectMembershipRow, ProjectMembershipRow.project_id == ProjectRow.id)
            .where(
                ProjectRow.account_id == str(account_id),
                ProjectMembershipRow.user_id == str(user_id),
            )
            .order_by(ProjectRow.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        project_ids = [row[0].id for row in rows]
        roles_by_project: dict[str, list[str]] = {}
        if project_ids:
            role_stmt = select(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.project_id.in_(project_ids),
                ProjectRoleAssignmentRow.user_id == str(user_id),
            )
            for role_row in (await self._session.execute(role_stmt)).scalars():
                roles_by_project.setdefault(role_row.project_id, []).append(role_row.role_key)
        return [
            (
                _project_row_to_read(project_row),
                MembershipStatus(membership_row.status),
                sorted(roles_by_project.get(project_row.id, [])),
            )
            for project_row, membership_row in rows
        ]

    async def get_member(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectMemberRead | None:
        """Return one membership projection with its current role keys."""

        row = await self.get_membership(project_id=project_id, user_id=user_id)
        if row is None:
            return None
        return await self._membership_read(row)

    async def update_membership_status(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: MembershipStatus,
    ) -> ProjectMemberRead:
        """Update one membership status and bump its version."""

        row = await self.get_membership(project_id=project_id, user_id=user_id)
        if row is None:
            raise ValueError(f"User {user_id} is not a member of project {project_id}")
        row.status = status.value
        row.version += 1
        await self._session.flush()
        return await self._membership_read(row)

    async def delete_role_assignment(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
    ) -> bool:
        """Delete one project role assignment; return whether a row was removed."""

        result = await self._session.execute(
            delete(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.project_id == str(project_id),
                ProjectRoleAssignmentRow.user_id == str(user_id),
                ProjectRoleAssignmentRow.role_key == role_key,
            )
        )
        await self._session.flush()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def delete_membership(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove one membership and all of its project role assignments."""

        row = await self.get_membership(project_id=project_id, user_id=user_id)
        if row is None:
            return False
        await self._session.execute(
            delete(ProjectRoleAssignmentRow).where(
                ProjectRoleAssignmentRow.project_id == str(project_id),
                ProjectRoleAssignmentRow.user_id == str(user_id),
            )
        )
        await self._session.execute(
            delete(ProjectMembershipRow).where(
                ProjectMembershipRow.project_id == str(project_id),
                ProjectMembershipRow.user_id == str(user_id),
            )
        )
        await self._session.flush()
        return True

    async def set_project_status(
        self,
        *,
        project_id: UUID,
        status: ProjectStatus,
    ) -> ProjectRead:
        """Set one project's lifecycle state and bump its version."""

        row = await self._session.get(ProjectRow, str(project_id))
        if row is None:
            raise ValueError(f"Project {project_id} does not exist")
        row.status = status.value
        row.version += 1
        await self._session.flush()
        return _project_row_to_read(row)

    async def count_active_project_admins(self, *, project_id: UUID) -> int:
        """Count active human project_admin assignments for one project.

        An inactive user, a suspended membership, or a missing project_admin
        assignment never satisfies the administrator invariant.
        """

        user_cls = _get_user_row()
        stmt = (
            select(func.count())
            .select_from(ProjectRoleAssignmentRow)
            .join(
                ProjectMembershipRow,
                (ProjectMembershipRow.project_id == ProjectRoleAssignmentRow.project_id)
                & (ProjectMembershipRow.user_id == ProjectRoleAssignmentRow.user_id),
            )
            .join(user_cls, cast(user_cls.id, CHAR(36)) == ProjectMembershipRow.user_id)
            .where(
                ProjectRoleAssignmentRow.project_id == str(project_id),
                ProjectRoleAssignmentRow.role_key == BuiltinRole.PROJECT_ADMIN.value,
                ProjectMembershipRow.status == MembershipStatus.ACTIVE.value,
                user_cls.__table__.c.is_active.is_(True),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_active_project_admins_for_projects(
        self, project_ids: set[UUID]
    ) -> dict[UUID, int]:
        """Count active project administrators for each requested project."""

        if not project_ids:
            return {}
        user_cls = _get_user_row()
        stmt = (
            select(
                ProjectRoleAssignmentRow.project_id,
                func.count(),
            )
            .select_from(ProjectRoleAssignmentRow)
            .join(
                ProjectMembershipRow,
                (ProjectMembershipRow.project_id == ProjectRoleAssignmentRow.project_id)
                & (ProjectMembershipRow.user_id == ProjectRoleAssignmentRow.user_id),
            )
            .join(user_cls, cast(user_cls.id, CHAR(36)) == ProjectMembershipRow.user_id)
            .where(
                ProjectRoleAssignmentRow.project_id.in_([str(item) for item in project_ids]),
                ProjectRoleAssignmentRow.role_key == BuiltinRole.PROJECT_ADMIN.value,
                ProjectMembershipRow.status == MembershipStatus.ACTIVE.value,
                user_cls.__table__.c.is_active.is_(True),
            )
            .group_by(ProjectRoleAssignmentRow.project_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {UUID(project_id): int(count) for project_id, count in rows}

    async def _membership_read(self, row: ProjectMembershipRow) -> ProjectMemberRead:
        """Project one membership row with its current role keys and user email."""

        user_cls = _get_user_row()
        user = await self._session.get(user_cls, UUID(row.user_id))
        if user is None:
            raise ValueError(f"User {row.user_id} does not exist")
        role_stmt = select(ProjectRoleAssignmentRow).where(
            ProjectRoleAssignmentRow.project_id == row.project_id,
            ProjectRoleAssignmentRow.user_id == row.user_id,
        )
        role_rows = (await self._session.execute(role_stmt)).scalars().all()
        return ProjectMemberRead(
            project_id=UUID(row.project_id),
            user_id=UUID(row.user_id),
            email=user.email,
            status=MembershipStatus(row.status),
            roles=sorted(role.role_key for role in role_rows),
            version=row.version,
        )


async def bootstrap_fresh_installation(
    session: AsyncSession,
    admin_user_id: UUID,
    *,
    account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
) -> RoleAssignmentRead:
    """Trusted bootstrap provisioning: ensures installation account and assigns system_admin.

    Idempotent: safe to run repeatedly on the same database.
    Does NOT grant privileges through public registration.
    """
    user_cls = _get_user_row()
    user_stmt = select(user_cls).where(user_cls.id == admin_user_id)  # type: ignore[arg-type]
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {admin_user_id} does not exist")
    if not user.is_active:
        raise ValueError(f"User {admin_user_id} is inactive")

    stmt = select(AccountRow).where(AccountRow.id == str(account_id))
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is None:
        account = AccountRow(id=str(account_id), status="active")
        session.add(account)
        await session.flush()
    elif account.status != "active":
        raise ValueError(f"Installation account {account_id} is not active")

    repo = ProjectRepository(session)
    return await repo.assign_system_role(
        account_id=account_id,
        user_id=admin_user_id,
        role_key=BuiltinRole.SYSTEM_ADMIN.value,
        granted_by=admin_user_id,
    )
