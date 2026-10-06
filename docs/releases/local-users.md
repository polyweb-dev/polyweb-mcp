# Release note — Local users, backend slice

This release adds local accounts, account roles, session families, and
account-only trace reads to FreeSearch. It covers the backend only. The browser
login interface comes in a later release.

---

## 1. Scope

This release includes:

- local email and password accounts through the `fastapi-users` library
- JWT Bearer access for the REST API and for the MCP surfaces
- three account roles: Admin, Developer, and Agent
- a protected refresh route, current-family logout, and login and registration limits
- account-only trace reads with the same HTTP 404 for every unowned record
- an operator CLI for Admin bootstrap and role assignment
- the whole-application Bearer guard, the role gates, the trace owner, and the stdio credential handoff

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
Run `uv run freesearch-db upgrade` on that target.
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
Run the previous release's `freesearch-db status` check before startup.

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
| Access token | JWT, HS256, audience `freesearch:auth`, 900 seconds |
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
uv run freesearch-db status
uv run freesearch-db upgrade
uv run freesearch-users create-admin --email admin@example.com
uv run freesearch-users set-role --user-id <account-uuid> --role developer
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

The stdio transport needs an explicit access JWT in
`FREESEARCH_MCP_BEARER_TOKEN`. That value comes from the process environment
only, so the local environment file can never supply an account credential.

Give the child process only that credential.
Renew the access JWT in the parent and restart the child after expiry.
Do not give the child a refresh credential, a password, or an Admin credential.

The child verifies the token and the live account at each tool call. The access
lifetime is 900 seconds, the same value as the API. An expired, revoked, or
deactivated credential stops tool access, and no provider call happens after a
rejected check.

---

## 8. Launch commands and checks

Launch both transports without a fixed port.

```powershell
uv run freesearch-api
uv run freesearch-mcp
```

`FREESEARCH_API_PORT` and `FREESEARCH_MCP_PORT` in the gitignored `.env` file
supply the binds. A missing port stops that transport at startup.

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

## 9. Release boundary

This release covers the backend only. The user accepted UI work as a later
cycle. The commit holds the backend slice, the migration, and this note. Local
secrets and the local environment file stay outside the commit.

The commit gate needs the API end-to-end suites, the complete offline suite, the
static checks, and Reviewer acceptance.
