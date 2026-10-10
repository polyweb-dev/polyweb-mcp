"""Offline Behave steps for the manual billing-anchor overlay."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import TEMP_PASSWORD, configure_bdd_secret, promote_account, temp_email


def _open_manual_repository(context: Any) -> None:
    with tempfile.NamedTemporaryFile(
        prefix="freesearch-manual-quota-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = temporary_file.name
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(Path(context.database_path))
    )
    context.app = create_app([], repository=context.repository)


def _client(context: Any) -> TestClient:
    return TestClient(context.app)


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _login_admin(context: Any) -> dict[str, str]:
    # Register one account, assign the Admin role, and return one access header.
    email = temp_email("quota-admin")
    with _client(context) as client:
        registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
        assert registered.status_code == 201
        context.loop.run_until_complete(promote_account(context.repository, email, UserRole.ADMIN))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    context.auth_headers = headers
    return headers


@given("an offline manual-quota API with stub adapters")
def step_given_manual_quota_api(context: Any) -> None:
    configure_bdd_secret(context)
    _open_manual_repository(context)
    # Manual quota writes need the Admin role.
    _login_admin(context)


@when('I set the Brave manual quota to allowance "{allowance}" usage "{usage}" for August 2026')
def step_when_set_brave_quota(context: Any, allowance: str, usage: str) -> None:
    with _client(context) as client:
        context.manual_response = client.put(
            "/api/v1/providers/brave/manual-quota",
            json={
                "billing_start": "2026-08-01",
                "billing_end": "2026-09-01",
                "allowance": allowance,
                "current_usage": usage,
            },
            headers=context.auth_headers,
        )
        context.manual_body = context.manual_response.json()


@then('the manual quota should be ESTIMATED with remaining "{remaining}" and percent "{percent}"')
def step_then_estimated_remaining(context: Any, remaining: str, percent: str) -> None:
    assert context.manual_response.status_code == 200
    body = context.manual_body
    assert body["provider"] == "brave"
    assert body["source"] == "estimated"
    assert _as_decimal(body["remaining"]) == Decimal(remaining)
    assert _as_decimal(body["remaining_percent"]) == Decimal(percent)


@when('I update the Brave manual quota usage to "{usage}"')
def step_when_update_usage(context: Any, usage: str) -> None:
    with _client(context) as client:
        context.manual_response = client.put(
            "/api/v1/providers/brave/manual-quota",
            json={
                "billing_start": "2026-08-01",
                "billing_end": "2026-09-01",
                "allowance": "5.00",
                "current_usage": usage,
            },
            headers=context.auth_headers,
        )
        context.manual_body = context.manual_response.json()


@then('the manual quota percent should adjust to "{percent}"')
def step_then_percent_adjusts(context: Any, percent: str) -> None:
    assert context.manual_response.status_code == 200
    assert _as_decimal(context.manual_body["remaining_percent"]) == Decimal(percent)


@when("I clear the Brave manual quota")
def step_when_clear_quota(context: Any) -> None:
    with _client(context) as client:
        context.clear_response = client.delete(
            "/api/v1/providers/brave/manual-quota", headers=context.auth_headers
        )
        context.get_after_clear = client.get(
            "/api/v1/providers/brave/manual-quota", headers=context.auth_headers
        )


@then("the manual quota should be missing")
def step_then_quota_missing(context: Any) -> None:
    assert context.clear_response.status_code == 204
    assert context.get_after_clear.status_code == 404
