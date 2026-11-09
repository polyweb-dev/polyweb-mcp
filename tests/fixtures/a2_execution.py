"""A2 execution fixtures: one real project, real bindings, and fake adapters.

These helpers seed the durable half of a project execution (project, private
credential secrets, enabled bindings, optional shared pool and allocations) and
compose a real :class:`ExecutionService` whose provider adapters are recording
doubles. No vendor I/O, no live key, and no shared database are involved.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.fixtures.execution import seed_execution_project

from polyweb.adapters.base import ProviderAdapter
from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.credentials import CredentialOperation
from polyweb.models.observability import ExecutionAttribution
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ProjectContext,
)
from polyweb.models.provider_limits import AuthMode
from polyweb.models.schema_enums import UpstreamScope
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.pools import (
    PoolAllocationRepository,
    StoredPool,
    UpstreamPoolRepository,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.credentials import credential_secret_slot
from polyweb.services.execution import ExecutionService
from polyweb.services.monitoring import clear_quota_poll_cache
from polyweb.services.provider_limits import ProviderLimitsService
from polyweb.services.provider_runtime import clear_config_cache

SearchHandler = Callable[["RecordingAdapter", SearchRequest], Awaitable[SearchResponse]]
FetchHandler = Callable[["RecordingAdapter", FetchRequest], Awaitable[FetchResponse]]


def provider_error(
    provider: str,
    *,
    code: str = "quota_exhausted",
    message: str = "vendor unavailable",
    status: int = 402,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> ProviderOperationError:
    """Build a normalized provider error with the requested wire status."""

    return ProviderOperationError(
        ProviderError(
            provider=provider,
            code=code,
            message=message,
            retryable=retryable,
            status_code=status,
            details=details or {},
        )
    )


class RecordingAdapter(ProviderAdapter):
    """A provider double that counts calls and runs an optional handler."""

    def __init__(self, name: str, *, auth_mode: AuthMode = AuthMode.KEYED) -> None:
        self._name = name
        self._auth_mode = auth_mode
        self.search_calls = 0
        self.fetch_calls = 0
        self.closed = False
        self.search_started = asyncio.Event()
        self.fetch_started = asyncio.Event()
        self.search_handler: SearchHandler | None = None
        self.fetch_handler: FetchHandler | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def limit_auth_mode(self) -> AuthMode:
        return self._auth_mode

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True, quota=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        self.search_started.set()
        if self.search_handler is not None:
            return await self.search_handler(self, request)
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[SearchResult(title="fake", url="https://example.com/fake")],
            total_results=1,
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("0"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        self.fetch_started.set()
        if self.fetch_handler is not None:
            return await self.fetch_handler(self, request)
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="fake document",
                fetched_at=datetime.now(UTC),
            ),
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.FETCH,
                units=Decimal("0"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self.name,
            operation=(
                UsageOperation.SEARCH
                if isinstance(request, SearchRequest)
                else UsageOperation.FETCH
            ),
            units=Decimal("0"),
        )

    async def aclose(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class PoolSpec:
    """Declarations for one shared upstream pool and its project allocation."""

    # A malformed declaration is intentionally allowed here so the fail-closed
    # tests can seed exactly the shapes a bad operator write could leave behind.
    constraints: Any
    max_concurrency: int | None = None
    operations: tuple[CredentialOperation, ...] = (CredentialOperation.SEARCH,)
    allocations: tuple[CredentialOperation, ...] = (CredentialOperation.SEARCH,)
    base_rate: int = 100
    rate_window_seconds: int = 3600


@dataclass(frozen=True)
class SeededCredential:
    label: str
    credential_id: UUID
    binding_id: UUID
    secret: str
    generation: int


@dataclass
class ExecutionWorld:
    """One seeded project plus the execution service that reads it."""

    repository: SQLiteRepository
    project: ExecutionAttribution
    context: ProjectContext
    store: EncryptedDbSecretStore
    credentials: dict[str, SeededCredential]
    adapters: dict[str, RecordingAdapter]
    service: ExecutionService
    limits: ProviderLimitsService | None = None
    pool: StoredPool | None = None
    adapters_by_secret: dict[str, RecordingAdapter] = field(default_factory=dict)

    async def aclose(self) -> None:
        await self.service.aclose()
        await self.repository.close()
        clear_config_cache()
        clear_quota_poll_cache()


async def _seed_credential(
    repository: SQLiteRepository,
    store: EncryptedDbSecretStore,
    project: ExecutionAttribution,
    *,
    provider: str,
    label: str,
    secret: str,
    operations: frozenset[CredentialOperation],
    priority: int,
) -> SeededCredential:
    async with repository.session() as session:
        credential = await CredentialRepository(session).insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type=provider,
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=project.project_id,
            label=label,
            auth_mode="api_key",
            created_by=project.actor_id,
        )
        bindings = ProjectBindingRepository(session)
        binding = await bindings.create(
            project_id=project.project_id,
            credential_id=credential.id,
            credential_scope=CredentialOwnerScope.PROJECT,
            route_label=label,
            created_by=project.actor_id,
            priority=priority,
        )
        enabled = await bindings.set_enabled_operations(
            project_id=project.project_id,
            binding_id=binding.id,
            operations=operations,
            expected_version=binding.version,
        )
        assert enabled is not None
        await store.create_slot_in_session(
            session,
            credential_secret_slot(credential.id, credential.generation),
            secret,
        )
        await session.commit()
    return SeededCredential(
        label=label,
        credential_id=credential.id,
        binding_id=binding.id,
        secret=secret,
        generation=credential.generation,
    )


async def build_execution_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str = "exa",
    labels: tuple[str, ...] = ("a1",),
    priorities: dict[str, int] | None = None,
    pool: PoolSpec | None = None,
    limits: bool = True,
    permissions: frozenset[PermissionAction] | None = None,
) -> ExecutionWorld:
    """Seed one project and compose its real execution service over fakes."""

    import polyweb.services.execution as execution_module

    repository = await SQLiteRepository.open(tmp_path / f"a2-{uuid4().hex[:8]}.db")
    project = await seed_execution_project(repository, name="A")
    store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))

    credentials: dict[str, SeededCredential] = {}
    adapters_by_secret: dict[str, RecordingAdapter] = {}
    for index, label in enumerate(labels):
        secret = f"fake-{provider}-{label}-{uuid4().hex[:10]}"
        credentials[label] = await _seed_credential(
            repository,
            store,
            project,
            provider=provider,
            label=label,
            secret=secret,
            operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
            priority=(priorities or {}).get(label, index),
        )
        adapters_by_secret[secret] = RecordingAdapter(provider)

    seeded_pool: StoredPool | None = None
    if pool is not None:
        async with repository.session() as session:
            pools = UpstreamPoolRepository(session)
            seeded_pool = await pools.create_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                upstream_scope=UpstreamScope.ACCOUNT,
                pool_key=f"a2-{uuid4().hex[:10]}",
                label="a2 pool",
                constraints=pool.constraints,
                max_concurrency=pool.max_concurrency,
            )
            for credential in credentials.values():
                for operation in pool.operations:
                    await pools.link_credential(
                        credential_id=credential.credential_id,
                        operation=operation,
                        pool_id=seeded_pool.id,
                        provider_type=provider,
                    )
            allocations = PoolAllocationRepository(session)
            for operation in pool.allocations:
                await allocations.create(
                    project_id=project.project_id,
                    pool_id=seeded_pool.id,
                    operation=operation,
                    base_rate=pool.base_rate,
                    rate_window_seconds=pool.rate_window_seconds,
                    granted_by=project.actor_id,
                )
            await session.commit()

    limits_service: ProviderLimitsService | None = None
    if limits:
        limits_service = ProviderLimitsService(repository.limits)
        await limits_service.initialize()

    def factory(client: Any, api_key: Any = None) -> ProviderAdapter:
        del client
        key = api_key.get_secret_value() if api_key is not None else ""
        adapter = adapters_by_secret.get(key)
        assert adapter is not None, "execution supplied an unknown fixture credential"
        return adapter

    def adapter_factory(name: str) -> Callable[..., ProviderAdapter] | None:
        return factory if name == provider else None

    monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)
    service = ExecutionService(
        repository=repository,
        secret_store=store,
        client=object(),
        limits=limits_service,
    )
    context = ProjectContext(
        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        project_id=project.project_id,
        principal=HumanPrincipal(user_id=project.actor_id, session_id=uuid4()),
        effective_permissions=permissions
        or frozenset({PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}),
        policy_revision=1,
    )
    return ExecutionWorld(
        repository=repository,
        project=project,
        context=context,
        store=store,
        credentials=credentials,
        adapters={label: adapters_by_secret[item.secret] for label, item in credentials.items()},
        service=service,
        limits=limits_service,
        pool=seeded_pool,
        adapters_by_secret=adapters_by_secret,
    )


def search_request(world: ExecutionWorld, **overrides: Any) -> SearchRequest:
    """Build one project search request for this world."""

    payload: dict[str, Any] = {"project_id": world.project.project_id, "query": "a2"}
    payload.update(overrides)
    return SearchRequest(**payload)


def fetch_request(world: ExecutionWorld, **overrides: Any) -> FetchRequest:
    """Build one project fetch request for this world."""

    payload: dict[str, Any] = {
        "project_id": world.project.project_id,
        "url": "https://example.com/document",
    }
    payload.update(overrides)
    return FetchRequest(**payload)
