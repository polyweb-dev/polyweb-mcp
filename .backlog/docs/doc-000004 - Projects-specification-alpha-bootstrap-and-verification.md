---
id: doc-000004
title: Projects specification - alpha bootstrap and verification
type: specification
created_date: '2026-10-24T15:49:00Z'
updated_date: '2026-10-24T15:57:00Z'
tags:
  - projects-first
  - specification
---
# Projects specification - alpha bootstrap and verification

Snapshot of .agents/communication/projects-feature-plan.md on 2026-10-24.

This Backlog-managed copy makes the accepted design available in other checkouts. All referenced sections retain their original numbers.

## 12. Alpha reset, schema evolution, and rollback

The user explicitly permits loss of prior history and accounts. Use a fresh-database cutover instead of a legacy migration project.
Do not create a Legacy project, backfill old records, convert agent accounts, or support old agent credentials.
The plan does not delete or modify the current database during research.

1. Build the project schema through small Alembic revisions. Keep schema validation metadata synchronized with each revision.
2. Use temporary fresh databases for each phase. Recreate disposable alpha fixtures when an intermediate contract changes.
3. Reject unsupported old database revisions with an actionable reset message. Do not silently adopt their accounts or provider settings.
4. Provision a new system administrator through a controlled local bootstrap operation.
5. Create projects and their first administrators atomically. Add global credentials and explicit grants, or project-private credentials.
6. Issue new project tokens through the authorized workflow. Reconfigure clients with those tokens.
7. Start project-first execution only after isolation, provider resolution, and atomic strict caps pass.

Provider credentials and settings need no import. Do not restore old users, execution history, authentication sessions, or provider secrets.
Retain Alembic for fresh-schema creation and schema validation. Old-data migration and backward-compatible upgrades are outside this alpha feature.
Never print secret material in schema or bootstrap output.

Once this feature stores new project data, normal schema evolution still requires safe upgrades and recovery.
Preserve new deletion tombstones, OAuth generations, native balances, CRD grants, attempt IDs, and recent rate consumption across restarts.
An alpha reset is a release operation. It is not a limiter recovery strategy.

For the alpha launch, retain a protected copy of the old installation only if useful to the operator.
A rollback to that separate installation does not preserve new project activity or reenable new project tokens.
After project adoption, prefer a forward fix or coordinated restore. Never run an old single-tenant application against the new project database.

## 13. Verification required for implementation

Use virtual time and fake providers for rate, fairness, retry, and deadline tests.
Use real temporary SQLite databases and independent connections/processes for atomic admission and membership race tests.
Do not test against the developer's live database or real provider credentials.

Required security cases include:

- A member in A and administrator in B receives only the selected project's permissions through the same human account.
- System administration is a scoped role assignment. Creating a human account does not implicitly grant it.
- REST, MCP, CLI, and queued execution agree on the common permission decision for the same principal, action, and scope.
- Cross-project IDs fail on detail, list, mutation, exports, counters, caches, and pagination.
- Concurrent account deactivation and membership removal preserve each project's active administrator.
- Role removal, grant removal, project archive, token revocation, and token expiry affect queued work before dispatch.
- A token never authorizes system or human account management.
- Credential rotation and OAuth refresh races cannot restore old or disconnected credentials.
- Project copy cannot expand grants, secret access, or allocation authority.
- All constrained dispatch paths reject missing authoritative storage.

Required capacity cases include:

- Strict A=4, B=6, shared=10, with both active and either project idle.
- A with loans enabled and maximum ten, both alone and under 4:6 contention.
- A late-arrival project after its neighbor consumed idle capacity.
- Multiple keys in one pool, multiple pools per operation, keyless shared IP limits, and mixed REST/MCP traffic.
- Cancellation, deadlines, queue saturation, retries, provider 429, fanout, fallback, and unknown dispatch outcomes.
- Native funds exhaustion, unknown balances, and CRD conversion behavior from existing suites.
- Restart and store failure without lost rate consumption or duplicate settlement.

Backend checks from the repository root:

```powershell
uv run ruff check src tests
uv run mypy
uv run pytest tests/unit
uv run pytest tests/integration
uv run behave tests/bdd/features
```

Run changed-area tests during each tasklet. Run the relevant full suites at each phase gate and cross-layer milestone.
Use `uv run freesearch-db status` and upgrades only against an explicitly selected temporary fixture database.
Read CLI help before database operations. The existing command is `status`, not `check`.

Frontend checks from `freesearch-ui/`:

```powershell
pnpm test
pnpm depcruise
pnpm knip
pnpm lint
pnpm typecheck
pnpm build
pnpm typecheck:e2e
pnpm test:e2e --project=chromium
```

The inspected Playwright project is `chromium`, with Desktop Chrome. Do not invent a `desktop` project or a `test:unit` script.
Keep one colocated `<basename>.test.ts` or `<basename>.test.tsx` per source file.
Preserve original suite provenance and case counts during relocations. Record deliberate additions and obsolete-contract replacements explicitly.
Require zero new findings in the frontend audit commands.

Launch services through `uv run freesearch-api`, `uv run freesearch-mcp`, and `pnpm dev`.
Use each workspace's local `.env` ports. Do not hardcode ports in code, test commands, or committed launch configuration.

## 14. Research basis and limits

The design combines source inspection, primary-source guidance, and explicit local design choices.
No external standard prescribes this exact schema, permission catalog, root-scope decision, or phase sequence.

- [AWS SaaS identity](https://docs.aws.amazon.com/whitepapers/latest/saas-architecture-fundamentals/saas-identity.html) supports tenant-aware identity context.
- [GitLab project access tokens](https://docs.gitlab.com/user/project/settings/project_access_tokens/) provide a product precedent for scoped tokens, expiry, and one-time disclosure.
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) offers future defense in depth. SQLite requires application scope enforcement today.
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) show why multiple API keys can share one upstream project quota.
- [Anthropic rate limits](https://platform.claude.com/docs/en/api/rate-limits) show that vendor algorithm semantics can differ from a local strict rolling window.

The pool abstraction applies to FreeSearch's current search providers too.
These LLM-provider examples illustrate quota scopes. They do not establish Tavily, Exa, or another search provider's numerical limits.
Keep existing provider documentation and observed-limit provenance authoritative for each supported adapter.

One exploration child reports a baseline result of 1,835 unit tests passed and one skipped.
This does not validate the proposed feature. The orchestrator did not repeat that suite or execute migration rehearsals and load tests.
The gates above specify evidence that coding agents must produce during implementation.
The main risks are incomplete scope propagation, incorrect shared-pool identity, uncoordinated dispatch, and incomplete bootstrap or token enforcement.
