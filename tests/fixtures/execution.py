"""Execution-scope test fixtures: projects, memberships, and attributions (P04).

Two layers of helpers share one contract:

* Pure contract/unit tests that never reach the execution boundary use
  :data:`EXECUTION_PROJECT_ID` and :func:`test_attribution` — placeholder
  identities that satisfy the required request/attribution fields without any
  database work.
* Tests on a real SQLite repository use :func:`seed_execution_project` and
  :func:`add_execution_member`, which persist a real project (and, when needed,
  a fresh human) so the NOT NULL foreign keys on ``usage_events`` and
  ``trace_spans`` hold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from tests.fixtures.alpha_fixtures import seed_alpha_system_admin
from tests.fixtures.auth import temp_email

from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ActorType, ExecutionAttribution
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    CredentialOwnerScope,
    MembershipStatus,
    ProjectCreate,
    ProjectRead,
)
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.projects import ProjectMembershipRow, ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.credentials import credential_secret_slot

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

#: Placeholder identities for tests that never hit a real execution boundary.
EXECUTION_PROJECT_ID: Final[UUID] = UUID("00000000-0000-4000-8000-0000000000aa")
EXECUTION_ACTOR_ID: Final[UUID] = UUID("00000000-0000-4000-8000-0000000000bb")

#: Verified-actor fields for capacity contexts built directly by limit tests.
#: Revision 0002 (A2) makes ``actor_type``/``actor_id`` NOT NULL on admissions
#: and rate attempts, so a direct ``LimitCallContext``/``LimitAdmission`` must
#: name the actor the execution path would have verified.
FIXTURE_ACTOR: Final[dict[str, Any]] = {
    "actor_type": ActorType.HUMAN,
    "actor_id": EXECUTION_ACTOR_ID,
}


def test_attribution(
    *,
    project_id: UUID = EXECUTION_PROJECT_ID,
    actor_id: UUID = EXECUTION_ACTOR_ID,
    actor_type: ActorType = ActorType.HUMAN,
) -> ExecutionAttribution:
    """Return an in-memory attribution for tests without a real project row."""

    return ExecutionAttribution(project_id=project_id, actor_type=actor_type, actor_id=actor_id)


# Imported into test modules; must not be collected as a test itself.
test_attribution.__test__ = False


async def seed_execution_user(repository: SQLiteRepository, prefix: str = "exec") -> Any:
    """Create one ordinary active human and return its user row."""

    user, _principal = await seed_alpha_system_admin(repository, email=temp_email(prefix))
    return user


async def seed_execution_project(
    repository: SQLiteRepository,
    *,
    user_id: UUID | None = None,
    name: str = "Execution Project",
    slug: str | None = None,
) -> ExecutionAttribution:
    """Create an active project administered by ``user_id`` (a fresh user when omitted).

    Returns the trusted :class:`ExecutionAttribution` for the project admin.
    """

    if user_id is None:
        user = await seed_execution_user(repository)
        user_id = user.id
    async with repository.session() as session:
        project, _membership, _role = await ProjectRepository(session).create_project_with_admin(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            created_by=user_id,
            project_create=ProjectCreate(
                name=name,
                slug=slug or f"exec-{uuid4().hex[:8]}",
                initial_admin_user_id=user_id,
            ),
        )
        await session.commit()
    return ExecutionAttribution(project_id=project.id, actor_type=ActorType.HUMAN, actor_id=user_id)


async def seed_provider_bindings(
    repository: SQLiteRepository,
    *,
    project_id: UUID,
    actor_id: UUID,
    store: EncryptedDbSecretStore,
    providers: tuple[str, ...],
    secrets: dict[str, str] | None = None,
    secret_values: dict[str, str] | None = None,
    operations: frozenset[CredentialOperation] = frozenset(
        {CredentialOperation.SEARCH, CredentialOperation.FETCH}
    ),
) -> dict[str, tuple[UUID, UUID]]:
    """Seed one enabled project credential per provider and stage its secret.

    Router and MCP integration tests inject fake adapters for the wire shape;
    execution still resolves a real durable binding and a real encrypted slot,
    exactly as production does. Returns ``provider -> (credential_id, binding_id)``.
    """

    seeded: dict[str, tuple[UUID, UUID]] = {}
    async with repository.session() as session:
        credentials = CredentialRepository(session)
        bindings = ProjectBindingRepository(session)
        for priority, provider in enumerate(providers):
            credential = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=project_id,
                label=f"fixture-{provider}-{uuid4().hex[:8]}",
                auth_mode="api_key",
                created_by=actor_id,
            )
            binding = await bindings.create(
                project_id=project_id,
                credential_id=credential.id,
                credential_scope=CredentialOwnerScope.PROJECT,
                route_label=provider,
                priority=priority,
                created_by=actor_id,
            )
            enabled = await bindings.set_enabled_operations(
                project_id=project_id,
                binding_id=binding.id,
                operations=operations,
                expected_version=binding.version,
            )
            assert enabled is not None
            secret = (
                secret_values[provider]
                if secret_values is not None
                else f"fixture-key-{provider}-{uuid4().hex[:8]}"
            )
            await store.create_slot_in_session(
                session,
                credential_secret_slot(credential.id, credential.generation),
                secret,
            )
            if secrets is not None:
                secrets[provider] = secret
            seeded[provider] = (credential.id, binding.id)
        await session.commit()
    return seeded


def install_adapter_map(
    monkeypatch: Any, adapters: Any, *, secrets: dict[str, str] | None = None
) -> None:
    """Construct fakes only for exact keys issued by this test's fixture maps."""
    import polyweb.services.execution as execution_module

    if secrets is None:
        raise ValueError("fake adapters require an exact fixture secret map")
    maps = getattr(monkeypatch, "_polyweb_adapter_maps", None)
    if maps is None:
        maps = []
        monkeypatch._polyweb_adapter_maps = maps
    maps.append(({adapter.name: adapter for adapter in adapters}, secrets))

    def adapter_factory(name: str) -> Any:
        if not any(name in by_name for by_name, _ in maps):
            return None

        def build(client: Any, api_key: Any = None) -> Any:
            del client
            assert api_key is not None, "missing fixture credential"
            for by_name, issued in reversed(maps):
                if name in by_name and issued.get(name) == api_key.get_secret_value():
                    return by_name[name]
            raise AssertionError("execution supplied an unknown fixture credential")

        return build

    monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)


