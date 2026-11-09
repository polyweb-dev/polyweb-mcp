import type { Page, Route } from "@playwright/test"
import {
  fetchResponseFixture as canonicalFetchFixture,
  searchResponseFixture as canonicalSearchFixture,
} from "../../src/test/backendFixtures"
import {
  AGGREGATED_TRACE_ID,
  ERROR_TRACE_ID,
  SUCCESS_TRACE_ID,
  aggregatedTraceDetailFixture,
  errorTraceDetailFixture,
  traceDetailFixture,
  traceListFixture,
} from "../../src/test/fixtures/activity"
import { SYSTEM_ADMIN_PERMISSIONS, userAccountBody } from "./accountStub"
import { installVaultRoutes } from "./vaultStub"

/** Account id of the default stubbed session (a system administrator). */
export const DEFAULT_ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"

/** Email of the default stubbed session. */
export const DEFAULT_ACCOUNT_EMAIL = "admin@example.com"

/**
 * Deterministic in-memory backend stub for state-neutral E2E.
 *
 * `installBackendStub(page)` intercepts the app's backend traffic (which
 * otherwise flows through the Vite proxy to the LIVE backend at
 * 127.0.0.1:8001) and serves fixed fixtures instead. Writes (routing PUT,
 * provider PATCH) mutate only per-scenario in-memory
 * variables, so toggle/save/delete interactions behave realistically inside
 * the scenario while the real backend is never touched.
 *
 * Fixture values mirror the live FastAPI wire contract (snake_case,
 * Decimal-as-string, ISO-8601 datetimes) and the canonical unit-test
 * fixtures in `src/test/backendFixtures.ts`:
 * - 8 canonical providers (brave, keenable, tavily, exa, firecrawl, you,
 *   parallel, tinyfish) with stable priorities 1..8, fixed p95 latencies, and
 *   catalog-faithful secret presence (you/parallel start "missing"). Provider
 *   secrets are credential instances since U3 (providerConfigStub.ts); the
 *   provider-scoped /secret and /oauth routes are gone and not stubbed.
 * - Routing starts chained/balanced/3 (master failover switch ON), so the
 *   K2 keyboard-toggle sequence is deterministic.
 */

const FIXED_AT = "2026-09-06T10:05:00Z"

type SecretPresence = "configured" | "missing" | "keyless_public"

interface StubProvider {
  provider_id: string
  enabled: boolean
  enable_mask: number
  support_mask: number
  priority: number
  health: "healthy"
  health_checked_at: null
  circuit_breaker: { state: "closed"; updated_at: string }
  latency_p95_ms: number
  secret_presence: SecretPresence
  free_tier_estimates: Record<string, string>
  reset_schedule: null
  /** Confirmed Tavily key environment readback; null for every other provider. */
  tavily_key_environment?: "dev" | "prod" | null
}


/**
 * In-memory manual billing entries for manual-quota scenarios. Mutated (never
 * reassigned) so route closures registered by installBackendStub always see
 * the current per-scenario state; writes via PUT persist for the scenario.
 */
const stubbedManualQuotas: Record<string, Record<string, unknown>> = {}

/**
 * System permissions served by GET /api/v1/system/access. Accounts carry no
 * role, so every system gate (Routing, Usage, Settings, Admin, control edits)
 * follows this list. The fixtures.ts Before hook resets it to the system
 * administrator set once per scenario (not per tab), and account steps narrow
 * it afterwards. The list is read per request, so a change applies to every
 * later system access read of every tab.
 */
let stubbedSystemPermissions: string[] = [...SYSTEM_ADMIN_PERMISSIONS]

export function setStubbedSystemPermissions(permissions: readonly string[]): void {
  stubbedSystemPermissions = [...permissions]
}

export function resetStubbedSystemPermissions(): void {
  stubbedSystemPermissions = [...SYSTEM_ADMIN_PERMISSIONS]
}

export function setStubbedManualQuota(
  provider: string,
  entry: Record<string, unknown> | null
): void {
  if (entry === null) delete stubbedManualQuotas[provider]
  else stubbedManualQuotas[provider] = entry
}

/**
 * Mutable dashboard latest_quota override. overrideDashboardLatestQuota
 * installs a dashboard route that reads this per request (instead of
 * closing over fixed rows), so a step can flip quota state and the SUT's
 * next dashboard refresh deterministically sees it.
 */
let dashboardQuotaOverride: unknown[] | null = null

// ---------------------------------------------------------------------------
// UI7 credit-unit stub (provider-credits.feature @ui7).
//
// Mutable per-scenario dashboard credit state plus grant/history/sync
// routes. All writes stay in memory; the live backend is never touched.
// ---------------------------------------------------------------------------

let stubbedProviderLimits: unknown[] | null = null
let stubbedUsdTotals: unknown[] | null = null

type StubbedHistoryValue = { events: unknown[]; nextCursor: string | null; error: string | null }
const stubbedHistory: Record<string, StubbedHistoryValue> = {}
const stubbedGrantRequests: Array<Record<string, unknown>> = []
let stubbedGrantMode: "ok" | "conflict" = "ok"
const stubbedSyncRequests: string[] = []

/** Serve this provider_limits array from GET /dashboard. */
export function setStubbedProviderLimits(limits: unknown[] | null): void {
  stubbedProviderLimits = limits === null ? null : [...limits]
}

/** Serve this spend_totals array from GET /dashboard. */
export function setStubbedUsdTotals(totals: unknown[] | null): void {
  stubbedUsdTotals = totals === null ? null : [...totals]
}

/** Serve one history page (or an error) for a backend provider id. */
export function setStubbedHistory(
  provider: string,
  value: StubbedHistoryValue,
): void {
  stubbedHistory[provider] = { events: [...value.events], nextCursor: value.nextCursor, error: value.error }
}

/** Next grant PUT answers 409 (stale version) instead of 200. */
export function setStubbedGrantMode(mode: "ok" | "conflict"): void {
  stubbedGrantMode = mode
}

/** Grant PUT bodies seen in this scenario, in order. */
export function stubbedGrantBodies(): Array<Record<string, unknown>> {
  return [...stubbedGrantRequests]
}

/** Provider ids that received POST /limits/sync in this scenario. */
export function stubbedSyncCalls(): string[] {
  return [...stubbedSyncRequests]
}

function ui7ConversionProfile(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    native_usd_per_unit: "1",
    cost_basis: "priced_native_use",
    price_version: "v2026-09",
    source: "documented",
    estimated: false,
    ...overrides,
  }
}

function ui7SearchRecord(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    provider: "brave",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    rate: null,
    budget: null,
    native_pool_id: "brave:keyed:usd",
    conversion_profile: ui7ConversionProfile(),
    plan_name: "Brave Search",
    usage_url: "https://api-dashboard.search.brave.com/",
    version: 1,
    ...overrides,
  }
}

function ui7FetchRecord(): Record<string, unknown> {
  return {
    provider: "brave",
    operation: "fetch",
    auth_mode: "keyed",
    supported: false,
    transport_available: false,
    rate: null,
    budget: null,
    native_pool_id: null,
    conversion_profile: ui7ConversionProfile({ native_usd_per_unit: null }),
    plan_name: null,
    usage_url: null,
    version: 1,
  }
}

/** Finite Brave card: USD 5 allowance, USD 4.500 left, 4500 Usd, 90%. */
export function braveCreditLimits(): unknown[] {
  return [
    {
      provider: "brave",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: ui7SearchRecord(),
          fetch: ui7FetchRecord(),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: {
            pool_id: "brave:keyed:usd",
            provider: "brave",
            auth_mode: "keyed",
            native_unit: "USD",
            remaining: "4.500",
            allowance: "5.000",
            actual_spend_usd: null,
            source: "vendor_headers",
            confidence: "observed",
            reset_at: "2026-10-01T00:00:00Z",
            observed_at: FIXED_AT,
            version: 1,
            credential_generation: 1,
            next_sync_at: null,
            stale: false,
            manual_anchor: false,
          },
          usd_views: [
            {
              state: "finite",
              operation: "search",
              remaining_usd: "4.5",
              local_remaining_usd: null,
              request_cost_usd: "0.005",
              shared_pool_id: "brave:keyed:usd",
              possible_standard_calls: "900",
              price_version: "v2026-09",
              priced: true,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_usd: null,
              local_remaining_usd: null,
              request_cost_usd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
          ],
          rate_progress: [
            {
              bucket_id: "brave:search:1h",
              operation: "search",
              window: "1h",
              unit: "requests",
              remaining: "950",
              limit: "1000",
              reset_at: "2026-09-06T11:00:00Z",
              source: "vendor_headers",
              confidence: "observed",
              kind: "rate",
              stale: false,
              enforceable: true,
            },
          ],
          grants: null,
          detail: {
            plan_name: "Brave Search",
            native_unit: "USD",
            native_balance: "4.500",
            native_allowance: "5.000",
            usd_per_call: "0.005",
            actual_spend_usd: null,
            reset_at: "2026-10-01T00:00:00Z",
            reset_rule: "vendor_period",
            usage_url: "https://api-dashboard.search.brave.com/",
            source: "vendor_headers",
            confidence: "observed",
            last_sync_at: FIXED_AT,
            stale: false,
            price_version: "v2026-09",
            balance_split_note: null,
            rate_windows: [
              {
                bucket_id: "brave:search:1s",
                limit: "50",
                window: "1s",
                scope: "org",
                unit: "requests",
                remaining: "50",
                reset_at: null,
                source: "vendor_headers",
                confidence: "observed",
              },
            ],
            tier_split_known: true,
            aggregate_pool_id: "brave:keyed:usd",
          },
        },
      ],
      documented_keyless_operations: [],
      version: 1,
      generated_at: FIXED_AT,
    },
  ]
}

/** Brave card after one 5-Usd debit: 4495 Usd, USD 4.495, 89.9%. */
export function braveCreditLimitsAfterDebit(): unknown[] {
  const limits = braveCreditLimits() as Array<Record<string, unknown>>
  const entry = limits[0] as Record<string, unknown>
  const auths = entry.auths as Array<Record<string, unknown>>
  const auth = auths[0] as Record<string, unknown>
  auth.aggregate_pool = {
    ...(auth.aggregate_pool as Record<string, unknown>),
    remaining: "4.495",
  }
  const views = auth.usd_views as Array<Record<string, unknown>>
  views[0] = { ...views[0], remaining_usd: "4.495", possible_standard_calls: "899" }
  const detail = auth.detail as Record<string, unknown>
  auth.detail = { ...detail, native_balance: "4.495" }
  return limits as unknown[]
}

/** Unknown card: no known balance, price, tier split, or reset. */
export function unknownCreditLimits(): unknown[] {
  return [
    {
      provider: "brave",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: ui7SearchRecord({
            conversion_profile: ui7ConversionProfile({ native_usd_per_unit: null }),
          }),
          fetch: ui7FetchRecord(),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [
            {
              pool_id: "brave:keyed:unknown",
              tier: "unknown",
              native_unit: "unknown",
              native_remaining: null,
              native_allowance: null,
              remaining_usd: null,
              allowance_usd: null,
              reset_rule: "unknown",
              reset_at: null,
              funding_mode: "unknown",
              source: "unknown",
              confidence: "unknown",
              transport_available: false,
              label: null,
            },
          ],
          tier_split_known: false,
          aggregate_pool: null,
          usd_views: [
            {
              state: "unknown",
              operation: "search",
              remaining_usd: null,
              local_remaining_usd: null,
              request_cost_usd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_usd: null,
              local_remaining_usd: null,
              request_cost_usd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
          ],
          rate_progress: [],
          grants: null,
          detail: {
            plan_name: null,
            native_unit: null,
            native_balance: null,
            native_allowance: null,
            usd_per_call: null,
            actual_spend_usd: null,
            reset_at: null,
            reset_rule: "unknown",
            usage_url: null,
            source: "unknown",
            confidence: "unknown",
            last_sync_at: null,
            stale: false,
            price_version: "",
            balance_split_note: null,
            rate_windows: [],
            tier_split_known: false,
            aggregate_pool_id: null,
          },
        },
      ],
      documented_keyless_operations: [],
      version: 1,
      generated_at: FIXED_AT,
    },
  ]
}

