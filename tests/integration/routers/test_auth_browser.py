"""Browser refresh-cookie contract over HTTP with isolated SQLite.

Every test uses a temporary database, stub adapters, and a generated signing
secret with an explicit browser origin allowlist. The suite pins cookie issue,
rotation, logout deletion, origin rules, and the unchanged programmatic JSON
pair contract for non-browser clients.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from polyweb.configuration.config import get_settings
from polyweb.infrastructure.browser_auth import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import TEMP_PASSWORD, raw_auth_headers, temp_email
from tests.integration.routers.test_users_transport import _StubAdapter

_BROWSER_ORIGIN = "http://localhost:5177"
_BROWSER_HEADERS = {"Origin": _BROWSER_ORIGIN, "X-Polyweb-Client": "browser"}


@pytest.fixture
def auth_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Point this test at a generated signing secret, restored on cleanup."""

    import secrets as secrets_module

    secret = secrets_module.token_urlsafe(32)
    monkeypatch.setenv("POLYWEB_AUTH_JWT_SECRET", secret)
    get_settings.cache_clear()
    yield secret
    get_settings.cache_clear()


@pytest.fixture
def browser_origins(monkeypatch: pytest.MonkeyPatch) -> str:
    """Enable cookie transport for one explicit loopback origin."""

    monkeypatch.setenv("POLYWEB_AUTH_BROWSER_ORIGINS", f'["{_BROWSER_ORIGIN}"]')
    get_settings.cache_clear()
    yield _BROWSER_ORIGIN
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def browser_client(tmp_path: Path, auth_secret: str, browser_origins: str) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "auth-browser.db")
    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        yield client
    await repository.close()