async def attributed_tracked_call(
    repository: Any,
    adapter: Any,
    call: Any,
    *,
    operation: Any,
    attribution: ExecutionAttribution | None = None,
    request: Any = None,
    limits: Any = None,
    **kwargs: Any,
) -> Any:
    """Call ``tracked_call`` with the attributed admission context execution builds.

    Revision 0002 (A2) refuses an admission without the verified actor, and
    the shared execution service always hands ``tracked_call`` an attributed
    ``LimitCallContext``. Direct rail tests that drive ``tracked_call`` with a
    limit service use this wrapper so the admission carries the same
    project and actor as the usage row; every other argument passes through.
    """

    from datetime import UTC, datetime

    from polyweb.models.contracts import UsageOperation
    from polyweb.models.provider_limits import AuthMode, LimitCallContext, LimitOperation
    from polyweb.services.monitoring import tracked_call

    owner = attribution or test_attribution()
    if (
        limits is not None
        and kwargs.get("context") is None
        and operation is not UsageOperation.COST_ESTIMATE
    ):
        mode = getattr(adapter, "limit_auth_mode", None)
        kwargs["context"] = LimitCallContext(
            provider=adapter.name,
            operation=LimitOperation(operation.value),
            auth_mode=mode if isinstance(mode, AuthMode) else AuthMode.KEYED,
            attempt_id=uuid4().hex,
            request=request,
            requested_at=datetime.now(UTC),
            project_id=owner.project_id,
            actor_type=owner.actor_type,
            actor_id=owner.actor_id,
        )
    return await tracked_call(
        repository,
        adapter,
        call,
        operation=operation,
        attribution=owner,
        request=request,
        limits=limits,
        **kwargs,
    )


async def seed_app_bound_project(
    repository: SQLiteRepository,
    *,
    user_id: UUID,
    app: Any,
    monkeypatch: Any,
    adapters: Any = None,
    operations: frozenset[CredentialOperation] = frozenset(
        {CredentialOperation.SEARCH, CredentialOperation.FETCH}
    ),
    secrets: dict[str, str] | None = None,
) -> ExecutionAttribution:
    """Seed a project ``user_id`` administers plus one enabled binding per app adapter.

    The REST app must already be inside its lifespan (``TestClient`` entered),
    so its encrypted runtime store exists. Each binding gets a private
    credential with a staged secret, and execution builds the injected fake
    adapter only when it is handed exactly that secret.
    """

    attribution = await seed_execution_project(repository, user_id=user_id)
    routes = list(adapters if adapters is not None else app.state._routes)
    secrets = {} if secrets is None else secrets
    await seed_provider_bindings(
        repository,
        project_id=attribution.project_id,
        actor_id=attribution.actor_id,
        store=app.state.secret_store,
        providers=tuple(adapter.name for adapter in routes),
        secrets=secrets,
        operations=operations,
    )
    install_adapter_map(monkeypatch, routes, secrets=secrets)
    return attribution


