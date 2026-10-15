# Provider Search and Fetch API options

This document is the source of truth for provider-native Search and Fetch
options exposed by the FreeSearch REST API and MCP tools. It covers the
providers registered by FreeSearch on **2026-10-15**. The vendor links below
are their current official API references; update this document and the typed
request models together when those references change.

## FreeSearch request shape

`SearchRequest` keeps common fields (`query`, `limit`, `mode`, `language`,
`country_code`, and `domains`) and routing together. The optional
`providerOptions` object follows `routing` and precedes `fanout`:

```json
{
  "query": "latest climate research",
  "limit": 10,
  "routing": {
    "mode": "prefer",
    "providers": ["exa"],
    "allow_fallback": true
  },
  "providerOptions": {
    "exa": {
      "type": "deep-lite",
      "contents": {"highlights": true}
    }
  },
  "fanout": false
}
```

`FetchRequest` has the same optional `providerOptions` field immediately after
`routing`. Its provider entries are Fetch-specific. The old top-level `tavily`
object is removed; Tavily options now live at
`providerOptions.tavily`. Provider keys and their nested fields are optional,
strictly typed, and reject unknown fields. Options are passed only to the
provider selected by routing. They never select a provider or change routing.

Common request values continue to supply defaults where a provider has an
equivalent parameter: `limit` maps to its result/page count, `language` and
`country_code` map to the provider's locale fields, and `domains` supplies an
include-domain filter. An explicit provider option takes precedence over its
equivalent common default. For example, `providerOptions.you.include_domains`
replaces `domains` for You.com; it is not merged with the common list. Fields
without an upstream equivalent remain FreeSearch-only and are not forwarded.
`providerOptions` does not change `routing.providers`, routing mode, or
fallback behavior.

REST `POST /search` and `POST /fetch`, and the MCP Search and Fetch tools, are
public data operations. A Bearer token is optional; when supplied, it is
validated and its account can be attached to local traces. Anonymous calls
have no account attribution. Provider-level quota and rate admission still
applies, with server-configured provider credentials and shared budgets; there
is no per-caller spend cap. Account, trace, and provider-control routes remain
protected. Project-scoped API keys are outside this contract.

The shared `mode` and vendor modes are distinct contracts. Where both express
the same provider setting, an explicit nested option wins; Tavily rejects a
conflict between `mode` and `search_depth`. Parallel's historic
`extra_bundles` field remains accepted for contract compatibility, but the
current `/v1/search` API has no such field. A non-zero value is rejected as a
normalized `bad_request` before vendor I/O rather than silently discarded.
For Parallel, use `providerOptions.parallel.search_queries`,
`objective`, `mode`, and `advanced_settings.max_results` to control its
documented search request. `extra_bundles` does not affect routing or options.

Provider-native features which do not fit the normalized `SearchResult` or
`FetchedDocument` shape are retained in `provider_metadata` when returned by
the provider. Search result details that belong to an individual result stay
in that result's `metadata`. This preserves requested vendor details without
changing the common result shape. `provider_metadata` is optional and omitted
when no provider-specific response data is available.

## Supported providers

Option names below are FreeSearch's JSON field names (snake case inside the
exact outer key `providerOptions`). Adapters map them to the vendor's wire
names and value shapes. Common fields such as `query`, `limit`, `url`, and
`max_chars` are not repeated in each list.

### Brave (`brave`)

