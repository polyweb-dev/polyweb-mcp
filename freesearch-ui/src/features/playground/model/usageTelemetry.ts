import { usageUnitsText } from "@/domains/usage"
import type { SearchResponse } from "@/domains/execution"

/** One telemetry item of the results bar: a label and its value with a unit. */
interface UsageTelemetry {
  label: string
  value: string
}

/**
 * What one search used. With a recorded unit kind the value carries its unit
 * ("0.007 USD", "3 requests", "Free"); without one, Tavily's native usage
 * reads as Credits and every other provider keeps the generic Units label.
 */
export function usageTelemetry(search: SearchResponse): UsageTelemetry {
  const unitKind = search.costUnitKind
  if (unitKind === "FREE") return { label: "Usage", value: "Free" }
  if (unitKind !== undefined && unitKind !== null) {
    return {
      label: "Usage",
      value: usageUnitsText(search.costEstimateCredits, unitKind, search.costDisplayUnit ?? null),
    }
  }
  return {
    label: search.selectedProviderId === "tavily" ? "Credits" : "Units",
    value: String(search.costEstimateCredits),
  }
}