/** Fund-less Parallel card (no vendor budget configured). */
export function parallelCardLimits(): unknown[] {
  return [
    {
      provider: "parallel",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: ui7SearchRecord({
            provider: "parallel",
            native_pool_id: null,
            conversion_profile: ui7ConversionProfile({ native_usd_per_unit: null }),
            plan_name: null,
            usage_url: null,
          }),
          fetch: ui7FetchRecord(),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
          usd_views: [
            {
              state: "unknown",
              operation: "search",
              remaining_usd: null,
              local_remaining_usd: null,
              request_cost_usd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_usd: null,
              local_remaining_usd: null,
              request_cost_usd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
          ],
          rate_progress: [],
          grants: null,
          detail: {
            plan_name: null,
            native_unit: null,
            native_balance: null,
            native_allowance: null,
            usd_per_call: null,
            actual_spend_usd: null,
            reset_at: null,
            reset_rule: "unknown",
            usage_url: null,
            source: "unknown",
            confidence: "unknown",
            last_sync_at: null,
            stale: false,
            price_version: "",
            balance_split_note: null,
            rate_windows: [],
            tier_split_known: true,
            aggregate_pool_id: null,
          },
        },
      ],
      documented_keyless_operations: [],
      version: 1,
      generated_at: FIXED_AT,
    },
  ]
}

/** Brave funds plus a fund-less Parallel card (usage offers no OAuth pairing since U3). */
export function bravePlusParallelLimits(): unknown[] {
  return [...braveCreditLimits(), ...parallelCardLimits()]
}

/** One history event with exact Usd balances plus a native fallback event. */
export function ui7HistoryEvents(): unknown[] {
  return [
    {
      event_id: "evt-2",
      provider: "brave",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "brave:keyed:usd",
      observed_at: "2026-09-06T10:04:00Z",
      source: "local",
      reason: "local_success",
      old_native: "4.500",
      new_native: "4.495",
      old_usd: "4.5",
      new_usd: "4.495",
      debit_usd: "0.005",
      native_debit: "0.005",
      actual_usd: null,
      confidence: "observed",
      local_attempt_id: "attempt-2",
      detail: { native_unit: "USD", actor: "" },
    },
    {
      event_id: "evt-1",
      provider: "brave",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "brave:keyed:usd",
      observed_at: "2026-09-06T10:03:00Z",
      source: "operator",
      reason: "grant",
      old_native: null,
      new_native: null,
      old_usd: null,
      new_usd: null,
      debit_usd: null,
      native_debit: null,
      actual_usd: null,
      confidence: "authoritative",
      local_attempt_id: null,
      detail: { native_unit: "USD", actor: "", search_granted_usd: "0.1" },
    },
  ]
}

// ---------------------------------------------------------------------------
// Tavily native Credits stub (provider-credits.feature U7-T*, quota-display).
//
// Native CREDIT pool with the documented free allowance (1000 Credits,
// monthly reset on day 1) and the PAYGO reference profile (USD 0.008 per
// Credit, 8 Usd per Credit). Search bills 1 Credit per basic call (2 per
// advanced); extract bills 0.2 Credits per good URL (1 Credit per 5 URLs,
// 2 per 5 advanced). The shared minute bucket is dev 100 RPM, prod 1000 RPM.
// ---------------------------------------------------------------------------

/** Safe vendor-402 message the stub serves for the out-of-Credits probe. */
export const TAVILY_402_MESSAGE = "Tavily is out of Credits. Wait until reset or upgrade."

/** Playground query that deterministically triggers the stubbed Tavily 402. */
export const TAVILY_402_QUERY = "tavily out of credits probe"

/** Fetch URL that deterministically triggers the stubbed Tavily 402. */
export const TAVILY_402_URL = "https://tavily-402.example.com/article"

function tavilyConversionProfile(): Record<string, unknown> {
  return {
    native_usd_per_unit: "0.008",
    cost_basis: "paygo_reference",
    price_version: "paygo-reference",
    source: "documented",
    estimated: true,
  }
}

function tavilySearchRecord(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    provider: "tavily",
    operation: "search",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    rate: null,
    budget: {
      model: "credits",
      free_allowance: "1000",
      allowance_unit: "Credits",
      allowance_period: "month",
      cost_per_1k: "8",
      standard_native_cost: "1",
      usd_per_call: "0.008",
      on_exhausted: "stop",
      usage_api: "https://api.tavily.com/usage",
      priced: true,
    },
    native_pool_id: "tavily:keyed:credits",
    conversion_profile: tavilyConversionProfile(),
    plan_name: "Free plan",
    usage_url: "https://app.tavily.com/home",
    version: 2,
    ...overrides,
  }
}

function tavilyFetchRecord(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    provider: "tavily",
    operation: "fetch",
    auth_mode: "keyed",
    supported: true,
    transport_available: true,
    rate: null,
    budget: {
      model: "credits",
      free_allowance: "1000",
      allowance_unit: "Credits",
      allowance_period: "month",
      cost_per_1k: "8",
      standard_native_cost: "0.2",
      usd_per_call: "0.0016",
      on_exhausted: "stop",
      usage_api: "https://api.tavily.com/usage",
      priced: true,
    },
    native_pool_id: "tavily:keyed:credits",
    conversion_profile: tavilyConversionProfile(),
    plan_name: "Free plan",
    usage_url: "https://app.tavily.com/home",
    version: 2,
    ...overrides,
  }
}

/** Shared minute rate window of the keyed rail (dev 100, prod 1000 RPM). */
function tavilyMinuteWindow(remaining: string, limit: string): Record<string, unknown> {
  return {
    bucket_id: "tavily:keyed:search:requests",
    limit,
    window: "1m",
    scope: "key",
    unit: "requests",
    remaining,
    reset_at: null,
    source: "vendor_headers",
    confidence: "observed",
  }
}

function tavilyFreeTier(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    pool_id: "tavily:keyed:free",
    tier: "free",
    native_unit: "CREDIT",
    native_remaining: "1000",
    native_allowance: "1000",
    remaining_usd: "8",
    allowance_usd: "8",
    reset_rule: "monthly_first",
    reset_at: "2026-10-01T00:00:00Z",
    funding_mode: "recurring",
    source: "documented_plan",
    confidence: "observed",
    transport_available: true,
    label: "Free plan credits (resets on the first)",
    ...overrides,
  }
}

function tavilyPaygoTier(): Record<string, unknown> {
  return {
    pool_id: "tavily:keyed:paygo",
    tier: "paid",
    native_unit: "CREDIT",
    native_remaining: null,
    native_allowance: null,
    remaining_usd: null,
    allowance_usd: null,
    reset_rule: "never",
    reset_at: null,
    funding_mode: "postpaid",
    source: "vendor_api",
    confidence: "observed",
    transport_available: true,
    label: "PAYGO access or an explicit spend cap (not stored credits)",
  }
}

function tavilyPool(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    pool_id: "tavily:keyed:credits",
    provider: "tavily",
    auth_mode: "keyed",
    native_unit: "CREDIT",
    remaining: "1000",
    allowance: "1000",
    actual_spend_usd: null,
    source: "vendor_api",
    confidence: "observed",
    reset_at: "2026-10-01T00:00:00Z",
    observed_at: FIXED_AT,
    version: 2,
    credential_generation: 1,
    next_sync_at: null,
    stale: false,
    manual_anchor: false,
    ...overrides,
  }
}

function tavilySearchView(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: "finite",
    operation: "search",
    remaining_usd: "8",
    local_remaining_usd: null,
    request_cost_usd: "0.008",
    shared_pool_id: "tavily:keyed:credits",
    possible_standard_calls: "1000",
    price_version: "paygo-reference",
    priced: true,
    ...overrides,
  }
}

function tavilyFetchView(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: "finite",
    operation: "fetch",
    remaining_usd: "8",
    local_remaining_usd: null,
    request_cost_usd: "0.0016",
    shared_pool_id: "tavily:keyed:credits",
    possible_standard_calls: "5000",
    price_version: "paygo-reference",
    priced: true,
    ...overrides,
  }
}

function tavilyDetail(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    plan_name: "Free plan",
    native_unit: "CREDIT",
    native_balance: "1000",
    native_allowance: "1000",
    usd_per_call: null,
    actual_spend_usd: null,
    reset_at: "2026-10-01T00:00:00Z",
    reset_rule: "monthly_first",
    usage_url: "https://app.tavily.com/home",
    source: "vendor_api",
    confidence: "observed",
    last_sync_at: FIXED_AT,
    stale: false,
    price_version: "paygo-reference",
    balance_split_note: null,
    rate_windows: [tavilyMinuteWindow("100", "100")],
    retry_after_seconds: null,
    tier_split_known: true,
    aggregate_pool_id: "tavily:keyed:credits",
    ...overrides,
  }
}

/** Finite Tavily card: 1000 / 1000 native Credits with the dev minute window. */
export function tavilyCreditLimits(): unknown[] {
  return [
    {
      provider: "tavily",
      active_auth_mode: "keyed",
      auths: [
        {
          auth_mode: "keyed",
          transport_available: true,
          search: tavilySearchRecord(),
          fetch: tavilyFetchRecord(),
          free_tiers: [tavilyFreeTier()],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: tavilyPool(),
          usd_views: [tavilySearchView(), tavilyFetchView()],
          rate_progress: [],
          grants: null,
          detail: tavilyDetail(),
        },
      ],
      documented_keyless_operations: ["search", "fetch"],
      version: 2,
      generated_at: FIXED_AT,
    },
  ]
}

function withTavilyBalance(limits: unknown[], remaining: string, calls: string): unknown[] {
  const entries = limits as Array<Record<string, unknown>>
  const entry = entries[0] as Record<string, unknown>
  const auths = entry.auths as Array<Record<string, unknown>>
  const auth = auths[0] as Record<string, unknown>
  auth.aggregate_pool = { ...(auth.aggregate_pool as Record<string, unknown>), remaining }
  const views = auth.usd_views as Array<Record<string, unknown>>
  const remainingUsd = String(Number(remaining) * 0.008)
  views[0] = { ...views[0], remaining_usd: remainingUsd, possible_standard_calls: calls }
  views[1] = { ...views[1], remaining_usd: remainingUsd }
  const detail = auth.detail as Record<string, unknown>
  auth.detail = { ...detail, native_balance: remaining }
  const tiers = auth.free_tiers as Array<Record<string, unknown>>
  auth.free_tiers = tiers.map((tier) => ({ ...tier, native_remaining: remaining, remaining_usd: remainingUsd }))
  return limits
}

/** Tavily card after one basic search debit: 999 / 1000 Credits. */
export function tavilyCreditLimitsAfterBasic(): unknown[] {
  return withTavilyBalance(tavilyCreditLimits(), "999", "999")
}

/** Tavily card after one advanced search debit: 998 / 1000 Credits. */
export function tavilyCreditLimitsAfterAdvanced(): unknown[] {
  return withTavilyBalance(tavilyCreditLimits(), "998", "499")
}

