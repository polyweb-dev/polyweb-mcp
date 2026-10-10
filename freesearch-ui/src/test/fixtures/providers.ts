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
  /** Decoded global compatibility (derived from enable_mask bit 0). */
  enabled: boolean
  /** Admin choice mask 0..7: bit 0 global, bit 1 search, bit 2 fetch. */
  enable_mask: number
  /** System support mask 0..7: Brave 3, all others 7. */
  support_mask: number
  priority: number
  health: "healthy" | "degraded" | "unavailable" | "unknown" | null
  circuit_breaker: { state: "closed" | "open" | "half_open"; updated_at: string }
  latency_p95_ms: number | null
  secret_presence: "configured" | "missing" | "keyless_public"
  free_tier_estimates: Record<string, string>
  reset_schedule: string | null
}

/** Canonical system support: Brave is search-only (3), all others support both tools (7). */
export const CANONICAL_SUPPORT_MASKS: Record<BackendId, number> = {
  brave: 3,
  keenable: 7,
  tavily: 7,
  exa: 7,
  firecrawl: 7,
  you: 7,
  parallel: 7,
  tinyfish: 7,
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
  const defaultEnableMask = 7
  const defaultSupportMask = CANONICAL_SUPPORT_MASKS[backendId] ?? 7
  const enableMask = overrides.enable_mask ?? defaultEnableMask
  const supportMask = overrides.support_mask ?? defaultSupportMask
  // `enabled` is derived from the global bit unless the caller sets an
  // explicit enable_mask; a bare `enabled` override translates to 7/0.
  const hasExplicitMask = overrides.enable_mask !== undefined
  const enabled = hasExplicitMask
    ? (enableMask & 1) !== 0
    : (overrides.enabled ?? (enableMask & 1) !== 0)
  const resolvedEnableMask = hasExplicitMask
    ? enableMask
    : overrides.enabled === true
      ? 7
      : overrides.enabled === false
        ? 0
        : enableMask
  return {
    provider_id: backendId,
    priority: order[backendId],
    health: "healthy",
    circuit_breaker: { state: "closed", updated_at: "2026-09-06T00:00:00Z" },
    latency_p95_ms: 100 + order[backendId] * 10,
    secret_presence: backendId === "keenable" ? "keyless_public" : "configured",
    free_tier_estimates: { search: "1000", fetch: "500", cost_estimate: "0" },
    reset_schedule: "monthly",
    ...overrides,
    enabled,
    enable_mask: resolvedEnableMask,
    support_mask: supportMask,
  }
}

export function allProvidersFixture(): WireProviderStatus[] {
  return (Object.keys(BACKEND_DISPLAY_NAMES) as BackendId[]).map((id) =>
    providerStatus(id)
  )
}
