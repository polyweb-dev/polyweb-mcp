import type { ReactNode } from "react"
import type { CRDConfidence, RateProgressView } from "@/domains/dashboard"
import { rateBarModel } from "../model/crdDisplay"
import { ConfidenceLabel } from "./ConfidenceLabel"

export interface ProviderRateBarsProps {
  providerName: string
  progress: RateProgressView[]
}

const WINDOW_TEXT = { "1h": "hourly", "1d": "daily" } as const
const UNIT_TEXT = { requests: "requests", urls: "URLs" } as const

function confidenceCell(confidence: CRDConfidence): ReactNode {
  if (confidence === "unknown") {
    return <span className="text-[11px] text-[var(--muted)]">unknown</span>
  }
  return <ConfidenceLabel confidence={confidence} />
}

function rateText(remaining: string | null, limit: string | null): string {
  if (remaining === null && limit === null) return "Unknown"
  if (limit === null) return remaining + " left"
  return (remaining ?? "—") + " of " + limit
}

/**
 * Hourly and daily rate capacity of one provider card.
 *
 * Only `1h` and `1d` progress entries become bars; second and minute windows
 * stay detail text. The bar carries a numeric `aria-valuenow` only when the
 * limit is known, so an unknown limit is never drawn as empty capacity.
 */
export function ProviderRateBars({ providerName, progress }: ProviderRateBarsProps): ReactNode {
  const bars = progress
    .filter((entry) => entry.window === "1h" || entry.window === "1d")
    .map((entry) => rateBarModel({ progress: entry }))
  if (bars.length === 0) return null

  return (
    <div className="space-y-2">
      {bars.map((bar) => {
        const windowText = WINDOW_TEXT[bar.window]
        const unitText = UNIT_TEXT[bar.unit]
        return (
          <div key={bar.bucketId + "-" + bar.window} className="space-y-1">
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <span className="text-[var(--text-strong)]">
                {bar.operation === "search" ? "Search" : "Fetch"} {windowText} rate
              </span>
              <span className="tnum text-[var(--text)]">
                {rateText(bar.remaining, bar.limit)} {unitText}
              </span>
            </div>
            {bar.percentRemaining !== null && (
              <div
                className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"
                role="progressbar"
                aria-label={
                  providerName + " " + bar.operation + " " + windowText + " " + unitText + " remaining"
                }
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={bar.percentRemaining}
              >
                <div
                  className="h-full rounded-full bg-[var(--status-warning)]"
                  style={{ width: bar.percentRemaining + "%" }}
                />
              </div>
            )}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--muted)]">
              {confidenceCell(bar.confidence)}
              {bar.kind === "free_daily_allowance" && <span>Free daily allowance</span>}
              {bar.resetAt !== null && <span>Resets {bar.resetAt}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
