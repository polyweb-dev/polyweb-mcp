from freesearch.contracts import FetchRequest, SearchRequest, UsageOperation


async def test_fake_adapter_implements_shared_contract(fake_adapter) -> None:
    search_request = SearchRequest(query="contract test")
    search_response = await fake_adapter.search(search_request)
    assert search_response.provider == fake_adapter.name
    assert str(search_response.results[0].url) == "https://example.com/result"
    assert search_response.usage is not None
    assert search_response.usage.operation is UsageOperation.SEARCH

    fetch_request = FetchRequest(url="https://example.com/document")
    fetch_response = await fake_adapter.fetch(fetch_request)
    assert fetch_response.provider == fake_adapter.name
    assert fetch_response.document.url == fetch_request.url

    estimate = await fake_adapter.estimate_cost(search_request)
    assert estimate.provider == fake_adapter.name
    assert estimate.operation is UsageOperation.SEARCH

    health = await fake_adapter.health()
    assert health.provider == fake_adapter.name
    assert await fake_adapter.quota() is None
