/**
 * Canonical backend wire fixtures mirroring the live FastAPI contract
 * (snake_case, Decimal-as-string, ISO-8601 datetimes, extra=forbid).
 *
 * UI display names per provider follow the existing registry:
 * brave → "Brave Search", keenable → "Keenable", tavily → "Tavily",
 * exa → "Exa", firecrawl → "Firecrawl", you → "You.com",
 * parallel → "Parallel".
 */

export const BACKEND_IDS = [
  "brave",
  "keenable",
  "tavily",
  "exa",
  "firecrawl",
  "you",
  "parallel",
] as const

export type BackendId = (typeof BACKEND_IDS)[number]

export const BACKEND_DISPLAY_NAMES: Record<BackendId, string> = {
  brave: "Brave Search",
  keenable: "Keenable",
  tavily: "Tavily",
  exa: "Exa",
  firecrawl: "Firecrawl",
  you: "You.com",
  parallel: "Parallel",
}

export const catalogNameOf = (backendId: string): string =>
  (BACKEND_DISPLAY_NAMES as Record<string, string>)[backendId] ?? backendId

export interface WireProviderStatus {
  provider_id: string
  enabled: boolean
  priority: number
  health: "healthy" | "degraded" | "unavailable" | "unknown" | null
  circuit_breaker: { state: "closed" | "open" | "half_open"; updated_at: string }
  latency_p95_ms: number | null
  secret_presence: "configured" | "missing" | "keyless_public"
  free_tier_estimates: Record<string, string>
  reset_schedule: string | null
}

export function providerStatus(
  backendId: BackendId,
  overrides: Partial<WireProviderStatus> = {}
): WireProviderStatus {
  const order: Record<BackendId, number> = {
    brave: 1,
    keenable: 2,
    tavily: 3,
    exa: 4,
    firecrawl: 5,
    you: 6,
    parallel: 7,
  }
  return {
    provider_id: backendId,
    enabled: true,
    priority: order[backendId],
    health: "healthy",
    circuit_breaker: { state: "closed", updated_at: "2026-09-06T00:00:00Z" },
    latency_p95_ms: 100 + order[backendId] * 10,
    secret_presence: backendId === "keenable" ? "keyless_public" : "configured",
    free_tier_estimates: { search: "1000", fetch: "500", cost_estimate: "0" },
    reset_schedule: "monthly",
    ...overrides,
  }
}

export function allProvidersFixture(): WireProviderStatus[] {
  return (Object.keys(BACKEND_DISPLAY_NAMES) as BackendId[]).map((id) =>
    providerStatus(id)
  )
}

export function routingConfigFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    fallback_policy: "chained",
    cost_optimization_preset: "balanced",
    max_attempts: 3,
    ...overrides,
  }
}

export interface WireDashboardUsageTotal {
  provider: string
  operation: string
  total_units: string
  event_count: number
  unit_kind?: string | null
}

export interface WireDashboardRecentUsage {
  provider: string
  operation: string
  units: string
  observed_at: string
  latency_ms: number | null
  status: string
  unit_kind?: string | null
  display_unit?: string | null
}

export interface WireDashboardQuota {
  provider: string
  source: "authoritative" | "observed" | "estimated"
  observed_at: string
  remaining: string | null
  remaining_percent?: string | null
  /** Decimal-as-string verbatim; null means no hard limit (e.g. You.com ESTIMATED). */
  limit: string | null
  reset_at: string | null
  unit_kind?: string | null
  display_unit?: string | null
}

export interface WireDashboard {
  notice: string
  usage_totals: WireDashboardUsageTotal[]
  recent_usage: WireDashboardRecentUsage[]
  latest_quota: WireDashboardQuota[]
  latest_health: Array<{ provider: string; status: string; checked_at: string }>
  generated_at: string
}

export function dashboardFixture(
  overrides: Partial<WireDashboard> = {}
): WireDashboard {
  return {
    notice: "Usage, quota, and health shown here are local-observed only.",
    usage_totals: [
      {
        provider: "tavily",
        operation: "search",
        total_units: "3.5",
        event_count: 4,
        unit_kind: "CREDIT",
      },
      {
        provider: "brave",
        operation: "search",
        total_units: "12",
        event_count: 12,
        unit_kind: "REQUEST",
      },
    ],
    recent_usage: [
      {
        provider: "tavily",
        operation: "search",
        units: "1",
        observed_at: "2026-09-06T10:00:00Z",
        latency_ms: 230,
        status: "success",
        unit_kind: "CREDIT",
        display_unit: "credits",
      },
      {
        provider: "brave",
        operation: "fetch",
        units: "0.001",
        observed_at: "2026-09-06T09:55:00Z",
        latency_ms: null,
        status: "failure",
        unit_kind: "REQUEST",
        display_unit: "requests",
      },
    ],
    latest_quota: [],
    latest_health: [
      { provider: "tavily", status: "healthy", checked_at: "2026-09-06T10:00:00Z" },
    ],
    generated_at: "2026-09-06T10:01:00Z",
    ...overrides,
  }
}

/**
 * Canonical quota rows for the Final Review Plan (QUOTA.md §4 Option A).
 * Covers AUTHORITATIVE credits (Tavily), OBSERVED requests with reset_at
 * (Brave), ESTIMATED USD with limit null (You.com), and a null-kind legacy
 * row (Exa). Limit strings are verbatim Decimal-as-string: "100000.10" must
 * NOT become 100000.1 and "0.00000001" must NOT become 1e-8 (RF1).
 */
