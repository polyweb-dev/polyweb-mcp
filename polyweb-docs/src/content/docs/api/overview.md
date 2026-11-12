---
title: Overview and auth
description: Base URL, authentication, headers, and error codes for the Polyweb REST API.
---

The REST API runs `search` and `fetch` from your own code. If an AI agent does the work, use the [MCP server](/mcp/connect/) instead. Both run the same operations with the same request and response shapes.

## Base URL

With Docker the API server listens at `http://localhost:8001` (host port `API_PORT`). Replace `localhost` with your server's address if you call it from another machine. In a manual setup the port comes from `POLYWEB_API_PORT`. Interactive Swagger docs are at `/docs`, and the OpenAPI schema is at `/openapi.json`.

## Authentication

Every request needs an `Authorization: Bearer ...` header. There are no anonymous calls.

For `POST /search` and `POST /fetch`, use a project API key. It looks like `fs_live_<prefix>_<secret>` and belongs to one project. The key needs the `search.execute` scope to search and `fetch.execute` to fetch. You create keys on the project's API keys page ([Project API keys](/dashboard/api-keys/)).

```bash
curl -X POST http://localhost:8001/search \
  -H "Authorization: Bearer fs_live_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"query": "solar panel prices", "limit": 5}'
```

With a key, `project_id` in the body is optional. If you send it, it must be the key's own project.

You can also call `search` and `fetch` with a sign-in access token, as yourself. In that case `project_id` is required, and you need permission to run searches in that project. Get a token with the sign-in form (`username` holds the email):

```bash
curl -X POST http://localhost:8001/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you@example.com&password=YOUR_PASSWORD"
```

The response contains `access_token`, `refresh_token`, `token_type` (`bearer`), `expires_in` (900 seconds by default), and `refresh_expires_in` (604800 seconds by default). Send the access token as the Bearer value. Rotate it with `POST /auth/jwt/refresh`, sending the refresh token as the Bearer value. Project API keys are never accepted on account, control, or refresh routes, and sign-in tokens are never accepted by the MCP server. For the full picture, see [Authentication and keys](/concepts/authentication/).

## Routes for search and fetch

| Method and path | Purpose |
| --- | --- |
| `POST /search` | Search the web. See [POST /search](/api/search/). |
| `POST /fetch` | Read one URL. See [POST /fetch](/api/fetch/). |

Request bodies are JSON, capped at 1 MiB (larger bodies get `413` with `request body is too large`). Unknown fields in the body are rejected with `422`.

## Headers

| Header | Direction | Meaning |
| --- | --- | --- |
| `Authorization` | request | `Bearer fs_live_...` or a sign-in access token. A missing, duplicated, or non-Bearer header gives `401`. |
| `X-Polyweb-Deadline-Ms` | request, optional | Unix time in milliseconds by which you want the call to finish. It can only shorten the server's own timeout (300 seconds by default), never extend it. |
| `X-Trace-Id` | response | The 32-character hex id of the trace for this call. Find it on the **Activity** page ([Activity and traces](/dashboard/activity/)). |
| `Retry-After` | response, on `429` | Seconds to wait before you retry. |
| `WWW-Authenticate: Bearer` | response, on `401` | Standard challenge. |

## Errors

Errors are JSON with a `detail` field. All access checks run before any provider is called, so a rejected request costs nothing.

| Status | `detail` or body | Cause |
| --- | --- | --- |
| `401` | `not authenticated` | The credential is missing, malformed, invalid, expired, or revoked. |
| `402` | provider message, plus `provider` | A provider is out of credits. Or a local budget denial, where `detail` is an object describing the limit. |
| `403` | `execution is not permitted` | The key lacks the scope, or you lack permission in the project. |
| `404` | `project is unavailable` | `project_id` names a project you cannot use. |
| `409` | `project is archived` | The project is archived. |
| `413` | `request body is too large` | The body exceeds 1 MiB. |
| `422` | validation list, or `project_id is required` | Bad fields, or a sign-in token without `project_id`. |
| `429` | message, with `Retry-After` | A queue is full or timed out, the deadline expired, or a rate limit applies. |
| `500` | message | Every provider that was tried failed (search). |
| `502` | `detail`, `provider`, `code`, `status_code` | A provider could not fetch the page (fetch). |
| `503` | message | Storage or the execution service is unavailable. Retry later. |

Per-route details are on [POST /search](/api/search/) and [POST /fetch](/api/fetch/). For the difference between `402` and `429` limits, see [Rate limits and budgets](/concepts/limits-and-budgets/).

## Next steps

- [Examples](/api/examples/): curl, Python, and JavaScript.
- [Project API keys](/dashboard/api-keys/): create a key.
