---
title: POST /search
description: Request fields, response fields, and errors for the REST search endpoint.
---

`POST /search` runs one web search through the best available provider, or through several providers at once. It needs a project API key with the `search.execute` scope ([Overview and auth](/api/overview/)). The MCP [`search` tool](/mcp/search-tool/) is the same operation.

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"query": "solar panel prices", "limit": 5}'
```

Replace `fs_live_REPLACE_ME` with your key. The body is JSON, and unknown fields are rejected.

## Request body

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `query` | string | yes | none | Search text, 1 to 2000 characters. |
| `limit` | integer | no | `10` | Number of results, 1 to 100. |
| `project_id` | UUID | with a sign-in token | the key's project | Optional with a project API key; if set, it must be the key's project. |
| `routing` | object | no | `{"mode": "auto"}` | Provider selection, see below. |
| `fanout` | boolean | no | `false` | Ask several providers at the same time. |
| `providerOptions` | object | no | none | Per-provider settings. They never change routing. See [Request options](/providers/request-options/). |
| `mode` | `turbo`, `fast`, `basic`, or `advanced` | no | none | Depth hint, passed to providers that support it. |
| `extra_bundles` | integer | no | `0` | Extra result bundles, 0 to 10000, for providers that support it. |
| `language` | string | no | none | 2 to 16 characters, for providers that support it. |
| `country_code` | string | no | none | Exactly 2 characters, for providers that support it. |
| `domains` | array of strings | no | `[]` | Restrict results to these domains, for providers that support it. |

The `routing` object:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `mode` | `auto`, `prefer`, `require`, or `fanout` | `auto` | `auto` lets Polyweb choose. `prefer` tries `providers` first. `require` uses only `providers`. `fanout` queries `providers` together. |
| `providers` | array of strings | `[]` | Provider names, for example `exa` or `tavily`. |
| `allow_fallback` | boolean | `true` | Try other providers if the preferred one fails. |
| `binding_id` | UUID | none | Pin one project binding when the project has several keys for the same provider. |

See [Routing](/concepts/routing/) for how Polyweb chooses among providers.

## Response body

| Field | Type | Meaning |
| --- | --- | --- |
| `query` | string | The query that ran. |
| `results` | array | The hits. Each has `title`, `url`, `snippet`, `published_at`, `source`, `score` (0 to 1, or null), `metadata`, and `sources`. |
| `provider` | string | The provider that produced the answer. |
| `total_results` | integer or null | Total hit count when the provider reports one. |
| `participating_providers` | array of strings | Every provider that took part. |
| `waterfall` | array | One row per attempted provider: `provider`, `latency_ms`, `status`, `results_count`, `cost_credits`, `error`. |
| `usage` | object or null | Measured usage when the provider meters the call. |
| `provider_metadata` | object | Provider extras. Present only when the provider returned some. |

```json
{
  "query": "solar panel prices",
  "results": [
    {
      "title": "Example result",
      "url": "https://example.com/article",
      "snippet": "Short text from the page.",
      "published_at": null,
      "source": null,
      "score": 0.9,
      "metadata": {},
      "sources": []
    }
  ],
  "provider": "tavily",
  "total_results": null,
  "usage": null,
  "participating_providers": ["tavily"],
  "waterfall": [
    {
      "provider": "tavily",
      "latency_ms": 420,
      "status": "success",
      "results_count": 1,
      "cost_credits": 0.0,
      "error": null
    }
  ]
}
```

The response carries an `X-Trace-Id` header for the trace of this call.

## Errors

| Status | Cause | What to do |
| --- | --- | --- |
| `401` | Missing, invalid, expired, or revoked credential. | Use a valid key. |
| `402` | A provider is out of credits, or a local budget denial. | Top up the provider, change routing, or raise the budget. |
| `403` | The key lacks `search.execute`. | Create a key with the scope. |
| `404` | `project_id` is not a project you can use. | Omit it or use the key's project. |
| `409` | The project is archived. | Ask a project admin to unarchive it. |
| `422` | Invalid fields, or `project_id is required` with a sign-in token. | Fix the body. |
| `429` | Queue full, queue wait expired, deadline expired, or a rate limit. Upstream rate limits add `provider`, `code`, and `status_code` to the body. | Wait for `Retry-After`, then retry. |
| `500` | Every provider that was tried failed. | Retry, or change routing. |
| `503` | Storage or the execution service is unavailable. | Retry later. |

## Next steps

- [Examples](/api/examples/): code in curl, Python, and JavaScript.
- [POST /fetch](/api/fetch/): read a result page.
