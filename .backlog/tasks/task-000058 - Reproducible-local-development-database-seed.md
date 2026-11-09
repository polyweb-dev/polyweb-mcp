---
id: TASK-000058
title: Reproducible local development database seed
status: Done
assignee:
  - '@codex'
created_date: '2026-11-01T23:37:00Z'
updated_date: '2026-11-01T23:46:00Z'
labels:
  - dev-environment
  - projects-first
dependencies: []
type: chore
ordinal: 35000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Manual project workflow review needs a known starting state instead of ad hoc accounts and unconfigured projects. Build a disposable local database from a Python script using provider credentials already present in the gitignored .env.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A fresh freesearch.dev.db contains two system administrators, three regular users, and documented projects covering two admins with two members, one admin with three members, and admins only.
- [x] #2 Configured provider keys are imported from .env into the encrypted credential store with usable project bindings; absent keys are reported without exposing secrets.
- [x] #3 The seed can be recreated safely without overwriting the normal database; FREESEARCH_DB selects the dev database and setup/login instructions are documented.
- [x] #4 Focused integration tests verify seeding, credential encryption, and safe rerun behavior; relevant Ruff and MyPy checks pass.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Reuse auth, project and credential services and FREESEARCH_DB. 2. Add an offline seed script with a fixed dev filename, account/membership matrix and env key import. 3. Verify with temporary databases and fake keys. 4. Seed the local database, select it in .env, and document accounts and restart/recreation commands.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented scripts/seed_dev.py and docs/development-database.md. Existing FREESEARCH_DB selects the fixture; no runtime resolver or application logic changed. Seed uses normal auth/RBAC/credential/grant/binding services, imports provider keys into encrypted storage without network calls, and refuses existing files, non-dev filenames, symlinks, sidecars, or non-development settings. Verification: 7 focused integration tests pass; Ruff lint and format pass; script MyPy and application MyPy (128 source files) pass; git diff --check passes. Created the gitignored local freesearch.dev.db and selected it in local .env. Read back/decrypted all six actual configured credentials without printing values and verified six enabled providers per project, five users, three projects, SQLite integrity and foreign keys. Keenable and Tinyfish skipped because no nonempty keys were configured; Brave Answers unused because this runtime has no separate adapter. Running backend requires restart; manual browser testing remains for a later session.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added and verified a reproducible dev-only database seed with two system admins, three regular users, three membership variants and encrypted shared provider credentials. Documented login details, FREESEARCH_DB selection, safe deletion/recreation and fixture limits. Local dev DB is created and selected; no live provider calls made.
<!-- SECTION:FINAL_SUMMARY:END -->
