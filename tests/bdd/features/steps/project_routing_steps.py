"""Offline acceptance flow for project provider ordering."""

from typing import Any
from uuid import UUID

from behave import given, then, when  # type: ignore[import-untyped]

import polyweb.services.execution as execution
from tests.bdd.features.steps.control_steps import (
    _build_app,
    _client,
    _ControlAdapter,
    step_given_control_api,
)
from tests.fixtures.execution import account_id_from_headers, bdd_project_id
from tests.fixtures.project_order import seed_order_pools


@given("an offline project with free and paid search providers")
def step_given_project(context: Any) -> None:
    step_given_control_api(context)
    context.adapters = [_ControlAdapter("exa"), _ControlAdapter("keenable")]
    _build_app(context)
    with _client(context) as client:
        enabled = client.patch(
            "/api/v1/providers/keenable",
            json={"enabled": True},
            headers=context.admin_headers,
        )
        assert enabled.status_code == 200, enabled.text
        context.routing_project_id = bdd_project_id(context, context.admin_headers)
        secrets: dict[str, str] = {}
        context.loop.run_until_complete(
            seed_order_pools(
                context.repository,
                project_id=UUID(context.routing_project_id),
                actor_id=account_id_from_headers(context.admin_headers),
                store=context.app.state.secret_store,
                providers=("exa",),
                secrets=secrets,
            )
        )

    def factory(name: str) -> Any:
        adapter = next((item for item in context.adapters if item.name == name), None)
        if adapter is None:
            return None

        def build(client: Any, api_key: Any = None) -> Any:
            del client
            if name == "keenable":
                assert api_key is None
            else:
                assert api_key is not None and api_key.get_secret_value() == secrets[name]
            return adapter

        return build

    context._execution_patcher.setattr(execution, "adapter_factory", factory)


@when("the project admin chooses Free first for Search")
def step_choose_free_first(context: Any) -> None:
    with _client(context) as client:
        response = client.put(
            f"/api/v1/projects/{context.routing_project_id}/routing/order/search",
            json={"strategy": "free_first"},
            headers=context.admin_headers,
        )
    assert response.status_code == 200, response.text
    context.project_order = response.json()


@then("the Search order lists the free provider first")
def step_check_order(context: Any) -> None:
    providers = context.project_order["search"]["providers"]
    assert providers[0]["provider"] == "keenable", providers
    assert providers[0]["keyless"] is True, providers
    assert any(item["provider"] == "exa" for item in providers[1:]), providers


@when("the project admin submits a search")
def step_search(context: Any) -> None:
    with _client(context) as client:
        context.order_search_response = client.post(
            "/search",
            json={"project_id": context.routing_project_id, "query": "routing"},
            headers=context.admin_headers,
        )


@then("the search uses the free provider")
def step_check_search(context: Any) -> None:
    assert context.order_search_response.status_code == 200, context.order_search_response.text
    assert context.order_search_response.json()["provider"] == "keenable"
