# Provider Limits — Rate Limits vs Budget Limits (research)

**Date:** 2026-10-05
**Method:** `freesearch` MCP `search` + `fetch` with routing `prefer ["keenable","tinyfish"] allow_fallback true`, `firecrawl` as fetch backup. All authoritative pages below were fetched through the MCP (no plain-web fallback).
**Goal:** separate **rate limits** (how *fast* you may call — req/sec/min, concurrency, 429 + `Retry-After`) from **budget limits** (how *much* you may spend — credits / USD / requests per day-month, 402 / quota headers / usage API), per operation (**search** vs **fetch/extract/contents/scrape**), per auth mode (**keyless/free** vs **keyed/paid**). No code was changed for this doc.

> Current code merges the two (some providers surface a rate number, others a budget number in the same field). The proposal at the bottom gives each its own settings block so free/keyless providers can have **rate-only** (no budget) and paid providers **rate + budget**.

---

## 1. Keenable (`api.keenable.ai`, keyless-capable)

Keyless by design. Free tier works with no key; a key raises rate limits and switches on metering.

### Rate limits (throughput)
| Auth | Limit | Scope |
|---|---|---|
| Authenticated (`X-API-Key: keen_***` or login) | **10 req/sec** | per organization |
| Unauthenticated (keyless) | **1,000 req/hour, max 10 req/sec** | per IP, shared public pool |

- Same bucket for **search and fetch** (docs: "applies across search and fetch endpoints").
- Auth removes the hourly cap; the per-second cap stays. Higher per-second available on some plans — contact sales.
- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`; 429 adds `Retry-After`.
- Shared-IP caveat: keyless headroom depends on other traffic from the same egress IP — outside your control.

### Budget limits (money / volume)
- **Keyless: no budget, not metered at all.** Capped only by rate limits above. Evaluating without a key does not draw on any allowance.
- **Keyed: 100,000 requests/month free**, resets monthly (recurring, not one-off trial). Shown in console at `app.keenable.ai/console`.
- Search and fetch each cost **1 credit** in the default modes (`search.pro`, `fetch`); other SKUs (`search.realtime`, `fetch.live`, future SKUs) can cost more than 1 — **read per-call cost from the response, don't count calls**.
- Per-call usage (MCP): `_meta["keenable/usage"] = {sku, amount, credits, paid}` where `paid=false` = free allowance, `true` = purchased credits. REST echoes mode/cost similarly. Unauthenticated calls omit the block.
- Exhausted (allowance + purchased = 0): `/v1/search` and `/v1/fetch` return **402**. Buy a package in console or wait for monthly reset.
- Published list price (secondary): Agent Builder **$4 / 1,000 requests**, Frontier **$1 / 1,000** (100+ RPS, cloud or on-prem).

### Keyless vs keyed
- Keyless: no signup, `X-Keenable-Title` app header only; lower rate (hourly cap), no budget, no realtime mode.
- Keyed: `keenable login` (device-code) or `KEENABLE_API_KEY`; removes hourly cap, enables monthly allowance + purchased credits + realtime.

### Sources
- https://keenableai.mintlify.app/rate-limits (fetched)
- https://keenableai.mintlify.app/credits (fetched)
- https://keenableai.mintlify.app/api-reference (search snippet)
- https://keenableai.mintlify.app/changelog (10 rps / 1k-per-hour numbers)

### Proposed separated settings
```yaml
keenable:
  rate:  { search_rps: 10, fetch_rps: 10, keyless_per_hour: 1000, keyless_rps: 10, scope_keyed: org, scope_keyless: ip }
  budget: { monthly_free_requests: 100000, per_call_credits_from_response: true, keyless_budget: null, on_exhausted: http_402 }
```

---

## 2. Tinyfish (`api.search.tinyfish.ai` GET, `api.fetch.tinyfish.ai` POST)

Free Search + Fetch for every keyed account. Wallet exists but Search/Fetch never draw from it.

### Rate limits (throughput — search vs fetch SEPARATE)
| Operation | Limit | Unit |
|---|---|---|
| **Search** | **30 requests/min** + **500 requests/hour** | requests |
| **Fetch** | **150 URLs/min** + **1,000 URLs/day**, max 10 URLs per request | urls |

- Per API key, across all requests. Exceed → **HTTP 429 `RATE_LIMIT_EXCEEDED`** with `details={limit, unit: requests|urls, window_seconds, upgrade_url}`.
- Headers (200 and 429): `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` (requests for search, URLs for fetch), `X-RateLimit-Reset` (unix sec), `X-Request-ID`.
- Raising limits is account-level ("a conversation, not a purchase" — talk to sales); Enterprise sets custom concurrency/rate.
- Outdated lower numbers (5/min search, 25/min fetch) on Reddit are superseded by current docs + pricing above.

### Budget limits (money / volume)
- **Search: $0. Free at any Wallet balance including $0.** "Search never draws from your wallet."
- **Fetch: $0. Same — free at $0 balance.**
- Per-1k: **$0 / 1k searches, $0 / 1k fetches**. No credits consumed. Wallet reaching $0 changes nothing for Search/Fetch ("Nothing breaks").
- What *does* cost (same account, different products): **Agent $0.016/step** (2 concurrent runs), **Browser $0.002/min** (5 sessions). New accounts start with **$8 Wallet funds**, $10 minimum top-up, auto-reload optional, no subscription.
- Failed fetch URLs don't count against quota (marketing page). Legacy credit-plan accounts see rates in dashboard instead.
- Search errors include **402 "Search API access required"** (account lacks Search access — entitlement, not spend), 403 upstream, 404 unavailable, 503 retry-with-backoff. Fetch errors: 400/401/422/429/500/503. Agent/Browser out-of-funds is **402 `INSUFFICIENT_CREDITS`** (wallet) vs legacy **403** — irrelevant to Search/Fetch budgeting.

### Keyless vs keyed
- **No keyless REST.** All Search/Fetch require `X-API-Key`. Missing → 401 `MISSING_API_KEY`, bad → 401 `INVALID_API_KEY`. One key at `agent.tinyfish.ai`, no card to start. MCP uses OAuth 2.1 browser login but still an account.
- Usage API: `GET https://api.fetch.tinyfish.ai/usage` (key required, `after/before/status/limit/page`, returns per-URL items + totals). No Search usage endpoint found. Wallet: `GET /v1/wallet` (404 = legacy account).

### Sources
- https://docs.tinyfish.ai/search-api/reference (fetched — 30/min, billing-free)
- https://docs.tinyfish.ai/fetch-api/reference (via subagent — 150 urls/min, max 10/req)
- https://docs.tinyfish.ai/error-codes (429/402/403 shapes, headers)
- https://docs.tinyfish.ai/authentication
- https://www.tinyfish.ai/pricing (fetched — 30/min·500/hour, 150/min·1000/day, $0, $8 Wallet)
- https://www.tinyfish.ai/blog/search-and-fetch-are-now-free-for-every-agent-everywhere (fetched)
- https://docs.tinyfish.ai/ (index)

### Proposed separated settings
```yaml
tinyfish:
  rate:  { search_rpm: 30, search_rph: 500, fetch_upm: 150, fetch_upd: 1000, fetch_max_urls_per_request: 10 }
  budget: null  # explicitly no budget for search/fetch; wallet only gates agent/browser
```

---

## 3. Brave Search API (`api.search.brave.com/res/v1`)

Key-required. No keyless. No generic URL fetch — closest is LLM Context.