async def bound_credential_id(
    repository: SQLiteRepository, *, project_id: UUID, provider: str
) -> UUID:
    """Return the credential behind the fixture binding routed as ``provider``.

    A2 health and quota observations are scoped to the credential that made
    the call, so a test reads them with this id instead of provider-wide.
    """

    async with repository.session() as session:
        bindings = await ProjectBindingRepository(session).list_for_project(project_id=project_id)
    matches = [binding.credential_id for binding in bindings if binding.route_label == provider]
    assert len(matches) == 1, f"expected one {provider} binding, found {len(matches)}"
    return matches[0]


async def add_execution_member(
    repository: SQLiteRepository,
    *,
    project_id: UUID,
    user_id: UUID,
    role_key: str = BuiltinRole.PROJECT_MEMBER,
    granted_by: UUID | None = None,
) -> ExecutionAttribution:
    """Add ``user_id`` to a project with one role; return its attribution."""

    async with repository.session() as session:
        await ProjectRepository(session).add_project_member(
            project_id=project_id,
            user_id=user_id,
            role_key=role_key,
            granted_by=granted_by or user_id,
        )
        await session.commit()
    return ExecutionAttribution(project_id=project_id, actor_type=ActorType.HUMAN, actor_id=user_id)


async def suspend_execution_member(
    repository: SQLiteRepository, *, project_id: UUID, user_id: UUID
) -> None:
    """Mark one membership suspended in place."""

    async with repository.session() as session:
        membership = (
            await session.execute(
                select(ProjectMembershipRow).where(
                    ProjectMembershipRow.project_id == str(project_id),
                    ProjectMembershipRow.user_id == str(user_id),
                )
            )
        ).scalar_one_or_none()
        assert membership is not None
        membership.status = MembershipStatus.SUSPENDED.value
        await session.commit()


async def project_read(repository: SQLiteRepository, project_id: UUID) -> ProjectRead | None:
    """Re-read one project row through the project repository."""

    async with repository.session() as session:
        return await ProjectRepository(session).get_project(project_id=project_id)


def account_id_from_token(token: Any) -> UUID:
    """Decode the account id (JWT ``sub``) from a raw or SecretStr token."""

    import jwt as pyjwt

    raw = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
    claims = pyjwt.decode(raw, options={"verify_signature": False})
    return UUID(str(claims["sub"]))


async def seed_token_project(repository: SQLiteRepository, token: Any) -> ExecutionAttribution:
    """Seed an active project administered by the account a JWT belongs to."""

    return await seed_execution_project(repository, user_id=account_id_from_token(token))


def account_id_from_headers(headers: dict[str, str]) -> UUID:
    """Decode the account id (JWT ``sub``) from Bearer auth headers."""

    import jwt as pyjwt

    token = headers["Authorization"].removeprefix("Bearer ").strip()
    claims = pyjwt.decode(token, options={"verify_signature": False})
    return UUID(str(claims["sub"]))


async def seed_member_project(
    repository: SQLiteRepository, headers: dict[str, str]
) -> ExecutionAttribution:
    """Seed an active project administered by the account behind ``headers``."""

    return await seed_execution_project(repository, user_id=account_id_from_headers(headers))


def _install_bdd_adapters(context: Any, adapters: Any, secrets: dict[str, str]) -> None:
    """Keep every issued scenario key exact across concurrent REST/MCP projects."""
    import pytest

    import polyweb.services.execution as execution

    patcher = getattr(context, "_execution_patcher", None)
    if patcher is None:
        patcher = pytest.MonkeyPatch()
        context._execution_patcher = patcher
    issued = getattr(context, "_bdd_adapters_by_secret", None)
    if issued is None:
        issued = {}
        context._bdd_adapters_by_secret = issued
    for adapter in adapters:
        issued[secrets[adapter.name]] = adapter

    def factory(name: str) -> Any:
        if not any(adapter.name == name for adapter in issued.values()):
            return None

        def build(client: Any, api_key: Any = None) -> Any:
            del client
            assert api_key is not None
            adapter = issued.get(api_key.get_secret_value())
            assert adapter is not None and adapter.name == name, "unknown scenario credential"
            return adapter

        return build

    patcher.setattr(execution, "adapter_factory", factory)


