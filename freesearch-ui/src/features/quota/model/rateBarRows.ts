import type { RateBarView, RateProgressView } from "@/domains/dashboard"
import { callsText, formatQuotaCount, rateBarModel } from "./crdDisplay"
import { groupDigits } from "./numberText"

/** One shown rate row: the bar view and its known count text. */
export interface RateBarRow {
  bar: RateBarView
  text: string
}

/** Search rows render before fetch rows; anything else keeps payload order. */
function compareOperation(a: RateProgressView, b: RateProgressView): number {
  if (a.operation === b.operation) return 0
  if (a.operation === "search") return -1
  if (b.operation === "search") return 1
  return 0
}

/**
 * Known parts of one rate amount; an incomplete entry yields no row.
 *
 * With whole requests, the request-unit counts floor through `callsText`, so a
 * decimal capacity never shows as a whole extra request. URL units and the
 * default path keep integer counts through `formatQuotaCount`.
 */
function rateText(bar: RateBarView, wholeRequests: boolean): string {
  const count = wholeRequests && bar.unit === "requests" ? callsText : formatQuotaCount
  const remaining = bar.remaining === null ? null : count(bar.remaining)
  const limit = bar.limit === null ? null : count(bar.limit)
  if (remaining === null || limit === null || Number(bar.limit) <= 0) return "Limit not reported"
  return groupDigits(remaining) + " of " + groupDigits(limit)
}

/**
 * The hour and day rate rows of one card.
 *
 * Only `1h` and `1d` entries become rows, an entry of an unsupported operation
 * never does, and an entry without a known amount yields no row. With the
 * shared flag, one row stands for each bucket and window.
 */
export function rateBarRows(
  progress: RateProgressView[],
  fetchAvailable: boolean,
  sharedBar: boolean,
): RateBarRow[] {
  const seenBuckets = new Set<string>()
  return [...progress]
    .sort(compareOperation)
    .filter((entry) => entry.window === "1h" || entry.window === "1d")
    .filter((entry) => entry.operation === "search" || fetchAvailable)
    .filter((entry) => {
      if (!sharedBar) return true
      const key = entry.bucket_id + "-" + entry.window
      if (seenBuckets.has(key)) return false
      seenBuckets.add(key)
      return true
    })
    .map((entry) => rateBarModel({ progress: entry }))
    .map((bar) => ({ bar, text: rateText(bar, sharedBar) }))
}
