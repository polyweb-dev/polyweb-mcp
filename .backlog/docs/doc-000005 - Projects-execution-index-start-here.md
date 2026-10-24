---
id: doc-000005
title: Projects execution index - start here
type: guide
created_date: '2026-10-24T15:53:00Z'
updated_date: '2026-10-24T15:57:00Z'
tags:
  - projects-first
  - execution-order
---
# Projects execution index - start here

This initiative is the highest-priority board work. All twenty phase tickets have High priority and precede unrelated work by board ordinal.

## Start and dependency rules

Start with TASK-000017 (P00). All phase tickets are To Do; none is completed merely by this board reorganization.

Only select phase tickets whose dependencies are Done and merged, with passing phase evidence. Backlog readiness reflects dependency statuses. Readiness does not replace the merged-code and validation gate. Do not manually move a blocked ticket to In Progress.

Use this command to find the current eligible phase tickets:

```powershell
backlog task list --labels projects-first --ready --status "To Do" --plain
```

If backlog is absent from PATH in this environment, prefix the same arguments with:

```powershell
& 'C:/Users/shara/.bun/bin/bunx.exe' --bun backlog.md@1.55.3
```

## Ticket map

| Phase | Ticket | Work | Depends on | Lane |
| --- | --- | --- | --- | --- |
| P00 | [TASK-000017](<../tasks/task-000017 - Projects-P00-Contract-and-alpha-baseline.md>) | Contract and alpha baseline | None - start here | serial-foundation |
| P01 | [TASK-000018](<../tasks/task-000018 - Projects-P01-Project-and-membership-schema.md>) | Project and membership schema | TASK-000017 | serial-foundation |
| P02 | [TASK-000019](<../tasks/task-000019 - Projects-P02-Project-lifecycle-and-authorization-service.md>) | Project lifecycle and authorization service | TASK-000018 | serial-foundation |
| P03 | [TASK-000020](<../tasks/task-000020 - Projects-P03-Project-context-and-typed-settings-storage.md>) | Project context and typed settings storage | TASK-000019 | serial-foundation |
| P04 | [TASK-000021](<../tasks/task-000021 - Projects-P04-Project-owned-usage-and-trace-isolation.md>) | Project-owned usage and trace isolation | TASK-000020 | parallel-a |
| P05 | [TASK-000022](<../tasks/task-000022 - Projects-P05-Shared-execution-service-and-scoped-REST-MCP-paths.md>) | Shared execution service and scoped REST/MCP paths | TASK-000020, TASK-000021 | parallel-a |
| P06 | [TASK-000023](<../tasks/task-000023 - Projects-P06-Desktop-project-shell-and-membership-UX.md>) | Desktop project shell and membership UX | TASK-000019, TASK-000020, TASK-000021, TASK-000022 | parallel-a |
| P07 | [TASK-000006](<../tasks/task-000006 - Add-Project-Keys-to-secure-search-and-fetch.md>) | Project tokens and authenticated machine execution | TASK-000022, TASK-000023 | parallel-a |
| P08 | [TASK-000024](<../tasks/task-000024 - Projects-P08-Credential-instances-and-explicit-global-grants.md>) | Credential instances and explicit global grants | TASK-000020 | parallel-b |
| P09 | [TASK-000025](<../tasks/task-000025 - Projects-P09-Binding-aware-routing-and-account-observations.md>) | Binding-aware routing and account observations | TASK-000022, TASK-000024 | parallel-b |
| P10 | [TASK-000026](<../tasks/task-000026 - Projects-P10-Per-instance-Parallel-OAuth-lifecycle.md>) | Per-instance Parallel OAuth lifecycle | TASK-000024, TASK-000025 | parallel-b |
| P11 | [TASK-000027](<../tasks/task-000027 - Projects-P11-Shared-upstream-pools-and-atomic-strict-caps.md>) | Shared upstream pools and atomic strict caps | TASK-000006, TASK-000024, TASK-000025, TASK-000026 | serial-join |
| P12 | [TASK-000005](<../tasks/task-000005 - Update-Projects-mode-tables-and-global-project-settings.md>) | Project provider, settings, and limits UX | TASK-000023, TASK-000024, TASK-000025, TASK-000026, TASK-000027 | serial-join |
| P13 | [TASK-000028](<../tasks/task-000028 - Projects-P13-Safe-settings-copy.md>) | Safe settings copy | TASK-000020, TASK-000025, TASK-000005 | parallel-copy |
| P14 | [TASK-000029](<../tasks/task-000029 - Projects-P14-Project-trace-policy-and-retention-jobs.md>) | Project trace policy and retention jobs | TASK-000021, TASK-000005 | parallel-retention |
| P15 | [TASK-000004](<../tasks/task-000004 - Disallow-Agent-Accounts.md>) | Project-first cutover and agent-account removal | TASK-000006, TASK-000027, TASK-000005, TASK-000028, TASK-000029 | serial-release |
| P16 | [TASK-000030](<../tasks/task-000030 - Projects-P16-Single-execution-authority-across-transports.md>) | Single execution authority across transports | TASK-000022, TASK-000027, TASK-000004 | serial-fairness |
| P17 | [TASK-000031](<../tasks/task-000031 - Projects-P17-Bounded-queues-with-strict-allocations.md>) | Bounded queues with strict allocations | TASK-000030 | serial-fairness |
| P18 | [TASK-000032](<../tasks/task-000032 - Projects-P18-Fair-capacity-loans.md>) | Fair capacity loans | TASK-000031 | serial-fairness |
| P19 | [TASK-000033](<../tasks/task-000033 - Projects-P19-Cross-process-recovery-and-operational-qualification.md>) | Cross-process recovery and operational qualification | TASK-000032 | serial-fairness |