/** Keyless Tavily rail: no reported quota, no numeric minute headroom. */
export function tavilyKeylessLimits(): unknown[] {
  const keylessProfile = {
    native_usd_per_unit: null,
    cost_basis: "keyless_unpublished",
    price_version: "",
    source: "keyless_unpublished",
    estimated: false,
  }
  const unknownView = (operation: string): Record<string, unknown> => ({
    state: "unknown",
    operation,
    remaining_usd: null,
    local_remaining_usd: null,
    request_cost_usd: null,
    shared_pool_id: null,
    possible_standard_calls: null,
    price_version: null,
    priced: false,
  })
  return [
    {
      provider: "tavily",
      active_auth_mode: "keyless",
      auths: [
        {
          auth_mode: "keyless",
          transport_available: true,
          search: tavilySearchRecord({
            auth_mode: "keyless",
            supported: true,
            transport_available: true,
            rate: null,
            budget: null,
            native_pool_id: null,
            conversion_profile: keylessProfile,
            plan_name: "Keyless access mode (rate limit not published)",
            usage_url: null,
          }),
          fetch: tavilyFetchRecord({
            auth_mode: "keyless",
            supported: true,
            transport_available: true,
            rate: null,
            budget: null,
            native_pool_id: null,
            conversion_profile: keylessProfile,
            plan_name: "Keyless access mode (rate limit not published)",
            usage_url: null,
          }),
          free_tiers: [],
          paid_tiers: [],
          unknown_tiers: [],
          tier_split_known: true,
          aggregate_pool: null,
          usd_views: [unknownView("search"), unknownView("fetch")],
          rate_progress: [],
          grants: null,
          detail: tavilyDetail({
            plan_name: "Keyless access mode (rate limit not published)",
            native_unit: null,
            native_balance: null,
            native_allowance: null,
            reset_at: null,
            reset_rule: "unknown",
            usage_url: "https://app.tavily.com/home",
            source: "unknown",
            confidence: "unknown",
            last_sync_at: null,
            rate_windows: [],
          }),
        },
      ],
      documented_keyless_operations: ["search", "fetch"],
      version: 2,
      generated_at: FIXED_AT,
    },
  ]
}

/** Free Tavily rail with zero Credits left and no PAYGO access. */
export function tavilyFreeExhaustedLimits(): unknown[] {
  return withTavilyBalance(tavilyCreditLimits(), "0", "0")
}

