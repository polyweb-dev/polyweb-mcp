---
id: doc-000002
title: Projects specification - storage, tokens, limits and UX
type: specification
created_date: '2026-10-24T15:49:00Z'
updated_date: '2026-10-24T17:18:00Z'
tags:
  - projects-first
  - specification
---
# Projects specification - storage, tokens, limits and UX

Snapshot of .agents/communication/projects-feature-plan.md on 2026-10-24.

This Backlog-managed copy makes the accepted design available in other checkouts. All referenced sections retain their original numbers.

## 5. Proposed database model

Keep schema migrations small. Add the tables in their owning phase rather than one large initial migration.
Use UUIDs for durable identity, UTC timestamps, exact Decimal representations for funds, and explicit version columns.

### Project and access records

```text
accounts(id, status)  # one internal installation account for now
users(id, email, auth_provider, auth_provider_id, hashed_password,
      is_active, is_verified)  # one human identity, existing provider constraints
projects(id, account_id, name, slug, status, created_by, created_at, version)
project_memberships(project_id, user_id, status, version)
system_role_assignments(account_id, user_id, role_key, granted_by, version)
project_role_assignments(project_id, user_id, role_key, granted_by, version)
project_tokens(id, project_id, label, prefix, verifier_digest, scopes,
               created_by, created_at, expires_at, revoked_at, last_used_at)
```

Keep role definitions separate from role assignments. Each role definition declares its allowed scope and permissions.
Enforce project assignments against active project membership. A new membership receives its default role in the same transaction.
Bootstrap creates an ordinary human account and its `system_admin` assignment through the trusted local provisioning path.

Replace the old `user_superuser_matches_role` constraint. Neither `user.role` nor `is_superuser` remains a separate authority in the target design.
An adapter for library compatibility can derive a flag from RBAC when necessary, but it must not store an independent privilege decision.

Do not import old alpha account roles.
Retain historical actor IDs after account removal through tombstones or attribution snapshots.

### Configuration and provider records

```text
system_settings(namespace, schema_version, document, revision)
project_settings(project_id, namespace, schema_version, overrides, revision)
provider_credentials(id, provider_type, owner_scope, owner_project_id,
                     label, auth_mode, secret_reference, generation, status)
credential_project_grants(credential_id, project_id, permitted_operations, version)
project_provider_bindings(id, project_id, credential_id, route_label,
                          enabled_operations, priority, overrides, version)
upstream_quota_pools(id, provider_type, upstream_scope, constraints, version)
credential_pool_links(credential_id, pool_id, operation_scope)
project_pool_allocations(project_id, pool_id, operation_scope,
                         base_rate, window, borrow_enabled, max_rate,
                         weight, max_concurrency, queue_policy, version)
```

Keep provider catalog facts separate from runtime account observations and project allocations.
Preserve native balance pools, CRD conversion profiles, and per-operation cost semantics.
Link existing limit tables to credential and pool identities instead of duplicating a shared upstream balance per project.

### Ownership of operational data

- Project usage, execution admissions, rate attempts, and execution traces carry `project_id`.
- Execution records also carry actor type, actor ID, credential ID, binding ID, pool ID, and correlation IDs where applicable.
- A shared provider balance snapshot belongs to its upstream pool. Project usage attribution belongs to the consuming project.
- Shared credential health and provider-wide outages remain shared facts. Project views expose only permitted projections.
- System changes use an explicit system-scoped audit event. Project changes use a project-scoped audit event.
- Authentication failures before project resolution use a system security event, without a forged project association.

Do not attach every shared pool row to one arbitrary project to satisfy ownership.
Give every row an explicit ownership category: project, system, shared credential, or shared pool.

Use composite relationships where practical to prevent cross-project references.
Require project identifiers in project repository methods. Avoid optional scope parameters that silently select all projects.
Include project scope in pagination cursors, cache keys, exports, dashboards, and background jobs.