## Parallel lanes and joins

Serial foundation: P00 -> P01 -> P02 -> P03.

After P03, Lane A is P04 -> P05 -> P06 -> P07. Lane B is P08 -> P09 -> P10. P09 also waits for P05. P04 and P08 can start together. P06 and P09 can overlap once P05 and P08 pass. P07 and P10 can overlap after their own prerequisites.

Join both lanes at P11, then P12. P13 and P14 can run together after P12. P15 waits for both. P16 -> P17 -> P18 -> P19 then run in order.

Parallel eligibility does not allow simultaneous ownership of the same shared file. Serialize schema/Alembic revisions, storage/validator edits, shared contracts and composition-root merges. Use isolated worktrees and their environment-based ports.

## Specification and durable references

Local plan: `.agents/communication/projects-feature-plan.md`. It is gitignored. The Backlog-managed documents below retain the design in other checkouts:

- doc-000001: identity, shared scoped RBAC and ownership, original plan sections 1-4.
- doc-000002: schema, project tokens, hierarchical limits and desktop UX, original plan sections 5-9.
- doc-000003: all phase scopes, acceptance gates, milestones and execution labels, original plan sections 10-11.
- doc-000004: fresh alpha setup and verification requirements, original plan sections 12-14.

Read a document with `backlog doc view doc-000001 --plain` (substitute the needed document ID). Every phase ticket also includes its own scope, testable criteria, source entry points, validation expectations and documentation references.

## Confirmed boundaries

One human identity type uses system/project role assignments through one common RBAC service. Preserve local/WorkOS schema seams without implementing WorkOS or cloud workflows. Seed one internal installation account. Project execution tokens support expiry or No expiration. Private and installation-shared provider credentials remain distinct. Strict project/global caps come first; fair loans come only after authority/queue gates. The alpha cutover uses a fresh database without old accounts, history, settings or credential imports.

Do not use a live database, real keys or paid providers for verification. Desktop UI only. Read AGENTS.md and applicable skills, use CodeGraph for indexed code, and update Backlog implementation plans after current-source research.

## Other board work

Other open tickets keep their existing scope and relative order below this initiative. TASK-000003 (Provider Tier settings) explicitly waits for TASK-000004 to avoid duplicating or bypassing the new scoped settings and strict admission model. Original tickets 4, 5 and 6 were refined into P15, P12 and P07 respectively.

This index is a navigation document. Live statuses and readiness come from Backlog.