/** Paid Tavily rail at zero plan Credits with observed PAYGO access. */
export function tavilyPaygoLimits(): unknown[] {
  const limits = withTavilyBalance(tavilyCreditLimits(), "0", "0") as Array<Record<string, unknown>>
  const auth = (limits[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auth[0] as Record<string, unknown>
  keyed.paid_tiers = [tavilyPaygoTier()]
  return limits as unknown[]
}

/** Finite Tavily rail with a stored operator grant (800 + 1600 Usd). */
export function tavilyGrantLimits(): unknown[] {
  const limits = tavilyCreditLimits() as Array<Record<string, unknown>>
  const auth = (limits[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auth[0] as Record<string, unknown>
  keyed.grants = {
    provider: "tavily",
    auth_mode: "keyed",
    period: "month" as const,
    version: 1,
    search_granted_usd: "0.8",
    search_consumed_usd: "0",
    search_reserved_usd: "0",
    fetch_granted_usd: "1.6",
    fetch_consumed_usd: "0",
    fetch_reserved_usd: "0",
  }
  return limits as unknown[]
}

/** Prod Tavily rail: 1000 RPM minute headroom with an active Retry-After delay. */
export function tavilyProdCreditLimits(): unknown[] {
  const limits = tavilyCreditLimits() as Array<Record<string, unknown>>
  const auth = (limits[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auth[0] as Record<string, unknown>
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = {
    ...detail,
    rate_windows: [tavilyMinuteWindow("1000", "1000")],
    retry_after_seconds: 45,
  }
  return limits as unknown[]
}

/** Brave finite card plus the finite Tavily card for the unchanged-Brave proof. */
export function bravePlusTavilyLimits(): unknown[] {
  return [...braveCreditLimits(), ...tavilyCreditLimits()]
}

/** Two Tavily balance events with native Credits sides plus a grant event. */
export function tavilyHistoryEvents(): unknown[] {
  return [
    {
      event_id: "evt-t2",
      provider: "tavily",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "tavily:keyed:credits",
      observed_at: "2026-09-06T10:04:00Z",
      source: "local",
      reason: "local_success",
      old_native: "1000",
      new_native: "999",
      old_usd: "8",
      new_usd: "7.992",
      debit_usd: "0.008",
      native_debit: "1",
      actual_usd: null,
      confidence: "observed",
      local_attempt_id: "attempt-t2",
      detail: { native_unit: "CREDIT", actor: "" },
    },
    {
      event_id: "evt-t1",
      provider: "tavily",
      auth_mode: "keyed",
      operation: "search",
      pool_id: "tavily:keyed:credits",
      observed_at: "2026-09-06T10:03:00Z",
      source: "operator",
      reason: "grant",
      old_native: null,
      new_native: null,
      old_usd: null,
      new_usd: null,
      debit_usd: null,
      native_debit: null,
      actual_usd: null,
      confidence: "authoritative",
      local_attempt_id: null,
      detail: { native_unit: "CREDIT", actor: "", search_granted_usd: "0.8" },
    },
  ]
}

/** Recorded Tavily search + extract use (8 Usd basic search, 1.6 Usd extract). */
export function tavilyUseTotals(): unknown[] {
  return [
    {
      provider: "tavily",
      operation: "search",
      spend_usd: "0.008",
      attempt_count: 1,
      volume_count: 1,
    },
    {
      provider: "tavily",
      operation: "fetch",
      spend_usd: "0.0016",
      attempt_count: 1,
      volume_count: 5,
    },
  ]
}

// ---------------------------------------------------------------------------
// FIX card/popover + routing fixtures (PLAN 10.5/10.6, FIX-Q1/FIX-Q2).
//
// All helpers below are additive: every existing export keeps its name and
// signature. These fixtures feed both provider-credits (card + popover) and
// routing (tier slot) scenarios. Minute windows live only in
// `detail.rate_windows` (popover-only rate rows); `rate_progress` stays empty
// in every fixture below, so the card renders no rate bars. Literal ceilings:
// dev 100, prod 1000 requests per minute. Funds and rate headroom are
// independent: consumed fixtures spend the minute window only, exhausted
// fixtures spend both, and the unknown-headroom fixture serves no minute row
// until the dashboard confirms the new ceiling.
// ---------------------------------------------------------------------------

/** Literal Development minute ceiling served in every dev minute window. */
export const TAVILY_DEV_MINUTE_LIMIT = "100"

/** Literal Production minute ceiling served in every prod minute window. */
export const TAVILY_PROD_MINUTE_LIMIT = "1000"

/** Free subscription account-plan name served as `detail.plan_name`. */
export const TAVILY_ACCOUNT_PLAN_FREE = "Free plan"

/**
 * Paid subscription account-plan name (Bootstrap). It identifies the
 * subscription only, never the key environment: a Bootstrap rail can serve
 * either the dev or the prod ceiling, so steps must not infer dev/prod from
 * it. The vendor usage payload carries this name as `account.current_plan`
 * with no rate-tier field (see tavilyVendorUsageWithoutTier).
 */
export const TAVILY_ACCOUNT_PLAN_BOOTSTRAP = "Bootstrap"

/** Long zero-decimal native input: displays as `100`, never rounded up. */
export const TAVILY_LONG_DECIMAL_NATIVE = "100.000000000"

/** Long zero-decimal extract Usd input: displays as `1.6 Usd`. */
export const TAVILY_LONG_DECIMAL_Usd = "1.600000000"

/** Long zero-decimal search USD input: displays as `[USD 0.008]`. */
export const TAVILY_LONG_DECIMAL_USD_SEARCH = "0.008000000"

/** Long zero-decimal extract USD input: displays as `[USD 0.0016]`. */
export const TAVILY_LONG_DECIMAL_USD_EXTRACT = "0.001600000"

/** Vendor usage fields that must never appear on the usage payload. */
export const TAVILY_VENDOR_ABSENT_TIER_FIELDS = ["key_environment", "rate_tier", "rate_limit_tier"] as const

function withTavilyMinuteWindow(limits: unknown[], remaining: string, limit: string): unknown[] {
  const entries = limits as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = { ...detail, rate_windows: [tavilyMinuteWindow(remaining, limit)] }
  return limits
}

function withTavilyStale(limits: unknown[]): unknown[] {
  const entries = limits as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  keyed.aggregate_pool = { ...(keyed.aggregate_pool as Record<string, unknown>), stale: true }
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = { ...detail, stale: true }
  return limits
}

function withTavilyPlanName(limits: unknown[], plan: string): unknown[] {
  const entries = limits as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  keyed.search = { ...(keyed.search as Record<string, unknown>), plan_name: plan }
  keyed.fetch = { ...(keyed.fetch as Record<string, unknown>), plan_name: plan }
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = { ...detail, plan_name: plan }
  return limits
}

/** Consumed Development rail: full 1000/1000 funds, minute headroom 90/100. */
export function tavilyConsumedDevLimits(): unknown[] {
  return withTavilyMinuteWindow(tavilyCreditLimits(), "90", TAVILY_DEV_MINUTE_LIMIT)
}

/** Consumed Production rail: full 1000/1000 funds, minute headroom 900/1000. */
export function tavilyConsumedProdLimits(): unknown[] {
  return withTavilyMinuteWindow(tavilyCreditLimits(), "900", TAVILY_PROD_MINUTE_LIMIT)
}

/** Exhausted Development rail: zero funds with a 0/100 minute row. */
export function tavilyExhaustedRateLimits(): unknown[] {
  return withTavilyMinuteWindow(withTavilyBalance(tavilyCreditLimits(), "0", "0"), "0", TAVILY_DEV_MINUTE_LIMIT)
}

/**
 * Unconfirmed Production headroom: full funds with no minute row yet. Pair
 * with a prod status readback (setTavilyStatusReadbackProd): the popover then
 * shows `unknown/1000 requests per minute` until the dashboard serves a prod
 * window. A stale dev window (tavilyCreditLimits with prod readback) yields
 * the same unknown row through the ceiling mismatch.
 */
export function tavilyUnknownProdHeadroomLimits(): unknown[] {
  const entries = tavilyCreditLimits() as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = { ...detail, rate_windows: [] }
  return entries as unknown[]
}

/** Stale Development rail: dev 100/100 window with stale pool and detail flags. */
export function tavilyStaleDevLimits(): unknown[] {
  return withTavilyStale(tavilyCreditLimits())
}

/** Bootstrap subscription on the dev ceiling: the plan name never implies prod. */
export function tavilyBootstrapDevLimits(): unknown[] {
  return withTavilyPlanName(tavilyCreditLimits(), TAVILY_ACCOUNT_PLAN_BOOTSTRAP)
}

/** Bootstrap subscription on the prod ceiling (Retry-After stays null). */
export function tavilyBootstrapProdLimits(): unknown[] {
  const limits = withTavilyMinuteWindow(tavilyCreditLimits(), TAVILY_PROD_MINUTE_LIMIT, TAVILY_PROD_MINUTE_LIMIT)
  return withTavilyPlanName(limits, TAVILY_ACCOUNT_PLAN_BOOTSTRAP)
}

/**
 * Fractional native rail: 999.6/1000 funds floor to 999 visible Credits with
 * exact amounts kept for the percent math. The 1.6 Usd extract cost and the
 * 0.008/0.0016 USD prices come from the base budgets unchanged (FIX-Q1).
 */
export function tavilyFractionalNativeLimits(): unknown[] {
  const entries = tavilyCreditLimits() as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  keyed.aggregate_pool = { ...(keyed.aggregate_pool as Record<string, unknown>), remaining: "999.6" }
  const views = keyed.usd_views as Array<Record<string, unknown>>
  views[0] = { ...views[0], remaining_usd: "7.9968", possible_standard_calls: "999.6" }
  views[1] = { ...views[1], remaining_usd: "7.9968" }
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = { ...detail, native_balance: "999.6" }
  const tiers = keyed.free_tiers as Array<Record<string, unknown>>
  keyed.free_tiers = tiers.map((tier) => ({ ...tier, native_remaining: "999.6", remaining_usd: "7.9968" }))
  return entries as unknown[]
}

/**
 * Long zero-decimal rail: `100.000000000` funds and windows display as 100,
 * `1.600000000` Usd as `1.6 Usd`, `0.008000000` USD as `[USD 0.008]`, and
 * `0.001600000` USD as `[USD 0.0016]` (FIX-Q1: trim, never integer-convert).
 */
export function tavilyLongDecimalLimits(): unknown[] {
  const entries = tavilyCreditLimits() as Array<Record<string, unknown>>
  const auths = (entries[0] as Record<string, unknown>).auths as Array<Record<string, unknown>>
  const keyed = auths[0] as Record<string, unknown>
  keyed.search = {
    ...(keyed.search as Record<string, unknown>),
    budget: {
      ...((keyed.search as Record<string, unknown>).budget as Record<string, unknown>),
      usd_per_call: TAVILY_LONG_DECIMAL_USD_SEARCH,
    },
  }
  keyed.fetch = {
    ...(keyed.fetch as Record<string, unknown>),
    budget: {
      ...((keyed.fetch as Record<string, unknown>).budget as Record<string, unknown>),
      usd_per_call: TAVILY_LONG_DECIMAL_USD_EXTRACT,
    },
  }
  keyed.aggregate_pool = {
    ...(keyed.aggregate_pool as Record<string, unknown>),
    remaining: TAVILY_LONG_DECIMAL_NATIVE,
    allowance: TAVILY_LONG_DECIMAL_NATIVE,
  }
  const views = keyed.usd_views as Array<Record<string, unknown>>
  views[0] = {
    ...views[0],
    remaining_usd: "0.800000000",
    request_cost_usd: "0.008000000",
    possible_standard_calls: TAVILY_LONG_DECIMAL_NATIVE,
  }
  views[1] = { ...views[1], remaining_usd: "0.800000000", request_cost_usd: TAVILY_LONG_DECIMAL_Usd }
  const detail = keyed.detail as Record<string, unknown>
  keyed.detail = {
    ...detail,
    native_balance: TAVILY_LONG_DECIMAL_NATIVE,
    native_allowance: TAVILY_LONG_DECIMAL_NATIVE,
    rate_windows: [tavilyMinuteWindow(TAVILY_LONG_DECIMAL_NATIVE, TAVILY_LONG_DECIMAL_NATIVE)],
  }
  const tiers = keyed.free_tiers as Array<Record<string, unknown>>
  keyed.free_tiers = tiers.map((tier) => ({
    ...tier,
    native_remaining: TAVILY_LONG_DECIMAL_NATIVE,
    native_allowance: TAVILY_LONG_DECIMAL_NATIVE,
    remaining_usd: "0.800000000",
    allowance_usd: "0.800000000",
  }))
  return entries as unknown[]
}

/** Keyless unknown rail: no numeric rate and no dev/prod denominator. */
export function tavilyKeylessUnknownLimits(): unknown[] {
  return tavilyKeylessLimits()
}

/**
 * Documentary vendor usage payload. It carries `account.current_plan`, key
 * usage, key caps, and credit totals only: no rate-tier field exists, so the
 * application must use the manual dev/prod status readback instead. Steps can
 * assert that none of TAVILY_VENDOR_ABSENT_TIER_FIELDS is a key of the result.
 */
export function tavilyVendorUsageWithoutTier(plan: string = TAVILY_ACCOUNT_PLAN_BOOTSTRAP): Record<string, unknown> {
  return {
    account: { current_plan: plan },
    key_usage: { used_credits: "10", credit_limit: "1000" },
    key_caps: { max_credits: "1000" },
    credits_total: "1000",
  }
}

/** Valid status readback: the application reports a dev key environment. */
export function setTavilyStatusReadbackDev(): void {
  setStubbedTavilyKeyEnvironment("dev")
}

/** Valid status readback: the application reports a prod key environment. */
export function setTavilyStatusReadbackProd(): void {
  setStubbedTavilyKeyEnvironment("prod")
}

/** Missing application readback: the tier control locks to Unknown. */
export function setTavilyStatusReadbackMissing(): void {
  setStubbedTavilyKeyEnvironment(null)
}

/** Invalid application readback: the tier control locks to Unknown. */
export function setTavilyStatusReadbackInvalid(): void {
  setStubbedTavilyKeyEnvironmentRaw("researcher")
}

/** Current stubbed status readback, including raw invalid values. */
export function stubbedTavilyStatusReadback(): unknown {
  return stubbedTavilyKeyEnvironment
}

let stubbedDashboardGetDelayMs: number | null = null

/**
 * Delay the next GET /dashboard reads by ms (or clear the delay). A delayed
 * dashboard refresh must not undo a confirmed ceiling or invent headroom: the
 * popover keeps `unknown/<ceiling>` until current dashboard data confirms it.
 */
export function delayStubbedDashboardGet(ms: number | null): void {
  stubbedDashboardGetDelayMs = ms
}

/** Hold the Tavily dashboard refresh open for ms (delayed-refresh proof). */
export function holdTavilyDashboardRefresh(ms: number): void {
  delayStubbedDashboardGet(ms)
}

/** Release a held Tavily dashboard refresh. */
export function clearTavilyDashboardHold(): void {
  delayStubbedDashboardGet(null)
}

/** Serve these limits while holding the dashboard refresh open for ms. */
export function deferTavilyDashboardLimits(limits: unknown[], ms: number): void {
  setStubbedProviderLimits(limits)
  delayStubbedDashboardGet(ms)
}

/** Reject the Tavily rate-tier PATCH with a 500 and this message. */
export function rejectTavilyRateTierPatch(message: string): void {
  failStubbedProviderPatch("tavily", message)
}

/** Clear the Tavily rate-tier PATCH rejection. */
export function clearTavilyRateTierPatchFailure(): void {
  failStubbedProviderPatch("tavily", null)
}

/** Fail the dashboard refresh (provider-credits + routing proof). */
export function failTavilyDashboardRefresh(message: string): void {
  failStubbedDashboardGet(message)
}

/** Clear the dashboard refresh failure. */
export function clearTavilyDashboardFailure(): void {
  failStubbedDashboardGet(null)
}

/** Fail the provider status refresh (readback-unavailable proof). */
export function failTavilyStatusRefresh(message: string): void {
  failStubbedProvidersGet(message)
}

/** Clear the provider status refresh failure. */
export function clearTavilyStatusFailure(): void {
  failStubbedProvidersGet(null)
}


// ---------------------------------------------------------------------------
// Provider PATCH failure/delay injection (provider-access-flags suite).
//
// Per-scenario maps cleared by installBackendStub. Failure forces the next
// PATCH for one backend provider id to 500; delay holds the PATCH response
// open so request-active (pending) controls stay observable. Neither map
// touches production sources.
// ---------------------------------------------------------------------------

const stubbedProviderPatchFailures: Record<string, string> = {}
const stubbedProviderPatchDelays: Record<string, number> = {}

/** Tavily rate-tier dropdown additions: PATCH body log plus refresh/test/usage tracking. */
interface StubbedProviderPatch {
  backendId: string
  body: Record<string, unknown>
}
const stubbedProviderPatches: StubbedProviderPatch[] = []
const stubbedTestRequests: string[] = []
const stubbedUsageRequests: string[] = []
let stubbedProvidersGetFailure: string | null = null
let stubbedDashboardGetFailure: string | null = null

/** PATCH bodies seen in this scenario, in order, with the backend provider id. */
export function stubbedProviderPatchBodies(): StubbedProviderPatch[] {
  return [...stubbedProviderPatches]
}

/** Provider ids that received POST .../test in this scenario. */
export function stubbedTestCalls(): string[] {
  return [...stubbedTestRequests]
}

/** URLs that hit a vendor-usage shaped endpoint in this scenario. */
export function stubbedUsageCalls(): string[] {
  return [...stubbedUsageRequests]
}

/** Set the confirmed Tavily key environment served by GET /api/v1/providers. */
export function setStubbedTavilyKeyEnvironment(
  env: "dev" | "prod" | null | undefined,
): void {
  stubbedTavilyKeyEnvironment = (env === undefined ? null : env) as typeof stubbedTavilyKeyEnvironment
}

/** Serve a raw (possibly invalid) Tavily key environment value for absent-state proof. */
export function setStubbedTavilyKeyEnvironmentRaw(value: unknown): void {
  stubbedTavilyKeyEnvironment = value as typeof stubbedTavilyKeyEnvironment
}

/** Override the secret presence served for one backend provider id. */
export function setStubbedSecretPresence(provider: string, presence: SecretPresence): void {
  stubbedSecretPresence[provider] = presence
}

/** Fail the next GET /api/v1/providers reads, or clear the failure. */
export function failStubbedProvidersGet(message: string | null): void {
  stubbedProvidersGetFailure = message
}

/** Fail the next GET /dashboard reads, or clear the failure. */
export function failStubbedDashboardGet(message: string | null): void {
  stubbedDashboardGetFailure = message
}

let stubbedTavilyKeyEnvironment: "dev" | "prod" | null = "dev"
const stubbedSecretPresence: Record<string, SecretPresence> = {}

/** Fail the next PATCH for one backend provider id, or clear the failure. */
export function failStubbedProviderPatch(provider: string, message: string | null): void {
  if (message === null) delete stubbedProviderPatchFailures[provider]
  else stubbedProviderPatchFailures[provider] = message
}

/** Delay the next PATCH for one backend provider id by ms, or clear it. */
export function delayStubbedProviderPatch(provider: string, ms: number | null): void {
  if (ms === null) delete stubbedProviderPatchDelays[provider]
  else stubbedProviderPatchDelays[provider] = ms
}

let stubbedTavilyPatchReadback: { armed: boolean; value: unknown } = { armed: false, value: undefined }

/**
 * Serve the next Tavily PATCH 200 with this raw readback instead of the
 * stored key environment. `undefined` omits the field (missing readback);
 * any other non dev/prod value is invalid. The stored environment stays at
 * its pre-save value, so the app treats the save as unconfirmed. One-shot:
 * the next Tavily PATCH consumes it. Cleared per scenario.
 */
export function setStubbedProviderPatchReadbackRaw(value: unknown): void {
  stubbedTavilyPatchReadback = { armed: true, value }
}

// ---------------------------------------------------------------------------
// Trace read API stub (Activity).
//
// `GET /api/v1/traces` serves the summary-only list (honoring the `operation`
// query filter, like the backend); `GET /api/v1/traces/{id}` serves the
// disclosed detail for the success (search) and error (fetch) fixtures and
// 404s unknown ids. Failure injection is per-scenario and cleared by
// installBackendStub.
// ---------------------------------------------------------------------------

const stubbedTraceListRequests: string[] = []
let stubbedTraceListFailure: string | null = null
const stubbedTraceDetailFailures: Record<string, string> = {}
const stubbedTraceDetailRequests: string[] = []

/** Query strings (including the leading `?`, or `""`) of trace list requests. */
export function traceListRequests(): string[] {
  return [...stubbedTraceListRequests]
}

/** Trace ids requested through `GET /api/v1/projects/{id}/traces/{trace_id}`, in order. */
export function traceDetailRequests(): string[] {
  return [...stubbedTraceDetailRequests]
}

/** Record one project trace list read (query string with its leading `?`). */
export function recordTraceListRequest(search: string): void {
  stubbedTraceListRequests.push(search)
}

/** Record one project trace detail read. */
export function recordTraceDetailRequest(traceId: string): void {
  stubbedTraceDetailRequests.push(traceId)
}

/** Injected trace list failure message, or null. */
export function traceListFailureMessage(): string | null {
  return stubbedTraceListFailure
}

/** Injected failure message of one trace detail, or null. */
export function traceDetailFailureMessage(traceId: string): string | null {
  return stubbedTraceDetailFailures[traceId] ?? null
}

/**
 * Calls of the removed global trace read (`/api/v1/traces[/{id}]`). The
 * backend no longer serves it, so the stub answers 404 and any call is a
 * regression a scenario can assert against.
 */
const legacyTraceCalls: string[] = []

export function legacyTraceRequests(): string[] {
  return [...legacyTraceCalls]
}

/**
 * The trace fixture list Activity has always rendered, now owned by the
 * project Alpha (see projectActivityStub.ts): the seven-provider fanout, the
 * legacy fixture list (aggregate, single-provider search, error fetch), then
 * the null-source and the fusion long-snippet traces. Unfiltered; the project
 * route applies the `operation` and `outcome` filters like the backend.
 */
export function activityTraceFixtures(): Record<string, unknown>[] {
  const list = traceListFixture() as { items: Record<string, unknown>[] }
  return [
    sevenProviderTraceSummaryFixture(),
    ...list.items,
    nullSourceTraceSummaryFixture(),
    fusionLongTraceSummaryFixture(),
  ]
}

/** A fresh copy of the success (search) trace detail fixture. */
export function successTraceDetailFixtureForStub(): Record<string, unknown> {
  return traceDetailFixture()
}

/** A fresh copy of the error (fetch) trace detail fixture. */
export function errorTraceDetailFixtureForStub(): Record<string, unknown> {
  return errorTraceDetailFixture()
}

/** Disclosed detail of one fixture trace, or null for an unknown id. */
export function activityTraceFixtureDetail(traceId: string): Record<string, unknown> | null {
  if (traceId === SUCCESS_TRACE_ID) return traceDetailFixture()
  if (traceId === ERROR_TRACE_ID) return errorTraceDetailFixture()
  if (traceId === AGGREGATED_TRACE_ID) return aggregatedTraceDetailFixture()
  if (traceId === SEVEN_PROVIDER_TRACE_ID) return sevenProviderTraceDetailFixture()
  if (traceId === NULL_SOURCE_TRACE_ID) return nullSourceTraceDetailFixture()
  if (traceId === FUSION_LONG_TRACE_ID) return fusionLongTraceDetailFixture()
  return null
}

// ---------------------------------------------------------------------------
// Project-scoped execution (POST /search, POST /fetch).
//
// Every request body must carry `project_id`; the project gate (installed by
// projectStub.ts) answers 404 for a project the caller cannot use and 403
// without the execution permission, like the backend. Each request is logged
// with its parsed body and headers so scenarios can assert the project id and
// the absence of any API key. A search can be held open (slow provider) to
// prove that a project switch aborts it or drops its late result.
// ---------------------------------------------------------------------------

export type ExecutionPermission = "search.execute" | "fetch.execute"

export type ExecutionGateResult = { status: 200; projectName: string } | { status: 403 | 404 }

/** Resolve one execution request against the project stub. */
export type ExecutionGate = (projectId: string, permission: ExecutionPermission) => ExecutionGateResult

let executionGate: ExecutionGate = () => ({ status: 404 })

/** Install the project gate (projectStub.ts calls this from installProjectStub). */
export function setExecutionGate(gate: ExecutionGate): void {
  executionGate = gate
}

export interface ExecutionRecord {
  operation: "search" | "fetch"
  body: Record<string, unknown>
  headers: Record<string, string>
  status: number | null
  /** "fulfilled" once answered, "aborted" when the browser dropped it first. */
  outcome: "pending" | "fulfilled" | "aborted"
}

const executionRecords: ExecutionRecord[] = []

/** Every search and fetch request of the scenario, oldest first. */
export function executionTraffic(): ExecutionRecord[] {
  return [...executionRecords]
}

/** Cleared once per scenario by the fixtures Before hook (not per tab). */
export function resetExecutionTraffic(): void {
  executionRecords.length = 0
  heldSearch.query = undefined
  releaseHeldSearches()
}

/**
 * Held search latch. `query` undefined holds nothing, null holds every search,
 * a string holds only searches for that query.
 */
const heldSearch: { query: string | null | undefined; waiters: Array<() => void> } = {
  query: undefined,
  waiters: [],
}

/** Hold matching search responses open until released (slow provider). */
export function holdStubbedSearches(query: string | null): void {
  heldSearch.query = query
}

/** Release every held search response and stop holding new ones. */
export function releaseHeldSearches(): void {
  heldSearch.query = undefined
  const waiters = heldSearch.waiters.splice(0)
  for (const release of waiters) release()
}

/** Number of search responses currently held open. */
export function heldSearchCount(): number {
  return heldSearch.waiters.length
}

/** Query marker that makes the stub return project-named results. */
export const ISOLATION_QUERY_MARKER = "isolation probe"

/** Title of the first result a project returns for an isolation query. */
export function isolationResultTitle(projectName: string): string {
  return `${projectName} isolation result`
}

function gateExecution(
  body: Record<string, unknown>,
  permission: ExecutionPermission
): { ok: true; projectName: string } | { ok: false; status: number; detail: unknown } {
  const projectId = body.project_id
  if (typeof projectId !== "string" || projectId === "") {
    return {
      ok: false,
      status: 422,
      detail: [{ loc: ["body", "project_id"], msg: "Field required", type: "missing" }],
    }
  }
  const gate = executionGate(projectId, permission)
  if (gate.status === 200) return { ok: true, projectName: gate.projectName }
  return {
    ok: false,
    status: gate.status,
    detail: gate.status === 404 ? "Project not found" : "Forbidden",
  }
}

async function fulfillRecorded(
  route: Route,
  record: ExecutionRecord,
  body: unknown,
  status: number
): Promise<void> {
  record.status = status
  try {
    await json(route, body, status)
    record.outcome = "fulfilled"
  } catch {
    record.outcome = "aborted"
  }
}

// ---------------------------------------------------------------------------
// Seven-provider fanout trace stub (Activity redesign acceptance, PLAN §6.2).
//
// Deterministic E2E-only fixture for the RED suite in
// `tests/features/activity-traces.feature`. Production fixtures in
// `src/test/fixtures/activity.ts` are intentionally untouched: this trace
// lives here so the new acceptance scenarios run against span-level provider
// identity (`span.provider`, lowercase ids) without changing any prod shape.
//
// - Seven `freesearch.provider` spans carry `provider` for
//   brave/keenable/tavily/exa/firecrawl/youcom/parallel, in wire order.
// - The `parallel` attempt FAILS (HTTP 502, zero results) but still records
//   its name, proving identity comes from the span field and not from
//   result-source inference (which has nothing to infer from).
// - Six fused output results carry scores; the Keenable result carries the
//   seeded long snippet used by the side-inspector scenarios.
// ---------------------------------------------------------------------------

/** Trace id of the seven-provider fanout stub (32-char lowercase hex). */
export const SEVEN_PROVIDER_TRACE_ID = "f7a1c2d3e4f5061728394a5b6c7d8e90"

/** Provider span identities, lowercase, in wire order. */
export const SEVEN_PROVIDER_IDS = [
  "brave",
  "keenable",
  "tavily",
  "exa",
  "firecrawl",
  "youcom",
  "parallel",
] as const

export type SevenProviderId = (typeof SEVEN_PROVIDER_IDS)[number]

/** Query recorded on the seven-provider trace (list rows must never show it). */
export const SEVEN_PROVIDER_QUERY = "seven-provider fanout acceptance probe"

/**
 * Seeded oversized snippet on the Keenable fused result. Compact result rows
 * must NOT render it; the side inspector shows it after selection.
 */
export const SEVEN_PROVIDER_LONG_SNIPPET =
  "Keenable recorded the full acceptance evidence for this seven-provider fanout probe. " +
  "This seeded long snippet must never render inside the compact result rows: it belongs " +
  "only in the side inspector after its result is selected. Repeating the core claim once " +
  "more for length, the compact list stays scannable while oversized payloads wait behind " +
  "an explicit selection in the side inspector."

const SEVEN_STARTED_AT_MS = Date.parse("2026-09-29T09:05:00.000Z")
/** Trace window of the seven-provider fanout stub (also the trajectory axis). */
export const SEVEN_TOTAL_MS = 4520

function sevenTs(offsetMs: number): string {
  return new Date(SEVEN_STARTED_AT_MS + offsetMs).toISOString()
}

/** Display label the UI derives per provider id (mirrors traceProviderLabel). */
export function sevenProviderLabel(provider: SevenProviderId): string {
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

/** Nested-row latency per provider span (deterministic, distinct). */
export const SEVEN_PROVIDER_DURATIONS: Record<SevenProviderId, number> = {
  brave: 412,
  keenable: 2025,
  tavily: 3223,
  exa: 618,
  firecrawl: 940,
  youcom: 755,
  parallel: 410,
}

export const SEVEN_PROVIDER_OFFSETS: Record<SevenProviderId, number> = {
  brave: 20,
  keenable: 30,
  tavily: 46,
  exa: 60,
  firecrawl: 74,
  youcom: 88,
  parallel: 100,
}

const SEVEN_PROVIDER_SCORES: Record<Exclude<SevenProviderId, "parallel">, number> = {
  brave: 0.55,
  keenable: 0.92,
  tavily: 0.71,
  exa: 0.63,
  firecrawl: 0.58,
  youcom: 0.49,
}

/**
 * Recorded trajectory geometry of the seven-provider stub in visible-row
 * order (total, backend, providers by offset, results assembly, response).
 * Steps compare each rendered bar against offset/total and duration/total.
 */
export interface StubStageGeometry {
  offsetMs: number
  durationMs: number
}

export const SEVEN_STAGE_GEOMETRY: StubStageGeometry[] = [
  { offsetMs: 0, durationMs: SEVEN_TOTAL_MS },
  { offsetMs: 4, durationMs: 4508 },
  ...SEVEN_PROVIDER_IDS.map((id) => ({
    offsetMs: SEVEN_PROVIDER_OFFSETS[id],
    durationMs: SEVEN_PROVIDER_DURATIONS[id],
  })),
  { offsetMs: 4400, durationMs: 8 },
  { offsetMs: 4512, durationMs: 8 },
]

export interface SevenProviderResultPayload {
  title: string
  url: string
  snippet: string
  source: SevenProviderId
  score: number
}

/** The single recorded result for one successful provider (fused + attempt). */
export function sevenProviderResult(provider: Exclude<SevenProviderId, "parallel">): SevenProviderResultPayload {
  return {
    title: `${sevenProviderLabel(provider)} acceptance result`,
    url: `https://e2e.freesearch.dev/seven/${provider}`,
    snippet:
      provider === "keenable"
        ? SEVEN_PROVIDER_LONG_SNIPPET
        : `${sevenProviderLabel(provider)} returned one recorded result for the acceptance probe.`,
    source: provider,
    score: SEVEN_PROVIDER_SCORES[provider],
  }
}

function sevenProviderSpan(provider: SevenProviderId, index: number): Record<string, unknown> {
  const offset = SEVEN_PROVIDER_OFFSETS[provider]
  const duration = SEVEN_PROVIDER_DURATIONS[provider]
  const failed = provider === "parallel"
  return {
    span_id: `b70000000000001${index}`,
    parent_span_id: "b700000000000001",
    name: "freesearch.provider",
    stage: "Provider request",
    kind: "client",
    started_at: sevenTs(offset),
    ended_at: sevenTs(offset + duration),
    duration_ms: duration,
    outcome: failed ? "error" : "success",
    error: failed ? { type: "http_error", message: "HTTP 502" } : null,
    // Span-level identity: the new contract. The failed attempt records its
    // name here while carrying zero results, so result-source inference
    // cannot name it.
    provider,
    events: failed
      ? [
          {
            name: "freesearch.provider.request",
            timestamp: sevenTs(offset),
            attributes: { query: SEVEN_PROVIDER_QUERY, limit: 6 },
          },
        ]
      : [
          {
            name: "freesearch.provider.request",
            timestamp: sevenTs(offset),
            attributes: { query: SEVEN_PROVIDER_QUERY, limit: 6 },
          },
          {
            name: "freesearch.provider.response",
            timestamp: sevenTs(offset + duration),
            attributes: { result_count: 1, results: [sevenProviderResult(provider)] },
          },
        ],
  }
}

/** `GET /api/v1/traces` summary row for the seven-provider fanout. */
export function sevenProviderTraceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: SEVEN_PROVIDER_TRACE_ID,
    operation: "search",
    started_at: new Date(SEVEN_STARTED_AT_MS).toISOString(),
    duration_ms: SEVEN_TOTAL_MS,
    provider: "aggregated",
    outcome: "success",
    result_count: 6,
    error: null,
    ...overrides,
  }
}

/** `GET /api/v1/traces/{seven}` detail: fused output + seven named spans. */
export function sevenProviderTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  const successful = SEVEN_PROVIDER_IDS.filter((id) => id !== "parallel") as Exclude<
    SevenProviderId,
    "parallel"
  >[]
  return {
    ...sevenProviderTraceSummaryFixture(),
    input: SEVEN_PROVIDER_QUERY,
    output: {
      kind: "search_results",
      query: SEVEN_PROVIDER_QUERY,
      results: successful.map((id) => sevenProviderResult(id)),
    },
    spans: [
      {
        span_id: "b700000000000000",
        parent_span_id: null,
        name: "POST /search",
        stage: "Search request",
        kind: "server",
        started_at: sevenTs(0),
        ended_at: sevenTs(SEVEN_TOTAL_MS),
        duration_ms: SEVEN_TOTAL_MS,
        outcome: "success",
        error: null,
        provider: null,
        events: [],
      },
      {
        span_id: "b700000000000001",
        parent_span_id: "b700000000000000",
        name: "freesearch.backend",
        stage: "Backend handling",
        kind: "internal",
        started_at: sevenTs(4),
        ended_at: sevenTs(4512),
        duration_ms: 4508,
        outcome: "success",
        error: null,
        provider: null,
        events: [],
      },
      ...SEVEN_PROVIDER_IDS.map((id, index) => sevenProviderSpan(id, index)),
      {
        span_id: "b700000000000020",
        parent_span_id: "b700000000000001",
        name: "freesearch.results",
        stage: "Results assembly",
        kind: "internal",
        started_at: sevenTs(4400),
        ended_at: sevenTs(4408),
        duration_ms: 8,
        outcome: "success",
        error: null,
        provider: null,
        events: [],
      },
      {
        span_id: "b700000000000021",
        parent_span_id: "b700000000000000",
        name: "freesearch.response",
        stage: "Response to caller",
        kind: "internal",
        started_at: sevenTs(4512),
        ended_at: sevenTs(SEVEN_TOTAL_MS),
        duration_ms: 8,
        outcome: "success",
        error: null,
        provider: null,
        events: [],
      },
    ],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Current-data fixtures (Activity Trace Detail UI, Tester Turn 1).
//
// Two appended list rows (after the four existing rows, so row 1 stays the
// seven-provider trace and rows 3/4 stay the single/error traces):
// - a single-provider Exa search whose one result records a null source and
//   a null score with a long snippet (attribution must come from the span and
//   the trace provider, never from "Source not recorded");
// - an all-providers fusion search with a comma-separated contributor source
//   and a long snippet, plus wire-only child spans (HTTP, parse) and one
//   function-level span that the trajectory must hide from its rows.
// ---------------------------------------------------------------------------

/** Trace id of the single-provider null-source stub (32-char lowercase hex). */
export const NULL_SOURCE_TRACE_ID = "c9d1e2f3a4b5061728394a5b6c7d8e91"

/** Query recorded on the null-source trace (list rows must never show it). */
export const NULL_SOURCE_QUERY = "null-source single-provider acceptance probe"

/** Title of the one null-source result. */
export const NULL_SOURCE_RESULT_TITLE = "Exa null-source acceptance result"

/** URL of the one null-source result. */
export const NULL_SOURCE_RESULT_URL = "https://e2e.freesearch.dev/null-source/exa"

/**
 * Seeded long snippet on the null-source result. The shared card clamps it to
 * two lines; the side inspector shows it in full inside its own scroll region.
 */
export const NULL_SOURCE_LONG_SNIPPET =
  "Exa returned this recorded result without a source label or a vendor score, and the " +
  "trace still attributes it to Exa through the provider span and the trace provider. " +
  "This seeded long snippet proves the inspector keeps its recorded metadata above a " +
  "long summary: rank, provider badge, score, and target host stay visible while the " +
  "full snippet waits in its own bounded scroll region below the metadata."

const NULL_SOURCE_STARTED_AT_MS = Date.parse("2026-09-30T08:00:00.000Z")
const NULL_SOURCE_TOTAL_MS = 2400

function nullSourceTs(offsetMs: number): string {
  return new Date(NULL_SOURCE_STARTED_AT_MS + offsetMs).toISOString()
}

function nullSourceSpan(
  spanId: string,
  parentSpanId: string | null,
  name: string,
  stage: string,
  offsetMs: number,
  durationMs: number,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    span_id: spanId,
    parent_span_id: parentSpanId,
    name,
    stage,
    kind: "server",
    started_at: nullSourceTs(offsetMs),
    ended_at: nullSourceTs(offsetMs + durationMs),
    duration_ms: durationMs,
    outcome: "success",
    error: null,
    provider: null,
    events: [],
    ...extra,
  }
}

/** `GET /api/v1/traces` summary row for the null-source single-provider trace. */
export function nullSourceTraceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: NULL_SOURCE_TRACE_ID,
    operation: "search",
    started_at: new Date(NULL_SOURCE_STARTED_AT_MS).toISOString(),
    duration_ms: NULL_SOURCE_TOTAL_MS,
    provider: "exa",
    outcome: "success",
    result_count: 1,
    error: null,
    ...overrides,
  }
}

/** `GET /api/v1/traces/{null-source}` detail: one null result, hidden children. */
export function nullSourceTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  const result = {
    title: NULL_SOURCE_RESULT_TITLE,
    url: NULL_SOURCE_RESULT_URL,
    snippet: NULL_SOURCE_LONG_SNIPPET,
    source: null,
    score: null,
  }
  return {
    ...nullSourceTraceSummaryFixture(),
    input: NULL_SOURCE_QUERY,
    output: {
      kind: "search_results",
      query: NULL_SOURCE_QUERY,
      results: [result],
    },
    spans: [
      nullSourceSpan("c900000000000000", null, "POST /search", "Search request", 0, 2400),
      nullSourceSpan(
        "c900000000000001",
        "c900000000000000",
        "freesearch.route",
        "Route selection",
        2,
        120
      ),
      nullSourceSpan(
        "c900000000000002",
        "c900000000000000",
        "freesearch.backend",
        "Backend handling",
        4,
        2392
      ),
      {
        ...nullSourceSpan(
          "c900000000000003",
          "c900000000000002",
          "freesearch.provider",
          "Provider request",
          130,
          2100,
          { kind: "client", provider: "exa" }
        ),
        events: [
          {
            name: "freesearch.provider.request",
            timestamp: nullSourceTs(130),
            attributes: { query: NULL_SOURCE_QUERY, limit: 6 },
          },
          {
            name: "freesearch.provider.response",
            timestamp: nullSourceTs(2230),
            attributes: { result_count: 1, results: [result] },
          },
        ],
      },
      // Wire-only children: decoded data keeps them, visible rows must not.
      nullSourceSpan(
        "c900000000000004",
        "c900000000000003",
        "freesearch.provider.http",
        "Provider HTTP call",
        132,
        2090,
        { kind: "client" }
      ),
      nullSourceSpan(
        "c900000000000005",
        "c900000000000003",
        "freesearch.provider.parse",
        "Provider response parse",
        2222,
        4,
        { kind: "internal" }
      ),
      nullSourceSpan(
        "c900000000000006",
        "c900000000000002",
        "freesearch.results",
        "Results assembly",
        2390,
        4,
        { kind: "internal" }
      ),
      nullSourceSpan(
        "c900000000000007",
        "c900000000000000",
        "freesearch.response",
        "Response to caller",
        2394,
        6,
        { kind: "internal" }
      ),
    ],
    ...overrides,
  }
}

/** Trace id of the fusion long-snippet stub (32-char lowercase hex). */
export const FUSION_LONG_TRACE_ID = "d1e2f3a4b5c61728394a5b6c7d8e90f1"

/** Query recorded on the fusion long-snippet trace. */
export const FUSION_LONG_QUERY = "fusion long-snippet acceptance probe"

/** Title of the multi-contributor fusion result. */
export const FUSION_LONG_RESULT_TITLE = "Fusion multi-engine acceptance result"

/** Title of the single-contributor fusion result. */
export const FUSION_SINGLE_RESULT_TITLE = "Fusion single-engine acceptance result"

/**
 * Seeded long snippet on the multi-contributor fusion result: top metadata
 * first, full text in its own scroll region.
 */
export const FUSION_LONG_SNIPPET =
  "Brave and Keenable both returned this recorded fusion result, and the fusion " +
  "projection stored their contributor ids as one comma-separated source text. " +
  "This seeded long snippet proves the fusion inspector keeps its recorded metadata " +
  "above a long summary: rank, both contributor badges, fusion score, and target host " +
  "stay visible while the full snippet waits in its own bounded scroll region below " +
  "the metadata. Selecting another result replaces these badges instead of repeating " +
  "every trace participant."

const FUSION_LONG_STARTED_AT_MS = Date.parse("2026-09-30T08:10:00.000Z")
const FUSION_LONG_TOTAL_MS = 3800

function fusionLongTs(offsetMs: number): string {
  return new Date(FUSION_LONG_STARTED_AT_MS + offsetMs).toISOString()
}

function fusionLongSpan(
  spanId: string,
  parentSpanId: string | null,
  name: string,
  stage: string,
  offsetMs: number,
  durationMs: number,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    span_id: spanId,
    parent_span_id: parentSpanId,
    name,
    stage,
    kind: "internal",
    started_at: fusionLongTs(offsetMs),
    ended_at: fusionLongTs(offsetMs + durationMs),
    duration_ms: durationMs,
    outcome: "success",
    error: null,
    provider: null,
    events: [],
    ...extra,
  }
}

function fusionLongProviderSpan(
  spanId: string,
  provider: string,
  offsetMs: number,
  durationMs: number,
  result: Record<string, unknown>
): Record<string, unknown> {
  return {
    ...fusionLongSpan(
      spanId,
      "d100000000000002",
      "freesearch.provider",
      "Provider request",
      offsetMs,
      durationMs,
      { kind: "client", provider }
    ),
    events: [
      {
        name: "freesearch.provider.request",
        timestamp: fusionLongTs(offsetMs),
        attributes: { query: FUSION_LONG_QUERY, limit: 6 },
      },
      {
        name: "freesearch.provider.response",
        timestamp: fusionLongTs(offsetMs + durationMs),
        attributes: { result_count: 1, results: [result] },
      },
    ],
  }
}

/** `GET /api/v1/traces` summary row for the fusion long-snippet trace. */
export function fusionLongTraceSummaryFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    trace_id: FUSION_LONG_TRACE_ID,
    operation: "search",
    started_at: new Date(FUSION_LONG_STARTED_AT_MS).toISOString(),
    duration_ms: FUSION_LONG_TOTAL_MS,
    provider: "aggregated",
    outcome: "success",
    result_count: 2,
    error: null,
    ...overrides,
  }
}

