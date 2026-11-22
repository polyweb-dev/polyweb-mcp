import type { ProjectUsageTotal } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import { usageTotalsView } from "@/features/usage/model/usageTotalsView"

/** All-time figures of the overview summary row. */
interface UsageFigures {
  searches: number
  fetches: number
  /** Known dollar cost, reported or estimated, or `null` when no call has a known price. */
  usd: number | null
  costIncomplete: boolean
  /** Part of the dollar cost is estimated from the catalog price. */
  estimated: boolean
  free: boolean
}

/**
 * Fold the dashboard totals into the summary row: call counts per
 * operation and the known dollar cost. Native units stay on Usage.
 */
export function usageFigures(totals: readonly ProjectUsageTotal[], order?: ProjectOrder): UsageFigures {
  const amounts = usageTotalsView(totals, order).total
  const figures: UsageFigures = {
    searches: 0, fetches: 0, usd: amounts.calls === 0 ? 0 : amounts.usd,
    costIncomplete: amounts.calls > 0 && amounts.unreportedCost,
    estimated: amounts.estimated,
    free: amounts.calls > 0 && amounts.free && !amounts.unreportedCost && (amounts.usd === null || amounts.usd === 0),
  }
  for (const total of totals) {
    if (total.operation === "search") figures.searches += total.eventCount
    if (total.operation === "fetch") figures.fetches += total.eventCount
  }
  return figures
}
