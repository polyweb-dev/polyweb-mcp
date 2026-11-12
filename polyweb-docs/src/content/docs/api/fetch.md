---
title: POST /fetch
description: Request fields, response fields, and errors for the REST fetch endpoint.
---

`POST /fetch` reads one web page through the best available provider and returns its text. It needs a project API key with the `fetch.execute` scope ([Overview and auth](/api/overview/)). Brave has no fetch, so routing picks another provider. The MCP [`fetch` tool](/mcp/fetch-tool/) is the same operation.

```bash
curl -X POST http://localhost:8001/fetch \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "max_chars": 8000}'
```

Replace `fs_live_REPLACE_ME` with your key. The body is JSON, unknown fields are rejected, and one call reads one URL.

## Request body

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `url` | string (http or https URL) | yes | none | The page to read. |
| `max_chars` | integer | no | none | Cut the content after this many characters, 1 to 2000000. |
| `project_id` | UUID | with a sign-in token | the key's project | Optional with a project API key; if set, it must be the key's project. |
| `routing` | object | no | `{"mode": "auto"}` | Same object as for search: `mode`, `providers`, `allow_fallback`, `binding_id`. See [POST /search](/api/search/). To pin one provider for a call, send `{"mode": "require", "providers": ["exa"]}`. |
| `providerOptions` | object | no | none | Per-provider settings. They never change routing. See [Request options](/providers/request-options/). |
| `url_count` | integer | no | `1` | URLs to try, 1 to 10000. |
| `pdf_pages` | integer | no | `0` | PDF pages to read, 0 to 10000. |
| `json_extract` | boolean | no | `false` | Ask for parsed output, for providers that support it. |
| `enhanced` | boolean | no | `false` | Ask for a richer parse, for providers that support it. |
| `zero_data_retention` | boolean | no | `false` | Ask the provider to retain no data, for providers that support it. |

## Response body

| Field | Type | Meaning |
| --- | --- | --- |
| `provider` | string | The provider that fetched the page. |
| `document` | object | The page: `url`, `content` (the page text), `title` (or null), `content_type` (or null), `fetched_at` (ISO 8601 time), `metadata`. |
| `usage` | object or null | Measured usage when the provider meters the call. |
| `provider_metadata` | object | Provider extras. Present only when the provider returned some. |

```json
{
  "provider": "firecrawl",
  "document": {
    "url": "https://example.com/article",
    "content": "# Example\n\nPage text here.",
    "title": "Example",
    "content_type": null,
    "fetched_at": "2026-11-09T00:00:00Z",
    "metadata": {}
  },
  "usage": null
}
```

The response carries an `X-Trace-Id` header for the trace of this call.

## Errors

| Status | Cause | What to do |
| --- | --- | --- |
| `401` | Missing, invalid, expired, or revoked credential. | Use a valid key. |
| `402` | A provider is out of credits (the body names the `provider`), or a local budget denial. | Top up the provider or change routing. |
| `403` | The key lacks `fetch.execute`. | Create a key with the scope. |
| `404` | `project_id` is not a project you can use. | Omit it or use the key's project. |
| `409` | The project is archived. | Ask a project admin to unarchive it. |
| `422` | Invalid fields (for example a bad URL), or `project_id is required` with a sign-in token. | Fix the body. |
| `429` | Queue full, queue wait expired, deadline expired, or a rate limit. | Wait for `Retry-After`, then retry. |
| `502` | The provider could not fetch the page (target blocked, bot check, fetch failed, upstream error). | Try another provider or URL. |
| `503` | Storage or the execution service is unavailable. | Retry later. |

A `502` body looks like this:

```json
{
  "detail": "upstream error text",
  "provider": "firecrawl",
  "code": "fetch_failed",
  "status_code": 502
}
```

`status_code` is the provider's own status for the failure and may be `null`. The `code` value comes from the provider adapter.

## Next steps

- [Examples](/api/examples/): code in curl, Python, and JavaScript.
- [POST /search](/api/search/): find pages to read.
