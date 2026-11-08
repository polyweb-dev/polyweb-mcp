import type { ReactNode } from "react"
import type { CRDConfidence, RateBarView, RateProgressView } from "@/domains/dashboard"
import { RemainingBar } from "@/shared/ui/RemainingBar"
import { rateBarRows } from "../model/rateBarRows"
import { formatDateTime } from "@/shared/lib/formatTime"

export interface ProviderRateBarsProps {
  providerName: string
  progress: RateProgressView[]
  /** A rail without fetch support shows its fetch rate bars nowhere. */
  fetchAvailable: boolean
  /** One row per bucket and window, with the counts in the hover text. */
  useSharedBar?: boolean
  /** Kept for callers; a reported confidence never shows a note. */
  hideAuthoritative?: boolean
  /** One shared title for every row, instead of one title per operation. */
  sharedTitle?: string
}

const WINDOW_TEXT = { "1h": "hourly", "1d": "daily" } as const
const WINDOW_NOUN = { "1h": "this hour", "1d": "today" } as const
const UNIT_TEXT = { requests: "requests", urls: "URLs" } as const

/**
 * Plain words of the confidence notes worth stating. A provider-reported
 * count is the normal case and an unknown confidence says nothing, so
 * neither shows a note.
 */
const CONFIDENCE_TEXT: Partial<Record<CRDConfidence, string>> = {
  observed: "Observed",
  estimated: "Estimated",
}

/** The quiet note line of one row: the confidence worth stating, the free allowance, the reset. */
function noteLine(bar: RateBarView): ReactNode {
  const confidence = CONFIDENCE_TEXT[bar.confidence] ?? null
  const free = bar.kind === "free_daily_allowance"
  if (confidence === null && !free && bar.resetAt === null) return null
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--muted)]">
      {confidence !== null && <span>{confidence}</span>}
      {free && <span>Free daily allowance</span>}
      {bar.resetAt !== null && <span title={formatDateTime(bar.resetAt)}>Resets {formatDateTime(bar.resetAt)}</span>}
    </div>
  )
}

/**
 * Hourly and daily rate capacity of one provider card.
 *
 * Every row draws through the shared bar, so its color follows the remaining
 * share like the funds bar. A row without a known limit keeps its count text
 * and draws no bar, so an unknown limit is never drawn as empty capacity.
 * With `useSharedBar`, the row carries its percent at the right of the bar and
 * its counts in the hover text; otherwise the counts sit on the title line.
 */
export function ProviderRateBars({
  providerName,
  progress,
  fetchAvailable,
  useSharedBar = false,
  sharedTitle,
}: ProviderRateBarsProps): ReactNode {
  const rows = rateBarRows(progress, fetchAvailable, useSharedBar)
  if (rows.length === 0) return null

  return (
    <div className="space-y-3">
      {rows.map(({ bar, text }) => {
        const windowKey = bar.window as "1h" | "1d"
        const unitText = UNIT_TEXT[bar.unit]
        const barName = sharedTitle === undefined
          ? providerName + " " + bar.operation + " " + WINDOW_TEXT[windowKey] + " " + unitText + " remaining"
          : providerName + " search and fetch limits remaining"
        const labelText = sharedTitle ?? (bar.operation === "search" ? "Search" : "Fetch")
        const countText = bar.percentRemaining === null ? "Limit not reported" : text + (sharedTitle ? "" : " " + unitText) + " left " + WINDOW_NOUN[windowKey]
        return (
          <div key={bar.bucketId + "-" + bar.window + "-" + bar.operation} className="space-y-1">
            <div className="tnum text-[12px] text-[var(--text)]">
              <span className="text-[var(--text-strong)]">{labelText}</span>{" · "}<span>{countText}</span>
            </div>
            {bar.percentRemaining !== null && <RemainingBar
              percentRemaining={bar.percentRemaining}
              label={barName}
              valueText={countText}
            />}
            {noteLine(bar)}
          </div>
        )
      })}
    </div>
  )
}
