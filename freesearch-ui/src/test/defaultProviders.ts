import type { ProviderConfig } from "@/domains/providers"
import { PROVIDER_CATALOG } from "@/services/api/providerCatalog"

/**
 * Display-only provider ordering fixture for routing utility tests.
 * Runtime provider state always comes from the backend.
 *
 * Canonical masks: Brave is search-only support (3) with all admin bits ON
 * (7); every other provider supports both tools (7). Parallel starts
 * globally OFF (enable 0); all others start fully ON (enable 7).
 * Raw search/fetch choices follow the enable bits, not capabilities:
 * Brave fetch stays ON raw (unsupported but chosen) so effective access
 * proves the support gate.
 */
function canonicalMasks(id: string): { enableMask: number; supportMask: number } {
  if (id === "brave") return { enableMask: 7, supportMask: 3 }
  if (id === "parallel") return { enableMask: 0, supportMask: 7 }
  return { enableMask: 7, supportMask: 7 }
}

export const DEFAULT_PROVIDERS: ProviderConfig[] = PROVIDER_CATALOG.map((entry, index) => ({
  id: entry.id,
  name: entry.name,
  description: entry.description,
  baseUrl: entry.baseUrl,
  isCustom: false,
  capabilities: [...entry.capabilities],
  enableMask: canonicalMasks(entry.id).enableMask,
  supportMask: canonicalMasks(entry.id).supportMask,
  globalEnabled: (canonicalMasks(entry.id).enableMask & 1) !== 0,
  searchEnabled: (canonicalMasks(entry.id).enableMask & 2) !== 0,
  fetchEnabled: (canonicalMasks(entry.id).enableMask & 4) !== 0,
  priority: index + 1,
  healthStatus: entry.id === "parallel" ? "offline" : "healthy",
  circuitBreaker: "closed",
  consecutiveFailures: 0,
  latencyP95Ms: [145, 190, 230, 310, 440, 360, 510, 210][index] ?? null,
  hasKey: entry.capabilities.includes("keyless_tier") ? false : true,
  keyMasked: "—",
  keyVaultStatus: entry.capabilities.includes("keyless_tier") ? "keyless_public" : "configured",
  authHeaderName: entry.authHeaderName,
  quota: {
    used: null,
    limit: null,
    unit: "units",
    confidence: "estimated",
    resetPeriod: null,
    nextReset: null,
    remaining: null,
    remainingPercent: null,
    unitKind: null,
    displayUnit: null,
    observedAt: null,
    window: null,
  },
}))