@pytest_asyncio.fixture
async def programmatic_client(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    # Empty allowlist keeps the programmatic contract. The worktree .env file
    # may carry origins, and pydantic-settings reads the file when the process
    # env lacks the var, so set an explicit empty value (env wins over .env).
    monkeypatch.setenv("POLYWEB_AUTH_BROWSER_ORIGINS", "")
    get_settings.cache_clear()
    try:
        repository = await SQLiteRepository.open(tmp_path / "auth-programmatic.db")
    except Exception:
        get_settings.cache_clear()
        raise
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            yield client
    finally:
        await repository.close()
        get_settings.cache_clear()


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": TEMP_PASSWORD,
            "username": f"tester-{uuid4().hex[:8]}",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert response.status_code == 201


def _browser_login(client: TestClient, email: str):
    return client.post(
        "/auth/jwt/login",
        data={"username": email, "password": TEMP_PASSWORD},
        headers=_BROWSER_HEADERS,
    )


def _set_cookie(response) -> str:
    raw = response.headers.get("set-cookie", "")
    assert raw != ""
    return raw


def _cookie_value(set_cookie: str) -> str:
    first = set_cookie.split(";", 1)[0]
    name, _, value = first.partition("=")
    assert name == REFRESH_COOKIE_NAME
    return value


def _assert_strict_cookie(set_cookie: str) -> str:
    assert set_cookie.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert f"Path={REFRESH_COOKIE_PATH}" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Domain=" not in set_cookie
    value = _cookie_value(set_cookie)
    assert value != ""
    return value


def _assert_cookie_deletion(set_cookie: str) -> None:
    assert set_cookie.startswith(f"{REFRESH_COOKIE_NAME}=; ")
    assert f"Path={REFRESH_COOKIE_PATH}" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Strict" in set_cookie


def _browser_cookie_headers(token: str, extra: dict[str, str] | None = None):
    headers = dict(_BROWSER_HEADERS)
    headers["Cookie"] = f"{REFRESH_COOKIE_NAME}={token}"
    if extra:
        headers.update(extra)
    return headers


def test_programmatic_login_keeps_json_pair_without_cookie(
    programmatic_client: TestClient,
) -> None:
    email = temp_email("prog")
    _register(programmatic_client, email)

    logged_in = programmatic_client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )

    assert logged_in.status_code == 200
    pair = logged_in.json()
    assert pair["token_type"] == "bearer"
    assert pair["access_token"]
    assert pair["refresh_token"]
    assert pair["expires_in"] == 900
    assert "set-cookie" not in logged_in.headers
    assert logged_in.headers["cache-control"] == "no-store"

    refreshed = programmatic_client.post(
        "/auth/jwt/refresh", headers=raw_auth_headers(pair["refresh_token"])
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"]
    assert "set-cookie" not in refreshed.headers


def test_browser_login_issues_strict_cookie_without_json_refresh(
    browser_client: TestClient,
) -> None:
    email = temp_email("browser")
    _register(browser_client, email)

    logged_in = _browser_login(browser_client, email)

    assert logged_in.status_code == 200
    body = logged_in.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 604800
    assert "refresh_token" not in body
    assert "refresh_token" not in logged_in.text
    assert logged_in.headers["cache-control"] == "no-store"

    value = _assert_strict_cookie(_set_cookie(logged_in))
    assert value not in logged_in.text


def test_browser_refresh_rotates_cookie_and_omits_json_refresh(
    browser_client: TestClient,
) -> None:
    email = temp_email("rotate")
    _register(browser_client, email)
    first_value = _assert_strict_cookie(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()

    rotated = browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(first_value))

    assert rotated.status_code == 200
    body = rotated.json()
    assert body["access_token"]
    assert "refresh_token" not in body
    assert rotated.headers["cache-control"] == "no-store"
    second_value = _assert_strict_cookie(_set_cookie(rotated))
    assert second_value != first_value
    assert second_value not in rotated.text


def test_consumed_cookie_reuse_revokes_successor_family(
    browser_client: TestClient,
) -> None:
    email = temp_email("reuse")
    _register(browser_client, email)
    first_value = _cookie_value(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()
    first_access = _browser_login(browser_client, email).json()["access_token"]
    assert first_access
    browser_client.cookies.clear()

    rotated = browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(first_value))
    assert rotated.status_code == 200
    second_value = _cookie_value(_set_cookie(rotated))
    second_access = rotated.json()["access_token"]
    browser_client.cookies.clear()

    reuse = browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(first_value))
    assert reuse.status_code == 401
    _assert_cookie_deletion(reuse.headers.get("set-cookie", ""))
    assert first_value not in reuse.text

    assert (
        browser_client.post(
            "/auth/jwt/refresh", headers=_browser_cookie_headers(second_value)
        ).status_code
        == 401
    )
    assert (
        browser_client.get("/users/me", headers=raw_auth_headers(second_access)).status_code == 401
    )


def test_invalid_origin_fails_without_family_revocation(
    browser_client: TestClient,
) -> None:
    email = temp_email("csrf")
    _register(browser_client, email)
    first_value = _cookie_value(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()
    rotated = browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(first_value))
    assert rotated.status_code == 200
    live_value = _cookie_value(_set_cookie(rotated))
    browser_client.cookies.clear()

    forged = browser_client.post(
        "/auth/jwt/refresh",
        headers={
            "Origin": "https://evil.example.com",
            "X-Polyweb-Client": "browser",
            "Cookie": f"{REFRESH_COOKIE_NAME}={first_value}",
        },
    )
    assert forged.status_code == 403
    assert "set-cookie" not in forged.headers
    assert first_value not in forged.text

    live = browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(live_value))
    assert live.status_code == 200


