import type { ReactNode } from "react"
import type { CRDConfidence, RateBarView, RateProgressView } from "@/domains/dashboard"
import { callsText, formatQuotaCount, rateBarModel } from "../model/crdDisplay"
import { timeText } from "../model/timeText"
import { ConfidenceLabel } from "./ConfidenceLabel"
import { RemainingBar } from "@/shared/ui/RemainingBar"

export interface ProviderRateBarsProps {
  providerName: string
  progress: RateProgressView[]
  /** A rail without fetch support shows its fetch rate bars nowhere. */
  fetchAvailable: boolean
  /** Draw each rate bar through the shared bar. */
  useSharedBar?: boolean
  /** Drop the authoritative confidence label of each rate row. */
  hideAuthoritative?: boolean
  /** One shared title for every row, instead of one title per operation. */
  sharedTitle?: string
}

const WINDOW_TEXT = { "1h": "hourly", "1d": "daily" } as const
const WINDOW_NOUN = { "1h": "hour", "1d": "day" } as const
const UNIT_TEXT = { requests: "requests", urls: "URLs" } as const

/** Search rows render before fetch rows; anything else keeps payload order. */
function compareOperation(a: RateProgressView, b: RateProgressView): number {
  if (a.operation === b.operation) return 0
  if (a.operation === "search") return -1
  if (b.operation === "search") return 1
  return 0
}

function confidenceCell(confidence: CRDConfidence): ReactNode {
  if (confidence === "unknown") {
    return <span className="text-[11px] text-[var(--muted)]">unknown</span>
  }
  return <ConfidenceLabel confidence={confidence} />
}

/**
 * Known parts of one rate amount; an incomplete entry yields no row.
 *
 * With whole requests, the request-unit counts floor through `callsText`, so a
 * decimal capacity never shows as a whole extra request. URL units and the
 * default path keep integer counts through `formatQuotaCount`.
 */
function rateText(bar: RateBarView, wholeRequests: boolean = false): string | null {
  const count = wholeRequests && bar.unit === "requests" ? callsText : formatQuotaCount
  const remaining = bar.remaining === null ? null : count(bar.remaining)
  const limit = bar.limit === null ? null : count(bar.limit)
  if (remaining === null && limit === null) return null
  if (limit === null) return remaining + " left"
  if (remaining === null) return "of " + limit
  return remaining + " of " + limit
}

/**
 * Hourly and daily rate capacity of one provider card.
 *
 * Only `1h` and `1d` progress entries become bars; second and minute windows
 * stay detail text. An entry of an unsupported operation and an entry without
 * a known amount never creates a row. Search rows render before fetch rows.
 * The bar carries a numeric `aria-valuenow` only when the limit is known, so
 * an unknown limit is never drawn as empty capacity.
 *
 * With `useSharedBar`, each bar draws through the shared full-width bar on its
 * own line below the text line with a clear gap, and the remaining and limit
 * counts of a request unit floor to whole requests through `callsText`. URL
 * units and the default path keep integer counts through `formatQuotaCount`.
 * Each shared row carries its percentage at the right of the bar and its full
 * counts in the hover popover, so the title line holds the title only. With
 * `hideAuthoritative`, only an authoritative confidence label drops, and a
 * note row without a remaining note drops with it. With `sharedTitle`, every
 * row shares one title instead of one title per operation.
 */
export function ProviderRateBars({
  providerName,
  progress,
  fetchAvailable,
  useSharedBar = false,
  hideAuthoritative = false,
  sharedTitle,
}: ProviderRateBarsProps): ReactNode {
  const seenBuckets = new Set<string>()
  const bars = [...progress]
    .sort(compareOperation)
    .filter((entry) => entry.window === "1h" || entry.window === "1d")
    .filter((entry) => entry.operation === "search" || fetchAvailable)
    .filter((entry) => {
      if (!useSharedBar) return true
      const key = entry.bucket_id + "-" + entry.window
      if (seenBuckets.has(key)) return false
      seenBuckets.add(key)
      return true
    })
    .map((entry) => rateBarModel({ progress: entry }))
    .map((bar) => ({ bar, text: rateText(bar, useSharedBar) }))
    .filter((row): row is { bar: RateBarView; text: string } => row.text !== null)
  if (bars.length === 0) return null

  return (
    <div className="space-y-2">
      {bars.map(({ bar, text }) => {
        const windowText = WINDOW_TEXT[bar.window as "1h" | "1d"]
        const unitText = UNIT_TEXT[bar.unit]
        const barName = sharedTitle === undefined
          ? providerName + " " + bar.operation + " " + windowText + " " + unitText + " remaining"
          : providerName + " search and fetch limits remaining"
        const showConfidence = !((hideAuthoritative || useSharedBar) && bar.confidence === "authoritative")
        const noteRow =
          showConfidence || bar.kind === "free_daily_allowance" || bar.resetAt !== null
        const labelText = sharedTitle ?? (bar.operation === "search" ? "Search" : "Fetch")
        const hoverText = text + " " + unitText + " per " + WINDOW_NOUN[bar.window as "1h" | "1d"]
        return (
          <div key={bar.bucketId + "-" + bar.window + "-" + bar.operation} className="space-y-0.5">
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <span className="text-[var(--text-strong)]">
                {labelText}
              </span>
              {!useSharedBar && (
                <span className="tnum text-[var(--text)]">
                  {text} {unitText}
                </span>
              )}
            </div>
            {bar.percentRemaining !== null &&
              (useSharedBar ? (
                <RemainingBar
                  percentRemaining={bar.percentRemaining}
                  label={barName}
                  showPercent
                  hoverText={hoverText}
                />
              ) : (
                <div
                  className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"
                  role="progressbar"
                  aria-label={barName}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={bar.percentRemaining}
                >
                  <div
                    className="h-full rounded-full bg-[var(--status-warning)]"
                    style={{ width: bar.percentRemaining + "%" }}
                  />
                </div>
              ))}
            {noteRow && (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--muted)]">
                {showConfidence && confidenceCell(bar.confidence)}
                {bar.kind === "free_daily_allowance" && <span>Free daily allowance</span>}
                {bar.resetAt !== null && <span>Resets {timeText(bar.resetAt)}</span>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
