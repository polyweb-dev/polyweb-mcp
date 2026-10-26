---
id: doc-000005
title: Projects execution index - start here
type: guide
created_date: '2026-10-24T15:53:00Z'
updated_date: '2026-10-26T09:48:00Z'
tags:
  - projects-first
  - execution-order
---
# Projects execution index - start here

This initiative is the highest-priority board work. On 2026-10-25 the phase plan (P00-P19) was replaced by a layered rebuild: database, then API, then UI, then release. The alpha keeps no compatibility with old databases, contracts or account roles. P00-P04, P06 and P08 were delivered under the phase plan and are archived. Their code is merged into feature/project.

## Start rules

Select only cards whose dependencies are Done and merged into feature/project. Backlog readiness reflects dependency statuses; it does not replace the merged-code gate. Do not manually move a blocked card to In Progress.

```powershell
backlog task list --labels projects-first --ready --status "To Do" --plain
```

When you start a card, research the current code and record your own implementation plan in Backlog. Cards contain intent, dependencies and acceptance criteria only.

## Card map

| Step | Card | Work | Depends on |
| --- | --- | --- | --- |
| 1 Database | TASK-000040 | Settled alpha schema and repositories | none |
| 2 API | TASK-000039 | Routing-latency acceptance (lands first) | none |
| 2 API | TASK-000041 | Identity, RBAC and project API keys | TASK-000040 |
| 2 API | TASK-000042 | Project-scoped execution, bindings and strict caps | TASK-000040 |
| 2 API | TASK-000043 | Providers: credentials, OAuth, pools and allocations | TASK-000040 |
| 2 API | TASK-000044 | Settings, copy, trace policy and activity reads | TASK-000040 |
| 2 API | TASK-000045 | Fair capacity: execution authority, bounded queues, loans and recovery | TASK-000042 |
| 3 UI | TASK-000046 | Project shell, members and API keys UI | TASK-000041 |
| 3 UI | TASK-000047 | Activity, usage and playground UI | TASK-000042, TASK-000044 |
| 3 UI | TASK-000048 | Providers, settings and limits UI | TASK-000045, TASK-000043, TASK-000044 |
| Release | TASK-000049 | Project-first release | TASK-000046, TASK-000047, TASK-000048, TASK-000039 |

TASK-000040 and TASK-000039 can start now. After TASK-000040 merges, TASK-000041, TASK-000042, TASK-000043 and TASK-000044 run in parallel. Each UI card starts when its API cards are merged. Step rules, the shared Definition of Done and file ownership are in doc-000003.

## Worktrees and merging

- Use one worktree and one short-lived branch per card. From the main checkout, run `scripts\windows\create_worktree.bat <branch> freesearch_wt_<N> <mode> --base feature/project`. The script sets the ports for slot N from AGENTS.md and does not copy the live `freesearch.db`.
- Open pull requests against feature/project, not main. Rebase onto feature/project after each merge and before you open a pull request.
- Use a fresh database in each worktree. After TASK-000040 merges, recreate every worktree database once. Never use the live database or real provider credentials.
- Only the card's own worktree edits that card in Backlog. Create new cards only from the main checkout.
- The gitignored local plan is not present in new worktrees. Use the documents below.

## Design references

- doc-000003: delivery steps, gates, shared Definition of Done, schema rule and file ownership.
- doc-000001: identity, scoped RBAC and ownership (plan sections 1-4).
- doc-000002: schema, project API keys, hierarchical limits and desktop UX (plan sections 5-9).
- doc-000004: fresh alpha setup and verification (plan sections 12-14).
- doc-000006: P00 ownership inventory and bootstrap runbook (historical record).

Phase numbers (P00-P19) in these documents are historical names for design sections. Delivery follows the cards above.

## Confirmed boundaries

One human identity type uses system and project role assignments through one common RBAC service. Machine clients use project API keys, which can expire or have no expiration. Private and installation-shared provider credentials stay distinct. Strict caps are the default; capacity loans are off until enabled per allocation. Preserve local/WorkOS schema seams without implementing WorkOS or cloud workflows. Use a fresh database; do not import old accounts, history, settings or credentials. Desktop UI only.

## Other board work

Other open cards keep their scope and order below this initiative. TASK-000003 (Provider Tier settings) waits for TASK-000049. TASK-000001 (signup profile fields) gets its columns from TASK-000040 and its signup work waits for TASK-000041.
