"""Firecrawl plugin wire behavior through the in-process app."""

from decimal import Decimal

import httpx
import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers.firecrawl import PLUGIN
from polyweb_provider_mock.store import MockStore

_HOST = {"Host": "api.firecrawl.dev"}
_SEARCH = {"query": "polyweb test", "limit": 3, "timeout": 300000, "origin": "python-sdk@4.41.0"}
_SCRAPE = {"url": "https://docs.python.org/3/library/json.html", "formats": ["markdown"]}
_INVALID_TOKEN = {"success": False, "error": "Unauthorized: Invalid token"}


def _key(store: MockStore, label: str = "default") -> str:
    return next(item.key for item in store.keys("firecrawl") if item.label == label)


@pytest.fixture
def headers(store: MockStore) -> dict[str, str]:
    return {**_HOST, "Authorization": f"Bearer {_key(store)}"}


def _used(store: MockStore) -> Decimal:
    return store.account("firecrawl").credits_used


def test_seeded_keys_match_the_fc_format(store: MockStore) -> None:
    keys = store.keys("firecrawl")
    assert all(key.key.startswith("fc-mock") and len(key.key) == 35 for key in keys)
    assert all(char in "0123456789abcdef" for char in keys[0].key[7:])
    assert store.export_keys().count(("POLYWEB_FIRECRAWL_API_KEY", keys[0].key)) == 1
    assert PLUGIN.key_format.generate().startswith("fc-mock")