def bdd_bind_project(context: Any, app: Any, project_id: UUID, actor_id: UUID) -> None:
    """Bind the current scenario roster, preserving exact keys across app lifespans."""
    marker = (id(context.repository), str(project_id))
    projects = getattr(context, "_bdd_bound_projects", None)
    if projects is None:
        projects = {}
        context._bdd_bound_projects = projects
    secrets, identities = projects.setdefault(marker, ({}, {}))
    providers = {a.name for a in app.state._routes}
    missing = tuple(a.name for a in app.state._routes if a.name not in identities)
    if missing:
        identities.update(
            context.loop.run_until_complete(
                seed_provider_bindings(
                    context.repository,
                    project_id=project_id,
                    actor_id=actor_id,
                    store=app.state.secret_store,
                    providers=missing,
                    secrets=secrets,
                )
            )
        )

    # A rebuilt fixture app can replace its roster (e.g. success -> failing
    # fetch). Its old fake routes must not survive as enabled credentials.
    async def roster() -> None:
        async with context.repository.session() as session:
            repo = ProjectBindingRepository(session)
            for binding in await repo.list_for_project(project_id=project_id):
                if binding.route_label not in identities:
                    continue
                wanted = (
                    frozenset(CredentialOperation)
                    if binding.route_label in providers
                    else frozenset()
                )
                if binding.enabled_operations != wanted:
                    await repo.set_enabled_operations(
                        project_id=project_id,
                        binding_id=binding.id,
                        operations=wanted,
                        expected_version=binding.version,
                    )
            await session.commit()

    context.loop.run_until_complete(roster())
    _install_bdd_adapters(context, app.state._routes, secrets)
    credential_ids = getattr(context, "_bdd_credential_ids", None)
    if credential_ids is None:
        credential_ids = {}
        context._bdd_credential_ids = credential_ids
    for provider, (credential_id, _binding_id) in identities.items():
        credential_ids[(str(project_id), provider)] = credential_id


def bdd_project_id(context: Any, headers: dict[str, str]) -> str:
    """Project id owned by the account behind ``headers``, seeded once per account.

    Behave scenarios drive the event loop synchronously; each account's
    project is created on first use and cached for the scenario.
    """

    account = str(account_id_from_headers(headers))
    pids = getattr(context, "_bdd_pids", None)
    if pids is None:
        pids = {}
        context._bdd_pids = pids
    if account not in pids:
        attribution = context.loop.run_until_complete(
            seed_member_project(context.repository, headers)
        )
        pids[account] = str(attribution.project_id)
    app = getattr(context, "otel_app", None) or getattr(context, "app", None)
    if app is not None:
        bdd_bind_project(context, app, UUID(pids[account]), UUID(account))
    return pids[account]


def bdd_token_project_id(context: Any, token: Any) -> str:
    """Project id owned by the account behind a raw/SecretStr JWT, cached."""

    account = str(account_id_from_token(token))
    pids = getattr(context, "_bdd_pids", None)
    if pids is None:
        pids = {}
        context._bdd_pids = pids
    if account not in pids:
        attribution = context.loop.run_until_complete(seed_token_project(context.repository, token))
        pids[account] = str(attribution.project_id)
    app = getattr(context, "app", None)
    if app is not None:
        bdd_bind_project(context, app, UUID(pids[account]), UUID(account))
    return pids[account]


def scenario_attribution(context: Any) -> ExecutionAttribution:
    """Lazily seed one execution project for a BDD scenario repository.

    Returns a placeholder attribution when the scenario has no repository.
    Steps that reopen ``context.repository`` get a fresh project for the new
    database so the foreign key always resolves.
    """

    repo = getattr(context, "repository", None)
    attribution = getattr(context, "_exec_attribution", None)
    owner = getattr(context, "_exec_attribution_repo", None)
    if attribution is None or (repo is not None and owner is not repo):
        if repo is None:
            attribution = test_attribution()
        else:
            attribution = context.loop.run_until_complete(seed_execution_project(repo))
            context._exec_attribution_repo = repo
        context._exec_attribution = attribution
    return attribution


async def register_project_admin(
    client: TestClient, repository: SQLiteRepository, prefix: str
) -> tuple[dict[str, str], ExecutionAttribution]:
    """Register and log in over HTTP, then create a project the account admins.

    Returns ``(auth headers, attribution)`` for execution calls.
    """

    from tests.fixtures.auth import account_id_from_pair, raw_auth_headers, register_and_login

    pair = register_and_login(client, temp_email(prefix))
    attribution = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
    return raw_auth_headers(pair["access_token"]), attribution


