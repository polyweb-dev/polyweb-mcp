---
id: doc-000003
title: Projects specification - phase gates and execution order
type: specification
created_date: '2026-10-24T15:49:00Z'
updated_date: '2026-10-24T17:18:00Z'
tags:
  - projects-first
  - specification
---
# Projects specification - phase gates and execution order

Snapshot of .agents/communication/projects-feature-plan.md on 2026-10-24.

This Backlog-managed copy makes the accepted design available in other checkouts. All referenced sections retain their original numbers.

## 10. Delivery phases

Each phase has a stable end state and its own acceptance evidence.
Target one focused agent assignment per tasklet and one or two small PRs per phase.
Do not combine all schema, authorization, provider, UI, and scheduler changes into one phase.
If a phase exceeds that size, split its tasklets before implementation.

### P00 — Contract and alpha baseline

**Dependency:** None. **Backlog:** Refine `TASK-000004`, `TASK-000005`, and `TASK-000006`.

Define the permission catalog, ownership inventory, API contracts, configuration fields, and feature rollout states.
Specify one human account contract and the shared system/project RBAC decision interface before implementation.
Confirm open decisions and capture current auth, routing, rate, and frontend case counts.
Prepare fresh-database fixtures and an explicit alpha reset/bootstrap procedure.

**Gate:** Reviewers can map every persistent table, cache, endpoint, and job to an ownership scope.
Define first-system-administrator provisioning. No application behavior changes in this phase.

Use explicit rollout states: `PROJECTS_PREVIEW`, `PROJECTS_STRICT`, and `PROJECTS_FAIR`.
Until P15, use preview mode with fake adapters and fixture databases for project execution.
The alpha release replaces the old installation at cutover. Do not expose incomplete tenant isolation through a UI-only restriction.

### P01 — Project and membership schema

**Dependency:** P00.

Add projects, memberships, scoped role assignments, and repositories with strict project parameters.
Preserve authentication-provider constraints while removing account-type role fields from the fresh target schema.
Seed one internal installation account and record its ownership on projects. Add no account-management UI or customer-role workflows.
Update schema validation metadata and fresh-database creation behavior.
Add explicit system-administrator provisioning and atomic project creation with a selected active project administrator.

**Gate:** Fresh install, repeated bootstrap, foreign-key checks, and schema validation pass on temporary databases.
An empty installation exposes a controlled bootstrap path. It never grants administrator authority through public registration.

### P02 — Project lifecycle and authorization service

**Dependency:** P01.

Add project list/create/archive and membership read/change endpoints behind the rollout state.
Implement the common RBAC service, built-in scoped roles, extra role assignments, delegation limits, and live authorization checks.
Guard all administrator-affecting operations in write transactions.

**Gate:** Two simultaneous removals or demotions cannot remove both administrators.
Account deactivation checks every affected project. A project administrator cannot alter system roles or unrelated human accounts.
An ordinary human account can receive different project roles without a change to its identity or authentication provider.
All authorization paths use the common service. No account-type or superuser shortcut bypasses it.

### P03 — Project context and typed settings storage

**Dependency:** P02.

Add `ProjectContext`, project-aware repository facades, system settings, project overrides, and revisioned resolution.
Expose scoped settings reads and bounded writes. Keep execution in preview mode during this phase.
Extract configuration resolution out of transport handlers where necessary.

**Gate:** Inherit, explicit false, null, array replacement, reset, invalid override, and stale-revision cases pass.
Two projects cannot read or mutate each other's settings. System constraints win after override resolution.

### P04 — Project-owned usage and trace isolation

**Dependency:** P03.

Tasklet A adds non-null project ownership to usage and execution traces, with corresponding writer changes.
Tasklet B scopes dashboard, activity detail, pagination, and export reads.
Keep actor attribution and distinguish system audit events. No historical data backfill is necessary.

**Gate:** A user in two projects sees only the selected project's activity.
Guessed trace IDs and cursors cannot cross projects. Root and child spans retain correct attribution across concurrent calls.

### P05 — Shared execution service and scoped REST/MCP paths

**Dependency:** P03 and P04.