/** `GET /api/v1/traces/{fusion-long}` detail: fused output + hidden children. */
export function fusionLongTraceDetailFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  const multi = {
    title: FUSION_LONG_RESULT_TITLE,
    url: "https://e2e.freesearch.dev/fusion/long",
    snippet: FUSION_LONG_SNIPPET,
    source: "brave, keenable, brave",
    score: 0.87,
  }
  const single = {
    title: FUSION_SINGLE_RESULT_TITLE,
    url: "https://e2e.freesearch.dev/fusion/tavily",
    snippet: "Tavily returned one recorded result for the fusion probe.",
    source: "tavily",
    score: 0.62,
  }
  return {
    ...fusionLongTraceSummaryFixture(),
    input: FUSION_LONG_QUERY,
    output: {
      kind: "search_results",
      query: FUSION_LONG_QUERY,
      results: [multi, single],
    },
    spans: [
      fusionLongSpan("d100000000000000", null, "POST /search", "Search request", 0, 3800, {
        kind: "server",
      }),
      fusionLongSpan(
        "d100000000000001",
        "d100000000000000",
        "freesearch.route",
        "Route selection",
        2,
        88
      ),
      fusionLongSpan(
        "d100000000000002",
        "d100000000000000",
        "freesearch.backend",
        "Backend handling",
        4,
        3788
      ),
      fusionLongProviderSpan("d100000000000003", "brave", 100, 900, {
        title: "Brave fusion acceptance result",
        url: "https://e2e.freesearch.dev/fusion/brave",
        snippet: "Brave returned one recorded result for the fusion probe.",
        source: "brave",
        score: 0.81,
      }),
      // Wire-only transport child of the Brave attempt: never a visible row.
      fusionLongSpan(
        "d100000000000004",
        "d100000000000003",
        "freesearch.provider.http",
        "Provider HTTP call",
        102,
        888,
        { kind: "client" }
      ),
      fusionLongProviderSpan("d100000000000005", "keenable", 200, 1500, {
        title: "Keenable fusion acceptance result",
        url: "https://e2e.freesearch.dev/fusion/keenable",
        snippet: "Keenable returned one recorded result for the fusion probe.",
        source: "keenable",
        score: 0.9,
      }),
      // Wire-only parse child of the Keenable attempt: never a visible row.
      fusionLongSpan(
        "d100000000000006",
        "d100000000000005",
        "freesearch.provider.parse",
        "Provider response parse",
        1690,
        6
      ),
      fusionLongProviderSpan("d100000000000007", "tavily", 300, 700, {
        title: "Tavily fusion acceptance result",
        url: "https://e2e.freesearch.dev/fusion/tavily",
        snippet: "Tavily returned one recorded result for the fusion probe.",
        source: "tavily",
        score: 0.74,
      }),
      // Function-level span: recorded data keeps it, visible rows must not.
      fusionLongSpan("d100000000000008", "d100000000000002", "freesearch.rank", "Rank fusion", 3710, 4),
      fusionLongSpan(
        "d100000000000009",
        "d100000000000002",
        "freesearch.results",
        "Results assembly",
        3720,
        8
      ),
      fusionLongSpan(
        "d10000000000000a",
        "d100000000000000",
        "freesearch.response",
        "Response to caller",
        3792,
        8
      ),
    ],
    ...overrides,
  }
}

