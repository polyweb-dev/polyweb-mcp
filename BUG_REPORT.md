# All-Providers search returns Exa-only results and ignores the Exa off switch

With "All Providers" selected, a search sometimes returns Exa results alone instead of mixing all providers.
Turning Exa off in Settings doesn't stick either: its name still shows on mixed results, and it turns itself back on after a reload.

## What I did (in order)

A. Opened the UI with all providers on. A Berlin jobs search mixed all 7 providers fine: [screenshot A](bug-evidence/bug1-fused-berlin-7providers.png)
B. Searched Iran news with All Providers selected. Only Exa ran (`Resolved by exa`, single Exa waterfall bar): [screenshot B](bug-evidence/bug2-exa-only-no-aggregation.png)
C. Turned Exa's Search switch off in Settings: [screenshot C](bug-evidence/bug3-settings-exa-off.png). Searched the Iran topic again and got mixed results back (screenshot in next step).
D. Looked closely at those mixed results: Exa's badge still shows on some of them, the counts disagree (header says 7 fused, footer says 6 of 7), the waterfall is a single `aggregated` bar, and Activity has no entry for the multi-provider run the way single searches do: [screenshot D](bug-evidence/bug4-fused-with-exa-attributed.png)
E. Reloaded the page. Exa's Search switch was back on by itself: [screenshot E](bug-evidence/bug5-settings-exa-on-after-reload.png)

## What's wrong

B1. Exa-only fusion — an All Providers search came back `Resolved by exa` with only one Exa waterfall bar, no mixing (screenshot B).
B2. Exa off still shows up — after switching Exa Search off, mixed results still carry Exa badges and list Exa in `Attributed:` (screenshot D).
B3. Waterfall shows only `aggregated`, and no Activity entry — the waterfall should show one row per provider used plus its time; multi-provider runs should also appear in Activity like single searches do (screenshot D; screenshot A shows the same single-bar waterfall).
B4. Toggles don't persist across reload — Exa Search was off (screenshot C) but back on after reload (screenshot E).

Secondary:

S1. Switching tabs loses the query — will address with Redux (keep the playground query in shared state). No screenshot.

## Evidence (true order A to E)

- A — all providers working, Berlin jobs mixed from 7: [bug1-fused-berlin-7providers.png](bug-evidence/bug1-fused-berlin-7providers.png)
- B — Iran news, Exa-only despite All Providers: [bug2-exa-only-no-aggregation.png](bug-evidence/bug2-exa-only-no-aggregation.png)
- C — Exa Search switched off: [bug3-settings-exa-off.png](bug-evidence/bug3-settings-exa-off.png)
- D — re-searched, mixed results but Exa still listed, single `aggregated` bar: [bug4-fused-with-exa-attributed.png](bug-evidence/bug4-fused-with-exa-attributed.png)
- E — after reload, Exa back on: [bug5-settings-exa-on-after-reload.png](bug-evidence/bug5-settings-exa-on-after-reload.png)

## Notes

- PR #22 was closed without merging. Discussion: [PR #22 comment](https://github.com/sharathnirmala16/freesearch/pull/22#issuecomment-5850710473)
- No dev work started on this (per user instruction).
- File names describe each screenshot's content (verified by viewing all 5). The attached order was wrong; the A-to-E order above is the true sequence, so no files were renamed.

## Root Causes Found & Resolutions

- **B1 (Exa-only fusion / secret failover)**:
  - *Cause*: Playground used a strict 5,000ms client timeout. Live multi-provider fanout occasionally exceeded 5s, throwing an abort error. `useSearchRunner` caught this and silently fell back to single-provider search, selecting Exa alone (`Resolved by exa` with `Failover active`).
  - *Fix*: Increased fanout client timeout to 15,000ms and bypassed single-provider fallback retries on fanout errors so aggregated semantics are preserved.

- **B2 (Exa off still shows up in fanout)**:
  - *Cause*: Playground passed an empty `providerIds: []` to `/search` when "All Providers" was selected, causing the backend route selector to dispatch to all registered adapters regardless of UI toggles.
  - *Fix*: Forwarded the active `eligibleProviders` list so toggled-off providers (like Exa Search off) are excluded from fanout execution and attribution badges.

- **B3 (Waterfall shows only `aggregated` & no Activity entry)**:
  - *Cause*: Backend `SearchResponse` only returned fused results without per-provider latency metrics. The waterfall UI hardcoded "Trace unavailable from backend". The repository only logged individual candidate usage events without an aggregated run event.
  - *Fix*: Added `waterfall: list[ProviderTraceItem]` to backend contracts and measured per-candidate latency during fanout; logged an overall `aggregated` `UsageEvent` to SQLite for Activity stream visibility; updated UI waterfall to render per-provider latency bars and display "Live execution trace".

- **B4 (Operation toggles don't persist across reload)**:
  - *Cause*: `searchEnabled` and `fetchEnabled` were stored only in ephemeral React component state; page reloads reset them to the server-wide default.
  - *Fix*: Persisted operation toggles in `localStorage` under `freesearch:operation_toggles` and hydrated them upon `refreshProviders()`.

- **Key Deletion Lifecycle (Follow-up bug identified)**:
  - *Cause*: `DELETE /api/v1/providers/{id}/secret` removes the key from the vault database, but does not evict the initialized `ProviderAdapter` from the backend's in-memory `routes` list. Furthermore, the frontend's `isEligibleForOperation` checks only `globalEnabled`/`searchEnabled` without verifying `provider.hasKey`.
  - *Next step*: Eject and close in-memory adapters upon secret deletion and gate frontend provider eligibility on credential availability.
