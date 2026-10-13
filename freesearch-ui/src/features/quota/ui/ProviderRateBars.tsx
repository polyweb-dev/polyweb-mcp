import type { ReactNode } from "react"
import type { CRDConfidence, LimitRateWindow, RateBarView, RateProgressView } from "@/domains/dashboard"
import { callsText, formatQuotaCount, percentRemaining, rateBarModel } from "../model/crdDisplay"
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
  /**
   * Optional detail rate windows of one rail. A Tavily card passes the
   * backend detail windows so the shared default minute bucket gets its bar;
   * every other surface leaves them absent and keeps hour/day exclusivity.
   */
  minuteWindows?: LimitRateWindow[]
}

const WINDOW_TEXT = { "1h": "hourly", "1d": "daily" } as const
const WINDOW_NOUN = { "1h": "hour", "1d": "day" } as const
const UNIT_TEXT = { requests: "requests", urls: "URLs" } as const
/** The one detail window the body renders, with its own noun. */
const MINUTE_WINDOW = "1m" as const
const MINUTE_NOUN = "minute"

/** One prepared minute row: the exact strings and the percentage. */
interface MinuteRateBar {
  bucketId: string
  remaining: string
  limit: string
  percentRemaining: number | null
  confidence: CRDConfidence
  resetAt: string | null
}

/** The wire confidence text clamps to the view enum only on a known member. */
function confidenceOf(entry: LimitRateWindow): CRDConfidence {
  return (entry.confidence === "authoritative" ||
    entry.confidence === "observed" ||
    entry.confidence === "estimated")
    ? entry.confidence
    : "unknown"
}

/**
 * Minute rows of the optional detail windows.
 *
 * Only `1m` request windows with a known remaining amount enter the model, and
 * duplicates by bucket and window fold into one row, so the shared search and
 * extract bucket renders once. The remaining and limit strings stay exact; the
 * percentage comes from the shared helper only when both parts are valid, so a
 * percentageless row renders its facts without a fake bar.
 */
function minuteBars(windows: LimitRateWindow[]): MinuteRateBar[] {
  const rows: MinuteRateBar[] = []
  const seen = new Set<string>()
  for (const entry of windows) {
    if (entry.window !== MINUTE_WINDOW || entry.unit !== "requests") continue
    if (entry.remaining === undefined || entry.remaining === null) continue
    const key = entry.bucket_id + "-" + entry.window
    if (seen.has(key)) continue
    seen.add(key)
    rows.push({
      bucketId: entry.bucket_id,
      remaining: entry.remaining,
      limit: entry.limit,
      percentRemaining: percentRemaining(entry.remaining, entry.limit),
      confidence: confidenceOf(entry),
      resetAt: entry.reset_at ?? null,
    })
  }
  return rows
}

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
 * stay detail text unless the optional `minuteWindows` input supplies a
 * minute row. An entry of an unsupported operation and an entry without a
 * known amount never creates a row. Search rows render before fetch rows. The
 * bar carries a numeric `aria-valuenow` only when the limit is known, so an
 * unknown limit is never drawn as empty capacity.
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
 *
 * The optional `minuteWindows` input renders the shared default minute bucket
 * through the shared bar as well, with exact counts in `formatQuotaCount` and
 * its values stated as requests per minute. A percentageless minute row keeps
 * its known limit visible and shows no bar.
 */
export function ProviderRateBars({
  providerName,
  progress,
  fetchAvailable,
  useSharedBar = false,
  hideAuthoritative = false,
  sharedTitle,
  minuteWindows,
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
  const minuteRows = useSharedBar && minuteWindows !== undefined ? minuteBars(minuteWindows) : []
  if (bars.length === 0 && minuteRows.length === 0) return null

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
      {minuteRows.map((row) => {
        const minuteName = providerName + " search and extract limits remaining"
        const text = formatQuotaCount(row.remaining) + " of " + formatQuotaCount(row.limit)
        const showConfidence = !(hideAuthoritative && row.confidence === "authoritative")
        const noteRow = showConfidence || row.resetAt !== null
        const labelText = sharedTitle ?? "Search and extract"
        return (
          <div key={row.bucketId + "-1m"} className="space-y-0.5">
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <span className="text-[var(--text-strong)]">{labelText}</span>
              <span className="tnum text-[var(--text)]">
                {text} {UNIT_TEXT.requests}/{MINUTE_NOUN}
              </span>
            </div>
            {row.percentRemaining !== null && (
              <RemainingBar
                percentRemaining={row.percentRemaining}
                label={minuteName}
                showPercent
                hoverText={text + " requests per " + MINUTE_NOUN}
              />
            )}
            {noteRow && (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--muted)]">
                {showConfidence && confidenceCell(row.confidence)}
                {row.resetAt !== null && <span>Resets {timeText(row.resetAt)}</span>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
