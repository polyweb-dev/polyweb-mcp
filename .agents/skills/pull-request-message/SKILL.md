---
name: pull-request-message
description: Use when creating or updating a pull request, writing a PR body or description, running `gh pr create` or `gh pr edit`, or preparing PR evidence for review. Defines the header block, the ten required sections, the split rule, the blocking red flags, and a copy-paste template that the owner's code-review agent checks.
---

# Pull-request message

The reviewer blocks on missing or wrong *evidence and description*, not only on code (PR #74 was clean code that was blocked for this).

## Before you write it

1. Push the final commit. Get the SHAs: `git rev-parse HEAD` and `git merge-base HEAD origin/main`.
2. Scope numbers: `git diff --stat origin/main...HEAD`. Group the files by area.
3. Pipeline numbers: trigger the Woodpecker workflows for this branch (AGENTS.md, "Cloud test runs"). Runs must be on the head SHA. If you push again, run the suites again.
4. Acceptance criteria: `backlog task view TASK-<id> --plain`. Copy the ACs. Do not add or change criteria.
5. Write the body to a file. Set it with `gh pr create --body-file <file>` or `gh pr edit <n> --body-file <file>`.

## Header block (first lines of the body)

```
Head SHA: <40-char sha>    Base: <sha> (<branch>)
Linked task: TASK-0000NN   (or "none — <reason>")
Suites at head SHA: api-unit #N, api-integration #N, api-bdd #N, api-latency #N, ui-quality #N
```

- List only the suites that apply. Every number must be for the head SHA.
- An older run: label it `stale @ <sha>` and say why it is still relevant.
- No head-SHA run = the PR is blocked, whatever the code quality.

## Section rules (2–10; the header is 1; add a one-paragraph Summary first)

2. **Scope** — table by area: `src/polyweb`, `tests`, `polyweb-ui`, `polyweb-docs`, `scripts`, compose/env, instruction files (`AGENTS.md`, skills). Files and `+/-` lines per row. List what was **added**, not only what was removed. Every touched area gets a row.
3. **Behavior changes** — per change: what, who is affected, how to verify, how to roll back. Always list changes to startup requirements, config precedence, API response shapes, and UI policy. Write "None" only when it is true, and say why.
4. **Contract changes** — every added, removed, or renamed request/response field goes in the table. A removed field needs a deprecation path or "breaking, accepted because …".
5. **Upgrade / migration** — exact steps for an existing deployment, the doc file path that states them, and whether a release note exists. A new required env var or a new startup failure is a migration item.
6. **Acceptance criteria** — link the task; map each AC to evidence (test name, pipeline #, or `file:line`). No task: say why and list the intended behavior. Never invent criteria.
7. **Test evidence** — failing-before test and its failure; passing-after run; pipeline numbers. For every deleted test, name the surviving test `file::test_name` ("duplicates removed" without a survivor = coverage loss). For contract changes, assert removed fields are **absent**.
8. **Manual / visual** — UI changes: desktop screenshots, or "not visually verified — needs owner check". For a claimed visual fix (baseline, spacing, truncation), show before/after or mark it unverified. Never claim manual testing that did not happen.
9. **Deferrals** — every known gap with `TASK-0000NN` and one line of scope. No silent TODOs, no "tracked later" without an ID.
10. **Out of scope** — what you deliberately did not do.

## Split rule

One concern per PR. If a PR mixes dead-code removal with features or contract changes, split it. If you cannot, map every commit to a section of the message and say why it cannot be split.

## Blocking red flags

Do not submit while any of these is true:

- "Behaviour is unchanged" when behavior changed.
- CI numbers from a different SHA.
- Deleted tests without a named survivor.
- Added/removed public fields without a contract table.
- New required config without an upgrade note.
- UI change with no screenshot and no explicit "unverified".
- A "cleanup" PR that contains features.
- A tautological or text-count test presented as coverage.

## Template

```markdown
Head SHA: <40-char sha>    Base: <sha> (<branch>)
Linked task: TASK-0000NN   (or "none — <reason>")
Suites at head SHA: api-unit #N, api-integration #N, api-bdd #N, api-latency #N, ui-quality #N

## Summary
<one paragraph: what this PR does and why>

## Scope
| Area | Files | +/- | What changed |
|---|---|---|---|

## Behavior changes
- <change> — affects <who>; verify with <how>; rollback <how>
(or: None. <why that is true>)

## Contract changes
| Endpoint | Field | Before → After | Consumer updated | External impact | Docs |
|---|---|---|---|---|---|

## Upgrade / migration
- <step> — documented in <path>; release note: <yes/no + path>

## Acceptance criteria
Linked task: TASK-0000NN
- [ ] AC1 — evidence: `tests/...::test_name` / pipeline #N

## Test evidence
- Failing before: `tests/...::test_name` — <failure>
- Passing after: <run> / pipeline #N
- Deleted tests and survivors: `old` → `new::test_name`
- Stale runs: #N @ <sha> (why still relevant)

## Manual / visual
<screenshots, or "not visually verified — needs owner check">

## Deferrals
- TASK-0000NN — <scope>

## Out of scope
- <item>
```