def test_browser_requests_require_origin_and_marker(
    browser_client: TestClient,
) -> None:
    email = temp_email("evidence")
    _register(browser_client, email)
    browser_client.cookies.clear()

    assert (
        browser_client.post(
            "/auth/jwt/login",
            data={"username": email, "password": TEMP_PASSWORD},
            headers={"Origin": _BROWSER_ORIGIN},
        ).status_code
        == 403
    )
    assert (
        browser_client.post(
            "/auth/jwt/login",
            data={"username": email, "password": TEMP_PASSWORD},
            headers={"X-Polyweb-Client": "browser"},
        ).status_code
        == 403
    )
    assert (
        browser_client.post(
            "/auth/jwt/login",
            data={"username": email, "password": TEMP_PASSWORD},
            headers={"Origin": "null", "X-Polyweb-Client": "browser"},
        ).status_code
        == 403
    )


def test_cookie_logout_revokes_family_and_deletes_cookie(
    browser_client: TestClient,
) -> None:
    email = temp_email("logout")
    _register(browser_client, email)
    logged_in = _browser_login(browser_client, email)
    value = _cookie_value(_set_cookie(logged_in))
    access = logged_in.json()["access_token"]
    browser_client.cookies.clear()

    logged_out = browser_client.request(
        "DELETE", "/auth/jwt/refresh", headers=_browser_cookie_headers(value)
    )

    assert logged_out.status_code == 204
    assert logged_out.headers["cache-control"] == "no-store"
    _assert_cookie_deletion(logged_out.headers.get("set-cookie", ""))

    assert (
        browser_client.post("/auth/jwt/refresh", headers=_browser_cookie_headers(value)).status_code
        == 401
    )
    assert browser_client.get("/users/me", headers=raw_auth_headers(access)).status_code == 401


def test_cookie_logout_needs_no_access_token_and_keeps_other_family(
    browser_client: TestClient,
) -> None:
    email = temp_email("twofamily")
    _register(browser_client, email)
    first_value = _cookie_value(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()
    second_login = _browser_login(browser_client, email)
    second_value = _cookie_value(_set_cookie(second_login))
    second_access = second_login.json()["access_token"]
    browser_client.cookies.clear()

    assert (
        browser_client.request(
            "DELETE", "/auth/jwt/refresh", headers=_browser_cookie_headers(first_value)
        ).status_code
        == 204
    )
    browser_client.cookies.clear()

    assert (
        browser_client.post(
            "/auth/jwt/refresh", headers=_browser_cookie_headers(second_value)
        ).status_code
        == 200
    )
    assert (
        browser_client.get("/users/me", headers=raw_auth_headers(second_access)).status_code == 200
    )


def test_stale_access_header_does_not_block_valid_cookie_refresh(
    browser_client: TestClient,
) -> None:
    email = temp_email("stale")
    _register(browser_client, email)
    value = _cookie_value(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()

    rotated = browser_client.post(
        "/auth/jwt/refresh",
        headers=_browser_cookie_headers(value, {"Authorization": "Bearer stale-access"}),
    )

    assert rotated.status_code == 200
    assert rotated.json()["access_token"]


def test_cookie_never_authenticates_ordinary_routes(
    browser_client: TestClient,
) -> None:
    email = temp_email("scoped")
    _register(browser_client, email)
    value = _cookie_value(_set_cookie(_browser_login(browser_client, email)))
    browser_client.cookies.clear()
    cookie_only = {"Cookie": f"{REFRESH_COOKIE_NAME}={value}"}

    assert browser_client.get("/users/me", headers=cookie_only).status_code == 401
    assert (
        browser_client.post(
            "/search", json={"query": "scoped probe"}, headers=cookie_only
        ).status_code
        == 401
    )


def test_empty_allowlist_keeps_programmatic_contract(
    programmatic_client: TestClient,
) -> None:
    email = temp_email("empty")
    _register(programmatic_client, email)

    logged_in = programmatic_client.post(
        "/auth/jwt/login",
        data={"username": email, "password": TEMP_PASSWORD},
        headers=_BROWSER_HEADERS,
    )

    assert logged_in.status_code == 200
    assert logged_in.json()["refresh_token"]
    assert "set-cookie" not in logged_in.headers
