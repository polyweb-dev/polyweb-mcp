"""Pool-backed setup for the Tavily terminal-402 fanout scenario."""

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from polyweb.adapters.base import ProviderAdapter
from polyweb.models.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
)
from polyweb.models.provider_limits import LimitHistoryQuery
from polyweb.routers.api import create_app
from polyweb.services.provider_runtime import _BACKGROUND_TASKS
from tests.bdd.features.steps.provider_limits_steps import _limits_repo, _tavily_pool_id
from tests.fixtures.execution import _install_bdd_adapters, account_id_from_headers, bdd_project_id
from tests.fixtures.project_order import seed_order_pools


class _HeldBrave(ProviderAdapter):
    def __init__(self, held: Any) -> None:
        self._held = held

    @property
    def name(self) -> str:
        return "brave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._held.capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return (await self._held.search(request)).model_copy(update={"provider": self.name})

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return await self._held.fetch(request)

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return await self._held.estimate_cost(request)


@given("the Tavily fanout uses pooled Tavily and Brave credentials")
def step_given_tavily_fanout_pools(context: Any) -> None:
    context.tavily_held_other = _HeldBrave(context.tavily_held_other)
    adapters = [context.tavily_fanout_adapter, context.tavily_held_other]
    context.tavily_fanout_app = create_app(adapters, repository=context.repository)
    context.app = context.tavily_fanout_app
    with TestClient(context.app):
        project_id = UUID(bdd_project_id(context, context.tavily_fanout_headers))
        context.tavily_fanout_project_id = str(project_id)
        secrets: dict[str, str] = {}
        context.loop.run_until_complete(
            seed_order_pools(
                context.repository,
                project_id=project_id,
                actor_id=account_id_from_headers(context.tavily_fanout_headers),
                store=context.app.state.secret_store,
                providers=("tavily", "brave"),
                secrets=secrets,
            )
        )
    _install_bdd_adapters(context, adapters, secrets)


@when("I run pooled Tavily fanout search with client fallback enabled")
def step_when_pooled_tavily_fanout(context: Any) -> None:
    payload = {
        "project_id": context.tavily_fanout_project_id,
        "query": "fanout 402 probe",
        "limit": 3,
        "routing": {"mode": "fanout", "providers": ["tavily", "brave"]},
    }
    with TestClient(context.tavily_fanout_app) as client:
        context.tavily_fanout_held = client.post(
            "/search", json=payload, headers=context.tavily_fanout_headers
        )
    context.tavily_other_released.set()
    with TestClient(context.tavily_fanout_app) as client:
        context.tavily_fanout_released = client.post(
            "/search", json=payload, headers=context.tavily_fanout_headers
        )
    payload["routing"] = {"mode": "require", "providers": ["tavily"]}
    with TestClient(context.tavily_single_app) as client:
        context.tavily_single_fallback = client.post(
            "/search", json=payload, headers=context.tavily_fanout_headers
        )

    async def drain_refresh() -> None:
        pending = [task for task in list(_BACKGROUND_TASKS) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    context.loop.run_until_complete(drain_refresh())


@then(
    "the pooled Tavily fanout released answer has Brave success "
    "and local denial without another vendor attempt"
)
def step_then_tavily_fanout_pooled_release(context: Any) -> None:
    response = context.tavily_fanout_released
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("provider") == "brave"
    assert len(context.tavily_fanout_sdk.search_calls) == 1
    tavily_legs = [
        entry for entry in body.get("waterfall", []) if entry.get("provider") == "tavily"
    ]
    assert len(tavily_legs) == 1
    assert "budget_exhausted" in (tavily_legs[0].get("error") or "")


@then("the pooled Tavily single fallback is a local 402 with no new vendor attempt or debit")
def step_then_tavily_pooled_single_fallback(context: Any) -> None:
    response = context.tavily_single_fallback
    assert response.status_code == 402, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, dict)
    assert detail.get("provider") == "tavily"
    assert detail.get("code") == "budget_exhausted"
    assert detail.get("status_code") == 402
    assert len(context.tavily_fanout_sdk.search_calls) == 1
    pools = context.loop.run_until_complete(_limits_repo(context).list_pools("tavily"))
    scoped = [pool for pool in pools if "#pool:" in pool.pool_id]
    assert len(scoped) == 1, [(pool.pool_id, pool.remaining) for pool in pools]
    assert scoped[0].remaining == Decimal("0")
    assert scoped[0].source == "vendor_402"
    catalog = context.loop.run_until_complete(_limits_repo(context).get_pool(_tavily_pool_id()))
    assert catalog is not None and catalog.remaining == Decimal("999")
    assert catalog.source == "vendor_api"
    history = context.loop.run_until_complete(
        context.service.history(LimitHistoryQuery(provider="tavily", limit=20))
    )
    assert all(event.reason != "local_success" for event in history.events)
