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

/**
 * Deterministic in-memory backend stub for state-neutral E2E.
 *
 * `installBackendStub(page)` intercepts the app's backend traffic (which
 * otherwise flows through the Vite proxy to the LIVE backend at
 * 127.0.0.1:8001) and serves fixed fixtures instead. Writes (routing PUT,
 * provider PATCH, secret PUT/DELETE) mutate only per-scenario in-memory
 * variables, so toggle/save/delete interactions behave realistically inside
 * the scenario while the real backend is never touched.
 *
 * Fixture values mirror the live FastAPI wire contract (snake_case,
 * Decimal-as-string, ISO-8601 datetimes) and the canonical unit-test
 * fixtures in `src/test/backendFixtures.ts`:
 * - 8 canonical providers (brave, keenable, tavily, exa, firecrawl, you,
 *   parallel, tinyfish) with stable priorities 1..8, fixed p95 latencies, and
 *   catalog-faithful secret presence (you/parallel start "missing" so the
 *   key-vault save flow starts from an empty vault).
 * - Routing starts chained/balanced/3 (master failover switch ON), so the
 *   K2 keyboard-toggle sequence is deterministic.
 */

const FIXED_AT = "2026-09-06T10:05:00Z"

type SecretPresence = "configured" | "missing" | "keyless_public"

interface StubProvider {
  provider_id: string
  enabled: boolean
  priority: number
  health: "healthy"
  circuit_breaker: { state: "closed"; updated_at: string }
  latency_p95_ms: number
  secret_presence: SecretPresence
  free_tier_estimates: Record<string, string>
  reset_schedule: null
}

interface StubRouting {
  fallback_policy: "chained" | "first_only"
  cost_optimization_preset: "balanced" | "free_first"
  max_attempts: number
}

/**
 * In-memory manual billing entries for manual-quota scenarios. Mutated (never
 * reassigned) so route closures registered by installBackendStub always see
 * the current per-scenario state; writes via PUT persist for the scenario.
 */
const stubbedManualQuotas: Record<string, Record<string, unknown>> = {}

export function setStubbedManualQuota(
  provider: string,
  entry: Record<string, unknown> | null
): void {
  if (entry === null) delete stubbedManualQuotas[provider]
  else stubbedManualQuotas[provider] = entry
}

// ---------------------------------------------------------------------------
// Parallel OAuth device-flow stub (adversarial test-only, Phase 1).
//
// Per-scenario in-memory flow state for POST/GET/DELETE
// /api/v1/providers/{id}/oauth[/device-code|/status]. Unpaired by default
// (GET status 404s, mirroring the frozen getOAuthStatus 404->unpaired
// mapping); steps mutate the flow so polling picks up transitions without
// sleeps. Cleared per scenario at the top of installBackendStub.
// ---------------------------------------------------------------------------

export type StubbedOAuthStatus = "pending" | "ready" | "expired" | "denied"

interface StubbedOAuthFlow {
  hasFlow: boolean
  status: StubbedOAuthStatus
  beginFails: boolean
}

const stubbedOAuthFlows: Record<string, StubbedOAuthFlow> = {}

function oauthFlowOf(provider: string): StubbedOAuthFlow {
  return stubbedOAuthFlows[provider] ?? { hasFlow: false, status: "pending", beginFails: false }
}

function clearStubbedOAuthFlows(): void {
  for (const key of Object.keys(stubbedOAuthFlows)) delete stubbedOAuthFlows[key]
}

export function setStubbedOAuthFlow(
  provider: string,
  status: "unpaired" | StubbedOAuthStatus
): void {
  if (status === "unpaired") {
    delete stubbedOAuthFlows[provider]
    return
  }
  const current = oauthFlowOf(provider)
  stubbedOAuthFlows[provider] = { ...current, hasFlow: true, status }
}

export function failStubbedOAuthBegin(provider: string): void {
  stubbedOAuthFlows[provider] = { ...oauthFlowOf(provider), beginFails: true }
}

/**
 * Mutable dashboard latest_quota override. overrideDashboardLatestQuota
 * installs a dashboard route that reads this per request (instead of
 * closing over fixed rows), so OAuth steps can flip pairing state and the
 * SUT's post-transition dashboard refresh deterministically sees it.
 */
let dashboardQuotaOverride: unknown[] | null = null

// ---------------------------------------------------------------------------
// UI7 credit-unit stub (provider-credits.feature @ui7).
//
// Mutable per-scenario dashboard credit state plus grant/history/sync
// routes. All writes stay in memory; the live backend is never touched.
// ---------------------------------------------------------------------------

let stubbedProviderLimits: unknown[] | null = null
let stubbedCrdTotals: unknown[] | null = null

