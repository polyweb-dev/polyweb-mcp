---
id: doc-000001
title: Projects specification - identity, RBAC and ownership
type: specification
created_date: '2026-10-24T15:49:00Z'
updated_date: '2026-10-25T15:05:00Z'
tags:
  - projects-first
  - specification
---
# Projects specification - identity, RBAC and ownership

Snapshot of .agents/communication/projects-feature-plan.md on 2026-10-24.

This Backlog-managed copy makes the accepted design available in other checkouts. All referenced sections retain their original numbers.

## 1. Outcome and confirmed decisions

Projects become the primary workspace and the boundary for authorization, execution, settings, and activity. Human accounts exist outside projects. Project membership determines access.

The user confirmed these decisions:

- A person can belong to multiple projects, with a different role in each project.
- System administrators control global settings, credentials, and shared limits. Project administrators have separate authority.
- Project allocations use strict caps by default. A system administrator can permit capacity loans for each allocation.
- This task covers research and the plan. It does not include Groma architecture curation.
- System administrators create projects and assign the first project administrator.
- Project administrators can add private provider credentials and use explicitly granted global credentials.
- The product is in alpha. Prior accounts and history do not need preservation or conversion.
- Provider credentials and global settings can also be entered again. No old-data migration or import is necessary.
- Project tokens can have an expiration date or no expiration.
- Current implementation targets self-hosted use. Preserve future cloud compatibility without cloud-specific feature work now.
- Use one human account type. Administrator and member privileges come from scoped role assignments, not account classifications.

The requested feature also establishes these requirements:

- Project tokens replace agent accounts.
- A project can use several credential instances of the same provider.
- Projects can reuse global credentials without duplicate secret storage.
- Projects have separate available providers and enabled providers.
- Settings, traces, and limits support system scope and project scope.
- Administrators can copy permitted settings between projects.
- Project members can read project settings. Project administrators can assign extra project permissions through the common RBAC module.
- Every project retains at least one active human administrator.

## 2. Recommended defaults and decisions still open

Use these defaults for estimation. Confirm them before the relevant implementation phase.

1. **Token lifetime default:** Offer 90 days as the initial default and an explicit No expiration option.
   Token expiry is optional, as the user confirmed.
2. **Project lifecycle:** Archive projects first. Defer permanent deletion and its retention policy to separate work.
3. **Membership:** Start with administrator assignment of human accounts. Defer invitation email and external identity federation.
4. **System access:** System administrators manage the platform. Project content access requires membership or an explicit, audited support-access operation.

These defaults are proposals, not additional user-confirmed requirements.
The alpha decision removes Legacy projects, historical backfills, agent-account conversion, and legacy credential compatibility from implementation scope.

## 3. What exists today

The exploration used Antigravity `gemini-3.8-flash-medium` for repository inspection and Codex `gpt-6-luna`, maximum reasoning, for web research.
CodeGraph supplied source and call paths. Groma reports an uncurated first scan, so its map does not establish architectural facts.

### Accounts and access

- `src/freesearch/models/users.py` defines global `admin`, `developer`, and `agent` roles and `UserPrincipal`.
- `src/freesearch/services/users.py` implements human credentials, access JWTs, refresh tokens, and session families.
- `src/freesearch/routers/auth.py` contains global role guards. Account-management stubs explicitly wait for project association.
- `src/freesearch/infrastructure/auth_asgi.py` provides the Bearer middleware. `src/freesearch/mcp/auth.py` handles MCP authentication.
- MCP currently permits absent credentials on its public execution transport. Project-token enforcement changes that contract.

### Provider configuration and runtime

- `src/freesearch/configuration/provider_config.py` defines frozen provider configuration and the process-wide provider registry.
- `ProviderConfig` combines administrator enablement and system capability masks. Preserve that distinction for project access.
- `src/freesearch/infrastructure/encrypted_store.py` stores envelopes under `secret.enc:<name>`, with delete-wins tombstones under `secret.deleted:<name>`.
- Normal provider slots use provider names. Parallel OAuth also uses fixed secret slots in `src/freesearch/services/parallel_oauth.py`.
- `src/freesearch/routers/control.py` exposes global provider configuration and secret operations.
- REST in `src/freesearch/routers/api.py` and MCP in `src/freesearch/mcp/server.py` each construct their own adapter runtime.
- Both execution paths use routing, monitoring, and provider-limit services. Adapter identity still follows provider name.

