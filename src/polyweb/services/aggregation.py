"""Reciprocal Rank Fusion (RRF) and URL canonicalization for multi-provider search.

Provides deterministic URL deduplication across search engines and principled
result ranking via Reciprocal Rank Fusion (RRF, Cormack et al., 2009).
"""

from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl

from polyweb.models.contracts import SearchResponse, SearchResult

_STRIP_QUERY_PARAMS = frozenset(
    {
        # Social & Ad Click Identifiers
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "twclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        # Referrals & tracking tokens
        "ref",
        "ref_src",
        "ref_url",
        "source",
        "_hsenc",
        "_hsmi",
        "__hssc",
        "__hstc",
        "hsCpsShared",
    }
)


def canonicalize_url(url: str | AnyHttpUrl) -> str:
    """Return a normalized, canonical URL string for deduplication across search engines.

    - Normalizes scheme to lowercase https (http -> https for matching)
    - Normalizes domain to lowercase and strips leading 'www.'
    - Strips default ports (:80, :443)
    - Strips trailing slash on path (preserving root '/')
    - Strips tracking / analytics query parameters (utm_*, fbclid, ref, etc.)
    - Alphabetically sorts remaining query parameters
    - Strips URL fragments (#section)
    """
    raw_str = str(url).strip()
    if not raw_str:
        return ""

    parsed = urlsplit(raw_str)
    scheme = parsed.scheme.lower()
    if scheme in ("http", "https"):
        scheme = "https"

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.endswith(":443"):
        netloc = netloc[:-4]
    elif netloc.endswith(":80"):
        netloc = netloc[:-3]

    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    filtered_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _STRIP_QUERY_PARAMS and not k.lower().startswith("utm_")
    ]
    filtered_params.sort(key=lambda item: (item[0], item[1]))
    new_query = urlencode(filtered_params)

    return urlunsplit((scheme, netloc, path, new_query, ""))


def reciprocal_rank_fusion(
    provider_results: Sequence[tuple[str, SearchResponse]],
    *,
    limit: int = 10,
    k: int = 60,
) -> list[SearchResult]:
    """Fuse and rank results from multiple search providers using Reciprocal Rank Fusion.

    Parameters:
        provider_results: Sequence of (provider_name, SearchResponse) tuples.
        limit: Maximum number of merged results to return (>= 1).
        k: RRF smoothing constant (default 60).

    Returns:
        List of fused SearchResult objects sorted by RRF score descending.
    """
    if not provider_results or limit <= 0:
        return []

    # Map canonical_url -> aggregated record dictionary
    records: dict[str, dict[str, Any]] = {}
    item_counter = 0

    # Count how many providers contributed at least one result
    active_providers = [name for name, resp in provider_results if resp.results]
    provider_count = len(active_providers) if active_providers else len(provider_results)

    for provider_name, response in provider_results:
        # Prevent a single provider from counting duplicate URLs twice
        seen_in_provider: set[str] = set()

        for rank_idx, item in enumerate(response.results, start=1):
            canon_key = canonicalize_url(item.url)

            if canon_key in seen_in_provider:
                continue
            seen_in_provider.add(canon_key)

            rrf_increment = 1.0 / (k + rank_idx)

            if canon_key not in records:
                records[canon_key] = {
                    "canonical_key": canon_key,
                    "first_seen_index": item_counter,
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                    "published_at": item.published_at,
                    "rrf_score": 0.0,
                    "sources": [],
                    "source_ranks": {},
                    "vendor_scores": {},
                    "extra_metadata": {},
                }
                item_counter += 1

            rec = records[canon_key]
            rec["rrf_score"] += rrf_increment
            if provider_name not in rec["sources"]:
                rec["sources"].append(provider_name)
            rec["source_ranks"][provider_name] = rank_idx

            if item.score is not None:
                rec["vendor_scores"][provider_name] = item.score

            # Retain the longest/richest snippet
            if len(item.snippet) > len(rec["snippet"]):
                rec["snippet"] = item.snippet

            # Retain non-empty title or longer title
            if not rec["title"] or (len(item.title) > len(rec["title"])):
                rec["title"] = item.title

            # Retain publication date if missing
            if rec["published_at"] is None and item.published_at is not None:
                rec["published_at"] = item.published_at

            # Merge any extra metadata (excluding internally managed keys)
            for mkey, mval in item.metadata.items():
                if mkey not in ("sources", "source_ranks", "rrf_score", "canonical_url"):
                    rec["extra_metadata"][mkey] = mval

    # Calculate theoretical maximum score (rank 1 across all active providers)
    max_possible_score = provider_count * (1.0 / (k + 1)) if provider_count > 0 else 1.0

    # Sort records: highest RRF score first, then most sources, then earlier appearance
    sorted_records = sorted(
        records.values(),
        key=lambda r: (
            r["rrf_score"],
            len(r["sources"]),
            -r["first_seen_index"],
        ),
        reverse=True,
    )

    fused_results: list[SearchResult] = []
    for rec in sorted_records[:limit]:
        raw_score = rec["rrf_score"]
        normalized_score = (
            min(1.0, max(0.0, raw_score / max_possible_score)) if max_possible_score > 0 else 0.0
        )

        metadata = {
            "sources": rec["sources"],
            "source_ranks": rec["source_ranks"],
            "rrf_score": round(raw_score, 6),
            "vendor_scores": rec["vendor_scores"],
            "canonical_url": rec["canonical_key"],
            **rec["extra_metadata"],
        }

        fused_results.append(
            SearchResult(
                title=rec["title"],
                url=rec["url"],
                snippet=rec["snippet"],
                published_at=rec["published_at"],
                source=", ".join(rec["sources"]),
                score=round(normalized_score, 4),
                metadata=metadata,
                sources=rec["sources"],
            )
        )

    return fused_results