async def allow_full_trace_capture(repository: SQLiteRepository) -> None:
    """Authorize full capture explicitly in one disposable repository only."""
    from tests.fixtures.auth import create_temp_user, temp_principal

    from polyweb.models.projects import TraceDetailPolicy
    from polyweb.models.settings import SystemSettingsUpdate, SystemTraceDefaults
    from polyweb.services.settings import SettingsService

    user = await create_temp_user(repository, temp_email("trace-policy"), system_admin=True)
    admin = temp_principal(user)
    service = SettingsService(repository)
    current = await service.get_system_settings(admin)
    await service.update_system_settings(
        admin,
        SystemSettingsUpdate(
            expected_revision=current.revision,
            trace=SystemTraceDefaults(detail=TraceDetailPolicy.FULL),
        ),
    )


def create_bound_provider(
    client: Any, project_id: str, provider: str, secret: str, headers: dict[str, str]
) -> Any:
    """Create a private credential via A4 HTTP, bind it, and explicitly enable it."""
    response = client.post(
        f"/api/v1/projects/{project_id}/credentials",
        headers=headers,
        json={"provider_type": provider, "label": f"proof-{uuid4().hex}", "secret": secret},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    credential_id = body.get("id", body.get("credential_id"))
    binding = client.post(
        f"/api/v1/projects/{project_id}/bindings",
        headers=headers,
        json={"credential_id": credential_id, "route_label": provider},
    )
    assert binding.status_code == 201, binding.text
    assert binding.json()["enabled_operations"] == []
    enabled = client.patch(
        f"/api/v1/projects/{project_id}/bindings/{binding.json()['id']}",
        headers=headers,
        json={"enabled_operations": ["search"] if provider == "brave" else ["search", "fetch"]},
    )
    assert enabled.status_code == 200, enabled.text
    return response


async def bdd_mcp_server(context: Any, adapters: Any, prefix: str) -> tuple[Any, str]:
    """Compose MCP with a real A1 key and private A4 bindings for scenario fakes."""
    import pytest
    from pydantic import SecretStr
    from tests.fixtures.api_keys import mcp_project_key

    from polyweb.mcp.server import _encrypted_store, create_server

    service, key = await mcp_project_key(context.repository, prefix)
    patcher = getattr(context, "_execution_patcher", None)
    if patcher is None:
        patcher = pytest.MonkeyPatch()
        context._execution_patcher = patcher
    secrets: dict[str, str] = {}
    await seed_provider_bindings(
        context.repository,
        project_id=key.project_id,
        actor_id=key.owner.id,
        store=_encrypted_store(context.repository),
        providers=tuple(adapter.name for adapter in adapters),
        secrets=secrets,
    )
    _install_bdd_adapters(context, adapters, secrets)
    server = create_server(
        adapters,
        repository=context.repository,
        auth_service=service,
        stdio_token=SecretStr(key.raw),
    )
    session = server._mcp_server.lifespan(server)
    await session.__aenter__()
    sessions = getattr(context, "_bdd_mcp_sessions", None)
    if sessions is None:
        sessions = []
        context._bdd_mcp_sessions = sessions
    sessions.append((session, server))
    return server, str(key.project_id)


async def bind_existing_project(
    repository: Any,
    project_id: Any,
    actor_id: Any,
    adapters: Any,
    monkeypatch: Any,
    store: Any = None,
) -> Any:
    """Add explicit A4 credentials to one existing A1 execution test project."""
    from polyweb.mcp.server import _encrypted_store

    secrets: dict[str, str] = {}
    identities = await seed_provider_bindings(
        repository,
        project_id=project_id,
        actor_id=actor_id,
        store=store or _encrypted_store(repository),
        providers=tuple(a.name for a in adapters),
        secrets=secrets,
    )
    install_adapter_map(monkeypatch, adapters, secrets=secrets)
    return identities


async def bound_mcp_credentials(
    repository: Any, adapters: Any, prefix: str, monkeypatch: Any
) -> Any:
    """A1 key plus exact-key private A4 bindings, without any auth override."""
    from tests.fixtures.api_keys import mcp_project_key

    service, key = await mcp_project_key(repository, prefix)
    await bind_existing_project(repository, key.project_id, key.owner.id, adapters, monkeypatch)
    return service, key.key, str(key.project_id)
