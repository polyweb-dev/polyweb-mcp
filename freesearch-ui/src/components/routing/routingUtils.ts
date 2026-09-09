import type { ProviderConfig, RoutingPreset } from "@/types/freesearch"

export type RoutingOperation = "search" | "fetch"

/** Providers eligible for `op` under the current flags, ordered for `preset`. */
export function getEligibleProviders(
  providers: ProviderConfig[],
  op: RoutingOperation,
  preset: RoutingPreset
): ProviderConfig[] {
  const eligible = providers.filter((provider) => {
    if (!provider.globalEnabled || provider.circuitBreaker === "open") return false
    return op === "search"
      ? provider.searchEnabled && provider.capabilities.includes("search")
      : provider.fetchEnabled && provider.capabilities.includes("fetch")
  })
  return [...eligible].sort(compareForPreset(preset))
}

type PresetComparator = (a: ProviderConfig, b: ProviderConfig) => number

function comparePriority(a: ProviderConfig, b: ProviderConfig): number {
  return a.priority - b.priority
}

function compareCost(a: ProviderConfig, b: ProviderConfig): number {
  const aFree = a.capabilities.includes("keyless_tier") ? 0 : 1
  const bFree = b.capabilities.includes("keyless_tier") ? 0 : 1
  return aFree - bFree
}

function compareLatency(a: ProviderConfig, b: ProviderConfig): number {
  if (a.latencyP95Ms === null && b.latencyP95Ms === null) return comparePriority(a, b)
  if (a.latencyP95Ms === null) return 1
  if (b.latencyP95Ms === null) return -1
  return a.latencyP95Ms - b.latencyP95Ms
}

function compareQuality(a: ProviderConfig, b: ProviderConfig): number {
  const aScore = a.capabilities.includes("neural_search") ? 1 : 0
  const bScore = b.capabilities.includes("neural_search") ? 1 : 0
  return bScore - aScore
}

const PRESET_COMPARATORS: Record<RoutingPreset, PresetComparator> = {
  priority: comparePriority,
  round_robin: comparePriority,
  cost_optimized: (a, b) => compareCost(a, b) || comparePriority(a, b),
  quality_first: (a, b) => compareQuality(a, b) || comparePriority(a, b),
  latency_optimized: compareLatency,
}

function compareForPreset(preset: RoutingPreset): PresetComparator {
  return PRESET_COMPARATORS[preset]
}

/** Human-readable reason the provider sits at its evaluated rank position. */
export function getProviderReason(
  provider: ProviderConfig,
  index: number,
  preset: RoutingPreset
): string {
  if (index === 0) {
    if (preset === "cost_optimized" && provider.capabilities.includes("keyless_tier")) {
      return "Ranked #1 for keyless free tier"
    }
    if (preset === "latency_optimized") {
      return provider.latencyP95Ms === null
        ? "Latency p95 unavailable"
        : `Fastest p95 roundtrip (${provider.latencyP95Ms}ms)`
    }
    if (
      preset === "quality_first" &&
      provider.capabilities.includes("neural_search")
    ) {
      return "Top neural quality score"
    }
    return `Configured as top priority (P${provider.priority})`
  }
  return `Fallback #${index}: Ready if prior provider fails`
}