Extract common execution policy into `services/` without a general rewrite of adapters.
Pass project context through route selection, dispatch, fanout, usage, and trace creation in both transports.
Add explicit project execution routes and preserve current fallback behavior.

**Gate:** REST and MCP produce equivalent project attribution and provider decisions with fake adapters.
No provider side effect occurs before scope validation. Deployment remains in preview mode until the complete release gate.

### P06 — Desktop project shell and membership UX

**Dependency:** P02–P05.

Tasklet A adds the project list, selector, URL routes, API scope, store keys, and request cancellation.
Tasklet B adds project creation for permitted system users, member administration, and extra role assignment.
Keep system navigation separate and expose no unsupported project execution mode.

**Gate:** Two tabs can use different projects without shared drafts or stale results.
A role change in one project leaves the other project unchanged. Direct links and no-membership states behave predictably.

### P07 — Project tokens and authenticated machine execution

**Dependency:** P05 and P06. **Backlog:** `TASK-000006`.

Tasklet A adds token schema, digest verification, issue, list, revoke, rotate, and expiry operations.
Tasklet B adds token administration UI and REST/MCP authentication, including stdio and persistent tool sessions.
Require project-token authentication for machine execution in preview mode. Keep human session authentication separate.
Support dated tokens and tokens without expiration throughout storage, API contracts, rotation, and UI controls.

**Gate:** Invalid, expired, revoked, wrong-project, wrong-scope, and control-plane token requests fail safely.
Secret material appears only in the issue response. Human browser execution still uses human sessions.
Tokens without expiration remain valid after the default lifetime passes and fail immediately after revocation or project suspension.
Creation distinguishes explicit null from an omitted expiry field. Rotation preserves No expiration unless an explicit update selects a date.

### P08 — Credential instances and explicit global grants

**Dependency:** P03.

Add credential metadata, per-instance encrypted slots, generation numbers, ownership, and global project grants.
Store newly entered provider secrets through the encrypted store. Preserve delete-wins tombstone behavior for the new per-instance slots.
No old provider-secret import is necessary.

**Gate:** Two credentials of one provider remain distinct. Project-private credentials cannot cross projects.
Deleting a credential cannot resurrect its old secret. Rotation invalidates the correct generation only.

### P09 — Binding-aware routing and account observations

**Dependency:** P05 and P08.

Add multiple project bindings per provider and credential-aware adapter resolution.
Migrate health, native quota observations, limit catalog links, and breaker keys to the correct credential or shared pool scope.
Retain project attribution separately from upstream balance ownership.

**Gate:** Two projects can use different keys for one provider, or share one granted key without duplicate balance state.
A credential failure does not disable an unrelated credential. Fanout and pinned binding selection remain correct.

### P10 — Per-instance Parallel OAuth lifecycle

**Dependency:** P08 and P09.

Namespace device flows and grants by credential instance. Scope start, poll, disconnect, refresh, and balance synchronization.
Use generation checks and per-credential refresh serialization so an old refresh cannot restore a disconnected grant.
Keep OAuth client and device secrets in the encrypted store.

**Gate:** Two connected accounts coexist. Disconnect or expiry of one account leaves the other usable.
Permission removal during a device flow prevents unauthorized completion and leaves no active orphan flow.

### P11 — Shared upstream pools and atomic strict caps

**Dependency:** P07–P10.

Add explicit upstream pools, credential links, and project allocations with loans disabled.
Generalize atomic rate and native funds admission across project and upstream constraints.
Replace process-local check-then-record paths for enforceable limits in both REST and MCP.
Split pool schema and identity from atomic enforcement into separate tasklets.

**Gate:** Concurrent requests from multiple processes cannot exceed configured pool or project windows.
Keys linked to the same pool share the same allowance. The 4/6 strict example stops A at four even when B is idle.
Store failure rejects new constrained execution. Retries do not duplicate one reservation or omit a new attempt charge.

### P12 — Project provider, settings, and limits UX

**Dependency:** P06 and P08–P11.

Tasklet A adds global credential/grant administration and project binding, private key, and OAuth controls.
Tasklet B adds setting provenance, allocation views, system allocation edits, and permission-based read-only behavior.
Show credential labels and pool ownership without raw secrets or unrelated project usage.

