"""Project provider and binding reads against materialized vault pools."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from polyweb.configuration.provider_config import ProviderConfig
from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.contracts import HealthStatus, ProviderHealth, UsageEvent, UsageOperation
from polyweb.models.observability import ActorType, ExecutionAttribution
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectRead,
)
from polyweb.models.provider_access import FETCH_BIT, GLOBAL_BIT, SEARCH_BIT
from polyweb.models.users import UserPrincipal
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from polyweb.persistence.storage import ProviderHealthRow
from polyweb.routers.api import create_app
from polyweb.services.credentials import credential_secret_slot
from polyweb.services.pool_materializer import materialize_pools
from polyweb.services.projects import ProjectService
from polyweb.services.provider_runtime import persist_provider_config
from tests.fixtures.alpha_fixtures import (
    ALPHA_ADMIN_PASSWORD,
    AlphaBootstrapResult,
    bootstrap_fresh_alpha,
)
from tests.fixtures.api_keys import ProjectKey, key_for_account
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal


@dataclass
class _World:
    boot: AlphaBootstrapResult
    client: TestClient
    store: EncryptedDbSecretStore
    project_a: ProjectRead
    project_b: ProjectRead
    a_admin: UserPrincipal
    a_member: UserPrincipal
    b_admin: UserPrincipal
    key: ProjectKey
    a: dict[str, str]
    a_member_h: dict[str, str]
    b: dict[str, str]

    def run(self, coro: Any) -> Any:
        portal = self.client.portal  # type: ignore[attr-defined]
        return portal.call(lambda: coro)

    @property
    def repository(self) -> Any:
        return self.boot.repository


def _login(client: TestClient, email: str, password: str = TEMP_PASSWORD) -> dict[str, str]:
    response = client.post("/auth/jwt/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def world(tmp_path: Path, auth_secret: str) -> Iterator[_World]:
    import asyncio

    async def _setup() -> tuple[AlphaBootstrapResult, tuple[Any, ...]]:
        boot = await bootstrap_fresh_alpha(tmp_path / "a4-control.db")
        system_admin = temp_principal(boot.admin_user)
        projects = ProjectService(boot.repository)
        a_admin = await create_temp_user(boot.repository, temp_email("ctl-a-admin"))
        a_member = await create_temp_user(boot.repository, temp_email("ctl-a-member"))
        b_admin = await create_temp_user(boot.repository, temp_email("ctl-b-admin"))
        project_a = await projects.create_project(
            system_admin,
            ProjectCreate(name="Ctl A", slug="ctl-a", initial_admin_user_id=a_admin.id),
        )
        project_b = await projects.create_project(
            system_admin,
            ProjectCreate(name="Ctl B", slug="ctl-b", initial_admin_user_id=b_admin.id),
        )
        await projects.add_member(
            temp_principal(a_admin), project_a.id, ProjectMemberAdd(user_id=a_member.id)
        )
        key = await key_for_account(boot.repository, a_admin.id, project_a.id)
        return boot, (project_a, project_b, a_admin, a_member, b_admin, key)

    boot, (project_a, project_b, a_admin, a_member, b_admin, key) = asyncio.run(_setup())
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    app = create_app([], repository=boot.repository, secret_store=store)
    try:
        with TestClient(app) as client:
            yield _World(
                boot=boot,
                client=client,
                store=store,
                project_a=project_a,
                project_b=project_b,
                a_admin=temp_principal(a_admin),
                a_member=temp_principal(a_member),
                b_admin=temp_principal(b_admin),
                key=key,
                a=_login(client, a_admin.email),
                a_member_h=_login(client, a_member.email),
                b=_login(client, b_admin.email),
            )
    finally:
        asyncio.run(boot.repository.close())


def _ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json() if response.content else None


def _provider(world: _World, project_id: UUID, provider: str) -> dict[str, Any]:
    view = _ok(world.client.get(f"/api/v1/projects/{project_id}/providers", headers=world.a))
    return next(item for item in view["providers"] if item["provider_type"] == provider)


def _create_key(
    world: _World, owner: UserPrincipal, provider: str, label: str, secret: str
) -> UUID:
    async def create() -> UUID:
        async with world.repository.session() as session:
            key = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=owner.id,
                label=label,
                auth_mode="api_key",
                created_by=owner.id,
            )
            await world.store.create_slot_in_session(
                session, credential_secret_slot(key.id, 1), secret
            )
            await session.commit()
            return key.id

    return world.run(create())


def _assign_pool(
    world: _World,
    key_id: UUID,
    owner: UserPrincipal,
    project_id: UUID,
    provider: str,
    operations: frozenset[Literal["search", "fetch"]],
    rate: int,
    *,
    label: str | None = None,
) -> UUID:
    async def create() -> UUID:
        async with world.repository.session() as session:
            pool = await KeyPoolRepository(session).create(
                credential_id=key_id,
                project_id=project_id,
                provider_type=provider,
                created_by=owner.id,
                values=KeyPoolValues(
                    label=label or f"{provider} shared pool",
                    operations=operations,
                    rate_limit=rate,
                ),
            )
            await materialize_pools(session, project_id=project_id)
            await session.commit()
            return pool.id

    return world.run(create())


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value)) if value else set()
    return set()


def test_ac3_project_scoped_routes_hide_projects_from_non_members(world: _World) -> None:
    pid = world.project_a.id
    key = _create_key(world, world.a_admin, "exa", "a-private", "a-secret")
    _assign_pool(world, key, world.a_admin, pid, "exa", frozenset({"search"}), 10)
    member_key = _create_key(world, world.a_member, "brave", "member-only", "member-secret")
    _assign_pool(world, member_key, world.a_member, pid, "brave", frozenset({"search"}), 10)

    for resource in ("providers", "bindings"):
        url = f"/api/v1/projects/{pid}/{resource}"
        ghost_url = f"/api/v1/projects/{uuid4()}/{resource}"
        real = world.client.get(url, headers=world.b)
        unknown = world.client.get(ghost_url, headers=world.b)
        assert real.status_code == unknown.status_code == 404
        assert real.content == unknown.content == b""
        assert world.client.get(url, headers=world.a_member_h).status_code == 200
        assert world.client.get(url, headers=world.key.headers()).status_code == 401

    bindings = _ok(world.client.get(f"/api/v1/projects/{pid}/bindings", headers=world.a))
    assert len(bindings) == 1
    assert bindings[0]["credential_id"] == str(key)
    assert bindings[0]["enabled_operations"] == ["search"]
    member_bindings = _ok(
        world.client.get(f"/api/v1/projects/{pid}/bindings", headers=world.a_member_h)
    )
    assert [binding["credential_id"] for binding in member_bindings] == [str(member_key)]


def test_pool_health_is_shared_and_uses_latest_bound_credential(world: _World) -> None:
    project = world.project_a.id
    key = _create_key(world, world.a_admin, "exa", "serving", "serving-secret")
    _assign_pool(world, key, world.a_admin, project, "exa", frozenset({"search"}), 10)
    other = _create_key(world, world.a_admin, "exa", "other", "other-secret")
    earlier = datetime(2026, 1, 1, 9, tzinfo=UTC)
    error_time = datetime(2026, 1, 1, 10, tzinfo=UTC)
    newer = datetime(2026, 1, 1, 11, tzinfo=UTC)

    async def seed() -> None:
        for credential, status, instant in (
            (key, HealthStatus.HEALTHY, earlier),
            (key, HealthStatus.DEGRADED, error_time),
            (other, HealthStatus.HEALTHY, newer),
        ):
            await world.repository.record_health(
                ProviderHealth(provider="exa", status=status, checked_at=instant),
                credential_id=credential,
            )

    world.run(seed())
    views = [
        _ok(world.client.get(f"/api/v1/projects/{project}/providers", headers=headers))
        for headers in (world.a, world.a_member_h)
    ]
    for view in views:
        exa = next(row for row in view["providers"] if row["provider_type"] == "exa")
        assert exa["health_status"] == "degraded"
        assert datetime.fromisoformat(exa["health_checked_at"].replace("Z", "+00:00")) == error_time
        credential = next(item for item in exa["credentials"] if item["id"] == str(key))
        assert credential["health_status"] == "degraded"
        assert credential["health_checked_at"] == exa["health_checked_at"]
        assert {item["credential_id"] for item in exa["bindings"]} == {str(key)}
        assert str(other) not in str(exa)

    system_headers = _login(world.client, world.boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
    system = _ok(world.client.get("/api/v1/providers", headers=system_headers))
    exa = next(item for item in system if item["provider_id"] == "exa")
    assert exa["health"] == "degraded"
    assert datetime.fromisoformat(exa["health_checked_at"].replace("Z", "+00:00")) == error_time


def test_keyless_health_uses_bound_system_credential_for_every_member(world: _World) -> None:
    project = world.project_a.id
    checked_at = datetime(2026, 1, 1, 12, tzinfo=UTC)

    async def seed() -> UUID:
        await persist_provider_config(world.repository, ProviderName.KEENABLE, ProviderConfig())
        async with world.repository.session() as session:
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="keenable",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.a_admin.id,
                label="owned-keyless",
                auth_mode="keyless",
                created_by=world.a_admin.id,
            )
            await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=project,
                provider_type="keenable",
                created_by=world.a_admin.id,
                values=KeyPoolValues(label="free-tier", operations=frozenset({"search"})),
            )
            await materialize_pools(session, project_id=project)
            await session.commit()
        await world.repository.record_health(
            ProviderHealth(provider="keenable", status=HealthStatus.HEALTHY, checked_at=checked_at),
            credential_id=credential.id,
        )
        return credential.id

    credential_id = world.run(seed())
    for headers in (world.a, world.a_member_h):
        view = _ok(world.client.get(f"/api/v1/projects/{project}/providers", headers=headers))
        keenable = next(row for row in view["providers"] if row["provider_type"] == "keenable")
        assert keenable["health_status"] == "healthy"
        assert datetime.fromisoformat(keenable["health_checked_at"].replace("Z", "+00:00")) == (
            checked_at
        )
        assert keenable["credentials"][0]["auth_mode"] == "keyless"
        assert {key["id"] for key in keenable["credentials"]} == {str(credential_id)}
        assert {binding["credential_id"] for binding in keenable["bindings"]} == {
            str(credential_id)
        }
        assert keenable["credentials"][0]["health_checked_at"] == keenable["health_checked_at"]


def test_ac4_materialized_enablement_respects_system_switches(world: _World) -> None:
    pid = world.project_a.id
    key = _create_key(world, world.a_admin, "tavily", "shared", "shared-secret")
    _assign_pool(world, key, world.a_admin, pid, "tavily", frozenset({"search", "fetch"}), 10)

    tavily = _provider(world, pid, "tavily")
    assert tavily["available"] is True
    assert tavily["enabled"] is True
    assert set(tavily["effective_operations"]) == {"search", "fetch"}
    assert tavily["credentials"][0]["id"] == str(key)
    assert set(tavily["bindings"][0]["enabled_operations"]) == {"search", "fetch"}

    world.run(
        persist_provider_config(
            world.repository, ProviderName.TAVILY, ProviderConfig(enable_mask=0)
        )
    )
    killed = _provider(world, pid, "tavily")
    assert killed["kill_switch"] is True
    assert killed["effective_operations"] == []
    assert killed["enabled"] is False
    assert set(killed["bindings"][0]["enabled_operations"]) == {"search", "fetch"}
    assert killed["bindings"][0]["effective_operations"] == []

    for bit, operation in ((SEARCH_BIT, "search"), (FETCH_BIT, "fetch")):
        world.run(
            persist_provider_config(
                world.repository, ProviderName.TAVILY, ProviderConfig(enable_mask=GLOBAL_BIT | bit)
            )
        )
        limited = _provider(world, pid, "tavily")
        assert limited["kill_switch"] is False
        assert limited["effective_operations"] == [operation]
        assert set(limited["bindings"][0]["enabled_operations"]) == {"search", "fetch"}

    world.run(persist_provider_config(world.repository, ProviderName.TAVILY, ProviderConfig()))
    assert set(_provider(world, pid, "tavily")["effective_operations"]) == {"search", "fetch"}
    brave = _provider(world, pid, "brave")
    assert brave["capability"] == ["search"]


def test_ac5_provider_view_hides_secrets_other_projects_usage_and_balances(world: _World) -> None:
    a, b = world.project_a.id, world.project_b.id
    shared_secret = f"fake-view-shared-{uuid4().hex}"
    shared = _create_key(world, world.a_admin, "tavily", "shared-label", shared_secret)
    _assign_pool(world, shared, world.a_admin, a, "tavily", frozenset({"search"}), 11)
    _assign_pool(
        world,
        shared,
        world.a_admin,
        b,
        "tavily",
        frozenset({"search", "fetch"}),
        37,
        label="other project pool",
    )
    private = _create_key(world, world.b_admin, "exa", "b-secret-label", "b-secret")
    _assign_pool(world, private, world.b_admin, b, "exa", frozenset({"search"}), 9)
    health_message = f"vendor said HEALTH-MESSAGE-{uuid4().hex}"
    usage_units = "12345.678"

    async def seed_health_and_usage() -> None:
        async with world.repository.session() as session:
            session.add(
                ProviderHealthRow(
                    provider="tavily",
                    status="degraded",
                    checked_at=datetime.now(UTC).isoformat(),
                    message=health_message,
                    credential_id=str(shared),
                )
            )
            await session.commit()
        await world.repository.record_usage(
            UsageEvent(
                provider="tavily",
                operation=UsageOperation.SEARCH,
                units=Decimal(usage_units),
                observed_at=datetime.now(UTC),
            ),
            attribution=ExecutionAttribution(
                project_id=b, actor_type=ActorType.HUMAN, actor_id=world.b_admin.id
            ),
            credential_id=shared,
        )

    world.run(seed_health_and_usage())

    async def other_binding_id() -> UUID:
        async with world.repository.session() as session:
            bindings = await ProjectBindingRepository(session).list_for_project(project_id=b)
            return next(binding.id for binding in bindings if binding.credential_id == shared)

    b_binding = world.run(other_binding_id())
    response = world.client.get(f"/api/v1/projects/{a}/providers", headers=world.a)
    view = _ok(response)
    assert set(view) == {"project_id", "providers", "allocations"}
    assert view["project_id"] == str(a)
    for provider in view["providers"]:
        assert set(provider) == {
            "provider_type",
            "call_cost_usd",
            "keyless_call_cost_usd",
            "capability",
            "kill_switch",
            "system_enabled_operations",
            "available",
            "enabled",
            "health_status",
            "health_checked_at",
            "keyless",
            "credentials",
            "bindings",
            "effective_operations",
        }
        for item in provider["credentials"]:
            assert set(item) == {
                "id",
                "label",
                "owner_scope",
                "auth_mode",
                "status",
                "health_status",
                "health_checked_at",
                "granted_operations",
                "supported_operations",
                "pools",
            }
            for pool in item["pools"]:
                assert set(pool) == {
                    "operation_scope",
                    "pool_id",
                    "label",
                    "upstream_scope",
                    "status",
                    "owner_scope",
                }
                assert pool["owner_scope"] == "system"
        for binding in provider["bindings"]:
            assert set(binding) == {
                "id",
                "credential_id",
                "route_label",
                "priority",
                "enabled_operations",
                "effective_operations",
            }
    assert "shared" not in _all_keys(view)
    tavily = next(item for item in view["providers"] if item["provider_type"] == "tavily")
    (credential,) = tavily["credentials"]
    assert credential["label"] == "shared-label"
    assert credential["owner_scope"] == "system"
    assert credential["health_status"] == "degraded"
    assert credential["granted_operations"] == ["search"]
    assert len(tavily["bindings"]) == 1
    assert [(item["project_id"], item["base_rate"]) for item in view["allocations"]] == [
        (str(a), 11)
    ]
    exa = next(item for item in view["providers"] if item["provider_type"] == "exa")
    assert exa["credentials"] == [] and exa["available"] is False

    for forbidden in (
        shared_secret,
        "secret.enc",
        f"credential.{shared}",
        health_message,
        usage_units,
        str(b_binding),
        str(private),
        "b-secret-label",
        str(b),
    ):
        assert forbidden not in response.text, forbidden
    assert not _all_keys(view) & {
        "secret",
        "digest",
        "fingerprint",
        "message",
        "remaining",
        "balance",
        "consumed",
        "usage",
        "units",
        "slot",
    }
    assert [(pool["operation_scope"], pool["label"]) for pool in credential["pools"]] == [
        ("search", "tavily shared pool")
    ]
