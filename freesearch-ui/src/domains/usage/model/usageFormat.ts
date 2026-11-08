import { unitLabel } from "@/shared/api/units"
import type { UnitKind } from "@/shared/api/units"

const OPERATION_LABELS: Readonly<Record<string, string>> = {
  search: "Search",
  fetch: "Fetch",
  cost_estimate: "Cost estimate",
}

/** Display label of one usage operation. */
export function usageOperationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation
}

/** Units with their unit kind, e.g. `12 requests` or `0.25 USD`. */
export function usageUnitsText(
  units: number,
  unitKind: UnitKind | null,
  displayUnit?: string | null
): string {
  const amount = units.toLocaleString("en-US", { maximumFractionDigits: 4 })
  const label = unitLabel(unitKind, displayUnit)
  // One request, one credit: the counted kinds take the singular at exactly 1.
  const singular = units === 1 && (label === "requests" || label === "credits")
  return `${amount} ${singular ? label.slice(0, -1) : label}`
}
