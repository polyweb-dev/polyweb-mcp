import { isProviderOperationEnabled } from "@/domains/providers";
import type { ProviderConfig } from "@/domains/providers/model/types";
import type { RoutingPreset } from "./types";

export type RoutingOperation = "search" | "fetch";

/** Providers eligible for `op` under the current flags, ordered for `preset`. */
export function getEligibleProviders(
  providers: ProviderConfig[],
  op: RoutingOperation,
  preset: RoutingPreset,
): ProviderConfig[] {
  const eligible = providers.filter((provider) => {
    if (provider.circuitBreaker === "open") return false;
    const hasCredential = provider.hasKey || provider.capabilities.includes("keyless_tier");
    if (!hasCredential) return false;
    return isProviderOperationEnabled(provider, op);
  });
  return [...eligible].sort(compareForPreset(preset));
}

function compareCostOptimized(a: ProviderConfig, b: ProviderConfig): number | null {
  const aFree = a.capabilities.includes("keyless_tier") ? 0 : 1;
  const bFree = b.capabilities.includes("keyless_tier") ? 0 : 1;
  return aFree === bFree ? null : aFree - bFree;
}

function compareLatencyOptimized(a: ProviderConfig, b: ProviderConfig): number {
  if (a.latencyP95Ms === null && b.latencyP95Ms === null) return a.priority - b.priority;
  if (a.latencyP95Ms === null) return 1;
  if (b.latencyP95Ms === null) return -1;
  return a.latencyP95Ms - b.latencyP95Ms;
}

function compareQualityFirst(a: ProviderConfig, b: ProviderConfig): number | null {
  const aScore = a.capabilities.includes("neural_search") ? 1 : 0;
  const bScore = b.capabilities.includes("neural_search") ? 1 : 0;
  return aScore === bScore ? null : bScore - aScore;
}

function compareForPreset(preset: RoutingPreset) {
  return (a: ProviderConfig, b: ProviderConfig): number => {
    if (preset === "cost_optimized") return compareCostOptimized(a, b) ?? a.priority - b.priority;
    if (preset === "latency_optimized") return compareLatencyOptimized(a, b);
    if (preset === "quality_first") return compareQualityFirst(a, b) ?? a.priority - b.priority;
    return a.priority - b.priority;
  };
}

/** Human-readable reason the provider sits at its evaluated rank position. */
export function getProviderReason(
  provider: ProviderConfig,
  index: number,
  preset: RoutingPreset,
): string {
  if (index === 0) {
    if (preset === "cost_optimized" && provider.capabilities.includes("keyless_tier")) {
      return "Ranked #1 for keyless free tier";
    }
    if (preset === "latency_optimized") {
      return provider.latencyP95Ms === null
        ? "Latency p95 unavailable"
        : `Fastest p95 roundtrip (${provider.latencyP95Ms}ms)`;
    }
    if (
      preset === "quality_first" &&
      provider.capabilities.includes("neural_search")
    ) {
      return "Top neural quality score";
    }
    return `Configured as top priority (P${provider.priority})`;
  }
  return `Fallback #${index}: Ready if prior provider fails`;
}
