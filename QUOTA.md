# Quota and usage plan

> **Status: PLANNING ONLY — DO NOT IMPLEMENT**  
> **Date:** 2026-09-09  
> SDLC is paused. This document records research, unit math, decisions, and a future implementation strategy; it authorizes no backend, frontend, migration, or test changes.

## 0. Decisions locked

1. **Canonical model:** use **Option A, dual-field units**. Preserve raw usage in `units`, add a machine-readable `unit_kind`, and add a human-readable `display_unit`.
2. **Arithmetic:** use `Decimal` end to end. Do not route quota/cost calculations through binary floating point.
3. **Tavily:** keep the existing vendor quota integration. `GET /usage` is the authoritative credit source.
4. **You.com:** keep the existing balance integration. Convert balance cents into floored call counts; snapshots are `ESTIMATED`, and `limit` remains `None`.
5. **Brave:** use the monthly values observed in successful-search rate-limit headers as an `OBSERVED` request quota. V1 has no USD 5.00 wallet, monthly-dollar reset, settings, or re-sync UX. Optional dollar-spend tracking is future work, not v1.
6. **Keenable:** authenticated Free is **100,000 requests/month** and API-key use raises limits relative to keyless access. The Keyless Public Tier is for testing, has stricter shared rate limits, and is not a monthly quota to display as remaining allowance. Public material reports up to **1,000 requests/hour via the MCP server**; the exact REST/keyless limits must be verified before implementation.
7. **Firecrawl:** poll `GET /v2/team/credit-usage`; do not use token usage as the current quota source. `remainingCredits` is the truth; `planCredits` is only the baseline limit.
8. **Parallel:** the adapter cannot poll a balance with its API key. Track estimated USD spend locally, keep raw response SKU counts, and distinguish a soft 402 balance signal from a transient 429.
9. **Failure accounting:** failed operations may be recorded with zero units for observability, but zero-valued `FAILURE` records are excluded from usage totals.
10. **No quota gate until populated:** routing must not claim quota awareness until snapshots are recorded and the gate is fed real state.

## 1. Root causes

### R1 — quota snapshots are never recorded

`Repository.record_quota(...)` exists, but the running request/control path does not call it. Consequently the live dashboard evidence is:

```json
{"latest_quota": []}
```

A provider implementing `quota()` is insufficient unless an orchestrator polls it and persists the returned snapshot.

### R2 — only Tavily and You.com implement `quota()`

The base adapter defaults to no quota. Tavily and You.com currently override it; Brave, Firecrawl, Keenable, Parallel, and Exa do not. Brave already receives quota headers after successful searches, but does not turn them into quota snapshots. The resulting empty state is therefore both a recording-pipeline problem and a provider-coverage problem.

### R3 — the routing quota gate is inert

The current routing inputs are effectively empty maps:

```text
({}, {})
```

With neither quota state nor usable provider budget data, the gate cannot steer away from exhaustion. Adding calculations only to the dashboard will not fix routing; persisted snapshots must be projected into the routing service deliberately.

### R4 — one `units: Decimal` column carries incompatible meanings

The same field currently represents values that cannot safely be summed or compared:

| Provider/path | Current meaning of `units` |
|---|---|
| Brave search | `1` query |
| Tavily | credits |
| Exa | USD, typically `0.001` |
| You.com search/fetch | USD `0.005` / `0.001`; missing response usage creates an accounting gap |
| Parallel | sum of raw response SKU counts |
| Keenable and failures | `0` |

The live semantic mismatch is exemplified by **`1` vs `0.001`**: they are both valid `Decimal` values but one is a request count and one is USD. A provider-wide total over that column is dimensionally invalid.

### R5 — confidence exists but is ignored in the UI

Quota sources can be authoritative, observed, or estimated, but the current UI does not communicate that confidence. Brave's successful-search header snapshot must be labelled `OBSERVED`, not presented as an authoritative polled balance.

## 2. Canonical unit model — Option A (dual field)

### 2.1 Contract

Keep the existing raw `units: Decimal` and add nullable/additive fields so old rows and clients remain readable:

```text
UnitKind = REQUEST | CREDIT | USD | FREE

UsageEvent
  units: Decimal                 # raw event amount
  unit_kind: UnitKind | None     # stable aggregation dimension
  display_unit: str | None       # UI label, e.g. "requests", "credits", "USD"

QuotaSnapshot
  remaining: Decimal
  limit: Decimal | None
  unit_kind: UnitKind | None
  display_unit: str | None
  source: AUTHORITATIVE | OBSERVED | ESTIMATED
```

`QuotaSnapshot` currently has no `unit_kind` or `display_unit`; these are proposed contract additions. Until migration, `CostEstimate.currency` is the only available convention for distinguishing credits from USD and must be used consistently, not treated as a final model.

### 2.2 Semantics

- `REQUEST`: count of billable requests, pages, URLs, or result bundles only where that is the provider's quota dimension.
- `CREDIT`: vendor credits whose price/consumption rules belong to that vendor.
- `USD`: monetary amount, stored as decimal dollars (for example `Decimal("0.001")`).
- `FREE`: explicitly unmetered/local-zero activity. This is not interchangeable with unknown cost.
- `display_unit` is presentation only. Logic branches on `unit_kind`, never label text.
- Additive nullable columns permit a staged migration; legacy rows with `unit_kind IS NULL` remain visible but are grouped as legacy/unknown and never merged into a known dimension.
- Aggregate `usage_totals` by **`(provider, operation, unit_kind)`**, not merely provider and operation.
- Preserve raw Parallel SKU count in `UsageEvent.units`; perform SKU-to-USD conversion in the quota/cost projection layer and retain SKU metadata.
- Exclude zero-valued `FAILURE` events from usage totals. Do not infer that every successful zero means free; it can mean unavailable metering.
- Never sum `REQUEST`, `CREDIT`, `USD`, `FREE`, or unknown values together.

