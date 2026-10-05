/**
 * Providers slice — verbatim extract from ../backendFixtures.ts (step 1).
 * Canonical backend wire fixtures mirroring the live FastAPI contract
 * (snake_case, Decimal-as-string, ISO-8601 datetimes, extra=forbid).
 *
 * UI display names per provider follow the existing registry:
 * brave → "Brave Search", keenable → "Keenable", tavily → "Tavily",
 * exa → "Exa", firecrawl → "Firecrawl", you → "You.com",
 * parallel → "Parallel", tinyfish → "Tinyfish".
 */

export const BACKEND_IDS = [
  "brave",
  "keenable",
  "tavily",
  "exa",
  "firecrawl",
  "you",
  "parallel",
  "tinyfish",
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
  tinyfish: "Tinyfish",
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
    tinyfish: 8,
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
