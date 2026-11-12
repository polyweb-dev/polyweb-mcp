---
title: Provider reference
description: For each of the eight providers, what it is good for, how to get a key, and the options Polyweb accepts for search and fetch.
---

Each section covers one provider in the same order: what it is good for, how to get a key, then the options and quirks. Pass options under `providerOptions.<provider>` as described in [Request options](/providers/request-options/). Common fields (`query`, `limit`, `url`, `max_chars`) are not repeated below.

## Compare providers

The free allowances come from vendor research in October 2026. Vendors change plans often, so confirm on their site. For how limits behave in Polyweb, see [Rate limits and budgets](/concepts/limits-and-budgets/).

| Provider | `search` | `fetch` | Key | Free allowance |
| --- | --- | --- | --- | --- |
| `brave` | yes | no | Required | $5 of credits each month (card required) |
| `exa` | yes | yes | Required | $10 monthly grant plus a one-time $10 bonus |
| `firecrawl` | yes | yes | Required | 1,000 credits per month |
| `keenable` | yes | yes | Optional | Keyless is unmetered; a key adds 100,000 requests per month |
| `parallel` | yes | yes | Required | $5 of credits each month (card required) |
| `tavily` | yes | yes | Optional | 1,000 credits per month with a key |
| `tinyfish` | yes | yes | Required | `search` and `fetch` are free, with rate limits |
| `you` | yes | yes | Required | $100 one-time credit plus 100 searches per day |

"Optional" means Polyweb ships a built-in public credential, so the provider works with no setup. Add your own key for higher limits.

## How to add a key

Provider keys live in the encrypted vault, never in `.env`. After you get a key from the vendor, add it in the dashboard under **Keys and pools**, put it in a key pool, and bind the pool to your project. See [Provider keys and pools](/dashboard/provider-keys/).

## Brave

Good for plain web results (`search_type: "web"`) or query-driven context sized for an LLM (`search_type: "llm_context"`). Brave has no fetch.

