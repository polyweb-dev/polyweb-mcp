---
id: TASK-000094
title: Keep SQL parameter values out of quota error logs
status: To Do
assignee: []
created_date: '2026-11-16T10:54:00Z'
updated_date: '2026-11-16T11:28:00Z'
labels:
  - backend
dependencies: []
priority: low
type: task
ordinal: 80000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Review verdict:** latent and minor data-minimization issue. SQLAlchemy database errors carry bound SQL parameter values (internal UUIDs, balances, timestamps) into logged tracebacks. No secret is bound in these statements. The fix is one engine setting. Priority Low.

## Background
TASK-000070 / PR #78 changes manual-quota projection failures from silent success to an operator-visible HTTP 503. The route logs the failure with the traceback so operators can find why Set balance did not reach the quota store. SQLAlchemy exception text ends with `[SQL: ...]` and `[parameters: (...)]`, so a logged database error carries the bound values.

## Current behavior (head 20405293f7440f4f0b30363646c074d54add4816)
- `PUT /api/v1/providers/{id}/manual-quota` (`src/polyweb/routers/control.py:323`) -> `_notify_manual_anchor` (`control.py:348`; DELETE at `:375`) -> `project_manual_record` -> `limits.apply_manual_anchor` -> `record_manual_anchor`, then `repository.record_quota` (`src/polyweb/services/manual_quota.py:343`).
- Every error other than `ManualAnchorRejectedError` reaches `control.py:456-461`:
```
logger.error("manual quota record for %s was not applied", provider.value, exc_info=True)
```
- The engine is `create_async_engine(URL.create(drivername="sqlite+aiosqlite", ...))` (`src/polyweb/persistence/storage.py:832-834`) with no `hide_parameters`. The migration engine `create_engine(URL.create("sqlite", ...), poolclass=pool.NullPool)` (`src/polyweb/persistence/migrations/env.py:44`) is the same.
- `SecretRedactionFilter` (`src/polyweb/infrastructure/logging.py:29`) redacts only `msg` and `args`, never `exc_info`. No production caller of `configure_logging` exists in `src/`.
- `exc_info` itself is safe and useful. The values come from the SQLAlchemy exception `__str__`.

## Scope gap
The next write, `persist_manual_quota` (`control.py:351` -> `set_runtime_setting`), is not wrapped. If it fails with a database error, uvicorn logs "Exception in ASGI application" with the same `[parameters: ...]` block. The same holds for every route. A fix only at `control.py:457` cannot remove the values from all logs.

## Scenario (reproduced)
1. An admin sends Set balance while the limits sync loop or lease writes hold the SQLite write lock longer than the busy timeout.
2. `record_manual_anchor` or `record_quota` raises `OperationalError: database is locked`.
3. The client gets the generic 503.
4. The log line carries the traceback with the pool id (`<provider>#cred:<uuid>`), the credential generation, the remaining and allowance Decimals, and timestamps.
Probe `/tmp/t94_probe.py` (aiosqlite engine, IntegrityError, same logger call):
```
hide_parameters=False: uuid_in_log=True ... "[parameters: ('11111111-2222-3333-4444-555555555555', '987.6543')]"
hide_parameters=True:  uuid_in_log=False ... '[SQL parameters hidden due to hide_parameters=True]'
```
The exposed values are internal UUIDs and the balance the operator typed. They are not credentials, and they are already in the same local SQLite file.

## Evidence
- Owner approval review N17/logs (/tmp/t70_pr78_approval.md).
- Sol (/tmp/t70_sol_report.md) confirms that exception detail can expose UUIDs and balances, and does not claim credential leakage.
- Opus code-path review (/tmp/t70_cardrev_000094.md): latent and minor, reproduced with the probe above.
- The existing test `tests/integration/routers/test_manual_quota.py:1285-1294` asserts `any(record.exc_info for record in caplog.records)` (`:1293`). It raises `RuntimeError("limit store unavailable")`, which contains no SQL. The test does not encode a leak. It only requires the traceback, which stays.

## Suggested minimal approach
- Use `create_async_engine(..., hide_parameters=True)` at `storage.py:832`. Apply the same setting to the migration engine at `migrations/env.py:44`.
- This removes the parameters from every SQLAlchemy exception string, chained causes included, in all handlers and in uvicorn logs. It keeps the SQL text, the error class and the traceback.
- Keep `exc_info=True` and the existing log message.

Do not change:
- The 409 path, the generic 503 detail, REST shapes, record-preservation behavior, the Tavily AC #15 rule, or Keenable free-tier admission.
- Nothing in `src/polyweb` reads `.params` or `statement_parameters` from exception text.
- Do not add structured logging or correlation IDs, and do not rewrite logging across the repository.

## Testing notes
- Add one persistence-level unit test in `tests/unit/persistence/`: open a temporary repository engine, force an IntegrityError with sentinel UUID and Decimal parameters, log it with `exc_info`, format it through a real `logging.Formatter`, and assert that no sentinel appears.
- Build the sentinel values at run time (for example from `uuid4()` or by joining parts), so they do not appear as literals in the test source. A literal in the source shows up in the traceback text and gives a false match.
- Before the fix the sentinel appears. After the fix it does not.
- Keep `test_manual_quota.py:1285-1294` unchanged.
- Per AGENTS.md: unit tests run locally. Integration and BDD suites run on Woodpecker CI. No live provider call or new BDD flow is necessary.

## References
- PR: https://github.com/polyweb-dev/polyweb-mcp/pull/78
- Source task: TASK-000070. Related: TASK-000088 (refused routing write), TASK-000095 (settings-write failure returns 503), TASK-000090 (N17/auth). No delivery dependency.
- Reviews: /tmp/t70_pr78_approval.md (N17/logs), /tmp/t70_sol_report.md, /tmp/t70_cardrev_000094.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No logged SQLAlchemy database error from the API or MCP process contains bound SQL parameter values, including handled errors (manual-quota 503) and uncaught route errors, in exception text, tracebacks or chained causes.
- [ ] #2 Operators keep the traceback, the error class and the SQL text. Clients keep the generic 503 response, and the existing conflict and record-preservation behavior stays intact.
- [ ] #3 A persistence-level unit test forces a real engine error with sentinel UUID and Decimal parameters, formats it through a real logging.Formatter, and asserts that no sentinel appears. The sentinels are built at run time, not written literally in the test source. The test fails before the fix and passes after it. The existing exc_info assertion in test_manual_quota.py stays unchanged.
<!-- AC:END -->