/** Fail the next trace list reads with a 500, or clear the failure. */
export function failStubbedTraceList(message: string | null): void {
  stubbedTraceListFailure = message
}

/** Fail one trace detail read with a 500, or clear the failure. */
export function failStubbedTraceDetail(traceId: string, message: string | null): void {
  if (message === null) delete stubbedTraceDetailFailures[traceId]
  else stubbedTraceDetailFailures[traceId] = message
}

export function setDashboardQuotaOverride(latestQuota: unknown[]): void {
  dashboardQuotaOverride = [...latestQuota]
}

const SECRET_PRESENCE: Record<string, SecretPresence> = {
  brave: "configured",
  keenable: "keyless_public",
  tavily: "configured",
  exa: "configured",
  firecrawl: "configured",
  you: "missing",
  parallel: "missing",
  tinyfish: "configured",
}

const PROVIDER_ORDER = ["brave", "keenable", "tavily", "exa", "firecrawl", "you", "parallel", "tinyfish"]

/** Global registry row as the project provider view needs it. */
export interface StubRegistryRow {
  provider_id: string
  enable_mask: number
  support_mask: number
  priority: number
  secret_presence: SecretPresence
}

let currentProviderRows: () => StubRegistryRow[] = () => initialProviders()

/** Current in-memory global provider registry of the scenario. */
export function stubbedProviderRows(): StubRegistryRow[] {
  return currentProviderRows()
}

