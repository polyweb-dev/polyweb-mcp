"""Unit tests for URL canonicalization and Reciprocal Rank Fusion."""

from datetime import UTC, datetime

import pytest
from pydantic import AnyHttpUrl

from polyweb.models.contracts import SearchResponse, SearchResult
from polyweb.services.aggregation import canonicalize_url, reciprocal_rank_fusion


class TestCanonicalizeUrl:
    """Test URL normalization rules for cross-engine deduplication."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://example.com", "https://example.com/"),
            ("https://example.com", "https://example.com/"),
            ("https://example.com/", "https://example.com/"),
            ("https://www.example.com/", "https://example.com/"),
            ("https://WWW.EXAMPLE.COM/docs/", "https://example.com/docs"),
            ("https://example.com/docs/", "https://example.com/docs"),
            ("https://example.com:443/docs", "https://example.com/docs"),
            ("http://example.com:80/docs", "https://example.com/docs"),
            (
                "https://example.com/page?utm_source=twitter&utm_medium=social",
                "https://example.com/page",
            ),
            ("https://example.com/page?fbclid=12345&gclid=67890", "https://example.com/page"),
            ("https://example.com/page?ref=search&b=2&a=1", "https://example.com/page?a=1&b=2"),
            ("https://example.com/page#section-3", "https://example.com/page"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_canonicalize_url_patterns(self, raw: str, expected: str) -> None:
        assert canonicalize_url(raw) == expected

    def test_preserves_legitimate_query_parameters(self) -> None:
        url = "https://example.com/search?q=python+asyncio&sort=relevance&lang=en"
        canon = canonicalize_url(url)
        assert canon == "https://example.com/search?lang=en&q=python+asyncio&sort=relevance"


class TestReciprocalRankFusion:
    """Test Reciprocal Rank Fusion score calculation, deduplication, and attribution."""

    def test_empty_or_zero_limit_returns_empty(self) -> None:
        assert reciprocal_rank_fusion([]) == []
        assert (
            reciprocal_rank_fusion(
                [("mock", SearchResponse(query="q", results=[], provider="mock"))],
                limit=0,
            )
            == []
        )

    def test_single_provider_preserves_order(self) -> None:
        r1 = SearchResult(
            title="Result 1",
            url=AnyHttpUrl("https://example.com/1"),
            snippet="Snippet 1",
            score=0.9,
        )
        r2 = SearchResult(
            title="Result 2",
            url=AnyHttpUrl("https://example.com/2"),
            snippet="Snippet 2",
            score=0.7,
        )
        response = SearchResponse(query="test", results=[r1, r2], provider="exa")

        fused = reciprocal_rank_fusion([("exa", response)], limit=10)

        assert len(fused) == 2
        assert str(fused[0].url) == "https://example.com/1"
        assert str(fused[1].url) == "https://example.com/2"
        assert fused[0].metadata["sources"] == ["exa"]
        assert fused[0].metadata["source_ranks"] == {"exa": 1}
        assert fused[1].metadata["source_ranks"] == {"exa": 2}
        assert fused[0].score == 1.0  # Normalized: top rank in all providers

    def test_consensus_boosts_shared_results_over_single_provider_first(self) -> None:
        """AC: An item ranked #2 in Exa and #2 in Brave outranks an item only in Exa at #1."""
        # Provider A (Exa):
        # Rank 1: Unique to Exa
        # Rank 2: Consensus item (in both Exa and Brave)
        exa_r1 = SearchResult(
            title="Exa Only Top Hit",
            url=AnyHttpUrl("https://example.com/exa-exclusive"),
            snippet="Short snippet from Exa",
        )
        consensus_from_exa = SearchResult(
            title="Consensus Hit",
            url=AnyHttpUrl("https://example.com/consensus-page?utm_source=exa"),
            snippet="Detailed snippet from Exa about consensus topic.",
            published_at=datetime(2025, 1, 15, tzinfo=UTC),
        )
        exa_resp = SearchResponse(
            query="test",
            results=[exa_r1, consensus_from_exa],
            provider="exa",
        )

        # Provider B (Brave):
        # Rank 1: Unique to Brave
        # Rank 2: Consensus item (same URL without utm params)
        brave_r1 = SearchResult(
            title="Brave Only Top Hit",
            url=AnyHttpUrl("https://example.com/brave-exclusive"),
            snippet="Short snippet from Brave",
        )
        consensus_from_brave = SearchResult(
            title="Consensus Hit - Full Title",
            url=AnyHttpUrl("https://www.example.com/consensus-page/"),
            snippet="Extremely rich, long snippet from Brave with deeper context.",
        )
        brave_resp = SearchResponse(
            query="test",
            results=[brave_r1, consensus_from_brave],
            provider="brave",
        )

        fused = reciprocal_rank_fusion(
            [("exa", exa_resp), ("brave", brave_resp)],
            limit=10,
            k=60,
        )

        # Consensus item should float to Rank #1 because:
        # Score(consensus) = 1/(60+2) + 1/(60+2) = 1/62 + 1/62 = 0.032258
        # Score(exa_r1) = 1/(60+1) = 0.016393
        # Score(brave_r1) = 1/(60+1) = 0.016393
        assert len(fused) == 3
        top_hit = fused[0]
        assert "consensus-page" in str(top_hit.url)
        assert set(top_hit.metadata["sources"]) == {"exa", "brave"}
        assert top_hit.metadata["source_ranks"] == {"exa": 2, "brave": 2}
        assert top_hit.snippet == "Extremely rich, long snippet from Brave with deeper context."
        assert top_hit.title == "Consensus Hit - Full Title"
        assert top_hit.published_at == datetime(2025, 1, 15, tzinfo=UTC)
        assert top_hit.score is not None and top_hit.score > fused[1].score

    def test_single_provider_duplicate_url_counted_once(self) -> None:
        """A single provider repeating the same URL should only get credit for its highest rank."""
        r1 = SearchResult(
            title="First Appearance",
            url=AnyHttpUrl("https://example.com/doc"),
            snippet="First snippet",
        )
        r2 = SearchResult(
            title="Second Appearance",
            url=AnyHttpUrl("https://example.com/doc/"),
            snippet="Second snippet",
        )
        response = SearchResponse(query="test", results=[r1, r2], provider="tavily")

        fused = reciprocal_rank_fusion([("tavily", response)], limit=10, k=60)
        assert len(fused) == 1
        assert fused[0].metadata["source_ranks"] == {"tavily": 1}
        assert fused[0].metadata["rrf_score"] == round(1.0 / 61, 6)

    def test_honors_limit(self) -> None:
        results = [
            SearchResult(
                title=f"Result {i}",
                url=AnyHttpUrl(f"https://example.com/{i}"),
                snippet=f"Snippet {i}",
            )
            for i in range(20)
        ]
        resp = SearchResponse(query="q", results=results, provider="p1")
        fused = reciprocal_rank_fusion([("p1", resp)], limit=5)
        assert len(fused) == 5
