---
id: doc-000003
title: Projects specification - delivery steps and gates
type: specification
created_date: '2026-10-24T15:49:00Z'
updated_date: '2026-10-26T09:48:00Z'
tags:
  - projects-first
  - specification
---
# Projects specification - delivery steps and gates

This document replaces the phase plan P00-P19 (decision 2026-10-25). The design in doc-000001, doc-000002 and doc-000004 still applies. Only the delivery order changed. The card map is in doc-000005.

## Why the plan changed

The alpha keeps no compatibility with old databases, contracts or account roles. Most of the phase plan existed to evolve a live system safely: small migrations, preview modes and strict ordering. Without that need, the rebuild changes one layer at a time, and a settled schema lets the API work run in parallel.

## Steps

1. **Database** - TASK-000040. One squashed baseline with the full schema, including fair capacity, plus the repository layer.
2. **API** - TASK-000041, TASK-000042, TASK-000043 and TASK-000044 in parallel after TASK-000040; TASK-000045 after TASK-000042. TASK-000039 has no dependency and lands first.
3. **UI** - TASK-000046, TASK-000047 and TASK-000048, each after the API cards it uses.
4. **Release** - TASK-000049.

## Gates

- A card is Done when the tests of the layer it changes pass. Tests of higher layers may fail until their step. feature/project may stay red until the UI step ends. main is untouched until TASK-000049.
- Step 2 is complete when all backend tests pass. Step 3 is complete when all tests pass.
- Latency and security are acceptance criteria from the start, not cleanup work afterwards.

## Shared Definition of Done

Every card carries these items:

1. Tests of the changed layer pass, plus ruff/mypy (backend) or lint/typecheck/depcruise/knip/build (frontend) with no new findings.
2. Tests use fake providers and temporary databases; security assertions are rewritten to the new model, never weakened or dropped without a replacement.
3. No secret material (passwords, API keys, provider keys, OAuth grants) appears in responses, logs, traces or test output.
4. If the card changes the request path, the routing-latency check passes: FreeSearch adds under 80 ms at p95 per provider, end to end, over REST and MCP. Database read counts are a diagnostic, not a limit.

## Schema after TASK-000040

The schema is settled. A later change is an exception: one small additive revision, merged by the integration owner, with one migration head. After it merges, every worktree recreates its database.

## File ownership during the API step

- Each API card owns its own service, router and MCP registration modules. Edits to `routers/api.py` and `mcp/server.py` are limited to registrations; resolve them on rebase.
- TASK-000041 owns principals and authentication: `routers/auth.py`, `mcp/auth.py`, `models/users.py` and the auth test fixtures. Other cards use principals through the execution boundary.
- TASK-000042 owns the execution path. TASK-000045 changes the same path and starts after TASK-000042 merges.
- The API card that owns an endpoint owns its DTOs. A UI card that needs a DTO change asks that card's owner, or lands it after that card merges.

## File ownership during the UI step

- TASK-000046 owns the project shell, routes, permissions and store composition.
- TASK-000047 and TASK-000048 own their feature folders and use the shell through public contracts.

## Performance

FreeSearch is a router, so the latency it adds is part of its value. TASK-000039 adds an end-to-end check per provider with instant fake adapters and keeps live-provider tests opt-in for a later CI job.
