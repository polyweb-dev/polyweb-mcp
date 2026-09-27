import type { FetchResponse, SearchResponse } from "./types";
import type { UsageEvent } from "@/domains/dashboard/model/types";

export function makeSearchEvent(response: SearchResponse): UsageEvent {
  const providerName =
    response.selectedProviderId === "aggregated"
      ? "All Providers"
      : (response.waterfall[0]?.providerName ?? response.selectedProviderId);
  return {
    id: `${response.timestamp}-${response.selectedProviderId}-local`,
    timestamp: response.timestamp,
    operation: "search",
    queryOrUrl: "",
    providerId: response.selectedProviderId,
    providerName,
    latencyMs: response.executionTimeMs,
    costCredits: response.costEstimateCredits,
    status: "success",
    routeReason: `Recorded search via ${providerName}`,
    fallbackChain: response.fallbackChain,
    // Canonical units arrive via the dashboard refresh below; local
    // optimistic events carry no unit claim rather than a fabricated one.
    unitKind: null,
    displayUnit: null,
  };
}

export function makeFetchEvent(response: FetchResponse): UsageEvent {
  return {
    id: `${response.timestamp}-${response.providerId}-local`,
    timestamp: response.timestamp,
    operation: "fetch",
    queryOrUrl: "",
    providerId: response.providerId,
    providerName: response.document.providerName,
    latencyMs: response.executionTimeMs,
    costCredits: response.costEstimateCredits,
    status: "success",
    routeReason: `Recorded fetch via ${response.providerId}`,
    fallbackChain: response.fallbackChain,
    unitKind: null,
    displayUnit: null,
  };
}