### Limits and storage

- `src/freesearch/services/provider_limits.py` coordinates rate admission and native funds admission.
- `src/freesearch/services/rate_limits.py` reads durable attempts and observations. It is not a fair project scheduler.
- `src/freesearch/persistence/limit_repository.py` has transactional reservation behavior, including provider-specific safeguards. Generalize this seam rather than replace established accounting.
- `src/freesearch/persistence/limit_rows.py` stores catalogs, native pools, grants, events, admissions, observations, and rate attempts without project ownership.
- `src/freesearch/persistence/storage.py` stores runtime settings, usage, health, quotas, and trace spans. Trace reads currently use account identity.
- `src/freesearch/persistence/database_migrations.py` validates expected tables, columns, indexes, and foreign keys after upgrades.
- The inspected Alembic head is `0005_tinyfish_plan_label`. Allocate new revisions from the actual head at implementation time.

### Frontend

- `freesearch-ui/src/app/routes.ts` defines flat routes such as `/playground`, `/usage`, and `/settings`.
- `freesearch-ui/src/app/permissions.ts` derives permissions from the account's global role.
- `freesearch-ui/src/app/ProtectedWorkspace.tsx` and the FreeSearch context tree use account identity for workspace lifetime.
- `freesearch-ui/src/store/AppStoreProvider.tsx` persists playground state per account.
- `freesearch-ui/src/services/api/freesearchApi.ts` and `shared/api` provide request seams without project scope.
- Existing providers, routing, dashboard, and execution contexts need project scope. Do not replace them with one large project context.

### Backlog execution tickets

All twenty phases now have High-priority tickets with explicit dependency fields and phase labels.
Start with `TASK-000017` for P00. The full ticket map is Backlog document `doc-000005`, Projects execution index - start here.

On 2026-10-25, P04, P06, P11, P12, and P15 were split into tasklet tickets.
Downstream work now depends only on the tasklet that it needs. Section 11 gives the revised order.

The board reuses these original tickets rather than duplicating their work:

- `TASK-000004`: P15A, removal of agent accounts, anonymous execution, and legacy account types. `TASK-000038` contains the P15 strict cutover.
- `TASK-000005`: P12, project provider, settings, and limits UX.
- `TASK-000006`: P07, project tokens and authenticated machine execution.

Backlog documents `doc-000001` through `doc-000004` contain durable specification copies because this local plan directory is gitignored.
Keep dependencies, assignment, implementation plans, and evidence current through the Backlog CLI.
Ticket creation does not mark implementation started or acceptance criteria complete.

## 4. Architecture decisions

### 4.1 Keep system scope separate from project scope

Use an explicit system scope for platform policy and shared resources. Do not make Global a normal project.
A root project can blur membership, inherited access, shared billing, and authorization. This recommendation is an architectural inference, not a standards requirement.

Reuse typed settings contracts and resolution code across both scopes. A common settings abstraction does not require a common tenant identity.
Do not implement recursive project trees in this feature.

