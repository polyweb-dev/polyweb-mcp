"""Default workspace of a newly created runtime account (TASK-000065).

``provision_signup_workspace`` runs inside the account's creation transaction
(``UserDatabase.on_created``): the new user owns one ``Default`` project with
assigned, owned, keyless pools for every keyless provider. It composes the normal
project, vault key and pool operations in the creating session, so their
authorization checks, audit events and runtime materialization behave exactly as
for a signed-in user. The project's runtime is rebuilt once, after the last pool.

Nothing here mints a session, token, project API key or secret, and nothing calls
a provider: REST and MCP execution through these pools needs a project API key,
which the owner issues explicitly. A failure raises and rolls the whole account
creation back.
"""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.configuration.config import Settings
from polyweb.infrastructure.secrets import KEYLESS_PROVIDER_TYPES
from polyweb.models.credentials import CredentialAuthMode
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, ProjectCreate
from polyweb.models.users import UserPrincipal
from polyweb.models.vault import KeyPoolCreate, VaultKeyCreate
from polyweb.persistence.projects import AccountRow
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserRow
from polyweb.services.key_pools import create_pool_in_session
from polyweb.services.pool_materializer import materialize_pools
from polyweb.services.projects import ProjectService
from polyweb.services.vault_keys import create_vault_key_in_session

DEFAULT_PROJECT_NAME = "Default"


async def provision_signup_workspace(
    session: AsyncSession,
    user: UserRow,
    *,
    settings: Settings,
    repository: SQLiteRepository,
) -> None:
    """Create ``user``'s default project and keyless pools in ``session``.

    ``user`` is already flushed in ``session``. The caller owns the commit and the
    rollback. The synthetic actor carries only the new account's id: it is never a
    session and no credential is issued for it.
    """

    actor = UserPrincipal(
        id=user.id,
        email=user.email,
        session_id=uuid4(),
        is_active=bool(user.is_active),
        is_verified=bool(user.is_verified),
    )
    if await session.get(AccountRow, str(DEFAULT_INSTALLATION_ACCOUNT_ID)) is None:
        session.add(AccountRow(id=str(DEFAULT_INSTALLATION_ACCOUNT_ID), status="active"))
        await session.flush()

    projects = ProjectService(repository, rollout_state=settings.projects_rollout_state)
    project = await projects.create_project_in_session(
        session,
        actor,
        ProjectCreate(name=DEFAULT_PROJECT_NAME, slug=f"default-{user.id.hex}"),
        materialize=False,
    )
    for provider in sorted(KEYLESS_PROVIDER_TYPES):
        name = provider.title()
        key = await create_vault_key_in_session(
            session,
            actor,
            VaultKeyCreate(
                provider_type=provider,
                label=f"{name} keyless",
                auth_mode=CredentialAuthMode.KEYLESS,
            ),
        )
        await create_pool_in_session(
            session,
            actor,
            key.credential.id,
            KeyPoolCreate(label=f"{name} · {DEFAULT_PROJECT_NAME}", project_id=project.id),
            materialize=False,
        )
    await materialize_pools(session, project_id=project.id)
