---
title: Examples
description: Working REST examples for search and fetch in curl, Python, and JavaScript.
---

These examples call a Docker setup on `localhost:8001`. Replace `fs_live_REPLACE_ME` with a project API key that has the `search.execute` and `fetch.execute` scopes ([Project API keys](/dashboard/api-keys/)), and replace `localhost` with your server's address if needed.

## curl

Search:

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"query": "solar panel prices", "limit": 5}'
```

Prefer one provider, and fall back to others if it fails:

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"query": "latest climate research", "limit": 5, "routing": {"mode": "prefer", "providers": ["exa"], "allow_fallback": true}}'
```

Ask two providers at the same time:

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"query": "latest climate research", "limit": 5, "fanout": true, "routing": {"mode": "fanout", "providers": ["exa", "tavily"]}}'
```

Fetch a page:

```bash
curl -X POST http://localhost:8001/fetch \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "max_chars": 8000}'
```

Add `-i` to see the `X-Trace-Id` response header.

## Python

This script uses only the standard library. It searches, then fetches the first result, and waits and retries once when the API answers `429`.

```python
import json
import time
import urllib.error
import urllib.request

BASE_URL = "http://localhost:8001"
API_KEY = "fs_live_REPLACE_ME"


def call(path, payload):
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt == 0:
                time.sleep(int(error.headers.get("Retry-After", "1")))
                continue
            raise RuntimeError(f"{error.code}: {error.read().decode()}") from error


search = call("/search", {"query": "solar panel prices", "limit": 5})
for result in search["results"]:
    print(result["title"], result["url"])

page = call("/fetch", {"url": search["results"][0]["url"], "max_chars": 8000})
print(page["document"]["content"][:500])
```

## JavaScript

This works in Node.js 18 or later. The API does not send CORS headers, so call it from a server, not from browser code, and keep the key out of client-side code.

```js
const BASE_URL = "http://localhost:8001";
const API_KEY = "fs_live_REPLACE_ME";

async function call(path, payload) {
  const response = await fetch(BASE_URL + path, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`${response.status}: ${await response.text()}`);
  }
  return response.json();
}

const search = await call("/search", { query: "solar panel prices", limit: 5 });
for (const result of search.results) {
  console.log(result.title, result.url);
}

const page = await call("/fetch", { url: search.results[0].url, max_chars: 8000 });
console.log(page.document.content.slice(0, 500));
```

## Error responses

Failures return JSON with a `detail` field.

```json
{ "detail": "execution is not permitted" }
```

A `429` includes a `Retry-After` header. The full list of status codes is in [Overview and auth](/api/overview/).

## Next steps

- [POST /search](/api/search/) and [POST /fetch](/api/fetch/): every request and response field.
- [Connect an agent](/mcp/connect/): the same operations as MCP tools.