Official references: [Web Search](https://api-dashboard.search.brave.com/api-reference/web/search/get),
[LLM Context](https://api-dashboard.search.brave.com/api-reference/ai/llm_context/get).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `search_type` (`web` or `llm_context`), `api_version`, `country`, `search_lang`, `ui_lang`, `offset`, `freshness`, `safesearch`, `spellcheck`, `text_decorations`, `result_filter`, `units`, `goggles`, `extra_snippets`, `summary`, `enable_rich_callback`, `include_fetch_metadata`, `operators`, `no_cache`, `location` | `location` maps to Brave's `X-Loc-*` headers. `limit` maps to `count` (up to 20 for Web Search and 50 for LLM Context). `result_filter` accepts `discussions`, `faq`, `infobox`, `news`, `query`, `summarizer`, `videos`, `web`, and `locations`. `goggles` accepts one to three rules/URLs. `offset` is Web Search only. Context controls below apply only to `llm_context`. |
| Search (`llm_context` only) | `maximum_number_of_urls`, `maximum_number_of_tokens`, `maximum_number_of_snippets`, `maximum_number_of_tokens_per_url`, `maximum_number_of_snippets_per_url`, `context_threshold_mode`, `enable_local`, `enable_source_metadata` | LLM Context is Brave's query-driven retrieval/context endpoint, not an arbitrary URL fetch API or a separate Answers endpoint. `ui_lang`, `summary`, `text_decorations`, `result_filter`, and `offset` are Web Search-only. |
| Fetch | Not supported | Brave does not expose a general URL Fetch endpoint. Use another routed provider for Fetch. |

### Exa (`exa`)

Official references: [Search](https://exa.ai/docs/reference/search),
[Contents](https://exa.ai/docs/reference/get-contents).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `type` (`instant`, `fast`, `auto`, `deep-lite`, `deep`, `deep-reasoning`), `category`, `include_domains`, `exclude_domains`, `start_published_date`, `end_published_date`, `moderation`, `additional_queries`, `user_location`, `compliance`, `output_schema`, `objective`, `system_prompt`, `user_identifier`, `contents` | `limit` maps to Exa `numResults`. `contents` accepts `text` (boolean or `max_characters`), `highlights` (boolean or `query`, `highlights_per_url`, `num_sentences`, `highlights_text_length`), `summary` (boolean or `query`, `max_characters`), `extras` (`links`, `image_links`, `rich_image_links`, `rich_links`, `code_blocks`), `livecrawl_timeout`, `max_age_hours`, `snapshot_as_of`, `subpages`, `subpage_target`, `compliance`, and `user_identifier`. Search output schema is JSON-valued. |
| Fetch | `text`, `highlights`, `summary`, `extras`, `livecrawl_timeout`, `max_age_hours`, `snapshot_as_of`, `subpages`, `subpage_target`, `compliance`, `user_identifier` | Uses Exa Contents for the requested URL. The nested extraction options have the same shapes listed under Search `contents`. |

`compliance="hipaa"` and user identifiers have vendor-specific eligibility and
privacy constraints; see Exa's references. Streaming/SSE delivery is not
exposed through the normalized FreeSearch API.

### Firecrawl (`firecrawl`)

Official references: [Search](https://docs.firecrawl.dev/api-reference/endpoint/search),
[Scrape](https://docs.firecrawl.dev/api-reference/endpoint/scrape).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `sources` (`web`, `images`, `news`, `alexandria`), `domain_tools`, `tool_detail`, `categories` (`developer`, `gov`, `research`, `pdf`, as strings or `{type: ...}` objects), `include_domains`, `exclude_domains`, `tbs`, `location`, `country`, `safe`, `timeout`, `ignore_invalid_urls`, `highlights`, `enterprise` (one-element list: `anon` or `zdr`), `scrape_options`, `threat_protection` | `limit` maps to Firecrawl `limit`. Search can request scraped result content through `scrape_options`; its nested fields are listed under Fetch. `include_domains` and `exclude_domains` are mutually exclusive. `gov` cannot be combined with another category. Alexandria tool contracts and result sections without a normalized URL are preserved in `provider_metadata.data`. |
| Fetch | `formats`, `only_main_content`, `only_clean_content`, `include_tags`, `exclude_tags`, `max_age`, `min_age`, `headers`, `wait_for`, `mobile`, `skip_tls_verification`, `timeout`, `parsers`, `actions`, `location`, `remove_base64_images`, `block_ads`, `proxy`, `store_in_cache`, `lockdown`, `check_prompt_injection`, `redact_pii`, `profile`, `zero_data_retention`, `domain_tools`, `tool_detail`, `threat_protection` | Uses Firecrawl Scrape for the requested URL. `formats` accepts strings or typed format objects. Format objects support `type`, `prompt`, `schema`, `selector`, `attributes`, `full_page`, `quality`, `viewport`, `mode`, `question`, and `query`. Parsers configure `pdf`/`image`; actions configure documented browser actions; `redact_pii`, `profile`, and `threat_protection` use typed nested objects. |

Firecrawl's `question` scrape format is part of Scrape, not the separate
Firecrawl `/answer` endpoint. Crawl, batch scrape, monitors, agents, and other
non-Search/non-Scrape operations are outside the FreeSearch request surface.

### Keenable (`keenable`)

Official references: [Search](https://docs.keenable.ai/api-reference/search),
[Fetch](https://docs.keenable.ai/api-reference/fetch).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `mode` (`pro` or `realtime`), `site`, `acquired_after`, `acquired_before`, `published_after`, `published_before`, `query_time`, `snippet_max_length` | `limit` maps to Keenable `max_results`. |
| Fetch | `live`, `prompt` | `max_chars` maps to the Fetch endpoint's `max_chars`. `live` requests a fresh page instead of an indexed copy; `prompt` guides extraction. |

### Parallel (`parallel`)

Official references: [Search](https://docs.parallel.ai/api-reference/search/search),
[Extract](https://docs.parallel.ai/api-reference/extract/extract),
[Search advanced settings](https://docs.parallel.ai/guides/search),
[Extract advanced settings](https://docs.parallel.ai/guides/extract).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `search_queries`, `objective`, `mode` (`turbo`, `fast`, `basic`, `advanced`), `max_chars_total`, `session_id`, `client_model`, `advanced_settings` | `advanced_settings` contains `source_policy` (`include_domains`, `exclude_domains`, `after_date`), `fetch_policy` (`max_age_seconds`, `timeout_seconds`, `disable_cache_fallback`), `excerpt_settings.max_chars_per_result`, `location`, and `max_results`. `search_queries` are keyword queries; `objective` expresses the goal. |
| Fetch | `objective`, `search_queries`, `max_chars_total`, `session_id`, `client_model`, `advanced_settings` | Uses Parallel Extract. `advanced_settings` contains `fetch_policy`, `excerpt_settings.max_chars_per_result`, and `full_content` (boolean or `max_chars_per_result`). The shared single-URL Fetch contract is translated to the endpoint's URL list. |

Parallel's `/v1/search` does not document `extra_bundles`; non-zero
`extra_bundles` is rejected before the request. Parallel Task, Responses,
Image Search, and other endpoints are not part of this Search/Extract surface.

### Tavily (`tavily`)

Official references: [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `search_depth` (`basic`, `advanced`, `fast`, `ultra-fast`), `chunks_per_source`, `topic` (`general`, `news`, `finance`), `time_range`, `start_date`, `end_date`, `days`, `include_domains`, `exclude_domains`, `include_answer` (boolean or `basic`/`advanced`), `include_raw_content` (boolean or `markdown`/`text`), `include_images`, `include_image_descriptions`, `include_published_date`, `filter_by_published_date`, `include_domains_mode` (`restrict`/`prefer`), `language`, `filter_by_language`, `safe_search`, `auto_parameters`, `include_favicon`, `exact_match`, `country` | `limit` maps to `max_results`. Shared `mode` supplies the default depth; explicit `search_depth` takes precedence, and incompatible `basic`/`advanced` values are rejected. Usage reporting remains enabled by the adapter for metering. |
| Fetch | `extract_depth` (`basic` or `advanced`), `format` (`markdown` or `text`), `query`, `chunks_per_source`, `include_images`, `include_favicon`, `timeout` | Uses Tavily Extract for the requested URL. URL list and usage reporting are controlled by the adapter. |

Tavily `/answer`, map, crawl, research, and other endpoints are excluded from
this Search/Extract contract.

### TinyFish (`tinyfish`)

Official references: [Search API](https://docs.tinyfish.ai/search-api/reference),
[Fetch API](https://docs.tinyfish.ai/fetch-api/reference).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `purpose`, `location`, `language`, `include_domains`, `exclude_domains`, `recency_minutes`, `after_date`, `before_date`, `domain_type` (`web`, `news`, `research_paper`), `pub_year_min`, `pub_year_max`, `page` | TinyFish Search has no documented result-count parameter and returns its vendor-defined page size (currently 10); `limit` caps the normalized result list. `page` selects a zero-based page (0–10). `recency_minutes` cannot be combined with explicit date bounds. Publication-year filters apply to research-paper search. |
| Fetch | `purpose`, `format` (`markdown`, `html`, `json`), `links`, `image_links`, `iframe_links`, `ttl`, `per_url_timeout_ms`, `if_none_match`, `if_modified_since`, `include_etag_and_last_modified`, `include_selectors`, `exclude_selectors`, `highlights` | `highlights` accepts `query`, `max_snippets`, `max_characters`, and `include_full_page_text`. Shared `max_chars` truncates normalized content after fetch. FreeSearch Fetch currently sends one URL per call. |

### You.com (`you`)

Official references: [Search](https://you.com/docs/api-reference/search/v1-search),
[Contents](https://you.com/docs/api-reference/contents).

| Operation | FreeSearch provider options | Notes |
| --- | --- | --- |
| Search | `freshness`, `offset`, `country`, `language`, `safesearch` (`off`, `moderate`, `strict`), `knowledge` (`core`), `include_domains`, `exclude_domains`, `boost_domains`, `strict_operators`, `extraction`, `crawl_timeout`, `livecrawl`, `livecrawl_formats` | `limit` maps to `count`. `extraction` accepts `mode` (`highlights` or `full_page`), `source` (`blend`, `cache`, `fetch`), `highlights.total_max_tokens`, or `full_page.extraction_formats` (`html`, `markdown`). Domain include/exclude filters are mutually exclusive; `boost_domains` cannot be combined with `include_domains`. `livecrawl` options are deprecated by You.com but remain accepted by its current Search reference. |
| Fetch | `formats` (`markdown`, `html`, `metadata`), `crawl_timeout`, `max_age` | Uses You.com Contents for one URL. `formats` selects returned content and metadata representations. |

## Response contract

Provider-specific response details are available through the normalized
contract as follows:

* Search returns the shared `results` array. Per-result vendor fields such as
  images, score, highlights, or source data belong in `results[].metadata`.
* Fetch returns the shared `document`; vendor metadata belongs in
  `document.metadata`.
* Response-level identifiers, warnings, usage data, and unassociated vendor
  result sections are placed in optional `provider_metadata` when available.
* Existing common fields (`provider`, `usage`, `participating_providers`, and
  `waterfall`) retain their existing meanings. Provider options do not change
  the normalized response shape or routing trace.

MCP `search` and `fetch` use the same Pydantic request and response contracts
as REST. The REST OpenAPI schema and MCP JSON-schema therefore expose the same
`providerOptions` provider entries and validation rules.

## Model and adapter coverage

`src/freesearch/models/provider_options.py` defines the accepted nested
options. The operation-specific adapters are responsible for mapping those
fields to vendor wire names, preserving useful upstream response metadata,
and translating upstream errors into the FreeSearch error contract. Unknown
fields are rejected rather than passed through. Options that FreeSearch does
not expose are intentionally excluded until a typed mapping, normalization,
and test can be provided.

