---
title: Request options
description: Pass provider-specific settings with providerOptions, and learn which defaults apply and which value wins.
---

`providerOptions` carries extra settings for one provider on one call. Use it when the common fields (`query`, `limit`, `url` and so on) are not enough. The accepted names for each provider are listed in the [provider reference](/providers/reference/).

## Add providerOptions to a request

Use the provider id as the key. `providerOptions` goes after `routing` on both `search` and `fetch`.

```json
{
  "query": "latest climate research",
  "limit": 10,
  "routing": {"mode": "prefer", "providers": ["exa"], "allow_fallback": true},
  "providerOptions": {
    "exa": {"type": "deep-lite", "contents": {"highlights": true}}
  }
}
```

A fetch call has the same shape, with fetch-specific options.

```json
{
  "url": "https://example.com/report",
  "max_chars": 8000,
  "routing": {"mode": "prefer", "providers": ["firecrawl"], "allow_fallback": true},
  "providerOptions": {
    "firecrawl": {"formats": ["markdown"], "only_main_content": true}
  }
}
```

The same JSON works on REST and on the MCP tools. The REST OpenAPI schema and the MCP tool schema list the same options.

## Rules

- Every provider key and every nested field is optional.
- Unknown fields are rejected with a `422` validation error. Names are snake case.
- Options go only to the provider that routing selects. Entries for other providers are ignored.
- `providerOptions` never picks a provider and never changes routing mode or fallback. Use `routing.providers` for that.
- The old top-level `tavily` object no longer exists. Use `providerOptions.tavily`.

## Defaults and precedence

Where a provider has an equivalent setting, the common fields fill it in for you.

| Common field | Becomes |
| --- | --- |
| `limit` | The provider's result or page count |
| `language`, `country_code` | The provider's locale fields |
| `domains` | An include-domain filter |

An explicit provider option always beats the common default. For example, `providerOptions.you.include_domains` replaces `domains` for You.com. The two lists are not merged.

Fields with no vendor equivalent are Polyweb-only and are not forwarded.

## Shared mode and vendor modes

The top-level `mode` (`turbo`, `fast`, `basic`, `advanced`) and a provider's own mode are separate settings. When both set the same thing, the nested option wins. Tavily rejects a conflict between `mode` and `search_depth`.

```json
{
  "query": "fusion power news",
  "limit": 5,
  "mode": "advanced",
  "routing": {"mode": "prefer", "providers": ["tavily"], "allow_fallback": true},
  "providerOptions": {"tavily": {"search_depth": "advanced", "topic": "news"}}
}
```

Changing `"mode"` to `"basic"` in this request fails with a `422` before any vendor call.

The `extra_bundles` field (default `0`, range 0 to 10000) is kept for compatibility. Leave it at `0`. Parallel rejects a non-zero value with a `bad_request` error before it calls the vendor. Use `providerOptions.parallel.search_queries`, `objective`, `mode` and `advanced_settings.max_results` instead.

## Provider extras in the response

Vendor details that do not fit the normal result shape come back in one of two places:

- `results[].metadata` for search, or `document.metadata` for fetch, holds details about one result or document, such as score, highlights or images.
- `provider_metadata` holds response-level details such as identifiers, warnings and usage. It is omitted when the vendor returns nothing extra.

`provider`, `usage`, `participating_providers` and `waterfall` keep their usual meaning. `providerOptions` does not change the response shape.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `422` naming a field | Unknown or misspelled option | Check the name in the [provider reference](/providers/reference/) |
| `422` on a Tavily search | `mode` and `search_depth` disagree | Make them match, or drop one |
| `bad_request` from Parallel | Non-zero `extra_bundles` | Set it to `0` or omit it |
| Options seem ignored | Routing selected a different provider | Check `provider` in the response and `routing.providers` in the request |

## Next steps

- [Routing](/concepts/routing/) explains how a provider is chosen.
- [POST /search](/api/search/) and [POST /fetch](/api/fetch/) list the common fields.
