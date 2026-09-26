# BUG_REPORT.md — fanout follow-up (PR #22 closed unmerged)
- Source: user screenshots + message 2026-09-26; PR comment https://github.com/sharathnirmala16/freesearch/pull/22#issuecomment-5850710473
- Status: noted only, no dev started per user instruction.

## Major
1. Exa ON → no aggregation: Provider=All Providers (Ranked Fusion) + Exa search-enabled resolves via single `exa` (`Resolved by exa`, single `Exa` waterfall bar) instead of fused `aggregated` with `All Providers (N fused)` + multi-engine badges.
2. Exa OFF → still used: Exa Search OFF in Settings yet All-Providers run still attributes `exa` (chips + `Attributed:`) in fused results — exclusion not honored.
3. Waterfall + Activity gap: fanout waterfall shows only single `aggregated` bar (must show every provider used + per-provider latency); fanout runs not tracked in Activity like single-search mode.
4. Disabled providers re-enable on reload: Exa Search OFF does not persist; after reload Settings shows Exa ON / 7/7 healthy.

## Secondary
5. No persisted playground UI state: switching tabs loses the query.

## Evidence / repro hints (no live run needed)
- Screenshots: fused 7-provider Berlin-jobs run; exa-only Iran-news run (`Resolved by exa`); Settings Exa-off; fused run with exa attributed; Settings Exa-on-after-reload.
- Routes: /playground (All Providers (Ranked Fusion)), /settings providers registry.
