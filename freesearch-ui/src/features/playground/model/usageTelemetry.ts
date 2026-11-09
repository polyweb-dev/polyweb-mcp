import type { SearchResponse } from "@/domains/execution"
import { providerCallCost } from "@/domains/providers"

/** One telemetry item of the results bar: a label and its value with a unit. */
interface UsageTelemetry {
  label: string
  value: string
}

/**
 * Show only recorded dollar costs; native units cannot be converted to USD.
 */
export function usageTelemetry(search: SearchResponse): UsageTelemetry {
  const unitKind = search.costUnitKind
  if (unitKind === "USD" && search.costEstimateCredits === 0) {
    return { label: "Cost", value: "$0.0000" }
  }
  const cost = unitKind === "FREE" ? 0 : unitKind === "USD" ? search.costEstimateCredits : null
  return { label: "Cost", value: providerCallCost({ callCostUsd: { search: cost } }, "search") }
}
