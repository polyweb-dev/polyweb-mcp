import type { OperationUsageSummary, ProjectUsageTotal } from "./types"

/**
 * Sum the totals per operation: events add up, units add up per unit kind
 * only, so requests, credits and dollars never merge into one number.
 */
export function summarizeUsageByOperation(
  totals: readonly ProjectUsageTotal[]
): OperationUsageSummary[] {
  const byOperation = new Map<string, OperationUsageSummary>()
  for (const total of totals) {
    const summary = byOperation.get(total.operation) ?? {
      operation: total.operation,
      eventCount: 0,
      units: [],
    }
    summary.eventCount += total.eventCount
    const amount = summary.units.find((entry) => entry.unitKind === total.unitKind)
    if (amount === undefined) summary.units.push({ unitKind: total.unitKind, units: total.totalUnits })
    else amount.units += total.totalUnits
    byOperation.set(total.operation, summary)
  }
  return [...byOperation.values()]
}
