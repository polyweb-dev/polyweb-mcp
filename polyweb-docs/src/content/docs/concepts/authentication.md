---
title: Authentication and keys
description: Sessions, project API keys, scopes, and which credential works where.
---

Polyweb has two kinds of credentials, and mixing them up is the most common auth error. A human session proves who you are. A project API key proves which project a machine acts for.

## Which credential works where

| Credential | Looks like | Works for |
| --- | --- | --- |
| Human session | Access token (15 minutes) and a refresh credential (7 days) | The dashboard, account and control routes, and REST `search` and `fetch` when the body includes `project_id` |
| Project API key | `fs_live_<prefix>_<secret>` | REST `search` and `fetch`, and the MCP `search` and `fetch` tools |

A project API key never reads accounts, traces, or control routes. A human session never works on MCP.

Neither route allows anonymous calls. Every `search` and `fetch` call needs one of the two.

## Sign in and register

Registering with an email and a password of 12 to 128 characters creates an ordinary account with no roles and no memberships. It does not sign you in. A system admin creates your project access, and only the CLI can create a `system_admin` (see [Admin accounts](/setup/admin-accounts/)).

Signing in returns an access token that lasts 900 seconds and a refresh credential that lasts 604800 seconds. Both lifetimes are configurable with `POLYWEB_AUTH_JWT_LIFETIME_SECONDS` and `POLYWEB_AUTH_REFRESH_LIFETIME_SECONDS`. Using a refresh credential once issues a new pair. Using it a second time revokes the whole family, which signs that session out.

Account auth needs `POLYWEB_AUTH_JWT_SECRET` with at least 32 random bytes. Without it, sign in and register fail. See [Configuration](/setup/configuration/).

Sign-in and registration are rate limited: 5 attempts per email and 20 per address in 15 minutes for sign in, and 5 per address and 100 per deployment in 15 minutes for registration. Too many attempts return `429` with a `Retry-After` header.

## Project API keys

Project admins and token managers create keys on a project's **API keys** page (see [Project API keys](/dashboard/api-keys/)). The full key is shown once, so copy it when you create it. If you lose it, rotate the key.

| Field | Meaning |
| --- | --- |
| `label` | A name for the key |
| `scopes` | `search.execute`, `fetch.execute`, or both. Omitting `scopes` grants both |
| `expires_at` | Omitted means 90 days. An explicit `null` means no expiry. A past time is rejected |

```json
{"label": "cursor-agent", "scopes": ["search.execute", "fetch.execute"]}
```

Send the key as a bearer token on every REST call and every MCP request:

```text
Authorization: Bearer fs_live_REPLACE_ME
```

Polyweb checks the key, its expiry, its scopes, and the project's archive state again on every call. Revoking a key stops it on the next request. With a key, `project_id` is optional. If you send one, it must be the key's own project.

Over the stdio MCP transport, the key comes from the `POLYWEB_MCP_BEARER_TOKEN` environment variable of the MCP process and is checked on every call.

## Errors

Every rejection happens before any provider is called, so a rejected call costs nothing.

| Problem | REST | MCP tool message | Fix |
| --- | --- | --- | --- |
| Unknown, expired, or revoked key | `401` | `authentication is required` | Create a new key |
| Human token sent to MCP | `401` | `authentication is required` | Use a project API key |
| Key without the needed scope | `403` | `execution is not permitted` | Create a key with the missing scope |
| `project_id` of another project | `404` | `project is unavailable` | Drop `project_id` or use the key's project |
| Archived project | `409` | `project is archived` | Ask a project admin to unarchive it |
| Wrong email or password | `400` | n/a | Check the credentials |
| Too many sign-in attempts | `429` | n/a | Wait for `Retry-After` |
| Auth secret missing or store down | `503` | n/a | Set `POLYWEB_AUTH_JWT_SECRET` and restart, or retry later |

Over HTTP, a bad key on the MCP endpoint is rejected with HTTP `401` before any tool runs.

## Next steps

- [Connect an agent](/mcp/connect/) puts a project API key into an MCP client.
- [Overview and auth](/api/overview/) shows the REST requests, including the sign-in endpoints.
- [Security](/reference/security/) explains how Polyweb stores and protects keys.
