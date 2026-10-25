---
id: doc-000005
title: Projects execution index - start here
type: guide
created_date: '2026-10-24T15:53:00Z'
updated_date: '2026-10-25T15:05:00Z'
tags:
  - projects-first
  - execution-order
---
# Projects execution index - start here

This initiative is the highest-priority board work. All Projects phase tickets have High priority and precede unrelated work by board ordinal.

## Start and dependency rules

P00-P03 (TASK-000017 to TASK-000020) are Done. On 2026-10-25, P04, P06, P11, P12 and P15 were split into tasklet tickets. Each downstream ticket depends only on the tasklet that it needs. A phase with more than one ticket is complete only when all of its tickets are Done.

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

Generated from the Backlog dependency fields on 2026-10-25. Live statuses and readiness come from Backlog.

| Phase | Ticket | Work | Depends on | Lane | Status |
| --- | --- | --- | --- | --- | --- |
| P00 | [TASK-000017](<../tasks/task-000017 - Projects-P00-Contract-and-alpha-baseline.md>) | Contract and alpha baseline | None - start here | serial-foundation | Done |
| P01 | [TASK-000018](<../tasks/task-000018 - Projects-P01-Project-and-membership-schema.md>) | Project and membership schema | TASK-000017 | serial-foundation | Done |
| P02 | [TASK-000019](<../tasks/task-000019 - Projects-P02-Project-lifecycle-and-authorization-service.md>) | Project lifecycle and authorization service | TASK-000018 | serial-foundation | Done |
| P03 | [TASK-000020](<../tasks/task-000020 - Projects-P03-Project-context-and-typed-settings-storage.md>) | Project context and typed settings storage | TASK-000019 | serial-foundation | Done |
| P04 | [TASK-000021](<../tasks/task-000021 - Projects-P04-Project-owned-usage-and-trace-isolation.md>) | Project-owned usage and trace writers | TASK-000020 | parallel-a | To Do |
| P04B | [TASK-000034](<../tasks/task-000034 - Projects-P04B-Project-scoped-activity-dashboard-and-export-reads.md>) | Project-scoped activity, dashboard and export reads | TASK-000021 | parallel-a | To Do |
| P05 | [TASK-000022](<../tasks/task-000022 - Projects-P05-Shared-execution-service-and-scoped-REST-MCP-paths.md>) | Shared execution service and scoped REST/MCP paths | TASK-000020, TASK-000021 | parallel-a | To Do |
| P06 | [TASK-000023](<../tasks/task-000023 - Projects-P06-Desktop-project-shell-and-membership-UX.md>) | Desktop project shell and membership UX | TASK-000019, TASK-000020 | parallel-ui | To Do |
| P06B | [TASK-000036](<../tasks/task-000036 - Projects-P06B-Project-scoped-activity-usage-and-playground-views.md>) | Project-scoped activity, usage and playground views | TASK-000034, TASK-000022, TASK-000023 | parallel-ui | To Do |
| P07 | [TASK-000006](<../tasks/task-000006 - Add-Project-Keys-to-secure-search-and-fetch.md>) | Project tokens and authenticated machine execution | TASK-000022, TASK-000023 | parallel-a | To Do |
| P08 | [TASK-000024](<../tasks/task-000024 - Projects-P08-Credential-instances-and-explicit-global-grants.md>) | Credential instances and explicit global grants | TASK-000020 | parallel-b | To Do |
| P09 | [TASK-000025](<../tasks/task-000025 - Projects-P09-Binding-aware-routing-and-account-observations.md>) | Binding-aware routing and account observations | TASK-000022, TASK-000024, TASK-000035 | parallel-b | To Do |
| P10 | [TASK-000026](<../tasks/task-000026 - Projects-P10-Per-instance-Parallel-OAuth-lifecycle.md>) | Per-instance Parallel OAuth lifecycle | TASK-000024, TASK-000025 | parallel-b | To Do |
| P11A | [TASK-000035](<../tasks/task-000035 - Projects-P11A-Upstream-pool-credential-link-and-allocation-schema.md>) | Upstream pool, credential link and allocation schema | TASK-000024 | parallel-b | To Do |
| P11 | [TASK-000027](<../tasks/task-000027 - Projects-P11-Shared-upstream-pools-and-atomic-strict-caps.md>) | Atomic strict caps across projects and shared pools | TASK-000006, TASK-000025, TASK-000026, TASK-000035 | serial-join | To Do |
| P12A | [TASK-000037](<../tasks/task-000037 - Projects-P12A-Settings-provenance-and-permission-aware-settings-UI.md>) | Settings provenance and permission-aware settings UI | TASK-000020, TASK-000023 | parallel-ui | To Do |
| P12 | [TASK-000005](<../tasks/task-000005 - Update-Projects-mode-tables-and-global-project-settings.md>) | Project provider, credential and limits UX | TASK-000006, TASK-000026, TASK-000027, TASK-000036, TASK-000037 | serial-join | To Do |
| P13 | [TASK-000028](<../tasks/task-000028 - Projects-P13-Safe-settings-copy.md>) | Safe settings copy | TASK-000020, TASK-000025, TASK-000035, TASK-000037 | parallel-copy | To Do |
| P14 | [TASK-000029](<../tasks/task-000029 - Projects-P14-Project-trace-policy-and-retention-jobs.md>) | Project trace policy and retention jobs | TASK-000021, TASK-000022, TASK-000036, TASK-000037 | parallel-retention | To Do |
| P15A | [TASK-000004](<../tasks/task-000004 - Disallow-Agent-Accounts.md>) | Agent-account, anonymous-execution and account-type removal | TASK-000006, TASK-000023 | parallel-cleanup | To Do |
| P15 | [TASK-000038](<../tasks/task-000038 - Projects-P15-Project-first-strict-cutover-and-release.md>) | Project-first strict cutover and release | TASK-000027, TASK-000005, TASK-000028, TASK-000029, TASK-000004 | serial-release | To Do |
| P16 | [TASK-000030](<../tasks/task-000030 - Projects-P16-Single-execution-authority-across-transports.md>) | Single execution authority across transports | TASK-000022, TASK-000006, TASK-000027, TASK-000004 | serial-fairness | To Do |
| P17 | [TASK-000031](<../tasks/task-000031 - Projects-P17-Bounded-queues-with-strict-allocations.md>) | Bounded queues with strict allocations | TASK-000030 | serial-fairness | To Do |
| P18 | [TASK-000032](<../tasks/task-000032 - Projects-P18-Fair-capacity-loans.md>) | Fair capacity loans | TASK-000031 | serial-fairness | To Do |
| P19 | [TASK-000033](<../tasks/task-000033 - Projects-P19-Cross-process-recovery-and-operational-qualification.md>) | Cross-process recovery and operational qualification | TASK-000032, TASK-000038 | serial-fairness | To Do |