**Get a key.** Create an account in the [Brave Search API dashboard](https://api-dashboard.search.brave.com/) and subscribe to a plan, even to use the free credits.

**Search options.** `search_type` (`web` or `llm_context`), `api_version`, `country`, `search_lang`, `ui_lang`, `offset` (0 to 9), `freshness`, `safesearch` (`off`, `moderate`, `strict`), `spellcheck`, `text_decorations`, `result_filter`, `units` (`metric`, `imperial`), `goggles`, `extra_snippets`, `summary`, `enable_rich_callback`, `include_fetch_metadata`, `operators`, `no_cache`, `location`.

Context options for `llm_context` only: `maximum_number_of_urls`, `maximum_number_of_tokens`, `maximum_number_of_snippets`, `maximum_number_of_tokens_per_url`, `maximum_number_of_snippets_per_url`, `context_threshold_mode` (`strict`, `balanced`, `lenient`, `disabled`), `enable_local`, `enable_source_metadata`.

**Quirks.**

- `limit` becomes `count`: up to 20 for `web`, up to 50 for `llm_context`.
- `ui_lang`, `offset`, `summary`, `text_decorations` and `result_filter` work only with `web`. Sending `summary` with `llm_context` fails validation.
- `result_filter` accepts `discussions`, `faq`, `infobox`, `news`, `query`, `summarizer`, `videos`, `web` and `locations`. `goggles` takes one to three entries.
- `location` maps to Brave's `X-Loc-*` headers. Give `latitude` and `longitude` together.

```json
{
  "query": "fusion power progress",
  "limit": 10,
  "routing": {"mode": "prefer", "providers": ["brave"], "allow_fallback": true},
  "providerOptions": {
    "brave": {"search_type": "llm_context", "maximum_number_of_tokens": 4096}
  }
}
```

## Exa

Good for semantic search, deep research queries and pulling page contents in the same call.

**Get a key.** Sign up at [dashboard.exa.ai](https://dashboard.exa.ai/). Free credits need no card.

**Search options.** `type` (`instant`, `fast`, `auto`, `deep-lite`, `deep`, `deep-reasoning`), `category` (`company`, `publication`, `news`, `personal site`, `financial report`, `people`), `include_domains`, `exclude_domains`, `start_published_date`, `end_published_date`, `moderation`, `additional_queries` (1 to 10), `user_location`, `compliance` (`hipaa`), `output_schema`, `objective`, `system_prompt`, `user_identifier`, `contents`.

`contents` accepts `text` (boolean or `{max_characters}`), `highlights` (boolean or `{query, highlights_per_url, num_sentences, highlights_text_length}`), `summary` (boolean or `{query, max_characters}`), `extras` (`links`, `image_links`, `rich_image_links`, `rich_links`, `code_blocks`), `livecrawl_timeout`, `max_age_hours`, `snapshot_as_of`, `subpages` (0 to 100), `subpage_target`, `compliance`, `user_identifier`.

**Fetch options.** The same extraction fields without the `contents` wrapper: `text`, `highlights`, `summary`, `extras`, `livecrawl_timeout`, `max_age_hours`, `snapshot_as_of`, `subpages`, `subpage_target`, `compliance`, `user_identifier`.

**Quirks.** `limit` becomes `numResults`. `deep-lite`, `deep` and `deep-reasoning` have lower vendor rate limits than `instant`, `fast` and `auto`. Streaming is not exposed.

```json
{
  "url": "https://example.com/report",
  "routing": {"mode": "prefer", "providers": ["exa"], "allow_fallback": true},
  "providerOptions": {"exa": {"text": {"max_characters": 5000}}}
}
```

## Firecrawl

Good for clean markdown from hard pages, with optional browser actions and structured extraction. Search can scrape each result too.

**Get a key.** Sign up at [firecrawl.dev](https://www.firecrawl.dev/). The free plan needs no card.

**Search options.** `sources` (`web`, `images`, `news`, `alexandria`), `domain_tools`, `tool_detail` (`compact`, `summary`, `full`), `categories` (`developer`, `gov`, `research`, `pdf`, as strings or `{type}` objects), `include_domains`, `exclude_domains`, `tbs`, `location`, `country`, `safe`, `timeout`, `ignore_invalid_urls`, `highlights`, `enterprise` (one-element list: `anon` or `zdr`), `scrape_options`, `threat_protection`.

**Fetch options.** `formats`, `only_main_content`, `only_clean_content`, `include_tags`, `exclude_tags`, `max_age`, `min_age`, `headers`, `wait_for`, `mobile`, `skip_tls_verification`, `timeout`, `parsers` (`pdf`, `image`), `actions`, `location`, `remove_base64_images`, `block_ads`, `proxy`, `store_in_cache`, `lockdown`, `check_prompt_injection`, `redact_pii`, `profile`, `zero_data_retention`, `domain_tools`, `tool_detail`.

**Quirks.**

- `formats` takes strings or objects with `type`, `prompt`, `schema`, `selector`, `attributes`, `full_page`, `quality`, `viewport`, `mode`, `question` and `query`.
- `include_domains` and `exclude_domains` are mutually exclusive. `gov` cannot be combined with another category.
- `threat_protection` is a search option. Fetch rejects it as an unknown field.
- `scrape_options` accepts the fetch fields above for each result.
- Only Search and Scrape are exposed. Crawl, batch scrape, monitors and agents are not.

```json
{
  "url": "https://example.com/docs",
  "routing": {"mode": "prefer", "providers": ["firecrawl"], "allow_fallback": true},
  "providerOptions": {"firecrawl": {"formats": ["markdown"], "only_main_content": true}}
}
```

## Keenable

Good for trying Polyweb with no signup. It works keyless, and a key adds a monthly allowance and removes the hourly cap.

**Get a key.** Optional. Create one in the [Keenable console](https://app.keenable.ai/console).

**Search options.** `mode` (`pro` or `realtime`), `site`, `acquired_after`, `acquired_before`, `published_after`, `published_before`, `query_time`, `snippet_max_length` (180 to 10000).

**Fetch options.** `live` (boolean, request a fresh page instead of an indexed copy), `prompt` (up to 2000 characters, guides extraction).

**Quirks.** `limit` becomes `max_results`, and `max_chars` is passed to the vendor. `realtime` mode and live fetches can cost more than one credit per call.

```json
{
  "query": "solar panel prices",
  "limit": 5,
  "routing": {"mode": "prefer", "providers": ["keenable"], "allow_fallback": true},
  "providerOptions": {"keenable": {"mode": "pro", "snippet_max_length": 500}}
}
```

## Parallel

Good when you can describe the goal in words. You give an `objective` and keyword `search_queries`, and Parallel returns excerpts.

**Get a key.** Create an account at [platform.parallel.ai](https://platform.parallel.ai/).

**Search options.** `search_queries`, `objective`, `mode` (`turbo`, `fast`, `basic`, `advanced`), `max_chars_total`, `session_id`, `client_model`, `advanced_settings`.

`advanced_settings` holds `source_policy` (`include_domains`, `exclude_domains`, `after_date`), `fetch_policy` (`max_age_seconds` of at least 600, `timeout_seconds`, `disable_cache_fallback`), `excerpt_settings.max_chars_per_result`, `location` and `max_results`.

**Fetch options.** `objective`, `search_queries`, `max_chars_total`, `session_id`, `client_model`, and `advanced_settings` with `fetch_policy`, `excerpt_settings.max_chars_per_result` and `full_content` (boolean or `{max_chars_per_result}`). Fetch uses Parallel Extract, and Polyweb turns the single `url` into the vendor's URL list.

**Quirks.**

- A non-zero top-level `extra_bundles` is rejected with `bad_request`. See [Request options](/providers/request-options/).
- Parallel supports OAuth keys, but that grant only reads the account balance (`balance:read`). An OAuth key cannot serve `search` or `fetch`, and a binding of one cannot enable either.

```json
{
  "query": "perovskite solar cell efficiency",
  "limit": 5,
  "routing": {"mode": "prefer", "providers": ["parallel"], "allow_fallback": true},
  "providerOptions": {
    "parallel": {"objective": "Find recent efficiency records", "mode": "fast"}
  }
}
```

## Tavily

Good for agent-oriented search with depth, topic and date controls. It works keyless for `search` and `fetch`.

**Get a key.** Optional. Sign up at [tavily.com](https://www.tavily.com/). Keys start with `tvly-`.

**Search options.** `search_depth` (`basic`, `advanced`, `fast`, `ultra-fast`), `chunks_per_source` (1 to 3), `topic` (`general`, `news`, `finance`), `time_range` (`day`, `week`, `month`, `year`, `d`, `w`, `m`, `y`), `start_date`, `end_date`, `days`, `include_domains`, `exclude_domains`, `include_answer` (boolean, `basic` or `advanced`), `include_raw_content` (boolean, `markdown` or `text`), `include_images`, `include_image_descriptions`, `include_published_date`, `filter_by_published_date`, `include_domains_mode` (`restrict` or `prefer`), `language`, `filter_by_language`, `safe_search`, `auto_parameters`, `include_favicon`, `exact_match`, `country`.

**Fetch options.** `extract_depth` (`basic` or `advanced`), `format` (`markdown` or `text`), `query`, `chunks_per_source`, `include_images`, `include_favicon`, `timeout` (1 to 60 seconds).

**Quirks.** The shared `mode` supplies the default depth, and an explicit `search_depth` wins. Conflicting `basic` and `advanced` values are rejected. Polyweb sets the endpoint, `max_results`, URL list and usage reporting itself. Crawl, map and research are not exposed.

```json
{
  "query": "fusion power news",
  "limit": 5,
  "routing": {"mode": "prefer", "providers": ["tavily"], "allow_fallback": true},
  "providerOptions": {"tavily": {"search_depth": "advanced", "topic": "news"}}
}
```

## Tinyfish

Good when you want search and fetch without a per-call charge. Both calls need a key.

**Get a key.** Create one at [agent.tinyfish.ai](https://agent.tinyfish.ai/). No card is needed to start.

**Search options.** `purpose` (up to 2000 characters), `location`, `language`, `include_domains`, `exclude_domains`, `recency_minutes`, `after_date`, `before_date`, `domain_type` (`web`, `news`, `research_paper`), `pub_year_min`, `pub_year_max`, `page` (zero-based, 0 to 10).

**Fetch options.** `purpose`, `format` (`markdown`, `html`, `json`), `links`, `image_links`, `iframe_links`, `ttl`, `per_url_timeout_ms` (1 to 110000), `if_none_match`, `if_modified_since`, `include_etag_and_last_modified`, `include_selectors` (1 to 20), `exclude_selectors` (1 to 20), `highlights`.

`highlights` accepts `query`, `max_snippets` (1 to 20), `max_characters` (100 to 20000) and `include_full_page_text`.

**Quirks.**

- Tinyfish has no result-count parameter. It returns its own page size (currently 10), and `limit` trims the list.
- `recency_minutes` cannot be combined with `after_date` or `before_date`. `pub_year_min` must not exceed `pub_year_max`.
- `max_chars` trims the content after the fetch. Each fetch sends one URL.

```json
{
  "query": "perovskite efficiency 2026",
  "limit": 5,
  "routing": {"mode": "prefer", "providers": ["tinyfish"], "allow_fallback": true},
  "providerOptions": {"tinyfish": {"domain_type": "research_paper", "pub_year_min": 2023}}
}
```

## You.com

Good for web search where you control how much page text comes back: short highlights or full pages.

**Get a key.** Create an account at [you.com/platform](https://you.com/platform). Keys look like `ydc-sk-...`.

**Search options.** `freshness`, `offset` (0 to 9), `country`, `language`, `safesearch` (`off`, `moderate`, `strict`), `knowledge` (`core`), `include_domains`, `exclude_domains`, `boost_domains`, `strict_operators`, `extraction`, `crawl_timeout` (1 to 60), `livecrawl` (`web`, `news`, `all`), `livecrawl_formats` (`html`, `markdown`).

`extraction` accepts `mode` (`highlights` or `full_page`), `source` (`blend`, `cache`, `fetch`), `highlights.total_max_tokens` (1024 to 8192) and `full_page.extraction_formats` (`html`, `markdown`).

**Fetch options.** `formats` (`markdown`, `html`, `metadata`), `crawl_timeout` (1 to 60), `max_age`.

**Quirks.**

- `limit` becomes `count`.
- `include_domains` and `exclude_domains` cannot be combined. `boost_domains` cannot be combined with `include_domains`.
- `highlights` settings need `extraction.mode: "highlights"`, and `full_page` settings need `extraction.mode: "full_page"`.
- `livecrawl` is deprecated by You.com but still accepted.

```json
{
  "query": "open source vector databases",
  "limit": 5,
  "routing": {"mode": "prefer", "providers": ["you"], "allow_fallback": true},
  "providerOptions": {"you": {"extraction": {"mode": "highlights"}}}
}
```