### 2.3 Decimal rules

- Parse vendor numeric/string inputs through strict `Decimal` validation.
- Reject NaN, infinities, booleans, and negative quota inputs unless the provider contract explicitly permits them.
- Clamp displayed remaining values with `max(Decimal("0"), value)`.
- Use decimal ceiling/floor operations explicitly. Do not cast through `float`.
- Preserve full storage precision; round only for display or a documented vendor billing increment.

## 3. Per-vendor strategy

### 3.1 Tavily — keep

**Decision:** no behavioral redesign. Continue polling Tavily `GET /usage` and treat returned credits as authoritative.

```text
unit_kind   = CREDIT
remaining   = Decimal(vendor remaining credits)
limit       = Decimal(vendor plan limit) when present, else None
source      = AUTHORITATIVE
```

Retain existing search/fetch credit estimates. The recorder, canonical unit fields, and UI confidence display are the missing shared pieces.

Docs:
- [Tavily API usage endpoint](https://docs.tavily.com/documentation/api-reference/endpoint/usage)
- [Tavily credits and pricing](https://docs.tavily.com/documentation/api-credits)

### 3.2 You.com — keep, with explicit usage gap

**Decision:** keep the current quota behavior. Vendor balance is cents; estimated calls must be floored because a partial call cannot be spent.

Let `b` be the validated balance in cents:

```text
balance_usd              = b / 100
estimated_search_calls   = floor(balance_usd / 0.005)
estimated_fetch_calls    = floor(balance_usd / 0.001)
limit                    = None
source                   = ESTIMATED
```

Search and fetch cannot share one request-count snapshot because their prices differ. Prefer displaying the authoritative monetary balance plus optional derived search/fetch call equivalents. The UI must not present either call count as a hard vendor limit.

Current cost assumptions:

```text
search = USD 0.005 per call
fetch  = USD 0.001 per URL
```

**Usage gap:** when a response omits usage, do not silently record a known zero. Record the event as metering unavailable/estimated in metadata or apply the documented local estimate; surface the confidence distinction.

Docs:
- [You.com API overview](https://documentation.you.com/)
- [You.com API pricing](https://documentation.you.com/api-reference/pricing)

### 3.3 Brave — observed monthly request quota from headers

Brave exposes no suitable vendor usage/balance API to poll proactively. Successful search responses provide three comma-pair headers:

```text
X-RateLimit-Remaining: "per-second remaining, monthly remaining"
X-RateLimit-Limit:     "per-second limit, monthly limit"
X-RateLimit-Reset:     "seconds to per-second reset, seconds to monthly reset"
```

For each header independently, split on `","`, take index `[1]`, strip whitespace, parse with `int`, and accept only values `>= 0`; an absent, malformed, missing-second, or negative value becomes `None`, never zero. Ignore index `[0]`: it describes per-second rate pressure, not monthly quota.

Capture one `now` in UTC and project the parsed monthly elements with Decimal-exact values:

```text
observed_at = now UTC
remaining   = Decimal(monthly_remaining) if present, else None
limit       = Decimal(monthly_limit) if present, else None
reset_at    = observed_at + timedelta(seconds=monthly_reset_secs) if present, else None
unit_kind   = REQUEST
display_unit = "requests"
source      = OBSERVED
```

Current-code gaps to fix:

- `_rate_limit_remaining` parses the entire `X-RateLimit-Remaining` value as one bare `int`, so a real comma pair such as `"1, 1000"` raises `ValueError` and becomes `None`.
- `X-RateLimit-Limit` and `X-RateLimit-Reset` are not read.
- The one parsed remaining value is metadata-only; no `QuotaSnapshot` is built.
- `record_quota` is never called.
- `capabilities.quota` remains its default `False`, and inherited `quota()` returns `None`.

Extend header parsing, build the `OBSERVED` request snapshot, and piggyback `record_quota` on the successful-search path. Proactive polling is impossible because obtaining these headers costs a search query. A search error raises before this success path, so 429 and other failures may not expose usable headers.

Before implementation, verify the documented pair order `[per-second, monthly]` against a real response and observe whether 429 responses carry these headers. Malformed elements remain unknown (`None`), never exhausted (`0`). Optional dollar-spend tracking may be considered later, but it is not part of v1.

Docs:
- [Brave Search API plans and pricing](https://brave.com/search/api/)
- [Brave Search API documentation](https://api-dashboard.search.brave.com/app/documentation)

### 3.4 Keenable — keyed allowance versus keyless rate limits

#### Keyed adapter

Endpoints use `/v1/search` and `/v1/fetch` with `X-API-Key`. Authenticated Free provides **100,000 requests/month**. The console shows allowance and remaining balance. Keenable describes one credit as one request for ordinary search/fetch, but differently priced operations may draw more; use reported cost when available.

Known SKUs include `search.realtime`, `search.pro`, `fetch`, and `fetch.live`.

```text
allowance_limit       = Decimal("100000")
allowance_spend       = Σ allowance credits in current month
remaining             = max(0, allowance_limit - allowance_spend)
unit_kind             = CREDIT (display "requests/credits" only after SKU rules verified)
source                = OBSERVED local counter
reset_at              = first day of next month 00:00Z (PROVISIONAL)
```

Authenticated MCP can report `_meta["keenable/usage"] = {sku, amount, credits, paid}`:

- `paid=false`: decrement monthly allowance by `credits`.
- `paid=true`: purchased usage must not be deducted from the free allowance. Until the model supports two counters, set combined remaining to `None` and preserve both values in metadata rather than fabricating one balance.
- If per-call credit detail is absent, fallback to one allowance credit per successful call and mark confidence accordingly.

REST per-call usage is undocumented in the supplied research. Inspect/verify `openapi.json` before coding.

**Error semantics**

- `402` on keyed `/v1/search` or `/v1/fetch`: persist `remaining=0` as a hard monthly exhaustion signal, mark `quota_exhausted` non-retryable, and let routing steer away.
- `429`: transient rate/concurrency excess; continue handling through `ResilientRunner` and honor retry metadata. Never turn it into monthly exhaustion.
- `400/401/403`: request/auth failures, not quota depletion.
- Re-anchor the local counter only on confirmed month rollover or after a 402/manual console reconciliation.

#### Keyless Public Tier

Endpoints use `/v1/search/public` and `/v1/fetch/public` with `X-Keenable-Title`. Keyless access is a testing/shared-pool mode, not metered monthly allowance:

```text
quota snapshot = None
raw usage      = 0 / FREE with metadata mode="keyless"
estimated cost = 0
```

Public findings report up to **1,000 requests/hour via MCP** and **10 requests/second per IP** in a shared pool. These are rate limits, not quota. The exact REST keyless limit remains unverified.

For keyed operation, fix `estimate_cost` from zero to approximately **USD 0.004/request** for the advertised $4/1,000 cloud price, while keeping the quota counter in credits/requests. Dedicated pricing is reported as $1/1,000 at 100 RPS+ and must not be assumed for normal cloud keys.

Docs (verify paths during implementation because the vendor surface is evolving):
- [Keenable documentation](https://docs.keenable.com/)
- [Keenable API OpenAPI document](https://api.keenable.com/openapi.json)
- [Keenable pricing](https://keenable.com/pricing)

### 3.5 Firecrawl — authoritative credit polling

#### Quota endpoint

Poll:

```http
GET /v2/team/credit-usage
Authorization: Bearer fc-...
```

Expected body includes `remainingCredits`, `planCredits`, `billingPeriodStart`, and `billingPeriodEnd`.

Do **not** use `/token-usage` as current quota: it is legacy (`1 credit = 15 tokens`). Historical credit usage is appropriate for month-by-month burn-rate charts only.

```text
q(v)        = strict finite, non-negative Decimal validation
remaining   = max(0, q(remainingCredits))
limit       = q(planCredits) if valid/present, else None
reset_at    = ISO-8601 parse(billingPeriodEnd) if valid/present, else None
unit_kind   = CREDIT
source      = AUTHORITATIVE
```

`planCredits` excludes coupons, packs, and recharge credits. Therefore `remainingCredits` is the operational truth and `planCredits` is only the baseline limit; remaining may legitimately exceed baseline.

#### Cost table

| Operation/modifier | Credit estimate |
|---|---:|
| Scrape | 1 per page |
| Crawl | 1 per page |
| Map | 1 per call |
| Search | 2 per 10 results, rounded up by result bundle |
| Interact | 2 per browser-minute |
| Agent | Dynamic; do not pretend a fixed estimate |
| PDF parsing | +1 per page |
| JSON/LLM extraction | +4 |
| Enhanced | +4 |
| Zero Data Retention | +1 |
| Status polling | 0 |

Target-site 4xx responses can still be billed. Batch charges can appear asynchronously minutes or hours later, so local event estimates are not authoritative.

Required estimate formulas:

```text
search_credits(limit) = ceil(Decimal(limit) / 10) × 2
fetch_credits          = 1 + pdf_pages + json_or_llm_extract + enhanced + zdr
```

Modifier terms are credit increments activated by request options; page-multiplied modifiers must use the actual/estimated page count. The current Firecrawl `estimate_cost` returning zero must be fixed to these credit estimates and `currency=CREDIT` (or the interim repository convention).

#### Polling and failures

- Poll on demand through a shared TTL cache, suggested **60–300 seconds**; never poll on every search/fetch request.
- Force refresh after `402` and `429`, while preserving their distinct meanings.
- `402 Insufficient credits` is non-retryable unless external balance/plan state changes.
- With Smart Upgrade enabled, Firecrawl steps up a tier when credits reach zero, stopping at Scale (1M) before Enterprise; without it, exhaustion returns 402. This is not pure pay-as-you-go.
- Crawl pre-flight may require enough balance for the full requested limit. Default crawl limit can be 10,000, so pass a small explicit limit.
- `429` means rate/concurrency pressure; honor `Retry-After`. Per-plan request/minute limits apply (Free findings include values such as 10/10/2/10 by endpoint; use the current vendor table rather than embedding these provisional figures).
- Free allocation sources conflict between approximately **500 and 1,000 credits**. **UNVERIFIED: confirm at implementation time.** Never derive the hard limit from marketing copy when the endpoint provides `planCredits`.

Docs:
- [Credit usage](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage)
- [Legacy token usage](https://docs.firecrawl.dev/api-reference/endpoint/token-usage)
- [Historical credit usage](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage-historical)
- [Billing](https://docs.firecrawl.dev/contributing/guide/billing)
- [Rate limits](https://docs.firecrawl.dev/rate-limits)
- [Errors](https://docs.firecrawl.dev/api-reference/introduction#errors)
- [Pricing](https://www.firecrawl.dev/pricing)

### 3.6 Parallel — local USD counter, no API-key balance poll

Parallel's response includes usage entries such as `sku_search: 1`. Their sum is raw activity, not USD credit balance. Keep `UsageEvent.units = Σ usage[].count` with SKU metadata, then price it in the quota layer.

Known pricing assumptions:

```text
search turbo                 = USD 0.001/request
search basic or advanced     = USD 0.005/request
omitted search mode          = advanced by OpenAPI default = USD 0.005
extra result bundle          = USD 0.001 each
extract                      = USD 0.001 × URL count
```

This corrects the adapter's stale blanket “1 free-tier credit” estimate. `estimate_cost` must be network-free, mode-aware, decimal-valued, and `currency=USD`.

```text
cost_usd(search) = mode_price + Decimal("0.001") × extra_bundles
cost_usd(extract) = Decimal("0.001") × url_count
period_spend = Σ successful billed operation costs
```

Billing is success-only. Failed requests do not decrement the local budget.

For an eligible free organization:

```text
seed_budget = Decimal("5.00") per month
remaining   = max(0, seed_budget - period_spend)
limit       = seed_budget
reset_at    = end-of-month boundary
unit_kind   = USD
source      = OBSERVED/ESTIMATED local counter
```

The reported free USD 5/month requires an eligible organization and card, is limited to approximately one organization/card, and expires at end of month. **UNVERIFIED: eligibility and exact reset behavior must be confirmed before seeding.** For non-eligible/unknown accounts, maintain a spend ledger but set `remaining=None` and `limit=None`.

#### Why polling is unavailable

The adapter authenticates `/v1/search` and `/v1/extract` with `x-api-key`. The balance endpoint `GET /service/v1/balance` requires an OAuth device-grant Bearer token; an API key cannot call it. Therefore automated balance polling is impossible without introducing a separate credential flow, which is out of this plan's current scope. Keep `capabilities.quota=False` for now.

#### Error semantics

- `402`: includes balance exhaustion and in-flight reservation shortfalls (`available < total`). Record `remaining=0` as a **soft**, temporary signal. Expire/clear it on the next successful billed operation or reconciliation; do not treat it as a hard month-long lockout.
- `429`: transient search/extract rate or concurrency limit (reported limits include 600/minute); it is not spend exhaustion.
- Spend limits are notify-only and do not establish a hard quota.

Docs:
- [Parallel API documentation](https://docs.parallel.ai/)
- [Search API](https://docs.parallel.ai/api-reference/search-v1/search)
- [Extract API](https://docs.parallel.ai/api-reference/extract-v1/extract)
- [Pricing](https://parallel.ai/pricing)

### 3.7 Exa — no change

Keep Exa's existing transparent USD estimates, including the current `Decimal("0.001")` convention where applicable. The shared model change merely labels these values as `unit_kind=USD` and prevents them being added to request or credit counts. No quota endpoint or new local allowance is proposed.

Docs:
- [Exa API documentation](https://docs.exa.ai/)
- [Exa pricing](https://exa.ai/pricing)

## 4. Target files (future work; no code now)

### Backend/contracts and persistence

- `src/freesearch/contracts.py` — add `UnitKind`, `unit_kind`, and `display_unit` to usage/quota contracts.
- `src/freesearch/storage.py` — additive nullable columns/migration path; aggregate by `(provider, operation, unit_kind)`; exclude zero `FAILURE` totals.
- `src/freesearch/monitoring.py` — quota polling/recording orchestration, TTL behavior, and dashboard projection.
- `src/freesearch/api.py`, `src/freesearch/control.py`, `src/freesearch/server.py` — wire polling at the appropriate service boundary without per-request vendor calls.
- `src/freesearch/routing.py` — feed real persisted quota state into the routing gate and distinguish hard, soft, and transient signals.
- `src/freesearch/config.py`, `src/freesearch/provider_config.py` — any opt-in Parallel budget eligibility settings.

### Backend/providers

- `src/freesearch/adapters/tavily.py` — preserve authoritative behavior; attach canonical units.
- `src/freesearch/adapters/youcom.py`, `src/freesearch/adapters/_youcom_support.py` — preserve balance conversion and identify missing usage.
- `src/freesearch/adapters/brave.py` — extend all three comma-pair header parsers, build an `OBSERVED` monthly `REQUEST` snapshot, and piggyback `record_quota` after successful search.
- `src/freesearch/adapters/keenable.py` — keyed/keyless accounting metadata and nonzero keyed estimate.
- `src/freesearch/adapters/firecrawl.py` — `/v2/team/credit-usage`, cost formulas, TTL-compatible quota method.
- `src/freesearch/adapters/parallel.py` — SKU metadata and mode-aware USD estimates.
- `src/freesearch/adapters/exa.py` — canonical USD labeling only.
- `src/freesearch/adapters/base.py` — only if shared quota/cost contract signatures require it.

### Frontend

- `freesearch-ui/src/services/api/backendTypes.ts` — receive canonical units/confidence metadata.
- `freesearch-ui/src/services/api/mappers.ts` — preserve unit kind, display unit, and confidence.
- `freesearch-ui/src/types/freesearch.ts` — model canonical units.
- `freesearch-ui/src/context/FreeSearchContext.tsx` — retain dashboard quota rather than static/provider-only estimates.
- `freesearch-ui/src/components/quota/QuotaAnalytics.tsx` — dimension-safe totals, confidence labels, and unavailable states.
- `freesearch-ui/src/components/routing/ProviderRanks.tsx` and `RouteSimulator.tsx` — show only comparable quota values and hard/soft routing state.

Independent test files are constraints in a future implementation cycle and are not targets for modification.

## 5. Acceptance criteria

### Shared AC-1 through AC-8

- **AC-1 — Persistence pipeline:** quota-capable providers are polled through a bounded TTL/on-demand service and every valid result reaches `record_quota`; populated providers no longer yield a universally empty `latest_quota`.
- **AC-2 — Brave observed headers:** an unconfigured Brave quota reports “quota unavailable” only until the first successful search. After a successful search with valid comma-pair headers, `remaining`, `limit`, and `reset_at` come from the second elements of `X-RateLimit-Remaining`, `X-RateLimit-Limit`, and `X-RateLimit-Reset`; the snapshot uses `unit_kind=REQUEST`, `source=OBSERVED`, and Decimal-exact quota values. Absent or malformed elements become `None`, never zero. No USD 5.00 wallet math is used.
- **AC-3 — Safe aggregation:** `usage_totals` groups by `(provider, operation, unit_kind)`, never combines incompatible dimensions, and excludes zero-unit `FAILURE` rows.
- **AC-4 — Existing authoritative providers:** Tavily remains authoritative from `GET /usage`; You.com remains estimated with `limit=None`, floored call equivalents, and explicit missing-usage handling.
- **AC-5 — Local providers:** Keenable keyed and Parallel use their documented local-counter rules.
- **AC-6 — Routing semantics:** hard exhaustion can steer routing away; Parallel soft 402 expires on later success; 429 never becomes quota exhaustion; empty/unknown quota does not masquerade as zero.
- **AC-7 — Honest UI:** the dashboard displays unit labels and `AUTHORITATIVE`/`OBSERVED`/`ESTIMATED` confidence and leaves unknown limits blank.
- **AC-8 — Compatibility and privacy:** new fields are additive/nullable, API serialization stays backward compatible, credentials are never persisted in usage metadata, and vendor polling is bounded rather than per request.

### Firecrawl-specific ACs

- **AC-FC-1:** Firecrawl quota uses `GET /v2/team/credit-usage` with Bearer auth and maps remaining, plan baseline, and billing-period end as authoritative credit data.
- **AC-FC-2:** malformed/nonfinite/negative fields are rejected safely; absent optional limit/reset fields become `None`; `remainingCredits` remains truth even when greater than `planCredits`.
- **AC-FC-3:** estimates are `ceil(limit/10) × 2` credits for search and `1 + modifiers` for fetch; status polling is free; dynamic agent cost is not fabricated.
- **AC-FC-4:** quota polling uses a configurable 60–300 second TTL/on-demand cache and refreshes after 402/429 without polling every operation.
- **AC-FC-5:** 402 is non-retryable insufficient credit, 429 follows `Retry-After`, and crawl requests pass a deliberate small limit rather than relying on the 10,000 default.

### Parallel-specific ACs

- **AC-PA-1:** raw response SKU counts and SKU metadata are retained, while quota projection prices them in Decimal USD using a verified SKU table.
- **AC-PA-2:** search estimation is mode-aware (turbo USD 0.001; omitted/default advanced USD 0.005; extras USD 0.001/bundle), and extract estimates USD 0.001 per URL.
- **AC-PA-3:** eligible free accounts may opt into a USD 5.00 monthly local seed; accounts without verified eligibility report spend with `remaining=None`, not a fabricated balance.
- **AC-PA-4:** no API-key balance poll is attempted against the OAuth-only balance endpoint; `capabilities.quota` stays false until a supported credential design exists.
- **AC-PA-5:** only successful billed activity decrements local budget; 402 creates a soft zero cleared by later success/reconciliation, while 429 remains transient.

## 6. Open questions and implementation verification list

1. **Brave wallet inputs — SUPERSEDED:** cost/query defaults, a local reset anchor, and re-sync UX are no longer v1 inputs; the observed monthly header elements supersede the wallet model.
2. **Brave header pair order:** verify against a real successful response that index `[1]` is monthly and index `[0]` is per-second for all three rate-limit headers.
3. **Brave 429 headers:** verify whether 429 responses include usable rate-limit headers despite the current error path raising before response parsing.
4. **Keenable keyless limit:** verify whether 1,000/hour applies only through MCP or also REST public endpoints; confirm the documented 10 req/s per-IP/shared-pool limits.
5. **Keenable reset day:** calendar-month rollover is provisional. Verify the actual organization billing/allowance reset day.
6. **Keenable REST usage block:** inspect the current `openapi.json` and real keyed responses for SKU, `amount`, `credits`, and `paid`; determine how purchased and free balances coexist.
7. **Full SKU table:** verify prices/credit weights for all Keenable and Parallel SKUs, modes, extra bundles, live fetch, and future variants before coding conversion logic.
8. **Polling cadence/cost:** choose the exact TTL within 60–300 seconds, request coalescing behavior, stale-on-error policy, and whether vendor quota endpoints themselves are rate-limited/billed.
9. **Legacy data jump:** decide how historical rows with `unit_kind=NULL` appear and whether a deterministic backfill is safe. Never infer units solely from a number such as `1` or `0.001`.
10. **You.com dual display:** decide whether the primary UI shows cents/USD balance, search-call equivalent, fetch-call equivalent, or all three without implying both call pools are independently spendable.
11. **Firecrawl Free allocation:** sources conflict at roughly 500–1,000 credits; verify in the endpoint/current pricing at implementation time.
12. **Parallel eligibility:** verify free-credit eligibility, card/org restriction, expiration, and reset semantics before enabling the USD 5.00 seed.
13. **Parallel OAuth:** decide whether a future device-grant credential is desirable; it is explicitly outside the API-key adapter strategy in this plan.
14. **Soft-signal expiry:** define a bounded timeout in addition to “next success” for Parallel 402 so a stale soft zero cannot suppress the provider indefinitely.

## 7. Historical DB migration (copy-test-replace, no data loss)

This is a migration design, not authorization to run a migration. The existing `freesearch.db` contains useful historical telemetry and must never be discarded, recreated, or migrated in place. Implementation of the script and every database operation below remains future work pending explicit approval.

### 7.1 Safety principles and rollback boundary

Use a **copy → migrate the copy → verify the copy → atomically swap** workflow:

1. Quiesce all database writers while leaving the existing `psmux` sessions (`freesearch-api`, `freesearch-ui`, and `freesearch-mcp`) alive.
2. Create a timestamped, byte-for-byte backup such as `freesearch.db.bak.YYYYMMDD-HHMMSS`, plus matching `-wal`/`-shm` sidecars when a clean checkpoint is not possible.
3. Verify that the backup opens read-only, passes `PRAGMA integrity_check`, and has the recorded table counts and hashes.
4. Copy the source to a separate destination, migrate **only** that copy, and perform all verification and smoke tests against it.
5. Quiesce writers again, make and verify a final timestamped backup, then place the verified copy on the same filesystem as the destination and use an atomic rename/replace.
6. Keep every backup until the user confirms the post-swap data and UI. Do not automatically delete it.

Rollback is the reverse swap: stop writes briefly, preserve the rejected migrated file for diagnosis, atomically restore the verified `.bak` file (and its coordinated sidecars if applicable), start/re-point only the API process in its existing `freesearch-api` session, and repeat integrity, count, hash, and application checks. Never stop, kill, reconfigure, or otherwise touch the `deepseek-harness` session.

### 7.2 Pre-migration inventory and write quiescence

Before any copy, record the source path, byte size, SQLite version, `PRAGMA journal_mode`, `PRAGMA user_version`, and the presence and size of `freesearch.db-wal` and `freesearch.db-shm`. Capture:

- a schema dump from `sqlite_master` (tables, columns, indexes, and triggers), ordered deterministically;
- row counts for every table, especially `usage_events` and `quota_snapshots`;
- a deterministic SHA-256 of each table's canonical, primary-key-ordered row serialization;
- for `usage_events`, count, exact Decimal sum, and an ordered hash of `(id, provider, operation, units)` for each `(provider, operation)` group; and
- the whole-file SHA-256 only after writers are quiesced and WAL state is resolved.

Do not rely on a file hash taken while writes are active. First stop incoming search/fetch/control traffic, wait for in-flight requests to drain, and prevent scheduled/background quota writes. Leave the `psmux` sessions themselves running. If traffic isolation alone cannot guarantee this, send the normal interrupt to the `freesearch-api` child process **inside the existing `freesearch-api` session** so its SQLite connection closes while the session remains alive; do not kill the session. The UI and MCP sessions may remain alive but must not send write-producing traffic during the window. Record the exact existing API launch command before interruption so it can be restarted unchanged.

For WAL mode, prefer a clean checkpoint (`PRAGMA wal_checkpoint(TRUNCATE)`) only after exclusive write quiescence, then copy the main database. If a checkpoint cannot be obtained, copy the database, `-wal`, and `-shm` as one coordinated snapshot using SQLite's backup API or another SQLite-aware method; copying only `freesearch.db` while a live WAL exists is not a valid backup.

### 7.3 Additive, nullable, idempotent schema changes

The historical migration adds exactly these nullable columns:

| Table | Column | SQLite declaration |
|---|---|---|
| `usage_events` | `unit_kind` | `TEXT NULL` |
| `quota_snapshots` | `unit_kind` | `TEXT NULL` |
| `quota_snapshots` | `display_unit` | `TEXT NULL` |

The script must use the same introspection pattern as `storage.py::_add_missing_column`: read `PRAGMA table_info(<table>)`, and run `ALTER TABLE ... ADD COLUMN ... TEXT` only when the named column is absent. SQLite's added `TEXT` column is nullable unless constrained otherwise. In equivalent SQL:

```sql
ALTER TABLE usage_events ADD COLUMN unit_kind TEXT;
ALTER TABLE quota_snapshots ADD COLUMN unit_kind TEXT;
ALTER TABLE quota_snapshots ADD COLUMN display_unit TEXT;
```

These statements are examples, not an unconditional batch: each is guarded by the column-existence check. Re-running the migration must be safe. Backfill updates must likewise target only rows that are unclassified or carry this migration's prior classification, and the migration ledger version must prevent duplicate work. Do not rebuild either table, drop columns, renumber IDs, alter raw `units`, or coerce decimal text through floating point. This migration does not add `usage_events.display_unit`; historical usage labels are derived from `unit_kind` unless the approved implementation schema later explicitly expands this migration.

Create an index only when the approved query plan demonstrates a need—for example, a guarded index over `usage_events(provider, operation, unit_kind, observed_at)`. Use `CREATE INDEX IF NOT EXISTS` and verify the query plan before retaining it.

### 7.4 Deterministic historical backfill

Classification uses normalized provider and operation names plus trusted historical metadata; it never guesses from a numeric magnitude such as `1` or `0.001`. Raw `usage_events.units` text and value are immutable.

| Historical provider/operation evidence | `unit_kind` | Rule |
|---|---|---|
| Brave search/fetch rows recorded as request telemetry | `REQUEST` | Preserve the raw request count. Future observed Brave header snapshots are separate quota records and must not rewrite these units. |
| Tavily metered search/fetch | `CREDIT` | Existing raw units are vendor credits. |
| Exa metered operations | `USD` | Existing estimates are decimal USD. |
| You.com search/fetch with recorded or documented local estimate | `USD` | Preserve the recorded USD estimate. If old You usage is missing or zero with no evidence that zero is a real metered amount, leave it legacy rather than inventing cost. |
| Parallel row with trusted metadata proving a raw SKU count | `REQUEST` | Preserve SKU count and metadata; pricing remains a separate USD projection under §3.6. |
| Parallel row with trusted evidence that the stored value is already priced spend | `USD` | Use only when metadata/schema provenance makes this deterministic. |
| Keenable keyless/unmetered row explicitly identified as such | `FREE` | A successful known keyless zero can be classified free. |
| Keenable keyed row with request-count evidence | `REQUEST` | Preserve request telemetry; do not silently reinterpret it as vendor credits. |
| Zero-unit row with `status=FAILURE` | Provider mapping when deterministic, otherwise `NULL` | Keep `units=0` and the failure row for observability; mark it `excluded_from_sums=true` in migration metadata and ensure aggregation excludes it. |
| Unknown provider/operation or insufficient evidence | `NULL` | Legacy/unknown; do not infer a kind. |

Parallel rows whose metadata cannot distinguish raw SKU counts from already priced USD, old You.com rows missing trustworthy usage, and any other mixed historical group remain `unit_kind=NULL`. The script adds a non-sensitive metadata annotation such as `migration_unit_note: "legacy (mixed)"` and an ambiguity flag without removing existing metadata. If the metadata cannot be safely decoded and merged, leave it byte-for-byte unchanged and report the row in the migration ledger/report rather than risking corruption.

The UI renders these rows in a separate **Legacy (mixed)** group with the original raw value and provider/operation visible, no currency/credit/request claim, and an explanation that the dimension could not be recovered. They remain available in activity/history but are excluded from known-kind and cross-kind totals. No total may combine `REQUEST`, `CREDIT`, `USD`, `FREE`, or `NULL`.

For existing `quota_snapshots` rows:

- Tavily becomes `unit_kind=CREDIT`, `display_unit="credits"`.
- You.com becomes `unit_kind=USD`, `display_unit="USD"`; any call count shown by the UI is explicitly derived and labelled “calls (estimated),” not stored as a second spendable quota.
- A future deterministically supported provider may be mapped only from the approved provider table and recorded provenance.
- Unknown or ambiguous providers remain `unit_kind=NULL`, `display_unit=NULL` and render as legacy.

The current repository may have few or zero quota rows; the script must handle the empty table without special failure and must never fabricate snapshots.

### 7.5 Future custom migration script contract

Implement, after approval, `scripts/migrate_quota_units.py` with this interface:

```text
python scripts/migrate_quota_units.py --src PATH --dst PATH [--dry-run] [--verify-only]
```

- `--src` is always opened read-only and is never the update target.
- `--dst` is the copied/migrated candidate. A normal run refuses to overwrite an existing destination; `--verify-only` opens an existing destination read-only.
- `--dry-run` performs schema/data discovery and prints exact planned column additions, indexes, per-rule update counts, ambiguous counts, and expected ledger data without copying or writing either path.
- `--verify-only` runs the complete verification suite without schema or data changes.

A normal run must:

1. Validate paths, free disk space, source integrity, WAL state, schema compatibility, and that source and destination are different files.
2. Copy with `shutil.copy2`/file-copy semantics only after a clean checkpoint, or use SQLite's online backup API for a coordinated live snapshot. Open only the destination read-write.
3. Add missing columns using the `_add_missing_column`-equivalent guard.
4. Begin a transaction, backfill deterministic rows in bounded primary-key batches, annotate/report ambiguities, and roll back the entire logical migration on error.
5. Create any approved index idempotently.
6. Write an idempotent migration ledger row in a dedicated table (for example `schema_migrations`) containing migration version, UTC timestamp, source fingerprint, before/after row counts, per-rule changed/ambiguous counts, and script version. Do not store credentials or request content.
7. Commit, then run `VACUUM` outside the transaction only when adequate disk space exists, followed by `PRAGMA integrity_check` and all semantic verification. A VACUUM failure blocks the swap but never damages the source.
8. Emit a machine-readable report alongside the candidate; never claim success when any blocking check fails.

### 7.6 Verification and acceptance on the copy

Verification is performed against the candidate copy, never by starting the normal service on the original during migration:

- Every pre-existing table has exactly the same row count before and after; only the dedicated migration-ledger table may gain its expected row.
- The canonical per-table hashes are unchanged except for the three added/backfilled columns, approved metadata annotations, the optional index/schema objects, and the ledger. Hash unchanged projected legacy columns separately to prove all pre-existing values survived.
- For every `(provider, operation)`, the raw-units count, exact Decimal sum, and ordered `(id, provider, operation, units)` SHA-256 match the source exactly.
- `PRAGMA integrity_check` returns exactly `ok`; foreign-key checks (if enabled) return no rows; schema before/after differs only by approved additive objects.
- No previously non-NULL value becomes NULL, no ID changes, no timestamp changes, and no Decimal is parsed through `float`.
- Classification totals reconcile: deterministic updates + ambiguous/legacy rows equal the original candidate row count, with no unaccounted row.

Required spot checks include queries equivalent to:

```sql
SELECT unit_kind, COUNT(*) FROM usage_events
 WHERE lower(provider) = 'brave' GROUP BY unit_kind;
SELECT units, unit_kind, metadata FROM usage_events
 WHERE lower(provider) = 'exa' ORDER BY id LIMIT 20;
SELECT id, units, status, unit_kind, metadata FROM usage_events
 WHERE units = '0' AND upper(COALESCE(status, 'SUCCESS')) = 'FAILURE';
SELECT provider, operation, unit_kind, COUNT(*) FROM usage_events
 GROUP BY provider, operation, unit_kind ORDER BY provider, operation, unit_kind;
```

Brave rows eligible under the mapping must all be `REQUEST`; Exa values must remain at their original USD scale and be labelled `USD`; zero-unit failures must still exist unchanged and carry/report the exclusion marker; ambiguous Parallel/You rows must remain NULL/legacy rather than being guessed.

For the application smoke test, set the documented `FREESEARCH_DB` override to the candidate path and start/re-point the API **only in the existing `freesearch-api` session**, for example with the repository's normal launcher `FREESEARCH_DB=<candidate-path> uv run freesearch-api` (PowerShell: `$env:FREESEARCH_DB='<candidate-path>'; uv run freesearch-api`). Keep the production writer quiesced. Load `/dashboard` and the approved `/usage` endpoint when present; until a separate `/usage` route exists, inspect `/dashboard`'s `usage_totals`. Confirm totals are grouped by `(provider, operation, unit_kind)`, legacy is separate, `latest_quota` deserializes, and activity shows correct unit labels and failure rows without adding failure zeros to totals.

The swap is blocked by any integrity error, count/hash mismatch, raw-unit difference, unclassified row outside the reported ambiguity set, schema drift, app deserialization error, cross-kind sum, incorrect unit label, unexpected write to the source, unresolved WAL snapshot, inability to obtain write quiescence, or inadequate free disk space. Acceptance requires all checks to pass, 100% reconciliation of source rows, zero raw-unit mutations, and explicit user approval of the generated report.

### 7.7 Production swap and post-swap checks

Perform these steps in order:

1. Confirm the candidate's final report is green and obtain approval to schedule the swap.
2. Stop incoming traffic and scheduled writes; drain requests. Briefly interrupt only the API child in the existing `freesearch-api` session, leaving all `psmux` sessions alive. Do not touch `deepseek-harness`.
3. Resolve WAL safely and create `freesearch.db.bak.YYYYMMDD-HHMMSS` from the now-stable original, including coordinated sidecars if no checkpoint was possible.
4. Open the backup read-only; require `integrity_check=ok`, expected schema, matching counts, projected hashes, and raw-unit checksums.
5. Ensure the verified candidate is on the same filesystem and in the same directory boundary needed for atomic replacement. Close all SQLite handles, remove no backup, and atomically replace `freesearch.db` with the candidate. Handle stale `-wal`/`-shm` only as a coordinated set; never attach old sidecars to the new main file.
6. In the existing `freesearch-api` session only, restore the recorded normal command/environment (normally `uv run freesearch-api`, with `FREESEARCH_DB` pointing to the production path if explicitly configured). Do not create a replacement session and do not restart the UI, MCP, or `deepseek-harness` sessions.
7. Re-enable traffic gradually and verify `/dashboard`, usage totals by kind, recent activity unit rendering, `latest_quota` for Tavily/You.com and unknown providers, plus one approved non-destructive read path. Watch logs for SQLite schema, lock, and deserialization errors.
8. Re-record counts and projected hashes and compare them with the migration report. Keep the backup until the user explicitly confirms success.

A SQLite hot-swap is allowed only if the platform, journal mode, connection lifecycle, and SQLite backup/replace behavior have been proven safe in rehearsal. The default is a brief API-process stop with all handles closed. On Windows, atomic replace requires source and destination on the same volume and may fail while a handle is open; such a failure blocks the swap rather than justifying an in-place migration.

If post-swap verification fails, quiesce traffic, stop only the API child, preserve the failed migrated DB under a diagnostic name, atomically restore the verified backup and its correct sidecar state, restart the recorded API command in `freesearch-api`, and repeat integrity/count/hash plus `/dashboard` checks before reopening traffic.

### 7.8 Risks and mitigations

| Risk | Mitigation |
|---|---|
| Large database, insufficient disk, or long `VACUUM` | Measure source plus WAL first; require space for source, backup, candidate, VACUUM working space, and rollback copy; batch updates; rehearse and estimate downtime; omit no verification. |
| SQLite locks/open Windows handles | Drain traffic and close the API's repository cleanly while retaining its `psmux` session; use a bounded lock timeout; abort rather than force file replacement. |
| WAL/SHM inconsistency | Prefer quiesce plus checkpoint; otherwise use SQLite online backup or copy main/WAL/SHM as a coordinated set; never mix sidecars from source, candidate, or backup. |
| Concurrent writes during copy | Stop ingress and background quota writers, drain in-flight work, compare pre/post source counters, and restart the copy if the source fingerprint changes. |
| Ambiguous legacy units | Use provider/operation plus trusted metadata only; leave uncertainty as `NULL` with `legacy (mixed)` annotation; exclude it from typed totals while preserving it in history. |
| Parallel or You.com price-table changes | Do not retroactively price rows from today's table. Backfill USD only where historical metadata records the applicable mode/SKU/price provenance; otherwise preserve raw data as legacy and defer projection. Version every future price table. |
| Metadata parse/corruption risk | Preserve undecodable metadata unchanged, report its row ID, and leave `unit_kind=NULL`; never rewrite the whole row merely to add an annotation. |
| Script interruption or partial work | Use one transaction for schema/backfill/ledger where SQLite permits, idempotent guards, deterministic batches, and a source that is never writable; discard the candidate and recopy on uncertainty. |

> **Status remains PLANNING ONLY — DO NOT IMPLEMENT.** This section specifies a future migration rehearsal and swap procedure; it does not authorize creation of `scripts/migrate_quota_units.py`, modification of `freesearch.db`, or any backend/frontend/test change.
