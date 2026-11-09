"""Price reads expose no control state and require live vault or project access."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project


@pytest.mark.asyncio
async def test_price_reads_require_authentication_and_scope(tmp_path, auth_secret):
    async with await SQLiteRepository.open(tmp_path / "prices.db") as repository:
        with TestClient(create_app([], repository=repository)) as client:
            assert client.get("/api/v1/provider-prices").status_code == 401
            pair = register_and_login(client, temp_email("no-price-scope"))
            assert (
                client.get(
                    "/api/v1/provider-prices", headers=raw_auth_headers(pair["access_token"])
                ).status_code
                == 403
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("project_reader", [False, True])
async def test_price_reads_allow_non_system_vault_admin_and_project_reader(
    tmp_path, auth_secret, project_reader
):
    async with await SQLiteRepository.open(tmp_path / "prices.db") as repository:
        with TestClient(create_app([], repository=repository)) as client:
            pair = register_and_login(client, temp_email("price-reader"))
            actor_id = account_id_from_pair(pair)
            await seed_execution_project(repository, user_id=actor_id)
            if project_reader:
                async with repository.session() as session:
                    await session.execute(
                        text("UPDATE project_role_assignments SET role_key='project_member'")
                    )
                    await session.execute(text("UPDATE project_memberships SET permissions=0"))
                    await session.commit()
            headers = raw_auth_headers(pair["access_token"])
            assert client.get("/api/v1/providers", headers=headers).status_code == 403
            response = client.get("/api/v1/provider-prices", headers=headers)
            assert response.status_code == 200, response.text
            prices = {row["provider_id"]: row for row in response.json()}
            assert len(prices) == 8
            for row in prices.values():
                assert set(row) == {
                    "provider_id",
                    "call_cost_usd",
                    "keyless_call_cost_usd",
                    "free",
                    "keyless",
                }
            assert prices["tavily"]["call_cost_usd"]["search"] == "0.008"
            assert prices["tavily"]["keyless_call_cost_usd"] == {"search": "0", "fetch": "0"}
            assert prices["tavily"]["keyless"] is True
            assert prices["tavily"]["free"] is False
            assert prices["keenable"]["free"] is True
            assert prices["tinyfish"]["free"] is True
            assert prices["brave"]["keyless"] is False
