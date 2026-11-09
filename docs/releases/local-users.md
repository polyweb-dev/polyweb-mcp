# Release note — Local users, backend slice

> **Superseded (TASK-000040):** the alpha baseline revision `0001_alpha_baseline`
> replaced the migrations described here. Polyweb MCP now refuses databases from
> these older revisions without changing them and prints reset steps; the
> upgrade, backup, and adoption instructions below no longer apply.

This release adds local accounts, account roles, session families, and
account-only trace reads to Polyweb MCP. It covers the backend only. The browser
login interface comes in a later release.

---

## 1. Scope

This release includes:

- local email and password accounts through the `fastapi-users` library
- JWT Bearer access for protected REST routes, with optional account context on public Search/Fetch
- three account roles: Admin, Developer, and Agent
- a protected refresh route, current-family logout, and login and registration limits
- account-only trace reads with the same HTTP 404 for every unowned record
- an operator CLI for Admin bootstrap and role assignment
- the Bearer guard, the role gates, the trace owner, and optional stdio account context

This release excludes WorkOS login, verification mail, password reset mail, an
OAuth authorization server, HTTP role management, provider tenant isolation, and
every frontend change.

---

## 2. Migration

Stop the API process and the MCP process before the migration.
Run the upgrade runner on the absolute database path.
Confirm the backup integrity result before application startup.

| Item | Value |
| :--- | :--- |
| Previous revision | `0003_open_telemetry_spans` |
| New revision | `0004_local_users` |
| New tables | `user`, `login_throttle`, `auth_sessions`, `refresh_tokens` |
| New columns | `user.role`, `user.auth_provider`, `user.auth_provider_id`, `trace_spans.user_id` |
| New indexes | the user email and provider keys, `auth_sessions_user_id`, `auth_sessions_expires_at`, `refresh_tokens_family_id`, `trace_spans_user_root_started_at` |
| Backup | `<database>.pre-alembic-<timestamp>-<discriminator>.bak`, integrity checked by the runner |

The runner keeps every current row. Historical trace rows keep a null owner and
stay outside every account read. The runner rejects a prior incompatible user
table. It never adopts that table.

The user table constrains the role values to `admin`, `developer`, and `agent`,
and the provider values to `local` and `workos`. The head check validates the
auth foreign keys through schema inspection and `PRAGMA foreign_key_check`.

The `trace_spans_user_root_started_at` index is partial: `(user_id, started_at,
span_id)` where `parent_span_id IS NULL`. The current trace indexes remain.

---

## 3. Backup

Stop both services before the release migration.
Resolve the absolute database target before each file operation.
Run `uv run polyweb-db upgrade` on that target.
Keep the backup and the master key outside the active database directory.
Restrict the backup to the operator.

The upgrade runner makes an integrity-checked copy of the database before it
changes the schema. The copy sits beside the active database. A master key loss
makes the encrypted provider vault unrecoverable, so the backup set must include
the key file.

---

## 4. Rollback

Stop both services before a production rollback.
Verify the absolute active path and the backup path.
Restore the integrity-checked pre-upgrade copy.
Restore the previous application release and its compatible master key.
Run the previous release's `polyweb-db status` check before startup.

Production rollback uses the backup, not a direct downgrade command. The
database CLI has no downgrade command. The integration suite exercises
`0004_local_users.downgrade()` on a temporary copy, and that test proves that the
old trace table and its rows survive.

A rollback removes the accounts, the session families, and the records of this
release. The operator must keep a separate copy of the current state before that
rollback.

---

## 5. Accounts, roles, and limits

Public registration creates an active local Agent account. The operator creates
Admin accounts through the trusted CLI. No first registration and no email match
grants Admin.

| Rule | Value |
| :--- | :--- |
| Password | 12 to 128 characters, with an upper-case letter, a lower-case letter, a digit, and a nonalphanumeric character |
| Login limits | 5 pair attempts and 20 peer-address attempts per 900 seconds |
| Registration limits | 5 attempts per peer address and 100 attempts per deployment per 900 seconds |
| Public auth body | 4096 bytes, measured on streamed bytes |
| Access token | JWT, HS256, audience `polyweb:auth`, 900 seconds |
| Refresh family | 604800 seconds absolute, from the password login |
| Refresh credential | opaque, 43 characters, single use, digest only in SQLite |

The limits use the actual peer address. A forwarded header never selects the
bucket, and a proxy policy needs separate operator configuration.

Public registration permits automated account creation and false email
addresses. The limits reduce that abuse. They do not stop a bot network, and a
shared NAT address can meet the peer limit. A billable public deployment needs
an operator-controlled provider-spend cap outside this release. This release
adds no CAPTCHA, no email challenge, and no per-account spend budget.

Roles:

- **Admin** can change provider controls, start or stop provider OAuth, and read
  the sanitized control views.
