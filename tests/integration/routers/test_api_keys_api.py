"""Project API key HTTP surface and REST key execution (A1, TASK-000041).

Real FastAPI app, temporary SQLite, counting fake provider, real JWTs and real
issued keys. Covers the one-time key response, omitted/null/past expiry on the
wire, rotation and revocation status codes, cross-project ids, the exclusion
of keys from every human/control route the app registers, and the REST
execution matrix where every rejected key path reaches no provider.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.api_keys import (
    archive_project,
    audit_rows,
    database_dump,
    expire_key,
    key_for_account,
)
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import add_execution_member, seed_execution_project

_KEY_SHAPE = re.compile(r"^fs_live_[a-z2-7]{12}_[A-Za-z0-9_-]{43}$")
_GENERIC_401 = {"detail": "not authenticated"}


class _CountingAdapter(ProviderAdapter):
    def __init__(self) -> None:
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def name(self) -> str:
        return "counting"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[SearchResult(title="t", url="https://example.com/r", snippet="s")],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(url=request.url, content="c", fetched_at=datetime.now(UTC)),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


class _World:
    def __init__(
        self, client: TestClient, repository: SQLiteRepository, adapter: _CountingAdapter
    ) -> None:
        self.client = client
        self.repository = repository
        self.adapter = adapter
        self.loop_run: Any = None

    def human(self, prefix: str) -> tuple[dict[str, str], UUID]:
        pair = register_and_login(self.client, temp_email(prefix))
        return raw_auth_headers(pair["access_token"]), account_id_from_pair(pair)


@pytest.fixture
def world(tmp_path: Path, auth_secret: str) -> Iterator[_World]:
    import asyncio

    loop = asyncio.new_event_loop()
    repository = loop.run_until_complete(SQLiteRepository.open(tmp_path / "keys-api.db"))
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    try:
        with TestClient(app) as client:
            state = _World(client, repository, adapter)
            state.loop_run = loop.run_until_complete
            yield state
    finally:
        loop.run_until_complete(repository.close())
        loop.close()


def _admin_project(world: _World, prefix: str = "keys-admin") -> tuple[dict[str, str], UUID, UUID]:
    headers, user_id = world.human(prefix)
    project = world.loop_run(seed_execution_project(world.repository, user_id=user_id))
    return headers, user_id, project.project_id


def _issue(world: _World, headers: dict[str, str], pid: UUID, **body: Any) -> dict[str, Any]:
    response = world.client.post(
        f"/api/v1/projects/{pid}/api-keys", json={"label": "k", **body}, headers=headers
    )
    assert response.status_code == 201, response.status_code
    return response.json()


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


# --- lifecycle over HTTP ---------------------------------------------------------


def test_key_appears_only_in_issue_and_rotate_responses(world: _World) -> None:
    headers, _user, pid = _admin_project(world)
    issued = world.client.post(
        f"/api/v1/projects/{pid}/api-keys", json={"label": "ci"}, headers=headers
    )
    assert issued.status_code == 201
    assert issued.headers["cache-control"] == "no-store"
    body = issued.json()
    raw = body["key"]
    assert _KEY_SHAPE.match(raw)
    assert raw.startswith(f"fs_live_{body['prefix']}_")
    assert body["status"] == "active"
    assert body["scopes"] == ["fetch.execute", "search.execute"]

    listed = world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=headers)
    assert listed.status_code == 200
    assert raw not in listed.text
    assert raw[len("fs_live_") + 13 :] not in listed.text
    assert all("key" not in item for item in listed.json())

    rotated = world.client.post(
        f"/api/v1/projects/{pid}/api-keys/{body['id']}/rotate", headers=headers
    )
    assert rotated.status_code == 201
    assert rotated.headers["cache-control"] == "no-store"
    new_raw = rotated.json()["key"]
    assert new_raw != raw
    assert rotated.json()["rotated_from_id"] == body["id"]

    relisted = world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=headers)
    assert len(relisted.json()) == 2
    for value in (raw, new_raw):
        assert value not in relisted.text
        assert value not in database_dump(world.repository)


def test_wire_expiry_semantics_and_validation(world: _World) -> None:
    headers, _user, pid = _admin_project(world)
    before = datetime.now(UTC)
    omitted = _issue(world, headers, pid)
    expires = datetime.fromisoformat(omitted["expires_at"])
    assert before + timedelta(days=90) - timedelta(minutes=1) <= expires
    assert expires <= datetime.now(UTC) + timedelta(days=90)

    explicit_null = _issue(world, headers, pid, expires_at=None)
    assert explicit_null["expires_at"] is None

    future = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
    dated = _issue(world, headers, pid, expires_at=future.isoformat())
    assert datetime.fromisoformat(dated["expires_at"]) == future

    for bad in (
        {"expires_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat()},
        {"expires_at": "2099-01-01T00:00:00"},
        {"scopes": []},
        {"scopes": ["tokens.manage"]},
        {"scopes": ["search.execute", "members.manage"]},
        {"label": ""},
        {"label": "x" * 101},
        {"project_id": str(uuid4())},
        {"key": "fs_live_aaaaaaaaaaaa_" + "a" * 43},
    ):
        rejected = world.client.post(
            f"/api/v1/projects/{pid}/api-keys", json={"label": "k", **bad}, headers=headers
        )
        assert rejected.status_code == 422, bad
        for issued in (omitted, explicit_null, dated):
            assert issued["key"] not in rejected.text
    assert len(world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=headers).json()) == 3


def test_rotation_status_codes_and_overlap_bounds(world: _World) -> None:
    headers, _user, pid = _admin_project(world)
    key = _issue(world, headers, pid)
    base = f"/api/v1/projects/{pid}/api-keys/{key['id']}"

    for overlap in (-1, 604_801):
        assert (
            world.client.post(
                f"{base}/rotate", json={"overlap_seconds": overlap}, headers=headers
            ).status_code
            == 422
        )
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert (
        world.client.post(f"{base}/rotate", json={"expires_at": past}, headers=headers).status_code
        == 422
    )

    first = world.client.post(f"{base}/rotate", json={"overlap_seconds": 0}, headers=headers)
    assert first.status_code == 201
    again = world.client.post(f"{base}/rotate", headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "API_KEY_INACTIVE"
    assert "fs_live_" not in again.text

    successor = first.json()["id"]
    assert (
        world.client.delete(
            f"/api/v1/projects/{pid}/api-keys/{successor}", headers=headers
        ).status_code
        == 204
    )
    assert (
        world.client.delete(
            f"/api/v1/projects/{pid}/api-keys/{successor}", headers=headers
        ).status_code
        == 204
    )
    revoked_rotate = world.client.post(
        f"/api/v1/projects/{pid}/api-keys/{successor}/rotate", headers=headers
    )
    assert revoked_rotate.status_code == 409
    assert (
        len(world.loop_run(audit_rows(world.repository, scope="project", action="api_key.revoked")))
        == 1
    )


def test_cross_project_and_unknown_ids_are_404_and_non_admins_403(world: _World) -> None:
    headers_a, _a, pid_a = _admin_project(world, "keys-a")
    headers_b, _b, pid_b = _admin_project(world, "keys-b")
    key_b = _issue(world, headers_b, pid_b)

    for method, path in (
        ("post", f"/api/v1/projects/{pid_a}/api-keys/{key_b['id']}/rotate"),
        ("delete", f"/api/v1/projects/{pid_a}/api-keys/{key_b['id']}"),
        ("post", f"/api/v1/projects/{pid_a}/api-keys/{uuid4()}/rotate"),
        ("delete", f"/api/v1/projects/{pid_a}/api-keys/{uuid4()}"),
        ("get", f"/api/v1/projects/{uuid4()}/api-keys"),
        ("post", f"/api/v1/projects/{uuid4()}/api-keys"),
    ):
        kwargs: dict[str, Any] = {"headers": headers_a}
        if path.endswith("api-keys") and method == "post":
            kwargs["json"] = {"label": "x"}
        response = getattr(world.client, method)(path, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code)

    # A's admin is not a member of B: B's keys are not listable or revocable.
    for response in (
        world.client.get(f"/api/v1/projects/{pid_b}/api-keys", headers=headers_a),
        world.client.delete(f"/api/v1/projects/{pid_b}/api-keys/{key_b['id']}", headers=headers_a),
        world.client.post(
            f"/api/v1/projects/{pid_b}/api-keys", json={"label": "x"}, headers=headers_a
        ),
    ):
        assert response.status_code in {403, 404}
        assert "fs_live_" not in response.text

    # B's key survived every attempt.
    ok = world.client.post("/search", json={"query": "still"}, headers=_bearer(key_b["key"]))
    assert ok.status_code == 200


def test_a_valid_key_is_rejected_by_every_non_execution_route(world: _World) -> None:
    headers, user_id, pid = _admin_project(world)
    key = _issue(world, headers, pid)
    key_id = key["id"]
    substitutions = {
        "project_id": str(pid),
        "key_id": key_id,
        "user_id": str(user_id),
        "credential_id": str(uuid4()),
        "provider_id": "counting",
        "trace_id": "0" * 32,
        "auth_mode": "keyed",
        "operation": "search",
        "role_key": "project_member",
    }
    checked = 0
    for route in world.client.app.routes:  # type: ignore[attr-defined]
        if not isinstance(route, APIRoute):
            continue
        if route.path in {"/search", "/fetch", "/auth/register", "/auth/jwt/login"}:
            continue
        path = route.path
        for name, value in substitutions.items():
            path = path.replace("{" + name + "}", value)
        assert "{" not in path, route.path
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            response = world.client.request(method, path, headers=_bearer(key["key"]), json={})
            assert response.status_code == 401, (method, route.path, response.status_code)
            assert response.json() == _GENERIC_401
            checked += 1
    assert checked >= 40

    # Nothing the key attempted changed anything: still one key, still live.
    listed = world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=headers).json()
    assert [(item["id"], item["status"]) for item in listed] == [(key_id, "active")]
    assert world.adapter.search_calls == 0
    ok = world.client.post("/search", json={"query": "still"}, headers=_bearer(key["key"]))
    assert ok.status_code == 200


# --- REST execution with keys ----------------------------------------------------


def test_rest_key_execution_matrix_reaches_no_provider_when_rejected(
    world: _World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="freesearch")
    headers, user_id, pid = _admin_project(world)
    other_headers, _other, other_pid = _admin_project(world, "keys-other")
    full = world.loop_run(key_for_account(world.repository, user_id, pid))
    search_only = world.loop_run(
        key_for_account(world.repository, user_id, pid, scopes={"search.execute"})
    )
    revoked = world.loop_run(key_for_account(world.repository, user_id, pid))
    expired = world.loop_run(key_for_account(world.repository, user_id, pid))
    world.client.delete(f"/api/v1/projects/{pid}/api-keys/{revoked.api_key_id}", headers=headers)
    world.loop_run(expire_key(world.repository, expired))
    tampered = full.raw[:-1] + ("A" if full.raw[-1] != "A" else "B")
    unknown = "fs_live_" + "q" * 12 + "_" + full.raw[len("fs_live_") + 13 :]

    search = {"query": "matrix"}
    fetch = {"url": "https://example.com/matrix"}

    # Successes: omitted project_id and the key's own project_id.
    assert world.client.post("/search", json=search, headers=full.headers()).status_code == 200
    assert (
        world.client.post(
            "/fetch", json={**fetch, "project_id": str(pid)}, headers=full.headers()
        ).status_code
        == 200
    )
    assert (world.adapter.search_calls, world.adapter.fetch_calls) == (1, 1)

    unauthenticated: list[dict[str, str]] = [
        {},
        revoked.headers(),
        expired.headers(),
        _bearer(tampered),
        _bearer(unknown),
        _bearer("fs_live_"),
        _bearer("fs_live_" + "a" * 12 + "_" + "!" * 43),
        {"Authorization": f"Token {full.raw}"},
        {"Authorization": f"Bearer {full.raw}", "X-Forwarded-Authorization": "x"},
    ]
    for candidate in unauthenticated[:-1]:
        for path, body in (("/search", search), ("/fetch", fetch)):
            response = world.client.post(path, json=body, headers=candidate)
            assert response.status_code == 401, (path, response.status_code)
            assert response.json() == _GENERIC_401
            assert response.headers["www-authenticate"] == "Bearer"

    wrong_project = world.client.post(
        "/search", json={**search, "project_id": str(other_pid)}, headers=full.headers()
    )
    assert wrong_project.status_code == 404
    assert wrong_project.json() == {"detail": "project is unavailable"}
    ghost = world.client.post(
        "/search", json={**search, "project_id": str(uuid4())}, headers=full.headers()
    )
    assert ghost.status_code == 404
    wrong_scope = world.client.post("/fetch", json=fetch, headers=search_only.headers())
    assert wrong_scope.status_code == 403
    assert wrong_scope.json() == {"detail": "execution is not permitted"}

    world.loop_run(archive_project(world.repository, pid))
    archived = world.client.post("/search", json=search, headers=full.headers())
    assert archived.status_code == 409
    assert archived.json() == {"detail": "project is archived"}

    assert (world.adapter.search_calls, world.adapter.fetch_calls) == (1, 1)
    for raw in (full.raw, tampered, search_only.raw, revoked.raw, expired.raw):
        assert raw not in caplog.text
        assert raw not in database_dump(world.repository)

    # R3: denial events are written by the app loop's background writer, at
    # most one per (key, reason) per window. Poll until it settles.
    import time as _time

    expected = sorted(
        [
            ("api_key.authentication_denied", "expired"),
            ("api_key.authentication_denied", "invalid_secret"),
            ("api_key.authentication_denied", "revoked"),
            ("api_key.authorization_denied", "project_archived"),
            ("api_key.authorization_denied", "wrong_project"),
            ("api_key.authorization_denied", "wrong_scope"),
        ]
    )
    deadline = _time.monotonic() + 10
    reasons: list[tuple[str, str]] = []
    while _time.monotonic() < deadline:
        reasons = sorted(
            (row["action"], row["detail_json"]["reason"])
            for row in world.loop_run(audit_rows(world.repository, scope="system"))
            if row["action"].startswith("api_key.")
        )
        if len(reasons) >= len(expected):
            break
        _time.sleep(0.05)
    _time.sleep(0.2)
    reasons = sorted(
        (row["action"], row["detail_json"]["reason"])
        for row in world.loop_run(audit_rows(world.repository, scope="system"))
        if row["action"].startswith("api_key.")
    )
    # Each (key, reason) once although every failure hit /search and /fetch;
    # the unknown prefix and malformed keys write nothing.
    assert reasons == expected
    del other_headers


def test_key_execution_is_attributed_to_the_key_not_its_creator(world: _World) -> None:
    import sqlite3

    _headers, user_id, pid = _admin_project(world)
    key = world.loop_run(key_for_account(world.repository, user_id, pid))
    assert (
        world.client.post("/search", json={"query": "who"}, headers=key.headers()).status_code
        == 200
    )

    con = sqlite3.connect(world.repository.database_path)
    try:
        rows = con.execute("SELECT project_id, actor_type, actor_id FROM usage_events").fetchall()
    finally:
        con.close()
    assert rows == [(str(pid), "project_api_key", str(key.api_key_id))]


def test_human_session_executes_by_membership_without_any_key(world: _World) -> None:
    owner_headers, owner_id, pid = _admin_project(world)
    member_headers, member_id = world.human("keys-member")
    outsider_headers, _outsider = world.human("keys-outsider")
    world.loop_run(
        add_execution_member(
            world.repository, project_id=pid, user_id=member_id, granted_by=owner_id
        )
    )

    for headers in (owner_headers, member_headers):
        ok = world.client.post(
            "/search", json={"query": "browser", "project_id": str(pid)}, headers=headers
        )
        assert ok.status_code == 200
    assert world.adapter.search_calls == 2

    missing = world.client.post("/search", json={"query": "browser"}, headers=member_headers)
    assert missing.status_code == 422
    assert missing.json() == {"detail": "project_id is required"}
    outsider = world.client.post(
        "/search", json={"query": "browser", "project_id": str(pid)}, headers=outsider_headers
    )
    assert outsider.status_code == 404
    assert world.adapter.search_calls == 2
    # No key exists or was needed.
    assert world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=owner_headers).json() == []


def test_token_manager_without_search_cannot_issue_a_search_key_over_http(world: _World) -> None:
    """R1 over HTTP: 403, no key row, no audit row."""

    from freesearch.models.projects import BuiltinRole

    owner_headers, owner_id, pid = _admin_project(world, "r1-owner")
    manager_headers, manager_id = world.human("r1-manager")
    world.loop_run(
        add_execution_member(
            world.repository,
            project_id=pid,
            user_id=manager_id,
            role_key=BuiltinRole.TOKEN_MANAGER,
            granted_by=owner_id,
        )
    )

    denied = world.client.post(
        f"/api/v1/projects/{pid}/api-keys",
        json={"label": "escalate", "scopes": ["search.execute"]},
        headers=manager_headers,
    )
    assert denied.status_code == 403
    assert "fs_live_" not in denied.text
    assert world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=owner_headers).json() == []
    assert (
        world.loop_run(audit_rows(world.repository, scope="project", action="api_key.issued")) == []
    )
    # The manager can still list (tokens.manage) but cannot mint execution.
    assert (
        world.client.get(f"/api/v1/projects/{pid}/api-keys", headers=manager_headers).status_code
        == 200
    )


def test_rest_denial_does_not_wait_on_a_slow_security_writer(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 over HTTP: a stalled event writer cannot delay the 401 or the 403."""

    import asyncio
    import time

    import freesearch.services.api_keys as api_keys_module

    async def _slow(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(1.5)

    _headers, user_id, pid = _admin_project(world, "r3-slow")
    full = world.loop_run(key_for_account(world.repository, user_id, pid))
    search_only = world.loop_run(
        key_for_account(world.repository, user_id, pid, scopes={"search.execute"})
    )
    monkeypatch.setattr(api_keys_module, "record_api_key_denial", _slow)
    tampered = full.raw[:-1] + ("A" if full.raw[-1] != "A" else "B")

    started = time.perf_counter()
    unauthenticated = world.client.post("/search", json={"query": "x"}, headers=_bearer(tampered))
    forbidden = world.client.post(
        "/fetch", json={"url": "https://example.com/x"}, headers=search_only.headers()
    )
    elapsed = time.perf_counter() - started

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert elapsed < 1.2, elapsed
    assert (world.adapter.search_calls, world.adapter.fetch_calls) == (0, 0)