### Rate limits (throughput)
| Plan | Limit |
|---|---|
| Search (web/news/images/video + LLM Context) | **50 queries/sec** |
| Answers (grounded chat) | **2 queries/sec** |
| Spellcheck / Autosuggest | **100 req/sec each** |
| Enterprise | custom |

- 1-sec sliding window, real-time; exceed → **429**, request fails. Up to 10 API keys per plan (keys share plan bucket).
- Headers on **every** response: `X-RateLimit-Limit` (e.g. `1, 15000`), `X-RateLimit-Policy` (e.g. `1;w=1, 15000;w=2592000` = 1/s + 15000/30d), `X-RateLimit-Remaining`, `X-RateLimit-Reset` (sec to retry / monthly reset). Backoff recipe: 1s, 2s, 4s.
- Two 429 causes — distinguish in code: **`RATE_LIMITED`** (burst QPS — wait Reset + retry) vs **`QUOTA_LIMITED`** (monthly/credit out — top-up or wait reset; retry won't help).
- Legacy free tier (retired Feb 2026, still on stale pages — do NOT encode): 2,000/mo @ 1 QPS (later 5,000/mo under Aug-2025 AI Grounding). Paid legacy ~20 QPS. Current docs supersede all of it.

### Fetch / extract
- **No generic fetch-by-URL.** No Tavily-Extract / Firecrawl-scrape equivalent.
- Closest: **LLM Context** `GET|POST /res/v1/llm/context?q=...` — pre-extracted chunks (text, tables, code, markdown, forum/YT captions) under `grounding.generic[].snippets` + `sources{}`, token-budget params (`maximum_number_of_tokens[_per_url]`, `maximum_number_of_urls/snippets`). Billed under Search plan ($5/1k). "No scraping needed."
- Separate **Answers** product: OpenAI-compatible `/res/v1/chat/completions`, cited + streaming, iterative multi-search. Billed under Answers plan.

### Budget limits (money)
- Model: **prepaid drawdown** + **$5 free credits auto-applied every month per plan** (Search *and* Answers each get $5). Card required on every plan (anti-fraud, now bills past credits).
- $/1k (official): **Search $5.00/1k** → $5 ≈ ~1,000 free/mo; **Answers $4.00/1k + $5.00/1M input + $5.00/1M output tokens**; **Spellcheck $5.00/10k**; **Autosuggest $5.00/10k**; Enterprise custom (ZDR, NDAs, invoicing).
- Overage: past credits → card billed metered, **no default spend cap** — dashboard + alerts + cache. Only successful (non-error) responses billed (422s etc. free). Credits reset monthly (2592000s window), no rollover.
- Legacy: hard-capped free 2k–5k/mo killed Feb-2026 for new signups; some old customers keep legacy terms — check dashboard. Stale "Free $0 2k/mo @1QPS, Base ~$3/1k, Pro $5–9/1k" = pre-Feb-2026.

### Keyless vs keyed
- **Key required.** Header **`X-Subscription-Token: <key>`** (NOT `Authorization: Bearer` — that 401s). Must subscribe to a plan first even for free credits; key is plan-scoped (wrong plan → 401). Base `https://api.search.brave.com/res/v1` (e.g. `/web/search?q=...&count=10`).
- 401 = missing/wrong header or no subscription; 422 = bad param; 429 = rate *or* quota (see `RATE_LIMITED` vs `QUOTA_LIMITED`).

### Sources
- https://brave.com/search/api/
- https://api-dashboard.search.brave.com/documentation/pricing
- https://api-dashboard.search.brave.com/documentation/guides/rate-limiting
- https://api-dashboard.search.brave.com/documentation/guides/authentication
- https://api-dashboard.search.brave.com/documentation/services/llm-context
- https://api-dashboard.search.brave.com/documentation/quickstart
- https://github.com/brave/brave-search-skills/blob/main/skills/llm-context/SKILL.md
- https://implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing (retirement timeline)
- https://apidog.com/blog/brave-api-key (headers table)
- https://agentscamp.com/tools/brave-search-api ; https://freeapihub.com/apis/brave-search-api

### Proposed separated settings
```yaml
brave:
  rate:  { search_qps: 50, answers_qps: 2, spellcheck_qps: 100, autosuggest_qps: 100, window: 1s }
  budget: { model: prepaid_credits, free_monthly_credits_usd: 5, search_usd_per_1k: 5, answers_usd_per_1k: 4, answers_usd_per_1M_tokens: 5, billed_only_on_success: true }
  fetch:  { generic_fetch: false, llm_context_billed_as: search }
```

---

## 4. Exa (`exa.ai`, `x-api-key`, Bearer also accepted)

Pay-as-you-go prepaid dollar credits (Stripe). Throughput is per-**team** QPS.

### Rate limits (throughput — per team, all keys share)
| Endpoint | Default QPS |
|---|---|
| `/search` (instant/fast/auto), `/answer`, `/chat/completions` | **10** |
| `/search` deep-lite / deep / deep-reasoning | **5** |
| `/contents` (fetch) | **100** |
| `/agent/runs` + `/responses` | **5 + 50 active runs** |
| `/websets/*` | **20** |

- Plan gating: Free/Starter **10 QPS + 50 agent concurrency**; Pay-as-you-go/Developer **10 QPS (up to 25 Search QPS via auto-boost) + 50 concurrency**; Enterprise custom. Auto-boost: purchase (not spend) **$1,000 in any 30d → 25 QPS for 90d** (requalify resets; track in billing dashboard). Above that → sales. (Older "Starter 5 QPS/3 runs, Developer 10/25" captures are stale.)
- You may set a *lower* per-key limit on the API Keys page; it still counts toward the team limit.
- Exceed → **429** (`RATE_LIMIT_EXCEEDED`; concurrency variant `CONCURRENCY_LIMIT_REACHED`; x402 variants `X402_TOO_MANY_UNPAID` / `X402_WALLET_RATE_LIMITED`). Honor `Retry-After` else exponential backoff. Each `POST /agent/runs` counts as **2** against QPS (10 QPS = 5 run-starts/sec); `GET` status/events/list polling does NOT count. `503 SERVICE_OVERLOADED` is explicitly **not billed** — retry, don't back off as if rate-limited.

### Fetch / contents rate limit
- `/contents` = **100 QPS** default (10× search), same team model. URL-level crawl failures do NOT 429 — they return **200 with per-URL `statuses[]`** (`CRAWL_NOT_FOUND`, `CRAWL_HTTP_{n}`, `CRAWL_TIMEOUT`, `CRAWL_LIVECRAWL_TIMEOUT`, `SOURCE_NOT_AVAILABLE`, `UNSUPPORTED_URL`, `CRAWL_UNKNOWN_ERROR`). Options: `livecrawl` (never|fallback|preferred|always), `livecrawlTimeout`, `maxAgeHours`, `subpages` (max 100/req), `extras`. No separate livecrawl QPS. No separate `/findSimilar` QPS in current docs (legacy; "shares /search pool" is unverified).

### Budget limits (money)
- Model: prepaid dollar credits, no subscription/minimum, auto-recharge ($5–$10,000 amount + threshold + optional monthly max), receipts from `billing@exa.ai`. Postpaid invoice + volume + custom index + ZDR + SLA/MSA = Enterprise-only. Every response carries `costDollars.total`.
- Per-1k (official endpoint table): **Instant $4** / **Fast+Auto $7** / **Deep $12** (lite+deep) / **Deep-Reasoning $15** / **Answer $5** / **Monitors $15** / **Contents $1 per 1k pages PER CONTENT TYPE**. Base covers **up to 10 results**; each result above 10 = **+$1/1k** (search/deep/monitors only; Answer and Contents `-` = not billed). AI page summaries = **+$1/1k pages** (everywhere except Answer). Contents `text` vs `highlights` vs `summary` billed separately (1 URL × text+highlights = 2 pages). Since Mar-2026: contents (text+highlights) for **first 10 search results bundled into the $7 search base**; standalone `/contents` still metered.
- Agent: fixed minimal **$0.012** / low **$0.025** / medium **$0.10** / high **$0.50** / x-high **$1.00** per run (enrichment extra); metered auto (default $5/run cap) and beta max ($20 cap): ACU **$0.10** + search tool **$0.005** + email **$0.02** + phone **$0.07**; Exa Connect provider calls extra (e.g. Fiber.ai $0.02/credit, Baselayer $0.15–$4.00/order). No separate livecrawl line item (cache policy; stale 2025 "$0.005 livecrawl" is stale; `/findSimilar $7` is third-party-only, unverified).
- Free: **$10 grant day-1, resets TO $10 on the 1st monthly** (never accumulates, max $10, first team only) + **one-time $10 onboarding bonus** on dashboard onboarding (no expiry). Marketed as "$20 on signup + $10/mo" = $10 grant + $10 bonus — don't double-count. ≈ **~1,400 standard searches per $10**. No card. Free spends at standard rates, never refunded.
- 402 vs 429: **402** = `NO_MORE_CREDITS` (team out) or `API_KEY_BUDGET_EXCEEDED` / `TEAM_BUDGET_EXCEEDED` (per-key/team spend budget hit; settable via dashboard / Team Management `POST /api-keys` rateLimit+budget) → top up at `dashboard.exa.ai` or ask admin. **429** = throughput/concurrency → backoff.
- Usage API: **Get API Key Usage** (service/team key, same-team only) → `total_cost_usd + cost_breakdown[]` (`price_id/price_name/quantity/amount_usd`); ISO8601 range, 180-day lookback max; `group_by hour|day|month` reserved. Also billing dashboard, Get Team Info (Websets concurrency), `costDollars` per response.

### Keyless vs keyed
- **Key required** (`x-api-key`; Bearer accepted per SDK docs). Missing/invalid → **401 `INVALID_API_KEY`**. Free credits need signup, no card.
- Only keyless-adjacent rail is **x402/MPP** pay-per-request crypto-wallet flow (no key; `X402_PAYMENT_REQUIRED` → 402 → pay → 200; 429 variants above) plus a mentioned unauthenticated MCP tier — non-primary, verify before relying on it.

### Sources
- https://exa.ai/docs/reference/rate-limits.md (fetched)
- https://exa.ai/docs/admin/pricing (fetched)
- https://exa.ai/pricing/api (fetched)
- https://exa.ai/docs/admin/error-codes (fetched)
- https://exa.ai/docs/reference/error-codes
- https://exa.ai/docs/reference/team-management/get-api-key-usage (fetched)
- https://exa.ai/docs/changelog (Mar-2026 bundling)

### Proposed separated settings
```yaml
exa:
  rate:  { search_qps: 10, deep_search_qps: 5, contents_qps: 100, agent_qps: 5, agent_concurrency: 50, scope: team, auto_boost_qps: 25 }
  budget: { model: prepaid_usd_credits, free_grant_usd: 10, free_reset: monthly_first, onboarding_bonus_usd: 10, search_usd_per_1k: 7, instant_usd_per_1k: 4, contents_usd_per_1k_pages_per_type: 1, on_exhausted: http_402, usage_api: get_api_key_usage }
```

---

## 5. Firecrawl (`firecrawl.dev`, credit-based, per-team RPM)

Docs state it explicitly: **rate limits are separate from pricing**.

### Rate limits (requests/min per team + concurrency — NOT budget)
All keys on a team share counters. Exceeding RPM *or* concurrency/queue → **429**.

| Plan | `/scrape` | `/map` | `/crawl` | `/search` | `/agent` | `/crawl\|/agent/status` |
|---|---|---|---|---|---|---|
| Free | 10 | 10 | 2 | 10 | 2 | 500 |
| Hobby | 100 | 100 | 20 | 100 | 20 | 5,000 |
| Standard | 500 | 500 | 100 | 500 | 100 | 25,000 |
| Growth | 5,000 | 5,000 | 1,000 | 5,000 | 1,000 | 250,000 |
| Scale | 10,000 | 10,000 | 2,000 | 10,000 | 2,000 | 500,000 |

- **Search rate = scrape/map rate** (no search-vs-scrape distinction). **Scrape/fetch rate = same row.** **Crawl is 5× tighter** everywhere. Status polling is high/free-ish and does NOT consume credits.
- **Extract → `/agent` limits** (2/20/100/1000/2000); **Batch scrape → `/crawl` limits** (same). Pricing page confirms; one billing-page bullet saying "batch shares scrape" contradicts rate-limits+pricing — treat rate-limits page as canonical.
- Browser Sandbox (Interact) separate RPM: Free `/interact` 2, `/interact/{id}/execute` 10; Hobby 20/100; Standard 100/500; Growth 1000/5000; Scale 1500/7500.
- Concurrency (separate ceiling): **2 / 5 / 25 / 50 / 100+** browsers; Max Queued Jobs **50k / 50k / 50k / 100k / 200k+** (custom = 2000× concurrency, cap 2M). Past ceiling **queues, not fails** (until browser frees; queue wait counts against request `timeout`; check Queue Status; queued jobs die after 48h). Past Max Queued → 429. Higher → `help@firecrawl.com`.

### Budget limits (credits — NOT RPM; same costs on every plan, shared across endpoints)
- Scrape **1/page**; Crawl **1/page** (+ per-page add-ons); Map **1/call**; **Search 2/10 results rounded up** (11 results = 4) + per-page scrape costs for each result scraped (Enterprise ZDR search separate); Interact **2/min code-only, 7/min with `prompt`**, 1-min minimum; Agent dynamic (5 daily runs free; FIRE-1 billed even if failed); Monitor **1/page/check** (deterministic-extraction engine **7/page/check**); Research Index paper endpoints **free**.
- Add-ons stack: PDF **+1/PDF page**; JSON / question / highlights / audio / video / PII redaction **+4/page each** (structured extraction = 5/page total); prompt-injection check **+4** (5 billed if fails after check ran); ZDR **+1**; lockdown cache-hit +4 / miss 1; enhanced proxy/auto escalation +0. Example JSON+ZDR = 6/page; JSON+PII = 9/page. X/Twitter via Grok: base 1 + Grok X Query +29 = **30/req** (34 with JSON).
- When charged: returned document = charged (base + options) **even on 403/404** (check `metadata.statusCode` to avoid retry-burn); no document = **0**, except threat scan 2/scanned URL, injection check 5, FIRE-1 usage, lockdown miss 1, Monitor error page base 1, Interact 1-min minimum. Failed scrape with no result = not charged. Batch/crawl billed async per page (minutes–hours delay). Crawl pre-flight: pass explicit `limit` (e.g. 100) — checked against allowance incl. overage, else 402; omitting `limit` does only a 1-credit check (default 10k NOT reserved).
- Free: **1,000 credits/mo, refreshed monthly, no card**, all core endpoints at same costs, 2 browsers, 50k queue, RPM 10 scrape/map/search + 2 crawl/agent/interact. No pay-as-you-go, no rollover, community support.
- Paid (effective Sep-4-2026): Hobby **5,000** (= 2,500 searches / 5,000 pages) **$19/mo or $16 yearly**; Standard **100,000 $99/$83**; Growth **500,000 $399/$333**; Scale **1,000,000 $749/$599**; Enterprise custom. Yearly billed annually, credits still reset monthly. Unused do NOT roll over (except annual Scale 1 mo, Enterprise 2 mo).
- Overage (paid only, not Free): auto top-up in **$5 increments** when balance hits zero (card on file, repeats to monthly pay-go limit; blank = no cap; 0 = off) + manual "Load more credits" (multiple of $5, spent first, persist till used, expire on cancel). Per-$5 credits: Hobby **1,000**; Standard **2,000**; Growth **2,500**; Scale **5,000**. Burst headroom while top-up settles (not kept credits): Hobby **1,500**; Standard **30,000**; Growth **150,000**; Scale **600,000**. Then **402 until next cycle**. Zero-balance: Free → 402 till reset; paid off/0 → 402, no charge; paid on → charge 1×$5, continue.
- **402 = out of credits** / crawl limit>balance / per-key spend limit / pay-go cap+allowance out. **429 = RPM/concurrency/queue/keyless-daily.** Per-API-key spend caps (credits per day/week/month, incl. Default) can 402 even with team balance.
- Tracking: dashboard `firecrawl.dev/app` (+billing), **Credit Usage + Credit Usage Historical API**, Queue Status for headroom. Coupons: subscription (% off at Stripe checkout) vs credit (bonus credits, dashboard redeem, survive upgrades).

### Keyless vs keyed
- Keyed: everything except below needs a key; RPM/concurrency per-team above.
- Keyless (no key), capped **per IP per day by TWO limits** (either → 429; exact numbers unpublished): max requests/day + max credits/day. Hosted MCP keyless exposes exactly **Search, Scrape, Parse** (other MCP tools need account/key). Official clients (CLI/SDKs/REST) keyless also include **Interact**; on Cloud, research + developer search also keyless. Heavier ops hit the credit cap sooner. Signup free key = 1,000 credits + higher limits; clients auto-use key once configured.

### Sources
- https://docs.firecrawl.dev/rate-limits (fetched)
- https://docs.firecrawl.dev/billing (fetched)
- https://firecrawl.dev/pricing (fetched)

### Proposed separated settings
```yaml
firecrawl:
  rate:  { scrape_rpm: [10,100,500,5000,10000], search_rpm: same_as_scrape, crawl_rpm: [2,20,100,1000,2000], extract_rpm: same_as_agent, concurrency: [2,5,25,50,100], queue: [50k,50k,50k,100k,200k], keyless: per_ip_daily_req_and_credit_caps }
  budget: { model: credits, free_monthly: 1000, scrape_per_page: 1, search_per_10: 2, json_addon: 4, topup_usd_step: 5, on_exhausted: http_402, usage_api: credit_usage_and_historical }
```

---

## 6. Tavily (`tavily.com`, `Authorization: Bearer tvly-...`)

Credit-based. Official docs separate RPM (rate-limits page) from credits (API-credits page).

### Rate limits (requests/min per key env — NOT budget)
| Bucket | Development key | Production key |
|---|---|---|
| Default (**Search, Extract, Map**) | **100 RPM** | **1,000 RPM** |
| Crawl | **100 RPM** | **100 RPM** (does NOT lift) |
| Research task *creation* | **20 RPM** | **20 RPM** (polling follows default) |
| Usage endpoint | **10 req / 10 min** | **10 req / 10 min** |

- Search vs extract share the default bucket (NOT separate). Only Crawl, Research, Usage get separate buckets.
- Exceed → **429 + `retry-after` (sec)**. Use status+header for retry, not message text (keyless uses different error format). Production key requires active Paid Plan OR PAYGO enabled. Stale "1/min free, 10/min pro / 60/min free" third-party numbers contradict current docs — ignore.

### Budget limits (monthly credits — NOT RPM)
- Model: credits; PAYGO **$0.008/credit** = overage once plan allotment reached. Monthly **$0.0075–$0.005/credit**. Enterprise custom.
- Allowances: Researcher (Free) **1,000/mo $0 no card**; Project **4,000/$30 ($0.0075)**; Bootstrap **15,000/$100 ($0.0067)**; Startup **38,000/$220 ($0.0058)**; Growth **100,000/$500 ($0.005)**; PAYGO per-usage $0.008; Enterprise custom. Pricing page cards: Researcher / PAYGO / Project-slider (4,000 base → Bootstrap → Startup → Growth) / Enterprise. Credits reset on the **1st of each month** regardless of billing date.
- Burn: Search basic **1/req**, advanced **2/req**; Extract basic **1 per 5 *successful* URLs**, advanced **2 per 5** (failures free); Map regular **1 per 10 successful pages**, with `instructions` **2 per 10**; Crawl = **Mapping + Extraction** (e.g. 10 pages basic = 1 map + 2 extract = 3; advanced = 1 + 4 = 5); Research dynamic mini **4–110/req**, pro **15–250/req**.
- Exhaust: paid + PAYGO → per-credit overage; free/out → **"requests stop until reset or upgrade"** (no surprise bill). Secondary mapping `CreditsExhausted` → **402** vs rate → **429** is non-official (official firmly ties 429 to rate, 402 to the x402 rail below — treat quota-402 as secondary).
- Usage: dashboard API real-time usage/remaining; programmatic Usage endpoint capped at 10/10min — poll at most ~1/min.

### Keyless vs keyed (+ x402, three distinct rails)
- **Keyless:** header `X-Tavily-Access-Mode: keyless`, no account/key. **Search + Extract ONLY** (full params, same success schema). Free but rate-limited — docs publish NO numeric keyless RPM ("rate-limited" + natural-language limit errors). Upgrade = signup free key (1,000/mo, no card), swap to `Authorization: Bearer tvly-...`, no code change. **Keyed required for Crawl, Map, Research.** Both headers sent → API key wins.
- **Keyed:** `Authorization: Bearer tvly-...`; include key to get correct dev/prod RPM. MCP `https://mcp.tavily.com/mcp/` works keyless via same header (only `tavily-search` + `tavily-extract`); URL-only clients must use key.
- **x402 (separate paid no-key rail, NOT keyless):** `POST https://x402.tavily.com/search`, Advanced Search only, **$0.01 USDC on Base**, flow call → 402 → pay → 200.

### Sources
- https://docs.tavily.com/documentation/rate-limits (fetched via subagent)
- https://docs.tavily.com/documentation/API-credits (fetched)
- https://docs.tavily.com/documentation/keyless
- https://docs.tavily.com/agents
- https://docs.tavily.com/guides/api-credits
- https://tavily.com/pricing
- https://tavily.com/blog/tavily-on-x402
- https://help.tavily.com/articles/3240802908-rate-limits (cross-check)

### Proposed separated settings
```yaml
tavily:
  rate:  { default_rpm_dev: 100, default_rpm_prod: 1000, crawl_rpm: 100, research_create_rpm: 20, usage_rpm: 1, keyless_rpm: unpublished }
  budget: { model: credits, free_monthly: 1000, search_basic: 1, search_advanced: 2, extract_per_5: 1or2, paygo_usd_per_credit: 0.008, on_exhausted_free: stop_until_reset, on_exhausted_paid: paygo_overage }
  keyless: { enabled: true, endpoints: [search, extract], header: X-Tavily-Access-Mode }
```

---

## 7. Parallel (`parallel.ai`, `api.parallel.ai`, Bearer or `x-api-key`)

Docs header: **"Rate limits are separate from pricing."** Pay-per-request USD, no plan/credit-pack unit. `POST` creates count; `GET` polls don't.

### Rate limits (per min — POST-only)
| Endpoint | Default |
|---|---|
| Search (`POST /v1/search`, all modes turbo/fast/basic/advanced share one bucket) | **600/min** |
| Extract (`POST /v1/extract`) | **600/min** (separate bucket — 600+600 achievable) |
| Tasks / TaskGroups (`POST /v1/tasks/runs`, `/v1/tasks/groups/{id}/runs`; each item in `inputs` counts) | **2,000/min** |
| Chat (`POST /v1beta/chat/completions`) | **300/min** |
| Monitor (`POST /v1alpha/monitors`) | **300/min** |
| Entity Search | **600/min** |
| FindAll (`POST /v1beta/findall/runs`) | **300/hour** |

- `GET` retrieving results / checking status does NOT count (e.g. `GET /v1/tasks/runs/{id}` polling is free vs quota). No per-second or per-mode throttle published. Higher → `support@parallel.ai`; custom on enterprise. Use `/v1/search` + `/v1/extract` for new integrations (`/v1beta/*` existing only).

### Budget limits (money — per-request USD, preload balance, free credit first)
- Model: **per-request flat rate per mode, no plan, no credits-as-unit**. Preload $ balance; free $ credit applied first, then card at standard rates.
- Search: **$1/1k Turbo or Fast** (default 10 results incl.) / **$5/1k Basic or Advanced** + **$1/1k per extra result page past 10**. Extract: **$1/1k URLs**. (Context: Task $5–$2,400/1k successful runs by processor lite→ultra8x; Responses $10/$50/$250 per 1k by low/med/high effort, only successful billed; Monitor $3 lite / $10 base per 1k checks; FindAll preview $0.10+$0.00 → base $0.25+$0.03/match → core $2.00+$0.15 → pro $10.00+$1.00 + enrichment; Entity $5/1k incl 100 + $0.05/1k extra; Chat $5–$25/1k. Only-successful billed for Task/Responses; "failed runs aren't billed".)
- Free: marketing headline **"up to 5,000 requests/mo free"** (`parallel.ai/pricing`). Operational: **$5 free credits every month, auto-applied, eligible orgs with card on file** (unused expires month-end, 1/org, 1 card activates 1 org, marketplace/postpaid excluded; past $5 → card billed, no cap documented). $5 = **5,000 Turbo/Fast searches** OR **5,000 Extracts** OR 1,000 Basic/Advanced searches OR 1,000 Task runs OR 1,666 Monitor checks, or combo. One-time **signup balance** (official existence confirmed; secondaries quantify up to **$80**) + **$250 startup grant** (qualified startups). No rollover. WARNING: `parallellabs.app` "Parallel AI" ($99/mo 2,000 etc.) is a DIFFERENT company — do not mix.
- Overage: past $5 → card at standard rates, no hard cap documented (guide warns card-attached credit "converts to metered billing instantly" + retry-loop risk). No authoritative 402/429 schema or balance-check endpoint found in fetched docs (only HN anecdote "insufficient balance" playground bug, since moved to 5k/mo) — **gap: test live or ask support**. Balance managed at `platform.parallel.ai` (keys/usage/billing).

### Keyless vs keyed, OAuth vs API key
- **Search MCP keyless:** `https://search.parallel.ai/mcp` (Streamable HTTP, `web_search` + `web_fetch`), free anonymous, no account/key/card. "Lower rate limits / sized for hobby/personal agents" (exact QPS unpublished). Anonymous runs Search in **fast mode**, ignores connection overrides, output capped ~25k chars/call (secondaries).
- **Keyed raise-limits:** account at `https://platform.parallel.ai`, pass key as `Authorization: Bearer <PARALLEL_API_KEY>`. Higher limits + analytics + mode/search-config overrides.
- **OAuth endpoint:** `https://search.parallel.ai/mcp-oauth` — enforced auth (anonymous → 401). Bearer key OR OAuth flow. Org-wide / ZDR / per-account attribution. Discovery intentionally NOT advertised on `/mcp`.
- **Task MCP:** `https://task-mcp.parallel.ai/mcp` — ALWAYS requires auth (Bearer or OAuth); anonymous rejected pre-handshake.
- REST/SDK: Bearer or `x-api-key` (OAuth recipe shows `x-api-key: access_token` to `/v1/tasks/runs`); SDKs `PARALLEL_API_KEY` env (Python `parallel-web`, TS, CLI `parallel-cli login` browser OAuth or `--device` headless). Multi-user: OAuth Provider at `platform.parallel.ai/getKeys/{authorize,token,register}`, PKCE S256, scope `key:read`, no client secret, `access_token` IS the user's API key, MCP-compatible via `/.well-known/oauth-authorization-server`.
- ZDR/Enterprise: Zero Data Retention, DPA, SSO on enterprise.

### Sources
- https://docs.parallel.ai/getting-started/rate-limits (fetched — table + "separate from pricing" + POST-only rule)
- https://docs.parallel.ai/getting-started/pricing (fetched)
- https://parallel.ai/pricing (headline 5k/mo)
- https://parallel.ai/ai/blog/free-tier-parallel (fetched — $5/mo mechanics, Jul-15-2026)
- https://parallel.ai/articles/best-free-web-search-api (fetched — $5 math, keyless MCP)
- https://parallel.ai/articles/tavily-to-parallel-search-api ($1 vs $5 table, 600/300/300-per-hour defaults)
- https://parallel.ai/articles/serper-to-parallel-search-api ; https://parallel.ai/articles/scrapingbee-vs-parallel
- https://parallel.ai/blog/free-web-search-mcp ; https://docs.parallel.ai/integrations/mcp/quickstart ; https://docs.parallel.ai/integrations/oauth-provider
- https://tinyfish.ai/blog/parallel-pricing ($80 signup context)
- https://parallel.ai/ai/articles/exa-to-parallel-search-api

### Proposed separated settings
```yaml
parallel:
  rate:  { search_rpm: 600, extract_rpm: 600, tasks_rpm: 2000, chat_rpm: 300, monitor_rpm: 300, findall_rph: 300, counts: post_only }
  budget: { model: usd_per_request, free_monthly_usd: 5, turbo_usd_per_1k: 1, basic_advanced_usd_per_1k: 5, extract_usd_per_1k: 1, signup_credit_usd: "~80 (secondary)", on_exhausted: bill_card }
  keyless: { search_mcp: anonymous_fast_mode_lower_limits, task_mcp: auth_required }
```

---

## 8. You.com (`you.com`, `api.you.com`, `X-API-Key` / YDC key)

Pure usage, no seats/platform fee. Five separately metered endpoints. Two free on-ramps: one-time $100 credit + renewing 100-calls/day Search quota.

### Rate limits (per-second throughput — NEW Sep-2026 page, no charge attached)
| Endpoint | Default self-serve |
|---|---|
| `/v1/search` (Web Search) | **10 req/sec** |
| `/v1/contents` (Contents) | **10 req/sec** |
| `/v1/answer` (Answer) | **10 req/sec** |
| `/v1/research` (incl. `background`) | **10 req/sec** (async background counts same) |
| `/v1/finance-research` | **5 req/sec** |

- "Each endpoint has its own per-second limit." Enterprise by contract ("those limits apply instead of defaults"). Raising self-serve = sales-gated ("Higher limits come with a custom plan" / `sales@you.com`).
- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`; exceed → **429 + `Retry-After`**, exponential-backoff recipe. (Page appeared between Aug-14 and Sep-11-2026 captures — first published caps.)

### Fetch / contents rate + budget
- Contents **rate: 10 req/sec** (above). Contents **budget: $1.00/1k pages** (batch URLs, Markdown/HTML; also via Search `livecrawl`/`extraction` patterns).
- Search **full-page extraction add-on: $1.00/1k pages *fetched live*** on top of base $5 search rate. `extraction_mode: "highlights"` (query-relevant passages only, `snippets` omitted) = **included, $0**. Since Sep-02-2026 `extraction_source` decides the billable multiplier (rate untouched): `blend` (default, cache-then-crawl — only cache *misses* billed) / `cache` (cached only — "adds no extraction charge at all") / `fetch` (always live). Docs 20-page example: **$0.023 default blend** (2 cached) vs **$0.025 all-live** vs **$0.005 cache-only** — 5× spread, same request, one string. `blend` default so existing bills fell with no code change. Field ignored for `highlights`, `POST /v1/search` only. Cache coverage "varies by query", not reported per call — budget assuming zero hits. Old `livecrawl` param renamed to `extraction` object (Aug-14 refresh).

### Budget limits (money — per-call / per-page, $100 credit + daily quota)
- **Search: $5.00/1k calls** (1–100 results/call, flat regardless of 1 or 100 since Mar-2026; news endpoint included; LLM-ready snippets; country/language/freshness filters). **Free for first 100 calls/day**, then $5/1k (pricing card since Jul-29-2026; docs pricing section still says flat $5/1k — docs drift, trust pricing page + changelog).
- **Contents: $1.00/1k pages.** **Answer (NEW Aug-2026): $5.00/1k calls** (one-call search + cited answer, Search parity). **Research: $12 (lite) / $50 / $100 / $450 / $1,200 (Frontier, requires `background: true`) per 1k** by `research_effort`; **Finance Research: $110 (deep) / $500 (exhaustive) per 1k** (dedicated finance index). History: Oct-2025 launch Web $6.25/$8.00, News $6.25, Contents $10, Express $11/1k, Advanced $15/call → early-2026 cuts to $5/$1 → Jul-2026 Frontier $2,000+ → $1,200 + 100/day quota → Aug Answer $5/1k → Sep cached-extraction-free.
- Free on-ramps: **$100 signup credit** (one-time, shared across products, no card per quickstart) + **100 Search calls/day renewing** (cheapest/highest-frequency endpoint). No minimums; volume + annual discounts; Enterprise custom QPS.
- Worked total (secondary): 50k searches ($250) + 200k live pages ($200) + 10k standard Research ($500) = **$950**.
- Analytics: `you.com/platform/analytics` (usage/spend); Team Management roles Owner/Admin/Developer/Billing (read-only finance, no seat fee).
- Machine payments (agents, no account): pay-per-call in **USDC from funded wallet** — covers `GET /v1/search` + both verbs of `/v1/agents/search` (Aug-14 capture).

### Keyless vs keyed
- **Keyed (normal):** account at `you.com/platform`, header `X-API-Key` (canonical env `YDC_API_KEY`, format `ydc-sk-...`). Billed to credit balance. **Host split matters:** Search (`POST/GET /v1/search`) + Contents (`POST /v1/contents`) live on **`ydc-index.io`**; Answer / Research / Finance live **only on `api.you.com`** — sending Answer/Research/Finance to `ydc-index.io` 403s even with a valid key.
- **Keyless A (free trial):** MCP `https://api.you.com/mcp?profile=free`, `you-search`, no signup/key, 100 queries/day, search-only (contents/research/finance need key + $100 path).
- **Keyless B (paid per-call, no account — x402/MPP/Nevermined machine payments):** call with NO `X-API-Key` → 402 Challenge (`PAYMENT-REQUIRED` + `WWW-Authenticate: Payment`, 10-min expiry) → sign with USDC wallet (`PAYMENT-SIGNATURE` → `PAYMENT-RESPONSE`, MPP `Authorization: Payment` → `Payment-Receipt`) → 200. Covers Web Search + Finance Research (x402) / Web Search GET + Finance Research POST (MPP). Never send key + payment header together (→ 401). Example amount `5000` = $0.005 = one search. Nevermined variant can purchase/top-up a $5 API key via `POST https://api.you.com/payments/v1/nevermined/purchase-key`.
- Errors: **401** = missing (`API key is required`) / invalid / expired key or auth-parse error; **403** = `Missing required scopes` (e.g. `/v1/contents`) or `Missing Authentication Token` = wrong host (see above); **402 `payment_required`** = (a) keyed `{"detail":"Insufficient credits"}` → add funds, or (b) keyless payment challenge → settle via wallet and retry; **429** = rate (backoff; MPP extra rule: >10 unpaid Challenge requests/min → 429, honor `Retry-After`, reuse held Challenge).
- **Budget API:** `GET https://api.you.com/v1/billing/account_balance` with `X-API-Key` + `Accept: application/json` → `data.attributes.balance` in **cents** (/100 = USD, e.g. 744300.0 = $7,443.00); org members share org/tenant pool, individuals personal.
- **Spend guards:** Auto Top-Up is org/tenant-level only (Admin/Owner, default card, whole-dollar `threshold` + `top_up_amount >= threshold`, real-time trigger, email on enable/disable/success/failure: `card_expired/insufficient_funds/card_declined/authentication_required`). **No monthly caps in current release.** Volume + annual discounts; enterprise custom QPS, ZDR, SOC 2, DPA (`api@you.com`).
- Rule: **429 = slow down** (`Retry-After` + backoff capped 60s, ~5 tries); **402 = out of money or pay-with-wallet** (top up or poll balance). Never retry 402 without a payment action.

### Sources
- https://you.com/docs/rate-limits (authoritative per-second table)
- https://you.com/docs/administration/billing (pay-as-you-go, $100, add-on rule)
- https://you.com/docs/quickstart + https://docs.you.com/get-started/quickstart ($100 no-card, host table, extraction example)
- https://you.com/docs/using-the-api/error-code-reference (402/429/401/403 split)
- https://you.com/docs/api-reference/billing/get-account-balance (cents balance API)
- https://you.com/docs/administration/machine-payments/x402 + .../mpp + .../nevermined (keyless-B rails)
- https://you.com/pricing (Free 100/day + $5/1k + $100 credit cards)
- https://docs.you.com/get-started/quickstart ($100 no-card, $5/1k + $1/1k livecrawl example)
- https://www.usagepricing.com/blueprint/you-com (100/day history, 10/5 rps table, $12–$1,200 Research ladder, changelog Jul-29/Sep-02/Sep-11)
- https://usagepricing.com/blueprint/activity/you-com-2026-09-11-cached-extraction-free (`extraction_source` rule + 20-page math)
- https://apio.sh/apis/you-search ($100 + 100/day unauthenticated MCP note)
- https://aipedia.wiki/tools/you-com (May-2026 $5/$1/$12 pivot)
- https://versustool.com/tool/you-com ; https://nolist.ai/item/you-com-api (flat $5 regardless of count)

### Proposed separated settings
```yaml
you:
  rate:  { search_rps: 10, contents_rps: 10, answer_rps: 10, research_rps: 10, finance_research_rps: 5 }
  budget: { model: usd_per_call, signup_credit_usd: 100, search_free_per_day: 100, search_usd_per_1k: 5, contents_usd_per_1k: 1, answer_usd_per_1k: 5, research_usd_per_1k: [12,50,100,450,1200], extraction_live_usd_per_1k: 1, extraction_cached_usd: 0 }
```

---

## 9. Cross-provider summary (design input — not code)

| Provider | Search rate | Fetch rate | Budget model | Free budget | Search $/1k | Fetch $/1k | Keyless? | Overage signal |
|---|---|---|---|---|---|---|---|---|
| Keenable | 10 rps (org) | same bucket | requests/mo | 100k/mo keyed; keyless $0/unmetered | $4 list (Agent Builder) | 1 credit ≈ 1 req | **yes** (1k/hr·10 rps per IP) | 402 |
| Tinyfish | 30/min + 500/hr | 150 urls/min + 1k/day | **none ($0)** | unlimited within rate | $0 | $0 | **no** (key required) | 429 only (+402 entitlement) |
| Brave | 50 rps | n/a (LLM Context as search) | prepaid $ credits | $5/mo (~1k) | $5 | n/a | no | `QUOTA_LIMITED` vs `RATE_LIMITED` |
| Exa | 10 rps (5 deep) | 100 rps (`/contents`) | prepaid $ credits | $10 + $10 bonus | $7 ($4 instant) | $1/1k pages/type | no (x402 rail only) | 402 vs 429 |
| Firecrawl | 10–10k/min by plan | same as search; crawl 5× tighter | credits | 1k/mo | 2/10 results | 1/page (+4 JSON) | partial (Search/Scrape/Parse per-IP daily) | 402 vs 429 |
| Tavily | 100 dev / 1k prod RPM | same bucket (extract) | credits | 1k/mo | 1–2 credits/req ($0.008/cr) | 1–2/5 URLs | **yes** (search+extract, `X-Tavily-Access-Mode`) | stop-till-reset (free) / PAYGO (paid) |
| Parallel | 600/min | 600/min separate | USD per request | $5/mo (~5k Turbo) + signup ~$80 | $1 Turbo / $5 Basic+Adv | $1/1k URLs | **yes** (Search MCP fast-mode) | bill card (no cap doc'd) |
| You.com | 10 rps | 10 rps (`/contents`) | USD per call/page | $100 once + 100/day search | $5 | $1/1k live pages | daily-quota MCP profile only | 429 + analytics |

Key design consequences:
1. **Rate and budget need separate knobs.** Free/keyless-only dimensions: Keenable keyless (rate-only, `budget: null`), Tinyfish search/fetch (`budget: null`, rate-only), Tavily keyless (rate-only, unpublished cap), Parallel Search MCP keyless (rate-only fast-mode), You.com 100/day (rate/daily-quota, no spend).
2. **Search vs fetch need separate knobs.** Separate: Tinyfish (30/min req vs 150/min urls + different daily/hourly windows), Exa (10 vs 100 QPS), Parallel (600 vs 600 separate buckets), Firecrawl (search=scrape but crawl/batch/extract differ + concurrency), Brave (no fetch — don't offer a fetch budget), You.com (same 10 rps but different $ units: $/call vs $/live-page).
3. **Keyed upgrades change rate AND budget together** (Keenable removes hourly cap + adds 100k/mo; Tavily dev→prod 100→1,000 RPM + PAYGO; Parallel keyless fast-only → keyed mode choice + $5/mo; Exa $10 grant + 10→25 QPS boost). Settings must allow `keyless: {rate, budget}` vs `keyed: {rate, budget}` pairs per provider.
4. **402 ≠ 429 everywhere.** 402 = money out (Keenable, Exa, Firecrawl, Tinyfish-agent, Tavily-x402); 429 = speed out (all) — except Brave which splits 429 into `RATE_LIMITED` vs `QUOTA_LIMITED`, and Tinyfish Search 402 = entitlement (no access) rather than spend. Router/backoff must branch on the pair, not the code alone.
5. **Don't count calls — read cost from responses** where SKUs vary (Keenable `_meta[keenable/usage]`, Exa `costDollars.total`, Firecrawl per-page add-ons, You.com `blend/cache/fetch` multiplier, Tavily success-only extract/map, Parallel success-only Task/Responses).

## 10. Suggested settings shape (proposal, no code changed)

```yaml
# per provider, per operation, per auth mode — rate and budget are siblings, either may be null
providers:
  <name>:
    auth: { keyless: bool, keyed: bool }
    search:
      rate:   { limit: int, window: "1s|1m|1h|1d", scope: "org|team|key|ip", headers: [...] }
      budget: { model: "none|requests|credits|usd", free_allowance: "100k/mo|1k/mo|$5/mo|$100 once|100/day", cost_per_1k: "...", on_exhausted: "402|stop|bill", usage_api: "..." } | null
    fetch:
      rate:   { ... } | null  # null = no generic fetch (Brave)
      budget: { ... } | null  # null = free/unmetered (Tinyfish search+fetch, Keenable keyless)
```

Examples from this research: `tinyfish.search.budget = null`, `tinyfish.fetch.budget = null`; `keenable.keyless.budget = null`, `keenable.keyed.budget = {100k/mo}`; `brave.fetch = null`; `exa.search.rate != exa.fetch.rate`; `parallel.search.rate` and `parallel.fetch.rate` same number, different buckets.

---

## 11. Common display + allocation unit (added 2026-10-05, research-only)

### 11.1 Decision: Search Credits (SC) — 1 SC = 1 normalized call

- **1 SC-search = 1 search call** (standard depth, ≤10 results, no add-ons).
- **1 SC-fetch = 1 fetched URL** (1 page in markdown, no add-ons). A fetch *call* with `url_count=N` subtracts **N** SC-fetch. (Rationale: every vendor meters fetch per page/URL — Tinyfish per URL, Exa per page/type, Firecrawl per page, Parallel/You.com per URL/page — while search is metered per call. Counting fetch per URL keeps "subtract 1 per usage" true at the unit the vendors bill.)
- Every successful search subtracts 1 SC-search from that provider's search pool; every successfully fetched URL subtracts 1 SC-fetch from its fetch pool. Failures subtract 0 (matches vendors: only successful responses billed, except Firecrawl 403/404-returns which do bill — see divergence note).
- Display: the **SC number is the constant unit** shown everywhere (budgets, remaining, allocation). The **USD/native amount lives in a details/drill-down section only** (balance, per-call USD, plan, reset date, usage API link).
- Routing: when priorities tie, pick the eligible provider with the **most remaining SC in the relevant pool** (search pool for search, fetch pool for fetch); tie-break by **lowest USD per SC**, then by rate headroom. Rate limits still gate independently (429 path); SC gates volume/spend (402 path).

### 11.2 Why two pools (search vs fetch), not one

Per-call native costs differ by operation on 5 of 8 providers (Tinyfish 30/min vs 150 urls/min; Exa 10 vs 100 QPS and $0.007 vs $0.001; Parallel separate 600/min buckets; Firecrawl crawl/extract buckets; You.com $/call vs $/live-page; Brave has no fetch at all). A single pool would let cheap fetches drain search budget or vice versa. So each provider exposes **SC-search and SC-fetch independently** — except where the vendor shares one pool (Keenable's 100k requests cover both; Firecrawl/Tavily credits are shared — the formulas below note the shared-pool depletion rule).

### 11.3 Conversion formulas (native → SC)

`SC balance = native_remaining / native_cost_per_normalized_call`. Standard-mode, ≤10 results, 1 page/URL, no add-ons. Add-ons/surcharges consume extra native (USD detail) but still cost 1 SC — i.e. **SC gates volume, USD tracks spend** (divergence accepted and displayed; see 11.4).

| Provider | SC-search = | SC-fetch = | USD detail per 1 SC (standard) | Free-pool SC |
|---|---|---|---|---|
| Keenable keyed | `requests_remaining / 1` (shared pool, see note) | `requests_remaining / 1` (shared pool) | $0.004 (Agent Builder $4/1k); $0.001 Frontier | 100,000/mo → **100,000 SC-s and 100,000 SC-f shared** (one call decrements both views of the same pool) |
| Keenable keyless | **∞** (unmetered) | **∞** | $0 (not billed) | unmetered within 1k/hr·10 rps |
| Tinyfish | **∞** within rate windows | **∞** within rate windows | $0.00 | rate-capped only: 30/min·500/hr search, 150/min·1k/day fetch |
| Brave | `balance_usd / 0.005` | n/a (`fetch = null`, LLM Context bills as search) | $0.005/call | $5/mo → **1,000 SC-s** |
| Exa | `balance_usd / 0.007` standard (`/ 0.004` if instant pinned) | `balance_usd / 0.001` per content type (text+highlights on 1 URL = 2 pages → halve) | $0.007 search / $0.001/page | $10 grant + $10 bonus = $20 → **~2,800 SC-s** standard (≈1,400 per $10) |
| Firecrawl | `floor(credits / 2)` (2/10 results) | `credits / 1` per page | plan-dependent $/credit (Hobby $0.0038 monthly / $0.0032 yearly; Standard $0.00099/$0.00083; Growth $0.00080/$0.00067; Scale $0.00075/$0.00060; top-ups $5 → 1k/2k/2.5k/5k by plan) | 1,000 credits/mo → **500 SC-s / 1,000 SC-f** |
| Tavily | `credits / 1` basic, `/ 2` advanced | per-URL: `credits / 0.2` basic (1 cr per 5 URLs), `/ 0.4` advanced; per *call* with N URLs: `credits / (N/5 × depth)` | $0.008/credit PAYGO ($0.0075→$0.005 plans) → $0.008 basic search, $0.016 advanced; $0.0016–$0.0032 per fetched URL basic | 1,000 credits/mo → **1,000 SC-s** basic (500 advanced) / **5,000 SC-f** basic URLs |
| Parallel | `balance_usd / 0.001` Turbo/Fast, `/ 0.005` Basic/Advanced | `balance_usd / 0.001` per URL | $0.001 Turbo/Fast/Extract, $0.005 Basic/Adv; +$0.001 per extra-result page past 10 | $5/mo → **5,000 SC-s** Turbo (1,000 Basic) / **5,000 SC-f**; signup ~$80 → ~80,000 Turbo SC-s |
| You.com | `balance_usd / 0.005` + daily free pool **100/day** (separate refill, search only) | `balance_usd / 0.001` per live page (`blend` bills misses only, `cache` $0) | $0.005/call search, $0.001/live-page; Answer $0.005, Research $0.012–$1.20, Finance $0.11/$0.50 | $100 once → **20,000 SC-s** (or 100,000 SC-f); plus 100 SC-s/day free |

Shared-pool depletion rules: Keenable — 1 search decrements the shared 100k *and therefore both* SC-s and SC-f views (single counter, two lenses). Firecrawl/Tavily credits — search and fetch draw on one credit balance: track one native balance, project two SC numbers from it (`SC-s` and `SC-f` are alternative views, not additive; spend on one reduces the other).

### 11.4 Known SC↔USD divergence (displayed, not hidden)

Base call = 1 SC, but these consume extra native while still costing 1 SC — the USD detail section must show the true spend, and spend caps (if any) stay USD-denominated:
- Exa: results >10 (+$1/1k), AI summaries (+$1/1k pages), second content type (×2 pages).
- Firecrawl: JSON/question/highlights/audio/video/PII (+4/page each), injection check (+4), ZDR (+1), Grok X (30/req), per-result scrape on search.
- You.com: `fetch`-mode extraction on all pages vs `blend` (misses only) vs `cache` ($0); `count` up to 100 still 1 SC-s.
- Parallel: extra results past 10 (+$1/1k); Task/Responses tiers above search.
- Tavily: advanced depth (×2), Research 4–250 credits (out of scope for SC-s; route Research off-SC or as N SC).
- Keenable: `realtime` / `fetch.live` SKUs (>1 credit) — read `_meta[keenable/usage]`, show actual credits in detail.
Rule of thumb: **SC answers "can we afford another call", USD answers "what did it really cost"**. For equal-priority routing this is the right split: SC picks the provider with the most calls left; USD breaks ties toward the cheapest real cost.

### 11.5 Worked examples (allocation + display)

- Exa $10.00 balance, standard search: `10 / 0.007 ≈ 1,428 SC-s`. Display: **"1,428 credits"**, detail: "$10.00 @ $0.007/search (standard, ≤10 incl. contents), resets to $10 on the 1st".
- Firecrawl 1,000 free credits: `1000/2 = 500 SC-s`, `1000/1 = 1,000 SC-f`. Display: **"500 search / 1,000 fetch credits"**, detail: "1,000 FC @ 2/10 search, 1/page scrape, Hobby-equiv $0.0038/cr".
- Brave $5.00: `5 / 0.005 = 1,000 SC-s`, SC-f n/a. Display: **"1,000 credits"**, detail: "$5.00 prepaid @ $5/1k, successful-only, monthly reset".
- Parallel $5.00, Turbo: `5 / 0.001 = 5,000 SC-s`. Display: **"5,000 credits"**, detail: "$5.00 @ $1/1k Turbo (10 incl.), Basic/Adv $5/1k".
- You.com $100 signup: `100 / 0.005 = 20,000 SC-s` + 100/day free pool. Display: **"20,000 credits + 100 free/day"**, detail: "$100.00 @ $5/1k search, $1/1k live pages, balance API `/v1/billing/account_balance` (cents)".
- Tinyfish / Keenable-keyless: Display: **"Free • unmetered"** (SC ∞), detail: rate windows only (Tinyfish 30/min·500/hr + 150/min·1k/day; Keenable 1k/hr·10 rps per IP).
- Equal-priority routing example: Exa 1,428 SC-s vs Brave 1,000 SC-s vs Tinyfish ∞ — Tinyfish is eligible but rate-thin (30/min); among paid, Exa wins on volume, Brave wins on USD/call tie-break only if SC-s tie ($0.005 vs $0.007).

### 11.6 Mapping from today's mixed `UnitKind` (migration sketch, no code changed)

- `REQUEST` (Brave/Tinyfish/Keenable-keyless search) → 1 SC per call/URL, USD detail from `COST_USD_PER_REQUEST` / $0.
- `CREDIT` (Firecrawl/Tavily/Keenable-keyed) → SC via §11.3 divisor; keep native credit balance as the detail + usage API.
- `USD` (Exa/Parallel/You.com) → SC via per-1k rate; keep dollar balance + `costDollars`/`account_balance` as the detail.
- `FREE` / `budget: null` → SC ∞, display "Free", detail shows rate windows only.
- Operator allocation becomes "grant N SC-s / M SC-f per provider per period"; each success decrements; 0 → local soft-402 (don't call vendor) while vendor 402/429 handling stays as documented in §§1–8.

---

*Research-only change. No source files modified. All fetches via freesearch MCP; per-claim URLs above.*
