"""The optional smart-routing advisor client and its use by execution ranking."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest

from polyweb.configuration.config import Settings
from polyweb.models.contracts import HealthStatus, RoutingMode, RoutingPreference, SearchRequest
from polyweb.services.execution import ExecutionService
from polyweb.services.route_advisor import RouteAdvice, RouteAdvisor


def advisor_with(handler: Any) -> RouteAdvisor:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RouteAdvisor("http://router.test/", secret="s3cret", client=client)


async def test_advise_sends_query_providers_objective_and_secret() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "provider": "exa",
                "fallback": ["brave", "exa", "tavily"],
                "route_id": "r1",
                "model_version": "v9",
            },
        )

    advice = await advisor_with(handler).advise("who is the CFO of Nike", ("exa", "brave"), "speed")

    assert seen["url"] == "http://router.test/v1/route"
    assert seen["auth"] == "Bearer s3cret"
    assert seen["body"] == {
        "query": "who is the CFO of Nike",
        "providers": ["exa", "brave"],
        "objective": "speed",
    }
    assert advice == RouteAdvice(("exa", "brave", "tavily"), route_id="r1", model_version="v9")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "down"}),
        httpx.Response(401, json={"detail": "secret"}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"fallback": ["exa"]}),
        httpx.Response(200, json={"provider": "exa", "fallback": [1]}),
        httpx.Response(200, json=["exa"]),
    ],
)
async def test_advise_returns_none_for_any_bad_answer(response: httpx.Response) -> None:
    assert await advisor_with(lambda _request: response).advise("q") is None


async def test_advise_returns_none_on_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    assert await advisor_with(handler).advise("q") is None


def test_from_settings_is_off_by_default() -> None:
    assert RouteAdvisor.from_settings(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    configured = RouteAdvisor.from_settings(
        Settings(_env_file=None, router_url="http://router.test", router_secret="x")  # type: ignore[call-arg]
    )
    assert isinstance(configured, RouteAdvisor)


class StubAdvisor:
    def __init__(self, advice: RouteAdvice | None) -> None:
        self.advice = advice
        self.calls: list[tuple[str, tuple[str, ...], str | None]] = []

    async def advise(
        self, query: str, providers: tuple[str, ...] = (), objective: str | None = None
    ) -> RouteAdvice | None:
        self.calls.append((query, tuple(providers), objective))
        return self.advice


def service_with(advisor: StubAdvisor | None) -> ExecutionService:
    service = ExecutionService.__new__(ExecutionService)
    service._route_advisor = advisor  # type: ignore[assignment]
    return service


def request(mode: RoutingMode, **routing: Any) -> SearchRequest:
    return SearchRequest(query="q", routing=RoutingPreference(mode=mode, **routing))


async def test_smart_request_takes_the_advised_order() -> None:
    stub = StubAdvisor(RouteAdvice(("brave", "exa")))
    advised = await service_with(stub)._advised(
        request(RoutingMode.SMART, providers=("exa", "brave"), objective="accuracy")
    )
    assert stub.calls == [("q", ("exa", "brave"), "accuracy")]
    assert advised.routing.mode is RoutingMode.SMART
    assert advised.routing.providers == ("brave", "exa")


@pytest.mark.parametrize(
    "original",
    [
        request(RoutingMode.AUTO),
        request(RoutingMode.PREFER, providers=("exa",)),
        request(RoutingMode.SMART, binding_id=UUID(int=1)),
        SearchRequest(query="q", fanout=True, routing=RoutingPreference(mode=RoutingMode.SMART)),
    ],
)
async def test_advisor_is_not_asked_outside_plain_smart(original: SearchRequest) -> None:
    stub = StubAdvisor(RouteAdvice(("brave",)))
    assert await service_with(stub)._advised(original) is original
    assert stub.calls == []


@pytest.mark.parametrize("advisor", [None, StubAdvisor(None)])
async def test_smart_without_an_answer_is_unchanged(advisor: StubAdvisor | None) -> None:
    original = request(RoutingMode.SMART, providers=("exa", "brave"))
    assert await service_with(advisor)._advised(original) is original


def test_rank_key_orders_by_position_only_for_smart() -> None:
    binding = SimpleNamespace(priority=0, route_label="", id=UUID(int=0))
    preference = ("gamma", "alpha")

    def key(provider: str, *, ordered: bool) -> tuple[int, ...]:
        return ExecutionService._rank_key(None, provider, 0, binding, preference, ordered=ordered)[
            :2
        ]  # type: ignore[arg-type]

    # smart: no health observation ranks with healthy providers, by advised position
    assert [key(p, ordered=True) for p in ("alpha", "beta", "gamma")] == [(0, 1), (0, 2), (0, 0)]
    # prefer keeps its existing membership-only behaviour
    assert [key(p, ordered=False) for p in ("alpha", "beta", "gamma")] == [(2, 0), (2, 1), (2, 0)]


def test_smart_ranks_unobserved_providers_with_healthy_ones() -> None:
    def leg(provider: str, status: HealthStatus | None) -> tuple[int, ...]:
        observation = (
            None if status is None else SimpleNamespace(status=status)  # type: ignore[arg-type]
        )
        binding = SimpleNamespace(priority=0, route_label="", id=UUID(int=0))
        return ExecutionService._rank_key(
            observation,  # type: ignore[arg-type]
            provider,
            0,
            binding,  # type: ignore[arg-type]
            ("exa", "parallel"),
            ordered=True,
        )[:2]

    # exa has never been observed, parallel is healthy: the advised order wins
    assert sorted(
        ["parallel", "exa"], key=lambda p: leg(p, None if p == "exa" else HealthStatus.HEALTHY)
    ) == [
        "exa",
        "parallel",
    ]
    # a degraded advised provider still drops behind a healthy one
    assert leg("exa", HealthStatus.DEGRADED) > leg("parallel", HealthStatus.HEALTHY)