const SUPPORT_MASKS: Record<string, number> = {
  brave: 3,
  keenable: 7,
  tavily: 7,
  exa: 7,
  firecrawl: 7,
  you: 7,
  parallel: 7,
  tinyfish: 7,
}

function initialProviders(): StubProvider[] {
  return PROVIDER_ORDER.map((id, index) => {
    const supportMask = SUPPORT_MASKS[id] ?? 7
    const enableMask = 7
    return {
      provider_id: id,
      enabled: (enableMask & supportMask & 1) !== 0,
      enable_mask: enableMask,
      support_mask: supportMask,
      priority: index + 1,
      health: "healthy",
      health_checked_at: null,
      circuit_breaker: { state: "closed", updated_at: FIXED_AT },
      latency_p95_ms: 110 + index * 10,
      secret_presence: stubbedSecretPresence[id] ?? SECRET_PRESENCE[id] ?? "missing",
      free_tier_estimates: { search: "0", fetch: "0", cost_estimate: "0" },
      reset_schedule: null,
      tavily_key_environment: id === "tavily" ? stubbedTavilyKeyEnvironment : null,
    }
  })
}

function dashboardFixture(): Record<string, unknown> {
  return {
    notice: "Usage, quota, and health shown here are local-observed only.",
    usage_totals: [{ provider: "brave", operation: "search", total_units: "14", event_count: 14 }],
    recent_usage: [
      {
        provider: "brave",
        operation: "search",
        units: "1",
        observed_at: "2026-09-06T10:00:00Z",
        latency_ms: 230,
        status: "success",
      },
      {
        provider: "keenable",
        operation: "fetch",
        units: "0.001",
        observed_at: "2026-09-06T09:55:00Z",
        latency_ms: null,
        status: "failure",
      },
    ],
    latest_quota: [],
    latest_health: [{ provider: "brave", status: "healthy", checked_at: FIXED_AT }],
    generated_at: FIXED_AT,
    provider_limits: stubbedProviderLimits ?? [],
    spend_totals: stubbedUsdTotals ?? [],
  }
}