**Gate:** Users can create a project, assign members, select providers, issue a token, and inspect isolated activity.
All mutation controls follow effective project permissions. No project edit raises a system ceiling.

### P13 — Safe settings copy

**Dependency:** P03, P09, and P12.

Add preview/apply contracts, revision checks, copy modes, binding validation, and the project copy dialog.
Make the operation transactional and auditable. Treat shared allocation changes as separate system-admin proposals.

**Gate:** Copy preserves inheritance semantics and rejects unavailable private credentials.
The operation never copies tokens, membership, secret material, balances, or extra privileges.

### P14 — Project trace policy and retention jobs

**Dependency:** P04 and P12.

Add project sampling, detail, redaction, retention resolution, and scoped cleanup jobs.
Keep security audit retention and system export destinations under system policy.
Add project policy controls and effective-policy summaries.

**Gate:** Different project policies affect their own new traces and cleanup results.
One project's retention job cannot delete another project's spans. Mandatory audit events survive optional trace sampling changes.

### P15 — Project-first cutover and agent-account removal

**Dependency:** P07 and P11–P14. **Backlog:** Complete `TASK-000004` and remaining project-key requirements.

Rehearse a fresh database bootstrap, project-token issue, provider setup, and client configuration with synthetic data.
Enable strict project authentication and release multiple-project execution.
Remove agent registration, agent login, and all legacy account-type role fields from the active schema and contracts.

Remove account-type role choices, anonymous execution, and obsolete global account-role checks.
Require a fresh database for the alpha cutover. Do not convert old users, sessions, history, or agent credentials.
Create non-null project ownership and scoped role-assignment constraints directly in the fresh schema.

**Gate:** No execution path accepts an agent account or anonymous request.
Human login, refresh, and project selection work after bootstrap. No unscoped execution rows, orphan grants, or administrator-free projects remain.

### P16 — Single execution authority across transports

**Dependency:** P05, P11, and P15.

Host one authoritative execution runtime and make MCP forward to it in shared deployments.
Preserve token checks, cancellation, end-to-end deadlines, and trace propagation at the authority.
Support an explicit standalone MCP authority mode only for exclusive deployments.

**Gate:** Combined REST and MCP requests use one dispatch authority.
Authority outage fails predictably without direct-provider bypass. Duplicate authority configuration fails before borrowed-pool execution.

### P17 — Bounded queues with strict allocations

**Dependency:** P16.

Add the queue interface, project and global bounds, deadline cancellation, dispatch hooks, and queue metrics.
Keep strict caps and loans disabled. Retain atomic admission at actual dispatch.
Document the loss of queued, nondispatched requests on process restart.

**Gate:** Canceled or expired queued calls never reach providers or consume rate attempts.
Queue overload remains bounded by count and bytes. Queue delay appears separately from provider latency.

### P18 — Fair capacity loans

**Dependency:** P17.

Add DRR, allocation weights, maximum rates, idle deficit limits, and per-allocation loan enablement.
Expose effective policy, borrowed starts, contention, and queue wait metrics.
Add system controls for loans and a project read-only explanation.

**Gate:** A alone can reach ten only with loans enabled.
Under continuous equal-cost demand, A and B approach 4:6 service with a documented bounded discrepancy.
The pool never exceeds its configured rate envelope. A returning project receives future service without preemption or starvation.

### P19 — Cross-process recovery and operational qualification

**Dependency:** P18.

Exercise authority restart, native funds reconciliation, provider throttles, credential rotation, policy edits, and cancellation under load.
Publish the supported deployment topology, scaling limits, failure responses, and rollback procedure.
Define acceptance targets for queue latency and throughput from measured capacity.

**Gate:** Recovery does not restore an unsafe full rate bucket or duplicate native funds settlement.
Security isolation and pool limits hold during mixed REST/MCP contention.
A distributed Redis coordinator remains a later project unless this qualification proves it necessary.

## 11. Milestones and implementation order

**Foundation checkpoint:** P00–P07 provide project contracts, membership, isolated data paths, desktop scope, and project tokens.
Use preview mode until provider isolation and hard limits pass. No legacy compatibility layer is part of this milestone.