Authentication alone does not provide tenant isolation. Carry validated project context through all resource access.
This follows [AWS tenant-isolation guidance](https://docs.aws.amazon.com/whitepapers/latest/saas-architecture-fundamentals/tenant-isolation.html).

### 4.2 Separate human identity, project membership, and machine identity

Use a discriminated principal contract:

```text
HumanPrincipal(user_id, session_id)
ProjectTokenPrincipal(token_id, project_id, scopes)
ProjectContext(account_id, project_id, principal, effective_permissions, policy_revision)
```

Keep human passwords and browser refresh sessions in the existing account service.
Resolve project membership and current permissions from the database, not solely from old JWT claims.
Resolve token status and scope on every new execution request.

Project context must be immutable for one operation. Pass it explicitly through services and repositories.
A request-local context variable can assist trace attributes, but it must not provide the sole authorization check.
Background work carries an explicit project identifier and rechecks permission before dispatch.

### 4.3 One human account type and one scoped RBAC module

Human accounts store identity, authentication provider, and account status. They do not have `admin`, `developer`, or `agent` account types.
Remove the global `user.role` classification from the target account schema and API contracts.
The same person can hold different roles in different projects.

Use one permission catalog and one authorization service for system and project operations.
Evaluate `authorize(principal, action, scope, resource)` through that service in REST, MCP, background execution, and CLI paths.
Project settings can configure permitted role assignments and policy within system constraints. Avoid separate per-user permission switches scattered across features.

Start with built-in project roles `project_admin` and `project_member`.
Represent extra privileges as assignments of bounded capability roles, such as `routing_editor`, `provider_editor`, and `token_manager`.
Use `system_admin` as an explicit assignment at installation scope. It is a role on an ordinary human account, not another account type.
Keep the initial permission catalog and built-in role definitions in code. Defer arbitrary custom roles, a general policy language, and deny-rule engines.

Default role definitions and action names remain consistent across projects.
Each project has its own memberships and assignments. Extra project roles add permissions only within that project.
System policy constrains project RBAC configuration, so a project cannot redefine a role to grant system actions.

Project members can read sanitized settings, enabled-provider metadata, permitted usage, and project activity. They can execute search and fetch.
Project administrators can manage membership, project settings, tokens, and private credentials within system policy.
System administrators alone manage shared credential grants, pool capacity, allocation ceilings, and system roles.
They also provision human accounts. Project administrators add existing humans without global account-directory or password-reset authority.

Extra roles never grant system authority. A user cannot grant a permission they cannot delegate.
Membership removal removes all extra role assignments for that project. Project roles never affect global human account status.
The system administrator role does not implicitly create project memberships or bypass project content access policy.

Project API tokens remain separate machine principals. Their stored scopes pass through the same authorization service and resource policy.

Proposed permission names include:

```text
project.read                 members.read
settings.read                settings.write
providers.read               providers.configure
credentials.manage_private   tokens.manage
routing.write                traces.read
usage.read                   search.execute
fetch.execute                members.manage
roles.assign                 settings.copy
```

Enforce permissions in the backend before any side effect. Use the frontend for affordances, not authorization.
Return effective permissions to the frontend instead of duplicating role-to-permission logic in UI components.
Deny access by default and validate every request, as described in the [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

### 4.4 Protect the last administrator transactionally

Create a project and its first active administrator in one transaction.
Guard removal, demotion, membership suspension, account deletion, account deactivation, and bulk account operations.
An inactive user does not satisfy the administrator invariant.
Route CLI account changes through the same guard. Direct SQL is outside the supported mutation interface.

Use one SQLite write transaction with `BEGIN IMMEDIATE` before the administrator count.
For account-wide changes, inspect every affected project in the same transaction. Use bounded retries for database contention.
An administrator transfer adds the replacement and removes the old assignment atomically.
Count active human memberships with the required `project_admin` assignment, not a global account-role column.
Changes to protected administrator-role assignments use this guard too.

Return `409 LAST_PROJECT_ADMIN` when a change removes the last active administrator.
Apply this rule to archived projects too. A system administrator does not count without an explicit project-admin membership.

SQLite permits one writer at a time. Its [transaction documentation](https://www.sqlite.org/lang_transaction.html) supports this serialization strategy.
For PostgreSQL later, lock the affected project rows in a stable order before the same validation.

### 4.5 Separate provider type, credential instance, binding, and quota pool

Use these identities consistently:

- **Provider type:** Adapter implementation and capabilities, such as Tavily or Exa.
- **Credential instance:** One encrypted API key or OAuth account, with an owner, label, status, and generation number.
- **Credential grant:** System authorization for a project to use a global credential.
- **Project binding:** A project route that selects a credential instance and its permitted operations, priority, and enablement.
- **Upstream pool:** The actual shared quota boundary, which can cover multiple credentials and operations.

A binding must have its own identifier. A primary key of `(project_id, provider_type)` prevents multiple credentials of one provider.
Prefer a unique key of `(project_id, credential_id, route_label)` or an equivalent validated binding identity.

Projects cannot enumerate all global secrets. They see only explicitly granted metadata and their own private credential metadata.
An imported credential remains system-owned. Project administrators cannot read, rotate, delete, or reshare its secret.
Grant revocation disables future dispatch through affected bindings. Recheck grants after queue wait.

Credentials from one upstream account can share a quota pool. Additional keys do not automatically create additional capacity.
Keyless providers can also share IP-scoped pools across projects.
Provider-specific documentation determines the pool identity, not the local credential UUID.

Cache adapters by credential identity, generation, and relevant transport configuration.
Do not mutate a shared adapter with a project's settings between calls.
Separate credential authentication failures from provider-wide outages and project-local validation errors in circuit breakers.

### 4.6 Resolve available and enabled providers separately

Effective operation access is the intersection of:

```text
adapter capability
AND system permission for the provider/credential
AND valid ownership or explicit credential grant
AND project binding enablement
AND principal operation permission
AND current capacity and credential health
```

An available provider has a valid binding opportunity. An enabled provider has an explicit project choice to use it.
New grants start disabled. A system kill switch always wins over project overrides.
Disabling one project binding does not mutate the credential or another project's binding.

Expose provider type for vendor selection and binding ID for exact credential selection.
Preserve existing fallback semantics unless a separate, explicit policy changes them.
Every fanout leg and every retry consumes capacity for the same originating project.

### 4.7 Use typed settings with explicit inheritance

Resolve system defaults, then explicit project overrides, then enforce system constraints.
An absent override means inherit. A reset action removes the override.
Define `null`, empty arrays, and explicit false values per field. Do not treat them all as inherit.

Return each effective value with its source scope, revision, and override permission.
Use optimistic concurrency for edits and copy operations. A stale revision produces a conflict instead of silent overwrite.
Invalidate effective settings with system revision and project revision, including across REST and MCP processes.

Classify fields before implementation:

- **System only:** Encryption roots, authentication policy, shared credential grants, upstream capacity, allocation authority, exporter destinations, and safety limits.
- **Project override:** Routing preferences, permitted binding enablement, local timeout within policy, trace detail, sampling rate, and retention within policy.
- **System constrained:** Maximum execution concurrency, queue depth, deadline, spend, rate ceiling, and sensitive payload capture.

Do not apply a numeric minimum to every setting. Retention can have minimum and maximum rules.
The system schema must specify each field's resolution and validation rule.

### 4.8 Copy settings without copying authority

Provide a dry-run preview and an apply operation. Check source read permission and target copy/write permission separately.
Use source and target revisions to prevent a stale preview from applying unnoticed.

Copy selected routing preferences, nonsecret overrides, and permitted binding references.
For inherited values, offer explicit overrides-only and effective-snapshot modes. Default to overrides-only.
An effective snapshot pins values and stops future inheritance for those fields.

Never copy tokens, members, roles, raw secrets, usage, trace history, quota balances, or accumulated limiter state.
Do not copy a source project's private credential to the target.
Copy a global credential reference only if the target already has a valid grant.

Shared capacity allocations are authority, not ordinary settings. A project copy can propose an allocation but cannot grant it.
Reject or flag missing bindings in the preview. Apply the selected valid changes atomically and record the result in the audit log.

### 4.9 Preserve extension boundaries without cloud implementation

Keep authentication separate from project authorization. Preserve the existing local/WorkOS provider fields, password constraints, and internal user UUIDs.
Self-hosted authentication remains database-based. A future WorkOS adapter must resolve to the same internal identity before project permission checks.

Give each project an immutable owning `account_id`. Seed one internal account for the self-hosted installation.
Carry that ownership through project context and resource checks. This is a schema boundary, not an account-management feature.
Current Global settings and shared credentials belong to the installation's account, except explicit platform infrastructure policy.

Keep project roles separate from installation privilege. Resolve both through scoped assignments in the common RBAC module.
Do not tie project administrator membership to `is_superuser` or retain that flag as an independent source of authorization.
Keep secret ownership, effective settings resolution, and admission storage behind focused service/repository interfaces.
Future hosting can add authentication and storage adapters without replacing the project permission model.

Do not add cloud signup, organization administration, WorkOS callbacks, webhooks, SSO, billing, or distributed infrastructure to these phases.
Future cloud integration can require schema additions and adapters. The goal is to avoid changes across core project authorization and execution logic.
The separate `projects-cloud-auth-and-rate-review.md` contains research, deferred considerations, and data-structure comparisons.