function dashboardWithQuotaOverride(): Record<string, unknown> {
  const base = dashboardFixture()
  if (dashboardQuotaOverride !== null) base.latest_quota = [...dashboardQuotaOverride]
  return base
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

function readJsonBody(route: Route): Record<string, unknown> {
  try {
    return JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>
  } catch {
    return {}
  }
}

/**
 * Register deterministic stub routes on `page`. Call from a `Before` hook
 * (before navigation) so every backend fetch in the scenario is served from
 * the fixed fixtures. State is per-call, hence per-scenario isolation.
 */
export async function installBackendStub(page: Page): Promise<void> {
  // Hygiene: manual overlays are module-level and must not leak across
  // scenarios (e.g. Brave overlay into later quota rows).
  for (const key of Object.keys(stubbedManualQuotas)) delete stubbedManualQuotas[key]
  dashboardQuotaOverride = null
  stubbedProviderLimits = null
  stubbedUsdTotals = null
  for (const key of Object.keys(stubbedHistory)) delete stubbedHistory[key]
  stubbedGrantRequests.length = 0
  stubbedGrantMode = "ok"
  stubbedSyncRequests.length = 0
  for (const key of Object.keys(stubbedProviderPatchFailures)) {
    delete stubbedProviderPatchFailures[key]
  }
  for (const key of Object.keys(stubbedProviderPatchDelays)) {
    delete stubbedProviderPatchDelays[key]
  }
  stubbedTraceListRequests.length = 0
  stubbedTraceListFailure = null
  stubbedTraceDetailRequests.length = 0
  for (const key of Object.keys(stubbedTraceDetailFailures)) {
    delete stubbedTraceDetailFailures[key]
  }
  stubbedProviderPatches.length = 0
  stubbedTestRequests.length = 0
  stubbedUsageRequests.length = 0
  stubbedProvidersGetFailure = null
  stubbedDashboardGetFailure = null
  stubbedDashboardGetDelayMs = null
  stubbedTavilyPatchReadback = { armed: false, value: undefined }
  stubbedTavilyKeyEnvironment = "dev"
  for (const key of Object.keys(stubbedSecretPresence)) delete stubbedSecretPresence[key]
  legacyTraceCalls.length = 0
  let providers = initialProviders()
  // The project provider view (projectStub.ts) reads the live in-memory
  // registry, so a Settings PATCH shows up in every project's picker.
  currentProviderRows = () =>
    providers.map((row) => ({
      ...row,
      ...(stubbedSecretPresence[row.provider_id] !== undefined
        ? { secret_presence: stubbedSecretPresence[row.provider_id] }
        : {}),
    }))
  // Manual billing entries: GET 404s while unconfigured, PUT stores the window,
  // DELETE clears it again. Writes persist per scenario via stubbedManualQuotas.
  await page.route("**/api/v1/providers/*/manual-quota", (route) => {
    const method = route.request().method()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 2] || ""
    if (method === "GET") {
      const entry = stubbedManualQuotas[backendId]
      if (!entry) return json(route, { detail: "no manual quota for " + backendId }, 404)
      return json(route, entry)
    }
    if (method === "PUT") {
      const body = readJsonBody(route)
      const stored: Record<string, unknown> = { provider: backendId }
      for (const key of Object.keys(body)) stored[key] = body[key]
      stubbedManualQuotas[backendId] = stored
      return json(route, stored)
    }
    if (method === "DELETE") {
      delete stubbedManualQuotas[backendId]
      return json(route, { provider: backendId, deleted: true })
    }
    return route.fallback()
  })

  await page.route("**/api/v1/providers/*/test", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 2] ?? "brave"
    stubbedTestRequests.push(backendId)
    return json(route, {
      provider: backendId,
      ok: true,
      status: "healthy",
      latency_ms: 142,
      checked_at: FIXED_AT,
      detail: null,
    })
  })

  await page.route("**/api/v1/providers/*/usage", (route) => {
    stubbedUsageRequests.push(new URL(route.request().url()).pathname)
    return json(route, { detail: "usage reads are not part of the rate-tier contract" }, 404)
  })

  await page.route("**/api/v1/providers/*/circuit-breaker/reset", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 3] ?? "brave"
    return json(route, { provider: backendId, state: "closed", updated_at: FIXED_AT })
  })

  // Provider PATCH (masks + priority): in-memory update only. Models both
  // masks with canonical seeds (Brave 7/3, others 7/7) and one-bit partial
  // updates. Never accepts support_mask from admin: the field is ignored.
  await page.route("**/api/v1/providers/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback()
    const backendId = new URL(route.request().url()).pathname.split("/").pop() ?? ""
    const failure = stubbedProviderPatchFailures[backendId]
    if (failure !== undefined) return json(route, { detail: failure }, 500)
    const delayMs = stubbedProviderPatchDelays[backendId]
    if (typeof delayMs === "number" && delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
    const patch = readJsonBody(route)
    const current = providers.find((row) => row.provider_id === backendId)
    if (!current) return json(route, { detail: "Unknown provider" }, 404)
    let enableMask = current.enable_mask
    const hasEnableMask = patch.enable_mask !== undefined
    const hasBooleanAccess =
      patch.enabled !== undefined ||
      patch.search_enabled !== undefined ||
      patch.fetch_enabled !== undefined
    if (hasEnableMask && hasBooleanAccess) {
      return json(route, { detail: "enable_mask cannot combine with boolean access fields" }, 422)
    }
    if (hasEnableMask) {
      if (
        typeof patch.enable_mask !== "number" ||
        !Number.isInteger(patch.enable_mask) ||
        patch.enable_mask < 0 ||
        patch.enable_mask > 7
      ) {
        return json(route, { detail: "enable_mask must be an integer 0..7" }, 422)
      }
      enableMask = patch.enable_mask as number
    } else {
      if (patch.enabled !== undefined) {
        if (typeof patch.enabled !== "boolean") {
          return json(route, { detail: "enabled must be a boolean" }, 422)
        }
        enableMask =
          (patch.enabled as boolean) ? enableMask | 1 : enableMask & ~1
      }
      if (patch.search_enabled !== undefined) {
        if (typeof patch.search_enabled !== "boolean") {
          return json(route, { detail: "search_enabled must be a boolean" }, 422)
        }
        enableMask =
          (patch.search_enabled as boolean) ? enableMask | 2 : enableMask & ~2
      }
      if (patch.fetch_enabled !== undefined) {
        if (typeof patch.fetch_enabled !== "boolean") {
          return json(route, { detail: "fetch_enabled must be a boolean" }, 422)
        }
        enableMask =
          (patch.fetch_enabled as boolean) ? enableMask | 4 : enableMask & ~4
      }
    }
    if (patch.tavily_key_environment !== undefined) {
      if (backendId !== "tavily") {
        return json(route, { detail: "tavily_key_environment applies to Tavily only" }, 422)
      }
      if (patch.tavily_key_environment !== "dev" && patch.tavily_key_environment !== "prod") {
        return json(route, { detail: "tavily_key_environment must be dev or prod" }, 422)
      }
    }
    const next: StubProvider = {
      ...current,
      enable_mask: enableMask,
      support_mask: current.support_mask,
      enabled: (enableMask & current.support_mask & 1) !== 0,
      priority: typeof patch.priority === "number" ? (patch.priority as number) : current.priority,
      tavily_key_environment:
        patch.tavily_key_environment === "dev" || patch.tavily_key_environment === "prod"
          ? (patch.tavily_key_environment as "dev" | "prod")
          : current.tavily_key_environment,
    }
    const tavilyRawReadback = backendId === "tavily" && stubbedTavilyPatchReadback.armed
      ? stubbedTavilyPatchReadback.value
      : undefined
    const tavilyReadbackOverridden = backendId === "tavily" && stubbedTavilyPatchReadback.armed
    if (tavilyReadbackOverridden) stubbedTavilyPatchReadback = { armed: false, value: undefined }
    if (!tavilyReadbackOverridden && next.provider_id === "tavily" && (next.tavily_key_environment === "dev" || next.tavily_key_environment === "prod")) {
      stubbedTavilyKeyEnvironment = next.tavily_key_environment
    }
    stubbedProviderPatches.push({ backendId, body: { ...patch } })
    providers = providers.map((row) => (row.provider_id === backendId ? next : row))
    if (tavilyReadbackOverridden) {
      if (tavilyRawReadback === undefined) {
        const { tavily_key_environment: _dropped, ...withoutReadback } = next
        void _dropped
        return json(route, withoutReadback)
      }
      return json(route, { ...next, tavily_key_environment: tavilyRawReadback })
    }
    return json(route, next)
  })

  await page.route("**/api/v1/providers", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    if (stubbedProvidersGetFailure !== null) {
      return json(route, { detail: stubbedProvidersGetFailure }, 500)
    }
    return json(route, providers.map((row) => ({
      ...row,
      ...(stubbedSecretPresence[row.provider_id] !== undefined
        ? { secret_presence: stubbedSecretPresence[row.provider_id] }
        : {}),
      ...(row.provider_id === "tavily"
        ? { tavily_key_environment: stubbedTavilyKeyEnvironment }
        : {}),
    })))
  })

  // Pathname-exact dashboard matcher: the legacy "**/dashboard*" glob also
  // matched the Vite module URL /src/app/selectors/dashboardOverlay.ts (new
  // in Slice 6), fulfilling a JS import with JSON and blanking the app.
  await page.route((url) => url.pathname === "/dashboard", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    if (stubbedDashboardGetFailure !== null) {
      return json(route, { detail: stubbedDashboardGetFailure }, 500)
    }
    const dashboardDelayMs: number | null = stubbedDashboardGetDelayMs
    if (dashboardDelayMs !== null && dashboardDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, dashboardDelayMs))
    }
    return json(route, dashboardWithQuotaOverride())
  })

  // UI7 grant route: PUT /api/v1/providers/{id}/budgets/{auth}.
  await page.route("**/api/v1/providers/*/budgets/*", (route) => {
    if (route.request().method() !== "PUT") return route.fallback()
    const body = readJsonBody(route)
    stubbedGrantRequests.push(body)
    if (stubbedGrantMode === "conflict") {
      return json(route, { detail: "stale version" }, 409)
    }
    return json(route, { ok: true })
  })

  // UI7 history route: GET /api/v1/providers/{id}/limits/history.
  await page.route("**/api/v1/providers/*/limits/history*", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    const entry = stubbedHistory[backendId]
    if (entry === undefined) return json(route, { events: [], next_cursor: null })
    if (entry.error !== null) return json(route, { detail: entry.error }, 500)
    return json(route, { events: entry.events, next_cursor: entry.nextCursor })
  })

  // UI7 sync route: POST /api/v1/providers/{id}/limits/sync.
  await page.route("**/api/v1/providers/*/limits/sync", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    stubbedSyncRequests.push(backendId)
    return json(route, {
      provider: backendId,
      status: "synced",
      observed_at: FIXED_AT,
      next_sync_at: null,
      error_code: null,
      stale: false,
      changed: true,
      reason: "stubbed sync",
    })
  })

  // Deterministic search: echoes the pinned provider from routing.providers
  // and serves a fixed two-result payload (with scores so "% match" renders).
  // The search body must name a project the session can use (project gate).
  // An isolation query returns results named after that project, so a
  // scenario can tell which project's answer rendered.
  await page.route("**/search", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const record: ExecutionRecord = {
      operation: "search",
      body,
      headers: await route.request().allHeaders(),
      status: null,
      outcome: "pending",
    }
    executionRecords.push(record)
    const gate = gateExecution(body, "search.execute")
    if (!gate.ok) return fulfillRecorded(route, record, { detail: gate.detail }, gate.status)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "brave"
    const query = typeof body.query === "string" ? (body.query as string) : "stubbed query"
    if (heldSearch.query === null || (heldSearch.query !== undefined && heldSearch.query === query)) {
      await new Promise<void>((resolve) => heldSearch.waiters.push(resolve))
    }
    if (query === TAVILY_402_QUERY) {
      return fulfillRecorded(route, record, { detail: TAVILY_402_MESSAGE, provider: "tavily" }, 402)
    }
    if (query === "doomed query") {
      return fulfillRecorded(route, record, { detail: "stubbed provider unavailable" }, 503)
    }
    const response = canonicalSearchFixture({ query, provider: pinned }) as {
      results: Record<string, unknown>[]
    }
    if (query.includes(ISOLATION_QUERY_MARKER)) {
      const title = isolationResultTitle(gate.projectName)
      response.results = response.results.map((result, index) => ({
        ...result,
        title: index === 0 ? title : `${title} ${index + 1}`,
        url: `https://${gate.projectName.toLowerCase()}.example.com/isolation/${index + 1}`,
      }))
    }
    return fulfillRecorded(route, record, response, 200)
  })

  // Deterministic fetch: echoes the pinned provider and target URL with
  // non-empty markdown content, behind the same project gate.
  await page.route("**/fetch", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const record: ExecutionRecord = {
      operation: "fetch",
      body,
      headers: await route.request().allHeaders(),
      status: null,
      outcome: "pending",
    }
    executionRecords.push(record)
    const gate = gateExecution(body, "fetch.execute")
    if (!gate.ok) return fulfillRecorded(route, record, { detail: gate.detail }, gate.status)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "keenable"
    const url = typeof body.url === "string" ? (body.url as string) : "https://example.com"
    if (url === TAVILY_402_URL) {
      return fulfillRecorded(route, record, { detail: TAVILY_402_MESSAGE, provider: "tavily" }, 402)
    }
    const base = canonicalFetchFixture() as {
      provider: string
      document: Record<string, unknown>
      usage: Record<string, unknown>
    }
    return fulfillRecorded(
      route,
      record,
      {
        ...base,
        provider: pinned,
        document: { ...base.document, url },
        usage: { ...(base.usage as Record<string, unknown>), provider: pinned },
      },
      200
    )
  })

  // The global trace read is gone (TASK-000044): Activity reads the project
  // routes served by projectStub.ts. A call here is logged and 404s like the
  // backend, so a UI still on the old path fails visibly.
  await page.route(
    (url) => url.pathname === "/api/v1/traces" || url.pathname.startsWith("/api/v1/traces/"),
    (route) => {
      legacyTraceCalls.push(new URL(route.request().url()).pathname)
      return json(route, { detail: "Not Found" }, 404)
    }
  )

  // Default browser session: a role-less system administrator account (the
  // backend account has no role; its authority is the system access below).
  // Scenario steps that need another account or an anonymous session
  // register their own handlers later, which take precedence (or unroute
  // these by the same glob first).
  await page.route("**/auth/jwt/refresh", (route) => {
    const method = route.request().method()
    if (method === "POST") {
      return json(route, {
        access_token: "stub-access-token",
        token_type: "bearer",
        expires_in: 900,
        refresh_expires_in: 604800,
      })
    }
    if (method === "DELETE") return route.fulfill({ status: 204, body: "" })
    return route.fallback()
  })
  await page.route("**/users/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(
      route,
      userAccountBody(DEFAULT_ACCOUNT_ID, DEFAULT_ACCOUNT_EMAIL, { username: "admin" })
    )
  })
  // Projects surface. Navigation follows effective permissions, so system
  // access is always served (a failed read is an error state with Retry, not
  // a hidden UI). The default account holds no project membership: the list
  // is empty and every project resource answers the backend's uniform 404.
  // projectStub.ts overrides these routes for project scenarios.
  await page.route(
    (url) => url.pathname === "/api/v1/system/access",
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      return json(route, {
        rollout_state: "preview",
        permissions: [...stubbedSystemPermissions].sort(),
      })
    }
  )
  await page.route(
    (url) => url.pathname === "/api/v1/projects" || url.pathname.startsWith("/api/v1/projects/"),
    (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === "/api/v1/projects" && route.request().method() === "GET") {
        return json(route, [])
      }
      return json(route, { detail: "Project not found" }, 404)
    }
  )

  // Project scenarios install a bridge with project membership and ownership.
  await installVaultRoutes(page, {
    projects: () => [],
    access: () => false,
    account: () => ({ user_id: DEFAULT_ACCOUNT_ID, email: DEFAULT_ACCOUNT_EMAIL }),
    owner: () => null,
    member: () => null,
  })
}

/**
 * Override the stubbed dashboard latest_quota for quota-display scenarios.
 *
 * The base stub serves an empty latest_quota; quota scenarios replace it
 * with per-provider deterministic rows from src/test/backendFixtures. The
 * previous dashboard handler is removed first so the override wins.
 */
export async function overrideDashboardLatestQuota(
  page: Page,
  latestQuota: unknown[]
): Promise<void> {
  // Mutable per-request read (not a fixed close-over): later
  // setDashboardQuotaOverride calls — e.g. the OAuth ready/revoke
  // transitions — are visible to the SUT's post-transition refresh.
  dashboardQuotaOverride = [...latestQuota]
  // Pathname-exact dashboard matcher: the legacy "**/dashboard*" glob also
  // matched the Vite module URL /src/app/selectors/dashboardOverlay.ts,
  // fulfilling a JS import with JSON and blanking the app.
  await page.unroute((url) => url.pathname === "/dashboard")
  await page.route((url) => url.pathname === "/dashboard", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const overrideDelayMs: number | null = stubbedDashboardGetDelayMs
    if (overrideDelayMs !== null && overrideDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, overrideDelayMs))
    }
    return json(route, dashboardWithQuotaOverride())
  })
}

/** Brave OBSERVED 950/1000 requests fixture for the quota-display suite. */
export function braveObservedQuota(): unknown[] {
  return [
    {
      provider: "brave",
      source: "observed",
      observed_at: FIXED_AT,
      remaining: "950",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
  ]
}

/** Parallel seeded USD 5.00 budget fixture (3.75 remaining). */
export function parallelSeededQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "estimated",
      observed_at: FIXED_AT,
      remaining: "3.75",
      limit: "5.00",
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Parallel paired fixture: AUTHORITATIVE remaining-only USD (frozen contract). */
export function parallelPairedQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "authoritative",
      observed_at: FIXED_AT,
      remaining: "3.75",
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Parallel unseeded spend-ledger fixture (no balance to show). */
export function parallelUnseededQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "estimated",
      observed_at: FIXED_AT,
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Keenable keyless rolling-hour request headroom fixture. */
export function keenableKeylessQuota(): unknown[] {
  return [
    {
      provider: "keenable",
      source: "observed",
      observed_at: FIXED_AT,
      remaining: "999",
      remaining_percent: "99.9",
      limit: "1000",
      reset_at: null,
      unit_kind: "REQUEST",
      display_unit: "requests",
      window: "hourly",
    },
  ]
}