**Project-first release:** P08–P15 complete multi-credential providers, strict allocation enforcement, settings copy, trace policy, and agent removal.
This is a stable product release without capacity loans.

**Fair-capacity release:** P16–P19 add one dispatch authority, bounded queues, and optional fair capacity loans.
Do not enable loans before the authority and queue gates pass.

### Execution labels and start order

Every phase starts only after its dependency gates pass on the integration branch.
Phase numbers identify work. They do not require all phases to run in numeric order.

**FIRST / SERIAL FOUNDATION:** Complete `P00 -> P01 -> P02 -> P03` in that order.
P00 is the first assignment. It fixes contracts and baseline evidence before schema and authorization implementation.

**PARALLEL LANES AFTER P03:** Start these two lanes independently:

```text
Lane A: P04 -> P05 -> P06 -> P07
Lane B: P08 -------> P09 -> P10
                     ^
                     |
              also waits for P05
```

P04 and P08 can start together after P03.
P05 can start after P04 without waiting for P08.
P09 needs both P05 and P08. It can overlap P06, and later P07 if those phases remain active.
P10 starts after P09 and can overlap P06 or P07. Neither lane waits for the other except at the stated dependencies.

**JOIN / SERIAL INTEGRATION:** P11 starts after both lanes finish, including P07 and P10.
Complete P11's atomic cap gate before P12's provider/settings/limits UX integration.
The sequence is `P11 -> P12`.

**SECOND PARALLEL GROUP:** P13 and P14 can run together after P12.
Their earlier dependencies must also remain satisfied. P15 waits for both phases.

**RELEASE / SERIAL:** Complete P15 only after the project-first release gates pass.
Then complete `P16 -> P17 -> P18 -> P19` in order for the fair-capacity milestone.
Do not implement fair loans before the authority, bounded queue, and atomic admission seams exist.

### Parallel work and file ownership

Parallel eligibility describes dependencies. It does not authorize simultaneous edits to the same shared file.
Assign each shared file to one owner per integration step.

- **P04 and P08:** Both can touch storage models and schema validation. Serialize edits to `storage.py`, Alembic metadata, and `database_migrations.py`.
- **P06 and P09:** Keep frontend shell work separate from backend routing. Give shared provider DTOs and API client changes one integration owner.
- **P07 and P10:** Keep project-token authentication separate from Parallel provider OAuth. Serialize composition-root and shared secret-interface changes.
- **P13 and P14:** Keep copy workflows separate from trace policy. Give settings schemas and shared settings UI composition one owner.

Use separate worktrees for parallel coding agents. Keep each worktree's existing environment-based ports.
Merge passing prerequisites before dependent implementation. Mocked contract prototypes can proceed earlier, but they do not satisfy dependency gates.
Allocate Alembic revisions serially and merge one schema head. Do not let parallel lanes create independent final schema histories.

Within a phase, backend and frontend tasklets can overlap after the DTO contract is stable and their files are disjoint.
Integrate them before the phase gate. Do not mark the phase complete because only one tasklet passes.

The implementation orchestrator must record owners and current implementation plans through the Backlog CLI before code work.
Phase tickets and dependencies are already created. They remain To Do until a worker starts eligible work.
Use `backlog task list --labels projects-first --ready --status "To Do" --plain` to select eligible phase tickets.
Do not start a blocked ticket based on its number, priority, or visual board position.

### Module placement for coding agents

- Put project and principal Pydantic contracts in `models/projects.py` and dedicated token/settings contract modules.
- Put project, membership, token, settings, and credential repositories in `persistence/`, with Alembic revisions beside the current migrations.
- Put authorization, settings resolution, copy policy, execution coordination, and fair allocation policy in focused `services/` modules.
- Keep HTTP routers and MCP registrations thin. Put generic queue and clock primitives in `infrastructure/` when they have no project business rules.
- Add frontend `domains/projects` for project contracts and state. Add project workflows under `features/` and compose their screens in `app/`.
- Pass project context into other domains through public contracts or app composition. Avoid feature-to-feature and upward imports.

These are proposed module locations, not instructions to create empty files.
Mirror backend tests under `tests/unit/` and `tests/integration/`. Keep frontend component tests beside each source.