## Parallel lanes and joins

Serial foundation: P00 -> P01 -> P02 -> P03.

After P03, three lanes start together:

```text
Lane A (execution):  P04 -> P05 -> P07
                       \-> P04B
Lane B (providers):  P08 -> P11A -> P09 -> P10
                                     ^
                                     |  also waits for P05
Lane UI (desktop):   P06 -> P12A
                       \-> P06B  (also waits for P04B and P05)
```

- P04, P06 and P08 can start together after P03.
- P05 starts after P04 (writers). P04B can run at the same time as P05.
- P11A starts after P08 and can run at the same time as P04 and P05.
- P07 needs P05 and the P06 shell. P15A needs P07 and the P06 shell.
- P11 (atomic caps) starts after P07, P09, P10 and P11A. P12 starts after P06B, P07, P10, P11 and P12A.
- P13 starts after P09, P11A and P12A. P14 starts after P05, P06B and P12A. Neither waits for P12.
- P15 (strict cutover) starts after P11, P12, P13, P14 and P15A.
- P16 starts after P05, P07, P11 and P15A, without waiting for P15. Then P16 -> P17 -> P18 -> P19. P19 also waits for P15, so the fair-capacity release follows the project-first release.

The longest dependency chain is P04 -> P05 -> P09 -> P10 -> P11 -> P16 -> P17 -> P18 -> P19.

## Worktrees and merging

Parallel eligibility does not allow simultaneous ownership of the same shared file. Section 11 of doc-000003 lists the shared files and their owners.

- Use one worktree and one short-lived branch per ticket. Create it from the main checkout with `scripts\windows\create_worktree.bat <branch> freesearch_wt_<N> <mode> --base <integration branch>`. The script sets the ports for slot N from AGENTS.md and does not copy the live `freesearch.db`.
- Use a fresh database in each worktree. Never copy or test against the live database or real provider credentials.
- Rebase onto the integration branch after each merge and before you open a pull request.
- Only the ticket's own worktree edits that ticket in Backlog. Create new tickets only from the main checkout.
- The gitignored local plan is not present in new worktrees. Use doc-000001 to doc-000004 there.

Schema changes:

- Allocate Alembic revisions serially and keep one migration head. `migration_head()` fails when two heads exist.
- When two active tickets both change the schema, land each migration and its schema-validation change as a small first pull request.
- P04 and P08 start together. P04 is on the longest chain, so P04 lands its migration first when both are ready. Otherwise, the first merged migration keeps the next number.
- The other branch rebases, renames its revision to the following number, sets `down_revision` to the new head, and updates the head literal in `tests/integration/persistence/test_database_migrations.py`, `tests/integration/persistence/test_projects.py` and `tests/fixtures/alpha_fixtures.py`.

## Specification and durable references

Local plan: `.agents/communication/projects-feature-plan.md`. It is gitignored. The Backlog-managed documents below retain the design in other checkouts:

- doc-000001: identity, shared scoped RBAC and ownership, original plan sections 1-4.
- doc-000002: schema, project tokens, hierarchical limits and desktop UX, original plan sections 5-9.
- doc-000003: all phase scopes, acceptance gates, milestones and execution labels, original plan sections 10-11.
- doc-000004: fresh alpha setup and verification requirements, original plan sections 12-14.
- doc-000006: P00 ownership inventory, bootstrap runbook and baseline matrix.

Read a document with `backlog doc view doc-000001 --plain` (substitute the needed document ID). Every phase ticket also includes its own scope, testable criteria, source entry points, validation expectations and documentation references.

## Confirmed boundaries

One human identity type uses system/project role assignments through one common RBAC service. Preserve local/WorkOS schema seams without implementing WorkOS or cloud workflows. Seed one internal installation account. Project execution tokens support expiry or No expiration. Private and installation-shared provider credentials remain distinct. Strict project/global caps come first; fair loans come only after authority/queue gates. The alpha cutover uses a fresh database without old accounts, history, settings or credential imports.

Do not use a live database, real keys or paid providers for verification. Desktop UI only. Read AGENTS.md and applicable skills, use CodeGraph for indexed code, and update Backlog implementation plans after current-source research.

## Other board work

Other open tickets keep their existing scope and relative order below this initiative. TASK-000003 (Provider Tier settings) explicitly waits for TASK-000038 (P15 strict cutover) to avoid duplicating or bypassing the new scoped settings and strict admission model. Original tickets 4, 5 and 6 were refined into P15A, P12 and P07 respectively.

This index is a navigation document. Live statuses and readiness come from Backlog.