export function canonicalQuotasFixture(): WireDashboardQuota[] {
  return [
    {
      provider: "tavily",
      source: "authoritative",
      observed_at: "2026-09-06T18:00:00Z",
      remaining: "90000.05",
      remaining_percent: "90.00005",
      limit: "100000.10",
      reset_at: null,
      unit_kind: "CREDIT",
      display_unit: "credits",
    },
    {
      provider: "brave",
      source: "observed",
      observed_at: "2026-09-06T18:05:00Z",
      remaining: "950",
      remaining_percent: "95",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "you",
      source: "estimated",
      observed_at: "2026-09-06T18:10:00Z",
      remaining: "4.75",
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
    {
      provider: "exa",
      source: "estimated",
      observed_at: "2026-09-06T18:15:00Z",
      remaining: "0.00000005",
      limit: "0.00000001",
      reset_at: null,
      unit_kind: null,
      display_unit: null,
    },
  ]
}

/**
 * Triple-keyed usage totals: (provider, operation, unit_kind). The two Tavily
 * search rows share provider+operation but differ in unit_kind and must stay
 * separate; the Exa row omits unit_kind entirely (legacy null-kind).
 */
export function canonicalTotalsFixture(): WireDashboardUsageTotal[] {
  return [
    {
      provider: "tavily",
      operation: "search",
      total_units: "3.5",
      event_count: 4,
      unit_kind: "CREDIT",
    },
    {
      provider: "tavily",
      operation: "search",
      total_units: "0.007",
      event_count: 2,
      unit_kind: "USD",
    },
    {
      provider: "brave",
      operation: "search",
      total_units: "12",
      event_count: 12,
      unit_kind: "REQUEST",
    },
    {
      provider: "exa",
      operation: "search",
      total_units: "9",
      event_count: 9,
    },
  ]
}

/** Canonical recent usage with unit_kind/display_unit plus a legacy row. */
export function canonicalRecentUsageFixture(): WireDashboardRecentUsage[] {
  return [
    {
      provider: "tavily",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:00:00Z",
      latency_ms: 230,
      status: "success",
      unit_kind: "CREDIT",
      display_unit: "credits",
    },
    {
      provider: "brave",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:01:00Z",
      latency_ms: 120,
      status: "success",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    {
      provider: "you",
      operation: "search",
      units: "0.005",
      observed_at: "2026-09-06T10:02:00Z",
      latency_ms: 150,
      status: "success",
      unit_kind: "USD",
      display_unit: "USD",
    },
    {
      provider: "exa",
      operation: "search",
      units: "2",
      observed_at: "2026-09-06T10:03:00Z",
      latency_ms: null,
      status: "success",
    },
  ]
}

/**
 * Full canonical dashboard: triple-keyed totals, canonical recent usage, and
 * the four canonical quota rows. Pass overrides to trim for a focused test.
 */
export function canonicalDashboardFixture(
  overrides: Partial<WireDashboard> = {}
): WireDashboard {
  return dashboardFixture({
    usage_totals: canonicalTotalsFixture(),
    recent_usage: canonicalRecentUsageFixture(),
    latest_quota: canonicalQuotasFixture(),
    ...overrides,
  })
}

export function searchResponseFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    query: "live backend query",
    results: [
      {
        title: "Live backend result one",
        url: "https://example.com/one",
        snippet: "First live snippet.",
        published_at: "2026-09-05T14:30:00Z",
        source: "Example Source",
        score: 0.92,
        metadata: {},
      },
      {
        title: "Live backend result two",
        url: "https://example.com/two",
        snippet: "Second live snippet.",
        published_at: null,
        source: null,
        score: null,
        metadata: {},
      },
    ],
    provider: "tavily",
    total_results: 2,
    usage: {
      provider: "tavily",
      operation: "search",
      units: "1",
      observed_at: "2026-09-06T10:02:00Z",
      request_id: "req-123",
      metadata: {},
      latency_ms: 187,
      status: "success",
    },
    ...overrides,
  }
}

export function minimalSearchResponseFixture(): Record<string, unknown> {
  return {
    query: "minimal query",
    results: [],
    provider: "you",
    total_results: null,
    usage: null,
  }
}

export function fetchResponseFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "firecrawl",
    document: {
      url: "https://example.com/doc",
      content: "# Live document\n\nFetched markdown body.",
      title: "Live document title",
      content_type: "text/markdown",
      fetched_at: "2026-09-06T10:03:00Z",
      metadata: {},
    },
    usage: {
      provider: "firecrawl",
      operation: "fetch",
      units: "2",
      observed_at: "2026-09-06T10:03:01Z",
      request_id: null,
      metadata: {},
      latency_ms: 412,
      status: "success",
    },
    ...overrides,
  }
}

export function providerTestFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "brave",
    ok: true,
    status: "healthy",
    latency_ms: 142,
    checked_at: "2026-09-06T10:04:00Z",
    detail: null,
    ...overrides,
  }
}

export function secretStatusFixture(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    provider: "tavily",
    presence: "configured",
    fingerprint: "TAV_••••••••9a1e",
    updated_at: "2026-09-06T10:05:00Z",
    source: "keyring",
    ...overrides,
  }
}

export function breakerResetFixture(provider = "brave"): Record<string, unknown> {
  return {
    provider,
    state: "closed",
    updated_at: "2026-09-06T10:06:00Z",
  }
}
