"""Offline Behave steps for all-providers fanout search with ranked fusion."""

import tempfile
from pathlib import Path
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
    SearchResult,
    UsageOperation,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import TEMP_PASSWORD, configure_bdd_secret, temp_email
from tests.fixtures.execution import _install_bdd_adapters, account_id_from_headers, bdd_project_id
from tests.fixtures.project_order import seed_order_pools


class _FanoutStubAdapter(ProviderAdapter):
    """Deterministic stub returning fixed URLs or raising on demand."""

    def __init__(self, name: str, urls: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._urls = urls
        self._fail = fail

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=False, cost_estimate=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail:
            raise RuntimeError(f"Provider {self._name} simulated failure")
        results = [
            SearchResult(
                title=f"{self._name} hit {index}",
                url=url,  # type: ignore[arg-type]
                snippet=f"Snippet {index} from {self._name} with enough detail.",
            )
            for index, url in enumerate(self._urls, start=1)
        ]
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=results,
            total_results=len(results),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise NotImplementedError

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
        )


def _open_fanout_repository(context: Any) -> None:
    # Open one temp database for account access in this scenario.
    with tempfile.NamedTemporaryFile(
        prefix="polyweb-fanout-",
        suffix=".db",
        dir=Path.cwd(),
        delete=False,
    ) as temporary_file:
        context.database_path = Path(temporary_file.name)
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )


def _ensure_agent_headers(client: TestClient, context: Any) -> dict[str, str]:
    # Register one Agent account on first use and return one access header.
    existing = getattr(context, "fanout_auth_headers", None)
    if existing is not None:
        return existing
    email = temp_email("fanout-agent")
    registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
    assert registered.status_code == 201
    logged_in = client.post("/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD})
    assert logged_in.status_code == 200
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    context.fanout_auth_headers = headers
    return headers


@given("an offline fanout search harness")
def step_given_fanout_harness(context: Any) -> None:
    """Reset scenario-local fanout state; stubs are registered per scenario."""
    configure_bdd_secret(context)
    _open_fanout_repository(context)
    context.fanout_adapters = []
    context.fanout_response = None
    context.fanout_status = None
    context.fanout_auth_headers = None


@given("the following fanout provider registry:")
def step_given_fanout_registry(context: Any) -> None:
    """Build stub adapters from a provider registry DataTable."""
    adapters: list[_FanoutStubAdapter] = []
    for row in context.table:
        urls = [url.strip() for url in row["urls"].split(",") if url.strip()]
        adapters.append(
            _FanoutStubAdapter(
                row["provider"],
                urls,
                fail=row["behavior"].strip().lower() == "fail",
            )
        )
    context.fanout_adapters = adapters


@given("the fanout providers have pooled vault keys")
def step_given_fanout_pools(context: Any) -> None:
    context.app = create_app(list(context.fanout_adapters), repository=context.repository)
    with TestClient(context.app) as client:
        headers = _ensure_agent_headers(client, context)
        project_id = UUID(bdd_project_id(context, headers))
        secrets: dict[str, str] = {}
        context.loop.run_until_complete(
            seed_order_pools(
                context.repository,
                project_id=project_id,
                actor_id=account_id_from_headers(headers),
                store=context.app.state.secret_store,
                providers=tuple(adapter.name for adapter in context.fanout_adapters),
                secrets=secrets,
            )
        )
    _install_bdd_adapters(context, context.fanout_adapters, secrets)


def _post_fanout_search(
    context: Any, query: str, limit: int, allow_list: tuple[str, ...] = ()
) -> None:
    """POST a fanout search through the real FastAPI app with stub adapters."""
    app = create_app(list(context.fanout_adapters), repository=context.repository)
    context.app = app
    payload: dict[str, Any] = {"query": query, "fanout": True, "limit": limit}
    if allow_list:
        payload["routing"] = {"mode": "fanout", "providers": list(allow_list)}
    with TestClient(app) as client:
        headers = _ensure_agent_headers(client, context)
        # Fanout search needs any authenticated role.
        response = client.post(
            "/search",
            json={"project_id": bdd_project_id(context, headers), **payload},
            headers=headers,
        )
    context.fanout_status = response.status_code
    context.fanout_response = response.json() if response.content else None


@when('I submit a fanout search for "{query}" with limit {limit:d}')
def step_when_fanout_search(context: Any, query: str, limit: int) -> None:
    """Fan out a search across every registered stub provider."""
    _post_fanout_search(context, query, limit)


@when('I submit a fanout search for "{query}" restricted to providers "{allow_list}"')
def step_when_fanout_search_allow_list(context: Any, query: str, allow_list: str) -> None:
    """Fan out a search restricted to an explicit provider allow-list."""
    providers = tuple(name.strip() for name in allow_list.split(",") if name.strip())
    _post_fanout_search(context, query, 10, providers)


@then('the response provider should be "{expected_provider}"')
def step_then_response_provider(context: Any, expected_provider: str) -> None:
    """Verify the fused response attribution (aggregated or single survivor)."""
    assert context.fanout_status == 200, f"Expected 200, got {context.fanout_status}"
    assert context.fanout_response["provider"] == expected_provider


@then('the participating providers should be "{expected}"')
def step_then_participating(context: Any, expected: str) -> None:
    """Verify exactly which providers contributed fused results."""
    wanted = [name.strip() for name in expected.split(",") if name.strip()]
    assert context.fanout_response["participating_providers"] == wanted


@then('the participating providers should include exactly "{expected}" in any order')
def step_then_participating_unordered(context: Any, expected: str) -> None:
    wanted = [name.strip() for name in expected.split(",") if name.strip()]
    assert sorted(context.fanout_response["participating_providers"]) == sorted(wanted)


@then("the fused result count should be {count:d}")
def step_then_fused_count(context: Any, count: int) -> None:
    """Verify canonical-URL deduplication collapsed the raw hits."""
    assert len(context.fanout_response["results"]) == count


@then('the top fused result URL should contain "{fragment}"')
def step_then_top_url(context: Any, fragment: str) -> None:
    """Verify RRF ranked the consensus hit first."""
    assert fragment in context.fanout_response["results"][0]["url"]


@then('the top fused result should fuse sources "{expected}"')
def step_then_top_sources(context: Any, expected: str) -> None:
    """Verify the top hit carries multi-provider attribution and ranks."""
    wanted = {name.strip() for name in expected.split(",") if name.strip()}
    top = context.fanout_response["results"][0]
    assert set(top["sources"]) == wanted
    assert set(top["metadata"]["sources"]) == wanted
    assert set(top["metadata"]["source_ranks"]) == wanted


@then("every fused result should carry source attribution and fusion scores")
def step_then_attribution(context: Any) -> None:
    """Verify every fused result has sources plus RRF metadata."""
    for result in context.fanout_response["results"]:
        assert result["sources"], f"Result {result['url']} missing sources"
        metadata = result["metadata"]
        assert metadata["sources"], "metadata missing sources"
        assert isinstance(metadata["rrf_score"], (int, float))
        assert "canonical_url" in metadata
        assert result["score"] is not None and 0 <= result["score"] <= 1


@then('the fanout search should fail with status {code:d} containing "{detail}"')
def step_then_fanout_error(context: Any, code: int, detail: str) -> None:
    """Verify partial/total-failure and no-eligible error contracts."""
    assert context.fanout_status == code, f"Expected {code}, got {context.fanout_status}"
    body = context.fanout_response
    text = body.get("detail", body) if isinstance(body, dict) else str(body)
    assert detail in str(text), f"Expected {detail!r} in {text!r}"
