"""Host dispatch, plugin discovery, the admin API, and log redaction."""

import random

import httpx
import pytest

from polyweb_provider_mock.app import MockApplication, request_host
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers.base import ProviderPlugin
from polyweb_provider_mock.store import MockStore
from tests.conftest import TAVILY


@pytest.mark.parametrize(
    ("header", "host"),
    [
        (b"api.tavily.com", "api.tavily.com"),
        (b"API.Tavily.com:443", "api.tavily.com"),
        (b"127.0.0.1:8212", "127.0.0.1"),
        (b"[::1]:8212", "::1"),
        (b"api.tavily.com.", "api.tavily.com"),
    ],
)
def test_request_host_strips_port_and_case(header: bytes, host: str) -> None:
    assert request_host({"headers": [(b"host", header)]}) == host


def test_discovery_finds_every_plugin_with_unique_hosts() -> None:
    plugins = discover()
    assert "tavily" in plugins
    assert all(isinstance(item, ProviderPlugin) for item in plugins.values())
    hosts = [host for item in plugins.values() for host in item.hosts]
    assert len(hosts) == len(set(hosts))


async def test_unknown_host_is_misdirected(client: httpx.AsyncClient) -> None:
    response = await client.post("/search", headers={"Host": "api.example.net"})

    assert response.status_code == 421
    assert response.json()["error"] == "misdirected_request"
    assert "api.tavily.com" in response.json()["provider_hosts"]


async def test_admin_health_and_state_routes(client: httpx.AsyncClient) -> None:
    health = await client.get("/_mock/health")
    assert health.json() == {"status": "ok", "providers": sorted(discover()), "seeded": True}

    keys = await client.get("/_mock/keys", params={"provider": "tavily"})
    assert [key["label"] for key in keys.json()] == ["default", "secondary"]
    added = await client.post("/_mock/credits/add", json={"provider": "tavily", "amount": "5"})
    assert added.json()["credit_limit"] == "1005"
    fault = await client.post(
        "/_mock/faults", json={"provider": "tavily", "kind": "outage", "count": 1}
    )
    assert fault.json()["remaining"] == 1
    exported = await client.get("/_mock/export-keys")
    assert exported.text.startswith("POLYWEB_TAVILY_API_KEY=tvly-dev-mock")
    applied = await client.post("/_mock/scenarios/tavily-down")
    assert applied.json()[0]["scenario"] == "tavily-down"
    cleared = await client.delete("/_mock/scenarios")
    assert cleared.json() == {"removed": 1}
    missing = await client.post("/_mock/keys/revoke", json={"provider": "tavily", "key": "x"})
    assert missing.status_code == 404


async def test_admin_token_guards_everything_but_health(store: MockStore) -> None:
    app = MockApplication(store, discover(), admin_token="s3cret", rng=random.Random(1))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as http:
        assert (await http.get("/_mock/health")).status_code == 200
        assert (await http.get("/_mock/keys")).status_code == 401
        allowed = await http.get("/_mock/keys", headers={"Authorization": "Bearer s3cret"})
        assert allowed.status_code == 200


async def test_provider_unknown_path_uses_provider_format(
    client: httpx.AsyncClient, tavily_headers: dict[str, str]
) -> None:
    response = await client.get("/crawl", headers=tavily_headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    wrong_method = await client.get("/search", headers=tavily_headers)
    assert wrong_method.status_code == 405


async def test_request_log_never_holds_the_presented_key(
    client: httpx.AsyncClient, store: MockStore, tavily_key: str
) -> None:
    secret = "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"
    await client.post(
        "/search",
        json={"query": "q", "api_key": secret},
        headers={**TAVILY, "Authorization": f"Bearer {secret}"},
    )
    await client.post(
        "/search", json={"query": "q"}, headers={**TAVILY, "Authorization": f"Bearer {tavily_key}"}
    )

    entries = store.log_tail("tavily", with_bodies=True)
    assert [entry.key_label for entry in entries] == ["invalid-key", "default"]
    dumped = "".join(entry.model_dump_json() for entry in entries)
    assert secret not in dumped and tavily_key not in dumped
    assert entries[0].request_summary["headers"]["authorization"] == "<redacted>"
    assert entries[0].request_summary["body"]["api_key"] == "<redacted>"