async def test_search_envelope_credits_and_debit(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    response = await client.post("/v2/search", json=_SEARCH, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["x-response-time"].endswith("ms")
    assert list(body) == ["success", "data", "creditsUsed", "id"]
    assert body["success"] is True and body["creditsUsed"] == 2
    assert list(body["data"]) == ["web"]
    assert [item["position"] for item in body["data"]["web"]] == [1, 2, 3]
    assert set(body["data"]["web"][0]) == {"url", "title", "description", "position"}
    assert _used(store) == 2


@pytest.mark.parametrize(("limit", "credits"), [(1, 2), (10, 2), (11, 4), (25, 6)])
async def test_search_costs_two_credits_per_ten_requested_results(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str], limit: int, credits: int
) -> None:
    body = (
        await client.post("/v2/search", json={**_SEARCH, "limit": limit}, headers=headers)
    ).json()
    assert body["creditsUsed"] == credits and _used(store) == credits


async def test_search_channels_and_scrape_options(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    sources = [{"type": "web"}, {"type": "news"}, {"type": "images"}]
    channels = (
        await client.post(
            "/v2/search", json={**_SEARCH, "limit": 1, "sources": sources}, headers=headers
        )
    ).json()
    scraped = (
        await client.post(
            "/v2/search",
            json={**_SEARCH, "limit": 2, "scrapeOptions": {"formats": ["markdown"]}},
            headers=headers,
        )
    ).json()

    assert list(channels["data"]) == ["web", "news", "images"]
    assert set(channels["data"]["news"][0]) == {
        "title",
        "url",
        "snippet",
        "date",
        "imageUrl",
        "position",
    }
    assert set(channels["data"]["images"][0]) == {
        "title", "imageUrl", "imageWidth", "imageHeight", "url", "position",
    }  # fmt: skip
    assert channels["creditsUsed"] == 2
    assert scraped["creditsUsed"] == 4
    assert scraped["data"]["web"][0]["markdown"].startswith("# ")
    assert scraped["data"]["web"][0]["metadata"]["statusCode"] == 200
    assert _used(store) == 6


async def test_scrape_returns_only_requested_formats_with_camelcase_metadata(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    request = {
        "url": "https://docs.python.org/3/",
        "formats": ["html", "rawHtml", "links", "images"],
    }
    body = (await client.post("/v2/scrape", json=request, headers=headers)).json()

    data = body["data"]
    assert body["success"] is True
    assert set(data) == {"html", "rawHtml", "links", "images", "metadata"}
    assert data["rawHtml"].startswith("<!DOCTYPE html>")
    metadata = data["metadata"]
    assert metadata["sourceURL"] == "https://docs.python.org/3/"
    assert metadata["statusCode"] == 200 and metadata["creditsUsed"] == 1
    assert metadata["cacheState"] == "miss" or "cachedAt" in metadata
    assert metadata["concurrencyLimited"] is False
    assert _used(store) == 1


@pytest.mark.parametrize(
    ("extra", "credits"),
    [
        (
            {
                "formats": [
                    {
                        "type": "json",
                        "schema": {"type": "object", "properties": {"t": {"type": "string"}}},
                    }
                ]
            },
            5,
        ),
        ({"formats": ["markdown", {"type": "question", "question": "why?"}]}, 5),
        ({"formats": ["markdown"], "zeroDataRetention": True}, 2),
        ({"formats": ["markdown"], "redactPII": True, "lockdown": True}, 9),
        ({"formats": ["summary", "screenshot"], "proxy": "enhanced"}, 1),
    ],
)
async def test_scrape_option_modifiers_stack(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    extra: dict[str, object],
    credits: int,
) -> None:
    body = (await client.post("/v2/scrape", json={**_SCRAPE, **extra}, headers=headers)).json()

    assert body["data"]["metadata"]["creditsUsed"] == credits
    assert _used(store) == credits
    if "zeroDataRetention" not in extra and "redactPII" not in extra:
        first = extra["formats"][0]  # type: ignore[index]
        name = first if isinstance(first, str) else first["type"]
        assert name in body["data"]


async def test_pdf_pages_cost_one_credit_each(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    url = "https://arxiv.org/pdf/2401.00001.pdf"
    capped = {"url": url, "parsers": [{"type": "pdf", "maxPages": 2}]}
    body = (await client.post("/v2/scrape", json=capped, headers=headers)).json()

    metadata = body["data"]["metadata"]
    assert metadata["contentType"] == "application/pdf" and metadata["numPages"] == 2
    assert metadata["creditsUsed"] == 3
    raw = (
        await client.post("/v2/scrape", json={"url": url, "parsers": []}, headers=headers)
    ).json()
    assert raw["data"]["metadata"]["creditsUsed"] == 1


async def test_target_site_errors_still_return_a_billed_document(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    blocked = await client.post(
        "/v2/scrape", json={"url": "https://blocked.example.org/a"}, headers=headers
    )
    missing = await client.post(
        "/v2/scrape", json={"url": "https://notfound.example.org/a"}, headers=headers
    )
    dns = await client.post("/v2/scrape", json={"url": "https://gone.invalid/"}, headers=headers)

    assert blocked.status_code == missing.status_code == 200
    assert blocked.json()["data"]["metadata"]["statusCode"] == 403
    assert missing.json()["data"]["metadata"]["statusCode"] == 404
    assert dns.status_code == 400
    assert dns.json()["code"] == "SCRAPE_DNS_RESOLUTION_ERROR"
    assert _used(store) == 2


async def test_processing_host_answers_408_resume_signals_then_bills_once(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    request = {"url": "https://processing.example.org/large.pdf", "formats": ["markdown"]}
    answers = [await client.post("/v2/scrape", json=request, headers=headers) for _ in range(3)]

    assert [answer.status_code for answer in answers] == [408, 408, 200]
    assert answers[0].json() == {
        "success": False,
        "code": "SCRAPE_TIMEOUT",
        "error": "Request timed out",
        "details": {"state": "processing_continues", "retryAfterSeconds": 5},
    }
    assert answers[2].json()["data"]["markdown"]
    assert _used(store) == answers[2].json()["data"]["metadata"]["creditsUsed"]


async def test_408_fault_can_be_an_ordinary_timeout_or_a_resume_signal(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="scrape",
            kind=FaultKind.HTTP_ERROR,
            params=FaultParams(status=408, scope="processing_continues"),
            count=1,
        )
    )
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            operation="search",
            kind=FaultKind.HTTP_ERROR,
            params=FaultParams(status=408),
        )
    )
    resume = await client.post("/v2/scrape", json=_SCRAPE, headers=headers)
    plain = await client.post("/v2/search", json=_SEARCH, headers=headers)

    assert resume.status_code == 408 and resume.json()["details"]["state"] == "processing_continues"
    assert plain.json() == {
        "success": False,
        "code": "SCRAPE_TIMEOUT",
        "error": "Request timed out",
    }
    assert (await client.post("/v2/scrape", json=_SCRAPE, headers=headers)).status_code == 200


@pytest.mark.parametrize(
    ("path", "request_body", "fragment"),
    [
        ("/v2/search", {"limit": 1}, "expected string, received undefined"),
        ("/v2/search", {"query": "", "limit": 1}, "Too small"),
        ("/v2/search", {"query": "q", "limit": 101}, "Too big"),
        ("/v2/search", {"query": "q", "sources": [{"type": "videos"}]}, "sources"),
        ("/v2/scrape", {"formats": ["markdown"]}, "expected string, received undefined"),
        ("/v2/scrape", {"url": "not a url"}, "Invalid URL"),
        (
            "/v2/scrape",
            {"url": "https://example.com", "formats": [{"type": "question"}]},
            "invalid_union",
        ),
    ],
)
async def test_validation_errors_are_bad_request_and_free(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    path: str,
    request_body: dict[str, object],
    fragment: str,
) -> None:
    response = await client.post(path, json=request_body, headers=headers)

    body = response.json()
    assert response.status_code == 400
    assert (body["success"], body["code"], body["error"]) == (False, "BAD_REQUEST", "Bad Request")
    assert fragment in response.text
    assert _used(store) == 0


async def test_invalid_and_revoked_keys_are_401_with_www_authenticate(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    wrong = await client.post(
        "/v2/scrape", json=_SCRAPE, headers={**_HOST, "Authorization": "Bearer fc-wrong"}
    )
    store.set_key_status("firecrawl", "default", "revoked")
    revoked = await client.get("/v2/team/credit-usage", headers=headers)

    for response in (wrong, revoked):
        assert (response.status_code, response.json()) == (401, _INVALID_TOKEN)
        assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")


async def test_keyless_tier_serves_search_and_scrape_but_not_credit_usage(
    client: httpx.AsyncClient, store: MockStore
) -> None:
    search = await client.post("/v2/search", json=_SEARCH, headers=_HOST)
    usage = await client.get("/v2/team/credit-usage", headers=_HOST)
    store.set_keyless("firecrawl", per_day=1)
    capped = await client.post("/v2/scrape", json=_SCRAPE, headers=_HOST)

    assert search.status_code == 200 and search.json()["creditsUsed"] == 2
    assert _used(store) == 0
    assert store.log_tail("firecrawl")[0].key_label == "keyless"
    assert usage.status_code == 401 and "keyless free tier" in usage.json()["error"]
    assert usage.json()["signup_url"].startswith("https://firecrawl.dev/k/")
    assert capped.status_code == 429 and int(capped.headers["retry-after"]) > 0
    assert capped.json()["success"] is False and "signup_url" in capped.json()


async def test_credit_usage_reflects_the_ledger_and_purchased_credits(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    await client.post("/v2/scrape", json=_SCRAPE, headers=headers)
    store.add_credits("firecrawl", Decimal(500))

    body = (await client.get("/v2/team/credit-usage", headers=headers)).json()

    account = store.account("firecrawl")
    assert body["success"] is True
    assert body["data"]["remainingCredits"] == 1499 and body["data"]["planCredits"] == 1000
    assert body["data"]["billingPeriodStart"].endswith("Z")
    assert body["data"]["billingPeriodEnd"].startswith(f"{account.period_reset:%Y-%m-%dT}")


async def test_exhaustion_is_402_and_never_half_debits(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.set_credits("firecrawl", Decimal(4))
    expensive = {**_SCRAPE, "formats": ["markdown", {"type": "json"}]}

    refused = await client.post("/v2/scrape", json=expensive, headers=headers)
    cheap = await client.post("/v2/scrape", json=_SCRAPE, headers=headers)

    assert refused.status_code == 402
    assert refused.json()["success"] is False and "Insufficient credits" in refused.json()["error"]
    assert cheap.status_code == 200 and _used(store) == 1


@pytest.mark.parametrize(
    ("spec", "status", "fragment"),
    [
        (
            FaultSpec(
                provider="firecrawl", kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=7)
            ),
            429,
            "Rate limit exceeded. Consumed (req/min)",
        ),
        (
            FaultSpec(
                provider="firecrawl",
                kind=FaultKind.RATE_LIMIT,
                params=FaultParams(scope="concurrency"),
            ),
            429,
            "Concurrency limit reached",
        ),
        (FaultSpec(provider="firecrawl", kind=FaultKind.OUTAGE), 503, "Service Unavailable"),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            502,
            "Bad Gateway",
        ),
        (FaultSpec(provider="firecrawl", kind=FaultKind.HTTP_ERROR), 500, "exception ID"),
        (
            FaultSpec(provider="firecrawl", kind=FaultKind.QUOTA_EXHAUSTED),
            402,
            "Insufficient credits",
        ),
        (FaultSpec(provider="firecrawl", kind=FaultKind.AUTH_INVALID), 401, "Invalid token"),
    ],
)
async def test_faults_render_the_success_false_envelope(
    client: httpx.AsyncClient,
    store: MockStore,
    headers: dict[str, str],
    spec: FaultSpec,
    status: int,
    fragment: str,
) -> None:
    store.add_fault(spec)
    response = await client.post("/v2/scrape", json=_SCRAPE, headers=headers)

    assert response.status_code == status
    assert response.json()["success"] is False and fragment in response.json()["error"]
    if spec.params.retry_after is not None:
        assert response.headers["retry-after"] == "7"
    assert _used(store) == 0


async def test_malformed_missing_field_drops_the_success_flag(
    client: httpx.AsyncClient, store: MockStore, headers: dict[str, str]
) -> None:
    store.add_fault(
        FaultSpec(
            provider="firecrawl",
            kind=FaultKind.MALFORMED,
            params=FaultParams(variant="missing_field"),
        )
    )
    scrape = (await client.post("/v2/scrape", json=_SCRAPE, headers=headers)).json()
    usage = (await client.get("/v2/team/credit-usage", headers=headers)).json()

    assert "success" not in scrape and "data" in scrape
    assert usage == {"success": True}
