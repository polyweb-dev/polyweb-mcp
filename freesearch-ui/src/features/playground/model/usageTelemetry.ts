import type { SearchResponse } from "@/domains/execution"
import { formatCallCost, providerCallCost } from "@/domains/providers"
import type { ProviderPrice } from "@/domains/providers"

/** One telemetry item of the results bar: a label and its value with a unit. */
interface UsageTelemetry {
  label: string
  value: string
}

/**
 * Prefer recorded dollars; native units cannot be converted to USD.
 */
export function usageTelemetry(search: SearchResponse, price?: ProviderPrice): UsageTelemetry {
  const unitKind = search.costUnitKind
  if (unitKind === "FREE" || unitKind === "USD") {
    return { label: "Cost", value: formatCallCost(unitKind === "FREE" ? 0 : search.costEstimateCredits) }
  }
  return { label: "Cost", value: price?.free ? formatCallCost(0) : providerCallCost(price, "search") }
}
