"""A4 AC2-AC5 over HTTP: OAuth routes, bindings, provider view, pools and allocations.

Temporary SQLite database, real app composition, fake Parallel vendor through
``app.state.credential_oauth_http_client`` and no network. Least privilege:
the bootstrap system administrator is used only for system routes; project
routes run as ordinary project administrators or members.

Error contract under test: 409/422 carry ``{"detail": {"code", "message"}}``
(422 from request validation carries FastAPI's list instead); 404/403 carry no
body. A1 rule: a non-member or unknown project is 404, a member without the
permission is 403, a project API key is 401.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from freesearch.configuration.provider_config import ProviderConfig
from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import UsageEvent, UsageOperation
from freesearch.models.observability import ActorType, ExecutionAttribution
from freesearch.models.projects import ProjectCreate, ProjectMemberAdd, ProjectRead
from freesearch.models.users import UserPrincipal
from freesearch.persistence.storage import ProviderHealthRow
from freesearch.routers.api import create_app
from freesearch.routers.control import persist_provider_config
from freesearch.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import (
    ALPHA_ADMIN_PASSWORD,
    AlphaBootstrapResult,
    bootstrap_fresh_alpha,
)
from tests.fixtures.api_keys import ProjectKey, audit_rows, database_dump, key_for_account
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal
from tests.fixtures.parallel_oauth_vendor import FakeParallelVendor

_SYSTEM_CREDS = "/api/v1/system/credentials"
_POOLS = "/api/v1/system/pools"


@dataclass
class _World:
    boot: AlphaBootstrapResult
    client: TestClient
    vendor: FakeParallelVendor
    project_a: ProjectRead
    project_b: ProjectRead
    a_admin: UserPrincipal
    a_member: UserPrincipal
    b_admin: UserPrincipal
    key: ProjectKey
    system: dict[str, str]
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
    vendor = FakeParallelVendor()
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    app = create_app([], repository=boot.repository, secret_store=store)
    app.state.credential_oauth_http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(vendor.handler)
    )
    try:
        with TestClient(app) as client:
            yield _World(
                boot=boot,
                client=client,
                vendor=vendor,
                project_a=project_a,
                project_b=project_b,
                a_admin=temp_principal(a_admin),
                a_member=temp_principal(a_member),
                b_admin=temp_principal(b_admin),
                key=key,
                system=_login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD),
                a=_login(client, a_admin.email),
                a_member_h=_login(client, a_member.email),
                b=_login(client, b_admin.email),
            )
    finally:
        asyncio.run(boot.repository.close())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json() if response.content else None


def _code(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, (response.status_code, response.text)
    assert response.json()["detail"]["code"] == code, response.text


def _system_credential(world: _World, provider: str, label: str, **extra: Any) -> str:
    body: dict[str, Any] = {"provider_type": provider, "label": label, **extra}
    if extra.get("auth_mode") != "oauth":
        body.setdefault("secret", f"fake-ctl-secret-{uuid4().hex}")
    return str(_ok(world.client.post(_SYSTEM_CREDS, headers=world.system, json=body), 201)["id"])


def _private_credential(
    world: _World, headers: dict[str, str], project_id: UUID, provider: str, label: str
) -> str:
    body = {"provider_type": provider, "label": label, "secret": f"fake-ctl-{uuid4().hex}"}
    response = world.client.post(
        f"/api/v1/projects/{project_id}/credentials", headers=headers, json=body
    )
    return str(_ok(response, 201)["id"])


def _grant(world: _World, credential_id: str, project_id: UUID, operations: list[str]) -> None:
    _ok(
        world.client.put(
            f"{_SYSTEM_CREDS}/{credential_id}/grants/{project_id}",
            headers=world.system,
            json={"permitted_operations": operations},
        )
    )


def _pool(world: _World, provider: str = "tavily", limit: int = 100) -> str:
    response = world.client.post(
        _POOLS,
        headers=world.system,
        json={
            "provider_type": provider,
            "upstream_scope": "account",
            "pool_key": f"{provider}-{uuid4().hex[:8]}",
            "label": f"{provider} shared pool",
            "constraints": [{"algorithm": "fixed_window", "window_seconds": 60, "limit": limit}],
        },
    )
    return str(_ok(response, 201)["id"])


def _allocation_url(project_id: UUID, pool_id: str, operation: str = "search") -> str:
    return f"/api/v1/system/projects/{project_id}/allocations/{pool_id}?operation_scope={operation}"


def _providers(world: _World, headers: dict[str, str], project_id: UUID) -> dict[str, Any]:
    body: dict[str, Any] = _ok(
        world.client.get(f"/api/v1/projects/{project_id}/providers", headers=headers)
    )
    return body


def _provider(view: dict[str, Any], provider: str) -> dict[str, Any]:
    return next(item for item in view["providers"] if item["provider_type"] == provider)


def _bindings_url(project_id: UUID, binding_id: str | None = None) -> str:
    base = f"/api/v1/projects/{project_id}/bindings"
    return base if binding_id is None else f"{base}/{binding_id}"


def _system_snapshot(world: _World) -> dict[str, Any]:
    """Every pool, link and allocation as the system administrator sees them."""

    pools = _ok(world.client.get(_POOLS, headers=world.system))
    links = {
        pool["id"]: _ok(world.client.get(f"{_POOLS}/{pool['id']}/links", headers=world.system))
        for pool in pools
    }
    allocations = {
        str(project): _ok(
            world.client.get(f"/api/v1/system/projects/{project}/allocations", headers=world.system)
        )
        for project in (world.project_a.id, world.project_b.id)
    }
    return {"pools": pools, "links": links, "allocations": allocations}


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value)) if value else set()
    return set()


# ---------------------------------------------------------------------------
# AC3: only system administrators manage shared resources
# ---------------------------------------------------------------------------


def test_ac3_system_control_routes_deny_project_admins_and_api_keys(world: _World) -> None:
    shared = _system_credential(world, "tavily", "shared")
    oauth = _system_credential(world, "parallel", "oauth", auth_mode="oauth")
    pool_id = _pool(world)
    _ok(
        world.client.put(
            f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", headers=world.system
        )
    )
    _ok(
        world.client.put(
            _allocation_url(world.project_a.id, pool_id),
            headers=world.system,
            json={"base_rate": 10, "rate_window_seconds": 60},
        )
    )
    before = _system_snapshot(world)
    pid = world.project_a.id
    routes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", _POOLS, None),
        (
            "POST",
            _POOLS,
            {"provider_type": "tavily", "upstream_scope": "account", "pool_key": "x", "label": "x"},
        ),
        ("GET", f"{_POOLS}/{pool_id}", None),
        ("PATCH", f"{_POOLS}/{pool_id}", {"label": "hijacked"}),
        ("GET", f"{_POOLS}/{pool_id}/links", None),
        ("PUT", f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=fetch", None),
        ("DELETE", f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", None),
        ("GET", f"/api/v1/system/projects/{pid}/allocations", None),
        ("GET", _allocation_url(pid, pool_id), None),
        ("PUT", _allocation_url(pid, pool_id), {"base_rate": 90, "rate_window_seconds": 60}),
        ("DELETE", _allocation_url(pid, pool_id), None),
        ("GET", f"{_SYSTEM_CREDS}/{shared}/grants", None),
        ("PUT", f"{_SYSTEM_CREDS}/{shared}/grants/{pid}", {"permitted_operations": ["search"]}),
        ("DELETE", f"{_SYSTEM_CREDS}/{shared}/grants/{pid}", None),
        ("GET", _SYSTEM_CREDS, None),
        ("POST", _SYSTEM_CREDS, {"provider_type": "tavily", "label": "x", "secret": "fake-x"}),
        (
            "POST",
            f"{_SYSTEM_CREDS}/{shared}/rotate",
            {"expected_generation": 1, "secret": "fake-y"},
        ),
        ("DELETE", f"{_SYSTEM_CREDS}/{shared}", None),
        ("POST", f"{_SYSTEM_CREDS}/{oauth}/oauth/device", None),
        ("POST", f"{_SYSTEM_CREDS}/{oauth}/oauth/poll", None),
        ("GET", f"{_SYSTEM_CREDS}/{oauth}/oauth", None),
        ("DELETE", f"{_SYSTEM_CREDS}/{oauth}/oauth", None),
    ]
    for method, url, body in routes:
        for headers, expected in ((world.a, 403), (world.b, 403), (world.key.headers(), 401)):
            response = world.client.request(method, url, headers=headers, json=body)
            assert response.status_code == expected, (method, url, response.text)
            if expected == 403:
                assert response.content == b"", (method, url)
    assert _system_snapshot(world) == before
    assert world.vendor.issued == []


def test_ac3_project_scoped_routes_hide_projects_from_non_members(world: _World) -> None:
    pid = world.project_a.id
    private = _private_credential(world, world.a, pid, "exa", "a-private")
    oauth_body = {"provider_type": "parallel", "label": "a-oauth", "auth_mode": "oauth"}
    oauth = _ok(
        world.client.post(f"/api/v1/projects/{pid}/credentials", headers=world.a, json=oauth_body),
        201,
    )["id"]
    binding = _ok(
        world.client.post(
            _bindings_url(pid),
            headers=world.a,
            json={"credential_id": private, "route_label": "main"},
        ),
        201,
    )["id"]

    def routes(project: object) -> list[tuple[str, str, dict[str, Any] | None]]:
        creds = f"/api/v1/projects/{project}/credentials/{oauth}/oauth"
        return [
            ("GET", f"/api/v1/projects/{project}/providers", None),
            ("GET", _bindings_url(project), None),  # type: ignore[arg-type]
            (
                "POST",
                _bindings_url(project),  # type: ignore[arg-type]
                {"credential_id": private, "route_label": "other"},
            ),
            (
                "PATCH",
                _bindings_url(project, binding),  # type: ignore[arg-type]
                {"enabled_operations": ["search"]},
            ),
            ("DELETE", _bindings_url(project, binding), None),  # type: ignore[arg-type]
            ("POST", f"{creds}/device", None),
            ("POST", f"{creds}/poll", None),
            ("GET", creds, None),
            ("DELETE", creds, None),
        ]

    ghost_project = uuid4()
    for (method, url, body), (_, ghost_url, _) in zip(
        routes(pid), routes(ghost_project), strict=True
    ):
        real = world.client.request(method, url, headers=world.b, json=body)
        unknown = world.client.request(method, ghost_url, headers=world.b, json=body)
        assert real.status_code == unknown.status_code == 404, (method, url, real.text)
        assert real.content == unknown.content == b""

    # A member without providers.configure / credentials.manage_private: reads
    # are allowed, every write is 403 and changes nothing.
    for method, url, body in routes(pid):
        response = world.client.request(method, url, headers=world.a_member_h, json=body)
        expected = 200 if method == "GET" else 403
        assert response.status_code == expected, (method, url, response.text)
    bindings = _ok(world.client.get(_bindings_url(pid), headers=world.a))
    assert [(item["id"], item["enabled_operations"]) for item in bindings] == [(binding, [])]
    assert world.vendor.issued == []


def test_ac3_no_project_route_or_settings_write_changes_pools_or_allocations(
    world: _World,
) -> None:
    pid = world.project_a.id
    shared = _system_credential(world, "tavily", "shared")
    _grant(world, shared, pid, ["search", "fetch"])
    pool_id = _pool(world)
    _ok(
        world.client.put(
            f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", headers=world.system
        )
    )
    _ok(
        world.client.put(
            _allocation_url(pid, pool_id),
            headers=world.system,
            json={"base_rate": 10, "rate_window_seconds": 60},
        )
    )
    before = _system_snapshot(world)

    binding = _ok(
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": shared, "route_label": "r"}
        ),
        201,
    )["id"]
    _ok(
        world.client.patch(
            _bindings_url(pid, binding),
            headers=world.a,
            json={"enabled_operations": ["search", "fetch"], "priority": 1},
        )
    )
    # Project bodies cannot smuggle allocation or pool fields.
    smuggled = world.client.patch(
        _bindings_url(pid, binding),
        headers=world.a,
        json={"enabled_operations": ["search"], "base_rate": 1000, "pool_id": pool_id},
    )
    assert smuggled.status_code == 422
    settings = world.client.put(
        f"/api/v1/projects/{pid}/settings",
        headers=world.a,
        json={"expected_revision": 0, "allocations": [{"pool_id": pool_id, "base_rate": 1000}]},
    )
    assert settings.status_code == 422
    legit = world.client.put(
        f"/api/v1/projects/{pid}/settings",
        headers=world.a,
        json={"expected_revision": 0, "execution": {"max_fanout_concurrency": 20}},
    )
    assert legit.status_code in {200, 409}, legit.text
    _ok(world.client.delete(_bindings_url(pid, binding), headers=world.a), 204)
    private = _private_credential(world, world.a, pid, "tavily", "own")
    _ok(world.client.delete(f"/api/v1/projects/{pid}/credentials/{private}", headers=world.a), 204)

    assert _system_snapshot(world) == before


def test_ac3_allocation_strict_rules_infeasibility_and_type_mismatch(world: _World) -> None:
    a, b = world.project_a.id, world.project_b.id
    pool_id = _pool(world, limit=100)

    def put(project: UUID, body: dict[str, Any], operation: str = "search") -> httpx.Response:
        return world.client.put(
            _allocation_url(project, pool_id, operation), headers=world.system, json=body
        )

    # Strict by default: loans off means max_rate null or equal to base_rate.
    for invalid in (
        {"base_rate": 10, "rate_window_seconds": 60, "max_rate": 20},
        {"base_rate": 0, "rate_window_seconds": 60},
        {"base_rate": 10, "rate_window_seconds": 60, "borrow_enabled": True, "max_rate": 5},
        {"base_rate": 10, "rate_window_seconds": 60, "borrow_enabled": True},
    ):
        assert put(a, invalid).status_code == 422, invalid
    strict = _ok(put(a, {"base_rate": 60, "rate_window_seconds": 60}))
    assert strict["borrow_enabled"] is False
    assert strict["max_rate"] in (None, 60)
    assert strict["effective_max_rate"] == 60
    assert (
        _ok(put(a, {"base_rate": 0, "rate_window_seconds": 60, "best_effort": True}, "fetch"))[
            "best_effort"
        ]
        is True
    )

    # The pool promises at most 100/60s across projects and operations.
    _code(put(b, {"base_rate": 41, "rate_window_seconds": 60}), 409, "ALLOCATION_INFEASIBLE")
    assert _ok(put(b, {"base_rate": 40, "rate_window_seconds": 60}))["base_rate"] == 40
    # Replacing one's own allocation is not double counted...
    assert _ok(put(a, {"base_rate": 60, "rate_window_seconds": 60}))["base_rate"] == 60
    # ...but raising it past the constraint is refused and changes nothing.
    _code(put(a, {"base_rate": 61, "rate_window_seconds": 60}), 409, "ALLOCATION_INFEASIBLE")
    assert (
        _ok(world.client.get(_allocation_url(a, pool_id), headers=world.system))["base_rate"] == 60
    )
    # Loans never count against base feasibility, but the base still does.
    loaned = {"base_rate": 1, "rate_window_seconds": 60, "borrow_enabled": True, "max_rate": 500}
    _code(put(b, loaned, "fetch"), 409, "ALLOCATION_INFEASIBLE")

    # Tightening the pool below the promised total is refused.
    tighten = world.client.patch(
        f"{_POOLS}/{pool_id}",
        headers=world.system,
        json={"constraints": [{"algorithm": "fixed_window", "window_seconds": 60, "limit": 99}]},
    )
    _code(tighten, 409, "ALLOCATION_INFEASIBLE")
    pool = _ok(world.client.get(f"{_POOLS}/{pool_id}", headers=world.system))
    assert pool["constraints"][0]["limit"] == 100

    # A credential links only to a pool of its own provider type.
    exa = _system_credential(world, "exa", "exa-shared")
    mismatch = world.client.put(
        f"{_POOLS}/{pool_id}/links/{exa}?operation_scope=search", headers=world.system
    )
    _code(mismatch, 422, "PROVIDER_TYPE_MISMATCH")
    assert _ok(world.client.get(f"{_POOLS}/{pool_id}/links", headers=world.system)) == []


# ---------------------------------------------------------------------------
# AC4: available versus enabled; new grants/bindings start disabled
# ---------------------------------------------------------------------------


def test_ac4_available_is_not_enabled_and_enablement_is_bounded(world: _World) -> None:
    pid = world.project_a.id
    shared = _system_credential(world, "tavily", "shared")
    _grant(world, shared, pid, ["search"])

    tavily = _provider(_providers(world, world.a, pid), "tavily")
    assert tavily["available"] is True
    assert tavily["enabled"] is False
    assert tavily["effective_operations"] == []
    assert tavily["bindings"] == []
    (credential,) = tavily["credentials"]
    assert credential["id"] == shared
    assert credential["granted_operations"] == ["search"]

    with_ops = world.client.post(
        _bindings_url(pid),
        headers=world.a,
        json={"credential_id": shared, "route_label": "main", "enabled_operations": ["search"]},
    )
    assert with_ops.status_code == 422
    binding = _ok(
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": shared, "route_label": "m"}
        ),
        201,
    )
    assert binding["enabled_operations"] == []
    assert _provider(_providers(world, world.a, pid), "tavily")["enabled"] is False
    _code(
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": shared, "route_label": "m"}
        ),
        409,
        "BINDING_ROUTE_CONFLICT",
    )

    # Outside the grant (fetch) is refused; inside it is effective.
    _code(
        world.client.patch(
            _bindings_url(pid, binding["id"]),
            headers=world.a,
            json={"enabled_operations": ["search", "fetch"]},
        ),
        422,
        "OPERATION_NOT_PERMITTED",
    )
    _ok(
        world.client.patch(
            _bindings_url(pid, binding["id"]),
            headers=world.a,
            json={"enabled_operations": ["search"]},
        )
    )
    tavily = _provider(_providers(world, world.a, pid), "tavily")
    assert tavily["enabled"] is True
    assert tavily["effective_operations"] == ["search"]

    # The system kill switch zeroes effective operations without editing bindings.
    world.run(
        persist_provider_config(
            world.repository, ProviderName.TAVILY, ProviderConfig(enable_mask=0)
        )
    )
    killed = _provider(_providers(world, world.a, pid), "tavily")
    assert killed["kill_switch"] is True
    assert killed["effective_operations"] == []
    assert killed["enabled"] is False
    assert killed["bindings"][0]["enabled_operations"] == ["search"]
    assert killed["bindings"][0]["effective_operations"] == []
    world.run(persist_provider_config(world.repository, ProviderName.TAVILY, ProviderConfig()))
    assert _provider(_providers(world, world.a, pid), "tavily")["effective_operations"] == [
        "search"
    ]

    # Capability: Brave cannot fetch, even on a private credential.
    brave = _private_credential(world, world.a, pid, "brave", "brave-own")
    brave_binding = _ok(
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": brave, "route_label": "b"}
        ),
        201,
    )["id"]
    _code(
        world.client.patch(
            _bindings_url(pid, brave_binding),
            headers=world.a,
            json={"enabled_operations": ["fetch"]},
        ),
        422,
        "OPERATION_NOT_PERMITTED",
    )
    # An OAuth credential serves no search or fetch.
    oauth = _system_credential(world, "parallel", "parallel-oauth", auth_mode="oauth")
    _grant(world, oauth, pid, ["search"])
    oauth_binding = _ok(
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": oauth, "route_label": "o"}
        ),
        201,
    )["id"]
    _code(
        world.client.patch(
            _bindings_url(pid, oauth_binding),
            headers=world.a,
            json={"enabled_operations": ["search"]},
        ),
        422,
        "OPERATION_NOT_PERMITTED",
    )


def test_ac4_unavailable_credentials_are_indistinguishable(world: _World) -> None:
    pid = world.project_a.id
    b_private = _private_credential(world, world.b, world.project_b.id, "exa", "b-only")
    ungranted = _system_credential(world, "tavily", "not-granted")
    responses = [
        world.client.post(
            _bindings_url(pid), headers=world.a, json={"credential_id": cid, "route_label": "x"}
        )
        for cid in (b_private, ungranted, str(uuid4()))
    ]
    for response in responses:
        _code(response, 422, "CREDENTIAL_NOT_AVAILABLE")
    assert len({response.text for response in responses}) == 1
    assert _ok(world.client.get(_bindings_url(pid), headers=world.a)) == []


def test_ac4_grant_narrowing_and_revocation_cascade_to_bindings(world: _World) -> None:
    a, b = world.project_a.id, world.project_b.id
    shared = _system_credential(world, "tavily", "cascade")
    _grant(world, shared, a, ["search", "fetch"])
    _grant(world, shared, b, ["search", "fetch"])
    bindings: dict[UUID, str] = {}
    for project, headers in ((a, world.a), (b, world.b)):
        bindings[project] = _ok(
            world.client.post(
                _bindings_url(project),
                headers=headers,
                json={"credential_id": shared, "route_label": "c"},
            ),
            201,
        )["id"]
        _ok(
            world.client.patch(
                _bindings_url(project, bindings[project]),
                headers=headers,
                json={"enabled_operations": ["search", "fetch"]},
            )
        )

    _grant(world, shared, a, ["search"])
    (narrowed,) = _ok(world.client.get(_bindings_url(a), headers=world.a))
    assert narrowed["enabled_operations"] == ["search"]
    assert _provider(_providers(world, world.a, a), "tavily")["effective_operations"] == ["search"]
    (untouched,) = _ok(world.client.get(_bindings_url(b), headers=world.b))
    assert sorted(untouched["enabled_operations"]) == ["fetch", "search"]

    _ok(world.client.delete(f"{_SYSTEM_CREDS}/{shared}/grants/{a}", headers=world.system), 204)
    assert _ok(world.client.get(_bindings_url(a), headers=world.a)) == []
    tavily_a = _provider(_providers(world, world.a, a), "tavily")
    assert tavily_a["available"] is False
    assert tavily_a["bindings"] == []
    assert (
        world.client.patch(
            _bindings_url(a, bindings[a]), headers=world.a, json={"enabled_operations": ["search"]}
        ).status_code
        == 404
    )
    (still_b,) = _ok(world.client.get(_bindings_url(b), headers=world.b))
    assert still_b["id"] == bindings[b]
    assert sorted(still_b["enabled_operations"]) == ["fetch", "search"]


# ---------------------------------------------------------------------------
# AC5: provider view shows ownership, never secrets or other projects
# ---------------------------------------------------------------------------

_VIEW_KEYS = {"project_id", "providers", "allocations"}
_PROVIDER_KEYS = {
    "provider_type",
    "capability",
    "kill_switch",
    "system_enabled_operations",
    "available",
    "enabled",
    "credentials",
    "bindings",
    "effective_operations",
}
_CREDENTIAL_KEYS = {
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
_POOL_KEYS = {"operation_scope", "pool_id", "label", "upstream_scope", "status", "owner_scope"}
_BINDING_KEYS = {
    "id",
    "credential_id",
    "route_label",
    "priority",
    "enabled_operations",
    "effective_operations",
}


def test_ac5_provider_view_hides_secrets_other_projects_usage_and_balances(
    world: _World,
) -> None:
    a, b = world.project_a.id, world.project_b.id
    shared_secret = f"fake-view-shared-{uuid4().hex}"
    shared = _system_credential(world, "tavily", "shared-label", secret=shared_secret)
    _grant(world, shared, a, ["search"])
    _grant(world, shared, b, ["search", "fetch"])
    pool_id = _pool(world)
    _ok(
        world.client.put(
            f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", headers=world.system
        )
    )
    a_alloc = {"base_rate": 11, "rate_window_seconds": 60}
    b_alloc = {"base_rate": 37, "rate_window_seconds": 60}
    _ok(world.client.put(_allocation_url(a, pool_id), headers=world.system, json=a_alloc))
    _ok(world.client.put(_allocation_url(b, pool_id), headers=world.system, json=b_alloc))
    b_binding = _ok(
        world.client.post(
            _bindings_url(b), headers=world.b, json={"credential_id": shared, "route_label": "bb"}
        ),
        201,
    )["id"]
    b_private = _private_credential(world, world.b, b, "exa", "b-secret-label")
    a_binding = _ok(
        world.client.post(
            _bindings_url(a), headers=world.a, json={"credential_id": shared, "route_label": "aa"}
        ),
        201,
    )["id"]
    health_message = f"vendor said HEALTH-MESSAGE-{uuid4().hex}"
    usage_units = "12345.678"

    async def _seed() -> None:
        async with world.repository.session() as session:
            session.add(
                ProviderHealthRow(
                    provider="tavily",
                    status="degraded",
                    checked_at=datetime.now(UTC).isoformat(),
                    message=health_message,
                    credential_id=shared,
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
            credential_id=UUID(shared),
        )

    world.run(_seed())

    response = world.client.get(f"/api/v1/projects/{a}/providers", headers=world.a)
    view = _ok(response)
    text = response.text
    assert set(view) == _VIEW_KEYS
    assert view["project_id"] == str(a)
    for provider in view["providers"]:
        assert set(provider) == _PROVIDER_KEYS
        for credential in provider["credentials"]:
            assert set(credential) == _CREDENTIAL_KEYS
            for pool in credential["pools"]:
                assert set(pool) == _POOL_KEYS
                assert pool["owner_scope"] == "system"
        for binding in provider["bindings"]:
            assert set(binding) == _BINDING_KEYS
    assert "shared" not in _all_keys(view)

    tavily = _provider(view, "tavily")
    (credential,) = tavily["credentials"]
    assert credential["label"] == "shared-label"
    assert credential["owner_scope"] == "system"
    assert credential["health_status"] == "degraded"
    assert credential["granted_operations"] == ["search"]
    assert [(p["pool_id"], p["label"]) for p in credential["pools"]] == [
        (pool_id, "tavily shared pool")
    ]
    assert [binding["id"] for binding in tavily["bindings"]] == [a_binding]
    assert [(item["project_id"], item["base_rate"]) for item in view["allocations"]] == [
        (str(a), 11)
    ]
    exa = _provider(view, "exa")
    assert exa["credentials"] == [] and exa["available"] is False

    for forbidden in (
        shared_secret,
        "secret.enc",
        f"credential.{shared}",
        health_message,
        usage_units,
        b_binding,
        b_private,
        "b-secret-label",
        str(b),
    ):
        assert forbidden not in text, forbidden
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


# ---------------------------------------------------------------------------
# AC2 over HTTP: OAuth routes expose only public fields
# ---------------------------------------------------------------------------


def test_ac2_oauth_routes_return_only_public_fields(world: _World) -> None:
    pid = world.project_a.id
    created = world.client.post(
        _SYSTEM_CREDS,
        headers=world.system,
        json={"provider_type": "parallel", "label": "sys-oauth", "auth_mode": "oauth"},
    )
    system_oauth = _ok(created, 201)["id"]
    with_secret = world.client.post(
        _SYSTEM_CREDS,
        headers=world.system,
        json={
            "provider_type": "parallel",
            "label": "bad",
            "auth_mode": "oauth",
            "secret": "fake-forbidden",
        },
    )
    assert with_secret.status_code == 422
    prefix = f"{_SYSTEM_CREDS}/{system_oauth}/oauth"
    texts: list[str] = [created.text]

    status = _ok(world.client.get(prefix, headers=world.system))
    assert status["status"] == "disconnected"
    device = world.client.post(f"{prefix}/device", headers=world.system)
    assert set(_ok(device, 201)) == {"user_code", "verification_uri", "interval", "expires_in"}
    texts.append(device.text)
    pending = world.client.post(f"{prefix}/poll", headers=world.system)
    assert _ok(pending)["status"] == "pending"
    texts.append(pending.text)
    world.vendor.approve_all()
    connected = world.client.post(f"{prefix}/poll", headers=world.system)
    assert _ok(connected)["status"] == "connected"
    texts.append(connected.text)
    again = world.client.post(f"{prefix}/device", headers=world.system)
    _code(again, 409, "OAUTH_ALREADY_CONNECTED")
    read = world.client.get(prefix, headers=world.system)
    texts.append(read.text)
    assert _ok(read)["status"] == "connected"
    assert _ok(world.client.delete(prefix, headers=world.system), 204) is None
    assert _ok(world.client.delete(prefix, headers=world.system), 204) is None
    assert _ok(world.client.get(prefix, headers=world.system))["status"] == "disconnected"

    # A non-OAuth credential and the project surface of a granted system credential.
    api_key_cred = _system_credential(world, "tavily", "api-key")
    _code(
        world.client.post(f"{_SYSTEM_CREDS}/{api_key_cred}/oauth/device", headers=world.system),
        422,
        "CREDENTIAL_NOT_OAUTH",
    )
    _grant(world, system_oauth, pid, ["search"])
    # Ruling: every project-route operation on a system credential granted to
    # that project is 403 with an empty body (status read included, for an
    # admin and for a reader); an ungranted or unknown one stays 404.
    ungranted_oauth = _ok(
        world.client.post(
            _SYSTEM_CREDS,
            headers=world.system,
            json={"provider_type": "parallel", "label": "ungranted-oauth", "auth_mode": "oauth"},
        ),
        201,
    )["id"]
    issued_before = list(world.vendor.issued)

    def _operations(credential_id: object) -> list[tuple[str, str]]:
        base = f"/api/v1/projects/{pid}/credentials/{credential_id}/oauth"
        return [
            ("GET", base),
            ("POST", f"{base}/device"),
            ("POST", f"{base}/poll"),
            ("DELETE", base),
        ]

    for headers in (world.a, world.a_member_h):
        for method, url in _operations(system_oauth):
            response = world.client.request(method, url, headers=headers)
            assert response.status_code == 403, (method, url, response.text)
            assert response.content == b"", (method, url)
    for credential_id in (ungranted_oauth, uuid4()):
        for method, url in _operations(credential_id):
            response = world.client.request(method, url, headers=world.a)
            assert response.status_code == 404, (method, url, response.text)
            assert response.content == b"", (method, url)
    assert world.vendor.issued == issued_before
    # The system credential's own connection was never touched from the project.
    assert _ok(world.client.get(prefix, headers=world.system))["status"] == "disconnected"

    # A project's private OAuth credential is invisible to another project's admin.
    private = _ok(
        world.client.post(
            f"/api/v1/projects/{pid}/credentials",
            headers=world.a,
            json={"provider_type": "parallel", "label": "prv-oauth", "auth_mode": "oauth"},
        ),
        201,
    )["id"]
    other = f"/api/v1/projects/{world.project_b.id}/credentials/{private}/oauth"
    assert world.client.post(f"{other}/device", headers=world.b).status_code == 404
    started = world.client.post(
        f"/api/v1/projects/{pid}/credentials/{private}/oauth/device", headers=world.a
    )
    assert set(_ok(started, 201)) == {"user_code", "verification_uri", "interval", "expires_in"}
    texts.append(started.text)

    dump = database_dump(world.repository)
    for value in world.vendor.issued:
        assert value not in dump
        for text in texts:
            assert value not in text


# ---------------------------------------------------------------------------
# Audit scope and rollback
# ---------------------------------------------------------------------------


def test_audit_rows_land_in_the_right_scope_for_each_mutation_family(world: _World) -> None:
    a = world.project_a.id
    shared = _system_credential(world, "tavily", "audited")
    _grant(world, shared, a, ["search"])
    private = _private_credential(world, world.a, a, "exa", "audited-private")
    pool_id = _pool(world)
    _ok(world.client.patch(f"{_POOLS}/{pool_id}", headers=world.system, json={"label": "renamed"}))
    _ok(
        world.client.put(
            f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", headers=world.system
        )
    )
    _ok(
        world.client.put(
            _allocation_url(a, pool_id),
            headers=world.system,
            json={"base_rate": 5, "rate_window_seconds": 60},
        )
    )
    binding = _ok(
        world.client.post(
            _bindings_url(a), headers=world.a, json={"credential_id": shared, "route_label": "x"}
        ),
        201,
    )["id"]
    _ok(
        world.client.patch(
            _bindings_url(a, binding), headers=world.a, json={"enabled_operations": ["search"]}
        )
    )
    _ok(world.client.delete(_bindings_url(a, binding), headers=world.a), 204)
    _ok(world.client.delete(_allocation_url(a, pool_id), headers=world.system), 204)
    _ok(
        world.client.delete(
            f"{_POOLS}/{pool_id}/links/{shared}?operation_scope=search", headers=world.system
        ),
        204,
    )
    # Failed mutations write nothing.
    failed = [
        world.client.post(
            _bindings_url(a),
            headers=world.a,
            json={"credential_id": str(uuid4()), "route_label": "z"},
        ),
        world.client.put(
            _allocation_url(a, pool_id),
            headers=world.system,
            json={"base_rate": 1000, "rate_window_seconds": 60},
        ),
    ]
    assert [response.status_code for response in failed] == [422, 409]

    system_rows = world.run(audit_rows(world.repository, scope="system"))
    project_rows = world.run(audit_rows(world.repository, scope="project"))
    system_actions = [row["action"] for row in system_rows]
    project_actions = [(row["action"], str(row["project_id"])) for row in project_rows]
    for action in (
        "credential.created",
        "credential_grant.put",
        "pool.created",
        "pool.updated",
        "pool_link.put",
        "pool_link.deleted",
        "allocation.put",
        "allocation.deleted",
    ):
        assert action in system_actions, action
    for action in (
        "binding.created",
        "binding.updated",
        "binding.deleted",
        "credential.created",
        "allocation.put",
        "allocation.deleted",
        "credential_grant.put",
    ):
        assert (action, str(a)) in project_actions, action
    assert not any(action.startswith("binding.") for action in system_actions)
    assert not any(action.startswith(("pool.", "pool_link.")) for action, _ in project_actions)
    assert system_actions.count("allocation.put") == 1
    assert [action for action, _ in project_actions].count("binding.created") == 1
    private_rows = [row for row in project_rows if row["target_id"] == private]
    assert [row["action"] for row in private_rows] == ["credential.created"]
    assert private not in {row["target_id"] for row in system_rows}
    for row in [*system_rows, *project_rows]:
        assert "fake-ctl" not in repr(row)


def test_ac4_credential_delete_and_project_archive_constrain_bindings(world: _World) -> None:
    a, b = world.project_a.id, world.project_b.id
    shared = _system_credential(world, "tavily", "to-delete")
    for project, headers in ((a, world.a), (b, world.b)):
        _grant(world, shared, project, ["search"])
        _ok(
            world.client.post(
                _bindings_url(project),
                headers=headers,
                json={"credential_id": shared, "route_label": "d"},
            ),
            201,
        )
    private = _private_credential(world, world.a, a, "exa", "own-to-delete")
    _ok(
        world.client.post(
            _bindings_url(a), headers=world.a, json={"credential_id": private, "route_label": "p"}
        ),
        201,
    )

    _ok(world.client.delete(f"{_SYSTEM_CREDS}/{shared}", headers=world.system), 204)
    _ok(world.client.delete(f"/api/v1/projects/{a}/credentials/{private}", headers=world.a), 204)
    assert _ok(world.client.get(_bindings_url(a), headers=world.a)) == []
    assert _ok(world.client.get(_bindings_url(b), headers=world.b)) == []
    assert _provider(_providers(world, world.b, b), "tavily")["available"] is False

    # An archived project's providers and allocations are frozen.
    pool_id = _pool(world)
    other = _private_credential(world, world.b, b, "tavily", "b-own")
    world.run(ProjectService(world.repository).archive_project(world.b_admin, b))
    _code(
        world.client.post(
            _bindings_url(b), headers=world.b, json={"credential_id": other, "route_label": "x"}
        ),
        409,
        "PROJECT_ARCHIVED",
    )
    _code(
        world.client.put(
            _allocation_url(b, pool_id),
            headers=world.system,
            json={"base_rate": 1, "rate_window_seconds": 60},
        ),
        409,
        "PROJECT_ARCHIVED",
    )
