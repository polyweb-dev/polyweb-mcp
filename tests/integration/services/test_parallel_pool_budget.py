"""Comprehensive integration tests for TASK-000077.

Parallel: OAuth credential in project pool and API-key budget tracking.
Validates AC #1 through #10:
- AC #1: Parallel OAuth credential added to project pool via API & service.
- AC #2: Project with OAuth-only Parallel pool runs search and fetch successfully.
- AC #3: Project with API-key-only Parallel pool runs search/fetch and records actual usage.
- AC #4 & AC #6: Project holds both Parallel credential kinds (mixed pools) without conflict.
- AC #5: Standardized model across credentials/pools.
- AC #7: Pools view shows each credential in its own correct pool; assigned pool not unassigned.
- AC #8: Removing, deleting, and re-adding pools/credentials leaves no stale state.
- AC #9: Parallel API-key calls record actual cost ($0.001 turbo/extract), summed into totals.
- AC #10: Authoritative balance from Parallel API is shown on the dashboard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import AnyHttpUrl, SecretStr

from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.contracts import (
    FetchRequest,
    QuotaSource,
    SearchRequest,
    UnitKind,
)
from polyweb.models.credentials import CredentialAuthMode
from polyweb.models.observability import ActorType, ExecutionAttribution
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    HumanPrincipal,
    PermissionAction,
    ProjectContext,
    ProjectCreate,
)
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.models.vault import KeyPoolCreate, PoolBudget, VaultKeyCreate
from polyweb.persistence.key_pools import KeyPoolRepository
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRow, oauth_secret_slot
from polyweb.persistence.storage import QuotaSnapshotRow, SQLiteRepository
from polyweb.services.execution import ExecutionService
from polyweb.services.key_pools import KeyPoolService
from polyweb.services.monitoring import _latest_quotas
from polyweb.services.pool_budget import pool_budget_used_micros
from polyweb.services.projects import ProjectService
from polyweb.services.provider_limits import (
    ProviderLimitsService,
)
from polyweb.services.vault_keys import VaultKeyService
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
from tests.fixtures.auth import temp_principal


def _parallel_search_payload() -> dict[str, Any]:
    return {
        "search_id": "search-parallel-test",
        "results": [
            {
                "url": "https://example.com/one",
                "title": "One",
                "excerpts": ["Excerpt one"],
            }
        ],
        "usage": [{"sku": "SEARCH_QUERY_TURBO", "count": 1}],
    }


def _parallel_extract_payload() -> dict[str, Any]:
    return {
        "extract_id": "extract-parallel-test",
        "results": [
            {
                "url": "https://example.com/one",
                "full_content": "Extracted text content",
            }
        ],
        "usage": [{"sku": "EXTRACT_URL", "count": 1}],
    }


def _mock_parallel_transport(
    search_headers: list[dict[str, str]],
    extract_headers: list[dict[str, str]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        headers_dict = dict(request.headers)
        if "/v1/search" in path:
            search_headers.append(headers_dict)
            return httpx.Response(200, json=_parallel_search_payload())
        if "/v1/extract" in path:
            extract_headers.append(headers_dict)
            return httpx.Response(200, json=_parallel_extract_payload())
        if "/account/service/v1/balance" in path:
            return httpx.Response(
                200,
                json={
                    "org_id": "org-parallel",
                    "credit_balance_cents": 2500,
                    "pending_debit_balance_cents": 0,
                    "will_invoice": False,
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ac1_parallel_oauth_credential_can_be_added_to_project_pool(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "ac1.db")
    try:
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        project_svc = ProjectService(boot.repository)
        pools_svc = KeyPoolService(boot.repository)

        project = await project_svc.create_project(
            admin, ProjectCreate(name="Proj1", slug=f"proj-{uuid4().hex[:8]}")
        )
        oauth_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel", label="Parallel OAuth", auth_mode=CredentialAuthMode.OAUTH
            ),
        )

        # Check available providers before assignment
        projects = await pools_svc.projects(admin)
        proj_view = next(p for p in projects if p.id == project.id)
        assert "parallel" in proj_view.available_providers

        # AC #1: Add Parallel OAuth credential to project pool
        pool = await pools_svc.create(
            admin,
            oauth_key.id,
            KeyPoolCreate(label="Parallel OAuth Pool", project_id=project.id),
        )
        assert pool.credential_id == oauth_key.id
        assert pool.project_id == project.id
        assert pool.provider_type == "parallel"

        # Check available providers after assignment (all Parallel keys assigned)
        projects_after = await pools_svc.projects(admin)
        proj_after = next(p for p in projects_after if p.id == project.id)
        assert "parallel" not in proj_after.available_providers
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac2_parallel_oauth_only_pool_runs_search_and_fetch(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "ac2.db")
    try:
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        project_svc = ProjectService(boot.repository)
        pools_svc = KeyPoolService(boot.repository)

        project = await project_svc.create_project(
            admin, ProjectCreate(name="ProjOAuth", slug=f"proj-{uuid4().hex[:8]}")
        )
        oauth_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel", label="Parallel OAuth", auth_mode=CredentialAuthMode.OAUTH
            ),
        )
        # Store OAuth access token with connected grant
        async with boot.repository.session() as session:
            session.add(
                CredentialOAuthGrantRow(
                    credential_id=str(oauth_key.id),
                    auth_mode="oauth",
                    credential_generation=1,
                    token_generation=1,
                    status=OAuthGrantStatus.CONNECTED.value,
                    updated_at=datetime.now(UTC).isoformat(),
                    version=1,
                )
            )
            await session.commit()
        await store.set(oauth_secret_slot(oauth_key.id, "access", 1), "oauth-token-secret")

        await pools_svc.create(
            admin,
            oauth_key.id,
            KeyPoolCreate(label="OAuth Pool", project_id=project.id),
        )

        search_headers: list[dict[str, str]] = []
        extract_headers: list[dict[str, str]] = []
        mock_client = httpx.AsyncClient(
            transport=_mock_parallel_transport(search_headers, extract_headers)
        )

        limits = ProviderLimitsService(boot.repository.limits)
        await limits.initialize()
        exec_svc = ExecutionService(
            repository=boot.repository,
            secret_store=store,
            client=mock_client,
            limits=limits,
        )

        context = ProjectContext(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            project_id=project.id,
            principal=HumanPrincipal(user_id=admin.id, session_id=uuid4()),
            effective_permissions=frozenset(
                {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
            ),
            policy_revision=1,
        )

        attr = ExecutionAttribution(
            project_id=project.id, actor_type=ActorType.HUMAN, actor_id=admin.id
        )

        # AC #2: Project runs search through Parallel OAuth credential
        search_res = await exec_svc.search(
            SearchRequest(project_id=project.id, query="test query"),
            attribution=attr,
            context=context,
        )
        assert search_res.provider == "parallel"
        assert len(search_res.results) == 1
        assert len(search_headers) == 1
        assert search_headers[0]["authorization"] == "Bearer oauth-token-secret"
        assert search_headers[0]["x-api-key"] == "oauth-token-secret"

        # AC #2: Project runs fetch through Parallel OAuth credential
        fetch_res = await exec_svc.fetch(
            FetchRequest(project_id=project.id, url=AnyHttpUrl("https://example.com/one")),
            attribution=attr,
            context=context,
        )
        assert fetch_res.provider == "parallel"
        assert str(fetch_res.document.url) == "https://example.com/one"
        assert len(extract_headers) == 1
        assert extract_headers[0]["authorization"] == "Bearer oauth-token-secret"
        assert extract_headers[0]["x-api-key"] == "oauth-token-secret"

        await exec_svc.aclose()
        await mock_client.aclose()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac3_and_ac9_api_key_only_pool_records_actual_cost(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "ac3.db")
    try:
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        project_svc = ProjectService(boot.repository)
        pools_svc = KeyPoolService(boot.repository)

        project = await project_svc.create_project(
            admin, ProjectCreate(name="ProjAPIKey", slug=f"proj-{uuid4().hex[:8]}")
        )
        api_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel",
                label="Parallel Key",
                auth_mode=CredentialAuthMode.API_KEY,
                secret=SecretStr("my-api-key"),
            ),
        )

        pool = await pools_svc.create(
            admin,
            api_key.id,
            KeyPoolCreate(
                label="API Key Pool",
                project_id=project.id,
                budget=PoolBudget(limit=Decimal("10.00"), period="month"),
            ),
        )

        search_headers: list[dict[str, str]] = []
        extract_headers: list[dict[str, str]] = []
        mock_client = httpx.AsyncClient(
            transport=_mock_parallel_transport(search_headers, extract_headers)
        )

        limits = ProviderLimitsService(boot.repository.limits)
        await limits.initialize()
        exec_svc = ExecutionService(
            repository=boot.repository,
            secret_store=store,
            client=mock_client,
            limits=limits,
        )

        context = ProjectContext(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            project_id=project.id,
            principal=HumanPrincipal(user_id=admin.id, session_id=uuid4()),
            effective_permissions=frozenset(
                {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
            ),
            policy_revision=1,
        )

        attr = ExecutionAttribution(
            project_id=project.id, actor_type=ActorType.HUMAN, actor_id=admin.id
        )

        # Execute search (turbo cost is $0.001)
        search_res = await exec_svc.search(
            SearchRequest(project_id=project.id, query="turbo search"),
            attribution=attr,
            context=context,
        )
        assert search_res.provider == "parallel"

        # Check that actual cost is $0.001 (1000 micro-dollars) in pool budget usage
        async with boot.repository.session() as session:
            used_micros = await pool_budget_used_micros(session, pool.id)
            assert used_micros == 1000  # $0.001 = 1000 microdollars, NOT 5000 (default)

        # Execute fetch (1 URL cost is $0.001)
        fetch_res = await exec_svc.fetch(
            FetchRequest(project_id=project.id, url=AnyHttpUrl("https://example.com/one")),
            attribution=attr,
            context=context,
        )
        assert fetch_res.provider == "parallel"

        # Check that cumulative cost is $0.002 (2000 microdollars)
        async with boot.repository.session() as session:
            used_micros = await pool_budget_used_micros(session, pool.id)
            assert used_micros == 2000  # 1000 search + 1000 fetch = 2000 micros

        # Verify KeyPoolService view reflects actual budget_used_usd
        pool_read = await pools_svc.get(admin, pool.id)
        assert pool_read.budget_used_usd == Decimal("0.002")

        await exec_svc.aclose()
        await mock_client.aclose()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac4_ac6_ac7_mixed_parallel_pools_without_conflict(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "mixed.db")
    try:
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        project_svc = ProjectService(boot.repository)
        pools_svc = KeyPoolService(boot.repository)

        project = await project_svc.create_project(
            admin, ProjectCreate(name="ProjMixed", slug=f"proj-{uuid4().hex[:8]}")
        )

        # Create both OAuth and API-key credentials
        oauth_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel", label="Parallel OAuth", auth_mode=CredentialAuthMode.OAUTH
            ),
        )
        # Connect OAuth grant
        async with boot.repository.session() as session:
            session.add(
                CredentialOAuthGrantRow(
                    credential_id=str(oauth_key.id),
                    auth_mode="oauth",
                    credential_generation=1,
                    token_generation=1,
                    status=OAuthGrantStatus.CONNECTED.value,
                    updated_at=datetime.now(UTC).isoformat(),
                    version=1,
                )
            )
            await session.commit()
        await store.set(oauth_secret_slot(oauth_key.id, "access", 1), "oauth-token-secret")

        api_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel",
                label="Parallel API Key",
                auth_mode=CredentialAuthMode.API_KEY,
                secret=SecretStr("api-key-secret"),
            ),
        )

        # AC #4 & #7: Add OAuth pool assigned to project
        oauth_pool = await pools_svc.create(
            admin,
            oauth_key.id,
            KeyPoolCreate(label="OAuth Pool", project_id=project.id),
        )
        assert oauth_pool.project_id == project.id

        # Verify Parallel is STILL an available provider for the project (API key is unassigned)
        projects = await pools_svc.projects(admin)
        proj_view = next(p for p in projects if p.id == project.id)
        assert "parallel" in proj_view.available_providers

        # AC #4 & #7: Add API Key pool ALSO assigned to the same project (no IntegrityError!)
        api_pool = await pools_svc.create(
            admin,
            api_key.id,
            KeyPoolCreate(
                label="API Key Pool",
                project_id=project.id,
                budget=PoolBudget(limit=Decimal("5.00"), period="month"),
            ),
        )
        assert api_pool.project_id == project.id

        # Both pools are assigned to the project and listed under their respective keys
        oauth_pools = await pools_svc.list_for_key(admin, oauth_key.id)
        api_pools = await pools_svc.list_for_key(admin, api_key.id)
        assert len(oauth_pools) == 1
        assert oauth_pools[0].id == oauth_pool.id
        assert oauth_pools[0].project_id == project.id  # NOT unassigned!

        assert len(api_pools) == 1
        assert api_pools[0].id == api_pool.id
        assert api_pools[0].project_id == project.id  # NOT unassigned!

        # Now both Parallel keys are assigned to project, so parallel is no longer available
        projects_full = await pools_svc.projects(admin)
        proj_full = next(p for p in projects_full if p.id == project.id)
        assert "parallel" not in proj_full.available_providers

        # AC #6: Execution works with mixed pools
        search_headers: list[dict[str, str]] = []
        extract_headers: list[dict[str, str]] = []
        mock_client = httpx.AsyncClient(
            transport=_mock_parallel_transport(search_headers, extract_headers)
        )

        limits = ProviderLimitsService(boot.repository.limits)
        await limits.initialize()
        exec_svc = ExecutionService(
            repository=boot.repository,
            secret_store=store,
            client=mock_client,
            limits=limits,
        )

        context = ProjectContext(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            project_id=project.id,
            principal=HumanPrincipal(user_id=admin.id, session_id=uuid4()),
            effective_permissions=frozenset(
                {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
            ),
            policy_revision=1,
        )

        attr = ExecutionAttribution(
            project_id=project.id, actor_type=ActorType.HUMAN, actor_id=admin.id
        )

        search_res = await exec_svc.search(
            SearchRequest(project_id=project.id, query="mixed test"),
            attribution=attr,
            context=context,
        )
        assert search_res.provider == "parallel"

        await exec_svc.aclose()
        await mock_client.aclose()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac8_removing_deleting_readding_pools_leaves_no_stale_state(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "ac8.db")
    try:
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        project_svc = ProjectService(boot.repository)
        pools_svc = KeyPoolService(boot.repository)

        project = await project_svc.create_project(
            admin, ProjectCreate(name="ProjLifecycle", slug=f"proj-{uuid4().hex[:8]}")
        )
        api_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel",
                label="Parallel Key",
                auth_mode=CredentialAuthMode.API_KEY,
                secret=SecretStr("my-api-key"),
            ),
        )

        # Create and assign pool
        pool = await pools_svc.create(
            admin,
            api_key.id,
            KeyPoolCreate(
                label="Pool 1",
                project_id=project.id,
                budget=PoolBudget(limit=Decimal("10.00"), period="month"),
            ),
        )

        # Unassign pool (removes from project)
        await pools_svc.assign(admin, pool.id, None)
        unassigned_pool = await pools_svc.get(admin, pool.id)
        assert unassigned_pool.project_id is None

        # Project now has Parallel available again
        projects = await pools_svc.projects(admin)
        proj_view = next(p for p in projects if p.id == project.id)
        assert "parallel" in proj_view.available_providers

        # Re-assign pool
        await pools_svc.assign(admin, pool.id, project.id)
        reassigned_pool = await pools_svc.get(admin, pool.id)
        assert reassigned_pool.project_id == project.id

        # Delete pool
        await pools_svc.delete(admin, pool.id)
        async with boot.repository.session() as session:
            assert await KeyPoolRepository(session).list_for_project(project.id) == []

        # Re-add pool
        new_pool = await pools_svc.create(
            admin,
            api_key.id,
            KeyPoolCreate(
                label="Pool Recreated",
                project_id=project.id,
                budget=PoolBudget(limit=Decimal("15.00"), period="month"),
            ),
        )
        assert new_pool.project_id == project.id
        assert new_pool.label == "Pool Recreated"
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac10_authoritative_balance_shown_on_dashboard(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "ac10.db")
    try:
        repository: SQLiteRepository = boot.repository
        admin = temp_principal(boot.admin_user)
        codec = SecretCodec(MasterKey(b"0" * 32))
        store = EncryptedDbSecretStore(boot.repository, codec)
        vault = VaultKeyService(boot.repository, store)
        oauth_key = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="parallel", label="Parallel OAuth", auth_mode=CredentialAuthMode.OAUTH
            ),
        )

        # Insert a credential-scoped authoritative quota snapshot
        # (as recorded by Parallel OAuth sync)
        now = datetime.now(UTC)
        async with repository.session() as session:
            session.add(
                QuotaSnapshotRow(
                    provider="parallel",
                    credential_id=str(oauth_key.id),
                    pool_id=None,
                    source=QuotaSource.AUTHORITATIVE.value,
                    remaining="25.00",
                    limit_units="100.00",
                    reset_at=None,
                    observed_at=now.isoformat(),
                    unit_kind="USD",
                    display_unit="USD",
                    metadata_json=json.dumps({"native_sync": True}),
                )
            )
            await session.commit()

        # Call _latest_quotas for dashboard
        quotas = await _latest_quotas(repository, ["parallel"], totals=[])
        assert len(quotas) == 1
        parallel_quota = quotas[0]
        assert parallel_quota.provider == "parallel"
        assert parallel_quota.remaining == Decimal("25.00")
        assert parallel_quota.source is QuotaSource.AUTHORITATIVE
        assert parallel_quota.unit_kind is UnitKind.USD
    finally:
        await boot.repository.close()