- **Developer** can read the sanitized control views, the statistics, and the
  dashboard.
- **Agent** can search, fetch, and read its own records only.

Every role reads only its own traces. An absent, foreign-owned, or historical
unowned trace gives the same HTTP 404.

REST `POST /search` and `POST /fetch` are public data operations. The MCP
Streamable HTTP transport exposes its Search and Fetch tools publicly on `/mcp`;
stdio also permits anonymous calls. A supplied Bearer credential is verified,
and a valid account is attached to trace records. An invalid supplied token is
rejected. Anonymous activity has no account attribution, so account-only trace
reads do not include it. Provider quota and rate admission still applies to all
calls, and all callers share the configured provider credentials and budgets;
this release adds no per-caller spend cap. Account, trace, and provider-control
routes remain protected.

Reuse of a consumed refresh credential revokes the whole family. Logout revokes
the current family. A role change revokes every family of that account. An
ordinary API call and an ordinary MCP call never extend an access token.

A custom ASGI guard enforces the access JWT before routing, instead of a
per-route dependency. The OpenAPI document therefore publishes the Bearer token
scheme with the login route as its token URL, so a discovery client can find
`auth/jwt/login`, and no single operation carries a security requirement.

---

## 6. Operator CLI

Run the commands from the worktree root.

```powershell
uv run polyweb-db status
uv run polyweb-db upgrade
uv run polyweb-users create-admin --email admin@example.com
uv run polyweb-users set-role --user-id <account-uuid> --role developer
```

The CLI reads the password from a masked terminal prompt. It refuses a password
argument, a missing terminal, a missing database file, and a duplicate email. It
prints only the account UUID and the role, and every failure uses one fixed
message.

The CLI resolves the database path through the shared precedence rule and
requires a file that is present. It opens the shared database and applies every
migration that is not yet applied, through the same runner as the API. A failed
promotion leaves a least-privileged Agent account, and the CLI reports that
state. It never claims a successful Admin creation.

---

## 7. Stdio MCP policy

The stdio transport accepts anonymous Search and Fetch calls. To attribute a
call to an account, set `POLYWEB_MCP_BEARER_TOKEN` in the child process
environment. That optional value comes from the process environment only, so
the local environment file cannot supply an account credential.

If configured, the child verifies the access token and live account at each
tool call. An expired, revoked, or deactivated credential stops that tool call,
and no provider call happens after a rejected check. Do not give the child a
refresh credential, a password, or an Admin credential.

The access lifetime is 900 seconds, the same value as the API. Renew the token
in the parent and restart the child after expiry if account attribution is
required.

---

## 8. Launch commands and checks

Launch both transports without a fixed port.

```powershell
uv run polyweb-api
uv run polyweb-mcp
```

`POLYWEB_API_PORT` and `POLYWEB_MCP_PORT` in the gitignored `.env` file
supply the binds. A missing port stops that transport at startup.

### Setup of the account secret

The account routes need one signing key. Set `POLYWEB_AUTH_JWT_SECRET` in the
gitignored `.env` file, or export it in the shell before the launch. Generate a
value with at least 32 random bytes:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

An absent, empty, or short value leaves every account route at HTTP 503. The
browser then shows its configuration state message instead of a sign-in form, and
it names this variable in that message. `POST /auth/register`,
`POST /auth/jwt/login`, and the refresh route all answer
503 until the value is present and the API process restarts.

Keep the real value in the local environment file and out of the commit, the
logs, and the browser. `.env.example` holds the empty placeholder only.

| Check | Command | Result |
| :--- | :--- | :--- |
| Format | `uv run ruff format --check src tests` | `205 files already formatted` |
| Lint | `uv run ruff check src tests` | `All checks passed` |
| Types | `uv run mypy` | `Success, 66 source files` |
| Unit | `uv run pytest tests/unit -q` | `1191 passed, 1 skipped` |
| Integration | `uv run pytest tests/integration -q` | `587 passed` |
| Unit and integration | `uv run pytest tests/unit tests/integration -q` | `1778 passed, 1 skipped` |
| BDD offline | `uv run behave --tags="not @live"` | `15 features passed, 158 scenarios passed, 0 failed` |

The migration proof covers a fresh database, a second upgrade, a downgrade to
`0003_open_telemetry_spans`, and a re-upgrade. The trace table keeps every row
through the downgrade of its new column. The account table rejects seven invalid
row shapes and accepts both valid shapes.

The account CLI proof covers 39 checks on real SQLite. The checks cover these
cases:

- a password argument and a usage error
- a missing database and a missing terminal
- a successful bootstrap, a weak password, and a duplicate email
- a role change, family revocation, and a repeated assignment
- an unknown UUID, a malformed UUID, and an unknown role

---

## 9. Browser refresh transport (Users UI, turn 1)

The API answers two credential transports on the same auth routes.