type StubbedHistoryValue = { events: unknown[]; nextCursor: string | null; error: string | null }
const stubbedHistory: Record<string, StubbedHistoryValue> = {}
const stubbedGrantRequests: Array<Record<string, unknown>> = []
let stubbedGrantMode: "ok" | "conflict" = "ok"
const stubbedSyncRequests: string[] = []

/** Serve this provider_limits array from GET /dashboard. */
export function setStubbedProviderLimits(limits: unknown[] | null): void {
  stubbedProviderLimits = limits === null ? null : [...limits]
}

/** Serve this crd_usage_totals array from GET /dashboard. */
export function setStubbedCrdTotals(totals: unknown[] | null): void {
  stubbedCrdTotals = totals === null ? null : [...totals]
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
    reference_usd_per_crd: "0.001",
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

/** Finite Brave card: USD 5 allowance, USD 4.500 left, 4500 CRD, 90%. */
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
          crd_views: [
            {
              state: "finite",
              operation: "search",
              remaining_crd: "4500",
              local_remaining_crd: null,
              request_cost_crd: "5",
              shared_pool_id: "brave:keyed:usd",
              possible_standard_calls: "900",
              price_version: "v2026-09",
              priced: true,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_crd: null,
              local_remaining_crd: null,
              request_cost_crd: null,
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
            crd_split_note: null,
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

/** Brave card after one 5-CRD debit: 4495 CRD, USD 4.495, 89.9%. */
export function braveCreditLimitsAfterDebit(): unknown[] {
  const limits = braveCreditLimits() as Array<Record<string, unknown>>
  const entry = limits[0] as Record<string, unknown>
  const auths = entry.auths as Array<Record<string, unknown>>
  const auth = auths[0] as Record<string, unknown>
  auth.aggregate_pool = {
    ...(auth.aggregate_pool as Record<string, unknown>),
    remaining: "4.495",
  }
  const views = auth.crd_views as Array<Record<string, unknown>>
  views[0] = { ...views[0], remaining_crd: "4495", possible_standard_calls: "899" }
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
              remaining_crd: null,
              allowance_crd: null,
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
          crd_views: [
            {
              state: "unknown",
              operation: "search",
              remaining_crd: null,
              local_remaining_crd: null,
              request_cost_crd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_crd: null,
              local_remaining_crd: null,
              request_cost_crd: null,
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
            crd_split_note: null,
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

/** Fund-less Parallel card so the relocated OAuth control mounts (NUDGE-5). */
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
          crd_views: [
            {
              state: "unknown",
              operation: "search",
              remaining_crd: null,
              local_remaining_crd: null,
              request_cost_crd: null,
              shared_pool_id: null,
              possible_standard_calls: null,
              price_version: null,
              priced: false,
            },
            {
              state: "unavailable",
              operation: "fetch",
              remaining_crd: null,
              local_remaining_crd: null,
              request_cost_crd: null,
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
            crd_split_note: null,
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

/** Brave funds plus a fund-less Parallel card for the OAuth pairing flow. */
export function bravePlusParallelLimits(): unknown[] {
  return [...braveCreditLimits(), ...parallelCardLimits()]
}

/** One history event with exact CRD balances plus a native fallback event. */
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
      old_crd: "4500",
      new_crd: "4495",
      crd_debit: "5",
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
      old_crd: null,
      new_crd: null,
      crd_debit: null,
      native_debit: null,
      actual_usd: null,
      confidence: "authoritative",
      local_attempt_id: null,
      detail: { native_unit: "USD", actor: "", search_granted_crd: "100" },
    },
  ]
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

/** Trace ids requested through `GET /api/v1/traces/{id}`, in order. */
export function traceDetailRequests(): string[] {
  return [...stubbedTraceDetailRequests]
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

function initialProviders(): StubProvider[] {
  return PROVIDER_ORDER.map((id, index) => ({
    provider_id: id,
    enabled: true,
    priority: index + 1,
    health: "healthy",
    circuit_breaker: { state: "closed", updated_at: FIXED_AT },
    latency_p95_ms: 110 + index * 10,
    secret_presence: SECRET_PRESENCE[id] ?? "missing",
    free_tier_estimates: { search: "0", fetch: "0", cost_estimate: "0" },
    reset_schedule: null,
  }))
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
    crd_usage_totals: stubbedCrdTotals ?? [],
  }
}

function dashboardWithQuotaOverride(): Record<string, unknown> {
  const base = dashboardFixture()
  if (dashboardQuotaOverride !== null) base.latest_quota = [...dashboardQuotaOverride]
  return base
}

function secretFixture(provider: string, presence: SecretPresence): Record<string, unknown> {
  return {
    provider,
    presence,
    fingerprint:
      presence === "configured" ? `${provider.slice(0, 3).toUpperCase()}_••••••••a1b2` : null,
    updated_at: FIXED_AT,
    source: presence === "configured" ? "keyring" : "none",
  }
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
  clearStubbedOAuthFlows()
  // Hygiene: manual overlays are module-level and must not leak across
  // scenarios (e.g. Brave overlay into later quota rows).
  for (const key of Object.keys(stubbedManualQuotas)) delete stubbedManualQuotas[key]
  dashboardQuotaOverride = null
  stubbedProviderLimits = null
  stubbedCrdTotals = null
  for (const key of Object.keys(stubbedHistory)) delete stubbedHistory[key]
  stubbedGrantRequests.length = 0
  stubbedGrantMode = "ok"
  stubbedSyncRequests.length = 0
  stubbedTraceListRequests.length = 0
  stubbedTraceListFailure = null
  stubbedTraceDetailRequests.length = 0
  for (const key of Object.keys(stubbedTraceDetailFailures)) {
    delete stubbedTraceDetailFailures[key]
  }
  let providers = initialProviders()
  let routing: StubRouting = {
    fallback_policy: "chained",
    cost_optimization_preset: "balanced",
    max_attempts: 3,
  }

  // Secret vault writes must land before the generic provider route (the
  // `/secret` suffix also matches `providers/*`).
  await page.route("**/api/v1/providers/*/secret", (route) => {
    const method = route.request().method()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 2] ?? ""
    if (method === "PUT") {
      providers = providers.map((row) =>
        row.provider_id === backendId ? { ...row, secret_presence: "configured" } : row
      )
      return json(route, secretFixture(backendId, "configured"))
    }
    if (method === "DELETE") {
      providers = providers.map((row) =>
        row.provider_id === backendId ? { ...row, secret_presence: "missing" } : row
      )
      return json(route, secretFixture(backendId, "missing"))
    }
    return route.fallback()
  })

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

  // OAuth device flow (see the stub-state block above). A POST begins (or
  // restarts) the flow as pending with a 1s poll interval; GET serves the
  // mutable flow state (404 while unpaired); DELETE revokes to unpaired and
  // flips the next dashboard refresh back to the unbudgeted row.
  await page.route("**/api/v1/providers/*/oauth/device-code", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    const flow = oauthFlowOf(backendId)
    if (flow.beginFails) {
      return json(route, { detail: backendId + " oauth unavailable" }, 503)
    }
    stubbedOAuthFlows[backendId] = { hasFlow: true, status: "pending", beginFails: false }
    return json(route, {
      provider: backendId,
      user_code: "ABCD-EFGH",
      verification_uri: "https://parallel.ai/activate",
      verification_uri_complete: "https://parallel.ai/activate?code=ABCD-EFGH",
      expires_in: 300,
      interval: 1,
    })
  })

  await page.route("**/api/v1/providers/*/oauth/status", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    const flow = stubbedOAuthFlows[backendId]
    if (!flow || !flow.hasFlow) {
      return json(route, { detail: "no oauth pairing for '" + backendId + "'" }, 404)
    }
    return json(route, {
      provider: backendId,
      status: flow.status,
      expires_in: flow.status === "pending" ? 299 : null,
    })
  })

  await page.route("**/api/v1/providers/*/oauth", (route) => {
    if (route.request().method() !== "DELETE") return route.fallback()
    const deleteParts = new URL(route.request().url()).pathname.split("/")
    const backendId = deleteParts[deleteParts.length - 2] ?? ""
    delete stubbedOAuthFlows[backendId]
    dashboardQuotaOverride = parallelUnseededQuota()
    return json(route, { provider: backendId, deleted: true })
  })
  await page.route("**/api/v1/providers/*/test", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 2] ?? "brave"
    return json(route, {
      provider: backendId,
      ok: true,
      status: "healthy",
      latency_ms: 142,
      checked_at: FIXED_AT,
      detail: null,
    })
  })

  await page.route("**/api/v1/providers/*/circuit-breaker/reset", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 3] ?? "brave"
    return json(route, { provider: backendId, state: "closed", updated_at: FIXED_AT })
  })

  // Provider PATCH (global enable / priority moves): in-memory update only.
  await page.route("**/api/v1/providers/*", (route) => {
    if (route.request().method() !== "PATCH") return route.fallback()
    const backendId = new URL(route.request().url()).pathname.split("/").pop() ?? ""
    const patch = readJsonBody(route)
    const current = providers.find((row) => row.provider_id === backendId)
    if (!current) return json(route, { detail: "Unknown provider" }, 404)
    const next = {
      ...current,
      enabled: typeof patch.enabled === "boolean" ? patch.enabled : current.enabled,
      priority: typeof patch.priority === "number" ? patch.priority : current.priority,
    }
    providers = providers.map((row) => (row.provider_id === backendId ? next : row))
    return json(route, next)
  })

  await page.route("**/api/v1/providers", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, providers)
  })

  // Routing config: PUT updates the in-memory variable; later GETs see it.
  await page.route("**/api/v1/routing/config", (route) => {
    const method = route.request().method()
    if (method === "GET") return json(route, routing)
    if (method === "PUT") {
      const patch = readJsonBody(route)
      routing = {
        fallback_policy: patch.fallback_policy === "first_only" ? "first_only" : "chained",
        cost_optimization_preset:
          patch.cost_optimization_preset === "free_first" ? "free_first" : "balanced",
        max_attempts: typeof patch.max_attempts === "number" ? patch.max_attempts : 3,
      }
      return json(route, routing)
    }
    return route.fallback()
  })

  // Pathname-exact dashboard matcher: the legacy "**/dashboard*" glob also
  // matched the Vite module URL /src/app/selectors/dashboardOverlay.ts (new
  // in Slice 6), fulfilling a JS import with JSON and blanking the app.
  await page.route((url) => url.pathname === "/dashboard", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, dashboardWithQuotaOverride())
  })

  // UI7 grant route: PUT /api/v1/providers/{id}/crd-grants/{auth}.
  await page.route("**/api/v1/providers/*/crd-grants/*", (route) => {
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
  await page.route("**/search", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "brave"
    const query = typeof body.query === "string" ? (body.query as string) : "stubbed query"
    if (query === "doomed query") {
      return json(route, { detail: "stubbed provider unavailable" }, 503)
    }
    return json(
      route,
      canonicalSearchFixture({ query, provider: pinned })
    )
  })

  // Deterministic fetch: echoes the pinned provider and target URL with
  // non-empty markdown content.
  await page.route("**/fetch", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "keenable"
    const url = typeof body.url === "string" ? (body.url as string) : "https://example.com"
    const base = canonicalFetchFixture() as {
      provider: string
      document: Record<string, unknown>
      usage: Record<string, unknown>
    }
    return json(route, {
      ...base,
      provider: pinned,
      document: { ...base.document, url },
      usage: { ...(base.usage as Record<string, unknown>), provider: pinned },
    })
  })

  // Trace read API (Activity). The list is summary-only by contract — no
  // query text or results — and honors the `operation` filter server-side.
  // Pathname-exact matchers keep these from colliding with each other or
  // with the Vite module graph.
  await page.route(
    (url) => url.pathname === "/api/v1/traces",
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const requestUrl = new URL(route.request().url())
      stubbedTraceListRequests.push(requestUrl.search)
      if (stubbedTraceListFailure !== null) {
        return json(route, { detail: stubbedTraceListFailure }, 500)
      }
      const operation = requestUrl.searchParams.get("operation")
      const list = traceListFixture() as {
        items: Record<string, unknown>[]
        generated_at: string
      }
      const base =
        operation === null
          ? list.items
          : list.items.filter((item) => item.operation === operation)
      // The seven-provider acceptance trace leads the list (it is a search
      // fanout, so the fetch filter still excludes it, like the backend).
      // The two current-data traces close the list (both are searches): the
      // null-source single-provider trace, then the fusion long-snippet trace.
      const items =
        operation === null || operation === "search"
          ? [
              sevenProviderTraceSummaryFixture(),
              ...base,
              nullSourceTraceSummaryFixture(),
              fusionLongTraceSummaryFixture(),
            ]
          : base
      return json(route, { items, generated_at: list.generated_at })
    }
  )

  // Disclosed detail: full input, tagged output, and stage timeline for the
  // two fixture traces; unknown ids 404 like the backend.
  await page.route(
    (url) => url.pathname.startsWith("/api/v1/traces/"),
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const traceId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").pop() ?? ""
      )
      stubbedTraceDetailRequests.push(traceId)
      const failure = stubbedTraceDetailFailures[traceId]
      if (failure !== undefined) return json(route, { detail: failure }, 500)
      if (traceId === SUCCESS_TRACE_ID) return json(route, traceDetailFixture())
      if (traceId === ERROR_TRACE_ID) return json(route, errorTraceDetailFixture())
      if (traceId === AGGREGATED_TRACE_ID) return json(route, aggregatedTraceDetailFixture())
      if (traceId === SEVEN_PROVIDER_TRACE_ID) {
        return json(route, sevenProviderTraceDetailFixture())
      }
      if (traceId === NULL_SOURCE_TRACE_ID) {
        return json(route, nullSourceTraceDetailFixture())
      }
      if (traceId === FUSION_LONG_TRACE_ID) {
        return json(route, fusionLongTraceDetailFixture())
      }
      return json(route, { detail: `unknown trace '${traceId}'` }, 404)
    }
  )
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
  await page.route((url) => url.pathname === "/dashboard", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
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
