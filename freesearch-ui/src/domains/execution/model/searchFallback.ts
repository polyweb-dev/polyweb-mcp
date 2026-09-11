import type { ProviderConfig } from "@/domains/providers/model/types";
import type { RoutingPreset } from "@/domains/routing/model/types";
import { getEligibleProviders } from "@/domains/routing/model/routingPolicy";

/**
 * Next-best search provider for client-side fallback after a failed attempt.
 *
 * Ordering reuses the routing policy (priority/latency/quality preset via
 * getEligibleProviders, which already drops disabled and circuit-open
 * providers); candidates must additionally hold an API key (hasKey covers
 * keyless_public tiers) so the retry never spends its single shot on a
 * provider that cannot authenticate. Never returns an id in excludeUiIds,
 * so the failed provider is never retried.
 */
export function pickFallbackSearchProvider(
  providers: ProviderConfig[],
  preset: RoutingPreset,
  excludeUiIds: readonly string[],
): ProviderConfig | undefined {
  const excluded = new Set(excludeUiIds);
  return getEligibleProviders(providers, "search", preset).find(
    (provider) => !excluded.has(provider.id) && provider.hasKey,
  );
}