A request without browser evidence keeps the programmatic contract. The response
holds one JSON credential pair, and `POST /auth/jwt/refresh` accepts the opaque
refresh credential in the `Authorization` header. The MCP transport and every
API client keep that contract.

A request with browser evidence keeps the refresh credential in one strict
cookie. The cookie name is `__Secure-polyweb_refresh`, and the cookie path is
`/auth/jwt/refresh`. The cookie uses `HttpOnly`, `Secure`, and `SameSite=Strict`,
and it carries no `Domain` attribute, so it stays host-only. The browser response
omits the `refresh_token` key. The guard accepts this cookie on the refresh route
only, so no cookie authenticates an ordinary API or MCP call.

Browser evidence needs one exact allowed origin and the `X-Polyweb MCP-Client:
browser` marker. Set `POLYWEB_AUTH_BROWSER_ORIGINS` to the exact origin list.
An empty list disables browser cookie transport. A failed evidence check returns
HTTP 403 before any credential issue, rotation, or family revocation. The cookie
is host-only, so it ignores the port: use a separate browser context or a
distinct local host name for concurrent worktrees.

The browser client reaches the account routes through the same-origin Vite
proxy. It keeps the access credential in memory only, and it renews that
credential under one Web Lock for the origin. `DELETE /auth/jwt/refresh` ends a
browser session after the access credential expires.

HTTPS is mandatory outside loopback development. A `Secure` cookie needs a
secure context, and the browser rejects it over cleartext.

The login, register, account, and account-creation screens, and per-account
playground storage, follow in the later sections of this document. This turn
claims no XSS protection and no CSRF protection beyond the exact origin check,
the client marker, and the strict cookie.

---

## 10. Browser client (Users UI, turn 2)

The dashboard client now owns a session.

`/login` and `/register` stay outside the protected workspace, so an anonymous
visitor mounts no control read. Every other path passes one session gate. The
gate completes one cookie restore and one `GET /users/me` before it mounts the
business providers, and it shows a retry view when the restore fails for a
network or server reason. An anonymous deep link returns to `/login` with the
internal destination, and the login screen accepts a destination from the
current route set only.

The client keeps the access credential in module memory. It holds no credential
in Redux, in `redux-persist`, in `localStorage`, in `sessionStorage`, in
`IndexedDB`, in a URL, or in browser history. One refresh promise serves every
caller in a tab, and one Web Lock serializes cookie rotation across the tabs of
one origin. A `BroadcastChannel` carries a session-change hint only. A browser
without Web Locks or `BroadcastChannel` receives a compatibility error before
any cookie request.

This app removes the global account list, creation, lookup, deactivation, and
role-change routes. Public registration and `GET /users/me` remain available.

One permission helper controls navigation and route access. Project permissions
control access to project pages, including Providers, Playground, and Activity.
System permissions control access to global pages and the account key vault.
Provider routing order is on the project Providers page.

The playground snapshot now uses one key per account:
`polyweb:playground:v1:<account-uuid>`. The client discards the legacy
unowned snapshot without assigning it to an account, and it remounts the store
when the account changes. This isolation prevents accidental cross-account
rehydration through this UI. It does not protect stored results against local
device access or against a script that runs in the page, and the stored results
stay unencrypted.

---

## 11. Open signup and account provisioning (Users UI, turn 2)

Signup is open for all three roles.

The register screen offers `Admin`, `Developer`, and `Agent`, and it starts on
`Agent`. The server accepts each role value in every deployment, including
localhost. An omitted role keeps the Agent default, so an older client holds its
current contract. The server keeps the accepted password rule, the 4096-byte body
cap, and the five-per-peer and 100-per-deployment attempt limits of public
registration.

The account model is a provisioning model, as in AWS and Azure. An Admin creates
new accounts of all three roles through the account-creation screen. One Admin
holds no authority over an existing account: the creation screen loads no target
and changes no stored role. The legacy lookup and role-change paths return HTTP
403 with the detail `account management is not available before project
association` for every authenticated caller, including an Admin and a caller that
names itself. That denial reads no account and revokes no session family.

The authenticated route shares the public attempt counters. It reserves one
attempt before any password hash work, and it starts no reservation for a
forbidden non-Admin request. A duplicate email and an invalid password return the
current registration errors. A storage failure returns HTTP 503.

Creation stays standalone in this cycle. The repository has no project identity
and no membership seam, so an account has no project membership and no
association with another account. Project association follows in a later cycle.

The login and register screens reuse the current palette, type, button, field,
card, and footer classes. This slice adds no component library and no visual
system.

---

## 12. Release boundary

This release covers the backend slice, the browser refresh transport, the browser
client, the role permissions of the control views, and the open-signup and
provisioning policy of this cycle. Local secrets and the local environment file
stay outside the commit.

The commit gate needs the API end-to-end suites, the complete offline suite, the
static checks, and Reviewer acceptance.
