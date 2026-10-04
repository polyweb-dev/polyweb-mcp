import type { ProviderConfig } from "@/domains/providers"
import { PROVIDER_CATALOG } from "@/services/api/providerCatalog"

/**
 * Display-only provider ordering fixture for routing utility tests.
 * Runtime provider state always comes from the backend.
 */
export const DEFAULT_PROVIDERS: ProviderConfig[] = PROVIDER_CATALOG.map((entry, index) => ({
  id: entry.id,
  name: entry.name,
  description: entry.description,
  baseUrl: entry.baseUrl,
  isCustom: false,
  capabilities: [...entry.capabilities],
  globalEnabled: entry.id !== "parallel",
  searchEnabled: entry.id !== "parallel" && entry.capabilities.includes("search"),
  fetchEnabled: entry.id !== "parallel" && entry.capabilities.includes("fetch"),
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