Enable foreign keys on every SQLite connection and inspect foreign-key integrity after migrations.
SQLite documents this connection-level requirement in its [foreign-key guide](https://www.sqlite.org/foreignkeys.html).
Do not rely on a simple SQL `CHECK` for the cross-row administrator invariant.

## 6. Project tokens and authentication

Issue opaque tokens with at least 256 bits of random secret material and a recognizable format.
Use a public lookup identifier plus a secret component. Store only a cryptographic verifier digest and sanitized metadata.
Use constant-time verification. Never store project tokens as decryptable provider secrets.

The issue response shows the secret once. Rotation creates a new token with an explicit overlap period.
Revocation takes effect on the next authorization and again before queued work dispatches.
For tokens with an expiration date, expiry prevents dispatch. Project suspension blocks tokens with either lifetime type.
Existing in-flight requests cannot always stop upstream work.

Store `expires_at` as nullable. An explicit API value of `expires_at: null` means no expiration.
An omitted creation field uses the documented default. Never substitute a default date for an explicit null.

Show No expiration in token creation and list views. Rotation preserves the lifetime choice unless the administrator explicitly changes it.
Tokens without expiration remain subject to revocation, scope checks, and project status checks on every execution.

Start with `search.execute` and `fetch.execute` token scopes. Project tokens cannot use account or control-plane management endpoints.
They do not inherit the creator's future roles. Removing a creator does not implicitly delete a project-owned token.
Show creator attribution so administrators can review and revoke these tokens explicitly.

Human playground calls use the browser's human session and project membership. They do not expose a project token to browser storage.
REST machine clients and MCP use project tokens. Stdio receives the token through the documented process credential channel.
An unknown, expired, or revoked token receives a generic authentication error.

Transport project selection cannot override token binding. A mismatched project identifier must fail before provider access.
MCP must revalidate each tool execution, including calls within a persistent session.
Do not advertise an OAuth flow that the project-token implementation does not provide.

Bearer security requires protection in storage and transit. Use the Authorization header and keep secrets out of URLs and logs.
See [RFC 6750](https://datatracker.ietf.org/doc/html/rfc6750) and the [OWASP secret lifecycle guidance](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).

## 7. Hierarchical limits and fair capacity loans

### 7.1 Define separate constraints

Separate upstream rate, project rate, concurrent requests, native funds, project spend, and queue capacity.
A request must satisfy every applicable constraint. A local project policy cannot expand upstream capacity.
Support aggregate installation and project budgets across provider pools, plus optional project limits for individual pools.
Keep ingress abuse controls separate from outbound provider limits. Credential creation never resets a pool's consumed allowance.

Use actual provider attempts as the rate accounting unit unless a vendor defines another unit, such as URLs.
One user search can produce several provider attempts. Each attempt consumes its own rate units.
Keep rate attempts separate from final billable units and native funds settlement.

Define whether each upstream constraint uses a rolling window, fixed window, or token bucket.
A 10/s token bucket with capacity 10 can admit close to 20 requests over some one-second intervals.
It does not implement a strict ten-request trailing window.
Use the configured algorithm in both enforcement and tests. [Azure throttling guidance](https://learn.microsoft.com/en-us/azure/architecture/patterns/throttling) describes these distinctions.

### 7.2 Strict mode first

For a shared upstream pool of 10 requests/second:

```text
Project A: base_rate=4/s, borrow_enabled=false, max_rate=4/s
Project B: base_rate=6/s, borrow_enabled=false, max_rate=6/s
Pool:      upstream_limit=10/s, explicit window semantics
```

A alone stops at 4/s in this mode. B's unused share remains unused.
Check and debit the project constraint and all upstream constraints in one atomic admission transaction immediately before dispatch.
Persist attempts so REST, MCP, and simultaneous workers observe the same aggregate allowance.

Use a unique attempt ID for reservation retries. A new upstream retry receives a new attempt ID under the same logical request.
Retain the rate debit when upstream receipt is uncertain.
Preserve idempotent native funds finalization separately.

### 7.3 Optional capacity loans

The system administrator can change A to `borrow_enabled=true`, `max_rate=10/s`, and weight 4.
B retains weight 6. Under sustained contention, their target shares are 40% and 60% of available service.
When B has no demand, A can use up to the pool limit. The pool's hard limit still applies.

The base rate becomes a contention entitlement in this mode. The maximum rate remains an absolute project ceiling.
For strict mode, the base rate is also the effective ceiling. Store these meanings explicitly in API contracts and labels.

Validate that promised base allocations fit every relevant shared constraint.
Reject infeasible guarantees. If capacity changes, flag overcommitment and publish the reduced effective allocation before further promises.
Projects with zero guaranteed share need an explicit best-effort policy. They must not obtain capacity through a zero-weight division edge case.

### 7.4 Use a fair scheduler, not a race for free tokens

Use bounded per-project queues and an authoritative scheduler per shared pool.
A first-come counter lets the fastest client consume idle capacity before another project can claim its share.
Two-tier counters alone do not provide fairness.

Choose weighted Deficit Round Robin for the first scheduler. Use one cost unit per actual provider attempt initially.
Keep cost estimation separate so later variable-cost scheduling can use URLs or another declared unit.
The [original DRR report](https://repository.library.washu.edu/cse_research/339/) supports efficient throughput fairness, not an unconditional latency guarantee.

Limit deficit accumulation for idle projects. Skip ineligible work without blocking unrelated pools.
Define a stable tie-break order and bounded service error in deterministic tests.
For the 4:6 equal-cost case, a continuously eligible ten-dispatch cycle targets four starts for A and six for B.

Guarantees apply over service intervals under sustained demand and available upstream capacity.
They do not promise exact 4/6 counts in every trailing second or successful provider responses.
Already-dispatched work cannot be preempted when another project returns.
These guarantees cover dispatch through this authority. External clients of the same upstream account consume capacity outside its control.
Allow an operator safety margin and reduce effective capacity after authoritative provider observations.

### 7.5 Make topology part of the contract

Current REST and MCP processes cannot each operate an independent fair queue for the same pool.
Atomic shared counters protect hard caps, but they do not provide a shared fair order.

Recommended initial topology: one execution authority hosts the adapter runtime, fair queues, and dispatch.
REST submits directly. MCP forwards execution to that authority with the original verified credential and trace context.
The API process is the simplest initial host. Extract a transport-neutral execution service first.

Standalone MCP can host the authority only in an exclusive single-runtime deployment.
Do not permit concurrent independent authorities for the same borrowed pool.
Authority failure stops new dispatch. A second replica cannot silently start with empty counters or a full burst bucket.

A later distributed coordinator can use Redis or another shared service.
Redis atomic scripts alone do not supply fair queue order or eliminate failover data loss.
Define durability, lease fencing, recovery pauses, and consistency before that extension.
See [Redis programmability](https://redis.io/docs/latest/develop/programmability/) and [replication semantics](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/).

### 7.6 Queue and failure policy

- Bound project and total queue counts, payload bytes, wait time, and in-flight concurrency.
- Admission validates and enqueues. Dispatch performs the final permission, grant, revision, and capacity checks.
- Remove canceled or expired queued work without a provider attempt debit.
- Give each logical request one end-to-end deadline for queue wait, retries, and fallback.
- Reenter the scheduler for every retry. Preserve project attribution and impose a retry budget.
- Respect provider `Retry-After` delays. Use bounded backoff and jitter when that header is absent.
- Keep rate exhaustion, spend exhaustion, queue saturation, and invalid credentials as separate error reasons.
- Fail closed for execution when the authoritative capacity store is unavailable.
- Cancel queued work on shutdown. Report a retriable outcome instead of claiming durable delivery.

Use monotonic time for local queue deadlines and waits. Use one authoritative clock for shared rate admission and durable timestamps.
Define conservative behavior for clock rollback and unknown in-flight attempts after a crash.
Do not release uncertain upstream concurrency solely because a worker lease expires.

Python provides bounded queues through [`asyncio.Queue`](https://docs.python.org/3/library/asyncio-queue.html).
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after) defines `Retry-After`.
Do not make automatic retries bypass existing terminal quota or fallback behavior.

## 8. Project-first API and desktop UX

Use explicit routes for control operations:

```text
/api/v1/projects
/api/v1/projects/{project_id}/members
/api/v1/projects/{project_id}/tokens
/api/v1/projects/{project_id}/settings
/api/v1/projects/{project_id}/providers
/api/v1/projects/{project_id}/traces
/api/v1/projects/{project_id}/usage
/api/v1/projects/{project_id}/search
/api/v1/projects/{project_id}/fetch
/api/v1/system/settings
/api/v1/system/credentials
/api/v1/system/quota-pools
```

Execution aliases can derive the project from a project token. They must never infer a human's project from the first membership.
Use one authoritative project selector per operation. Reject conflicting URL, token, or body context.
Use `401` for absent or invalid credentials and a consistent inaccessible-resource response for cross-project lookups.

Desktop routes use `/p/:projectId/playground`, `/routing`, `/usage`, `/activity`, and `/settings` under the same project prefix.
Keep `/account`, `/projects`, and `/system/...` outside project routes.
The project selector preserves the current screen where permissions permit it.

Use URL project identity for deep links and independent browser tabs.
A remembered last project is only a navigation preference. Validate membership before a redirect.
Users with no membership see an empty project list and an access message. They receive no automatic project creation privilege.

On a project switch, abort pending requests, stop old polls, clear old results, and reset unsaved project forms.
Key project stores and persisted drafts by `(account_id, project_id, schema_version)`.
Ignore stale responses even when cancellation loses a race. Keep human session state outside the project subtree.

Show effective settings with system/project provenance and an Inherit action.
Show project-member settings as read-only unless the effective permission permits an edit.
Keep project provider enablement separate from shared credential administration.
Token creation shows the secret once and permits an intentional copy action without persistence in application state history.

## 9. Trace, audit, and retention policy

Capture `project_id` and actor identity at the trusted execution boundary.
Propagate project identity to child spans and every fanout attempt. Do not accept tenant attribution from unverified trace baggage.
Project activity reads, detail routes, exports, counts, and pagination all use project scope.
Project trace access changes the current account-only visibility model. Document that permitted teammates can inspect new traces in the same project.

Allow project settings for sampling, detail, payload redaction, and retention within system policy.
Keep exporter destinations and encryption policy system-only.
Keep mandatory security audit events independent from optional request trace sampling.

Trace payloads can contain queries, URLs, and provider results. Default to metadata-only capture unless the deployment policy permits more detail.
Retention jobs select projects explicitly. A project administrator cannot purge another project's data through a global cleanup path.
Archive blocks new execution and token use but preserves configured audit and history retention.

Record membership, token lifecycle, credential grants, allocation changes, settings edits, copy operations, and support access in the audit log.
Exclude passwords, raw tokens, provider keys, OAuth grants, and sensitive response payloads.
The [OWASP logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) supports these event and redaction rules.
