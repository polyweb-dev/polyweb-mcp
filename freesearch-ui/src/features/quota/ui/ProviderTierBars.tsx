import type { ReactNode } from "react"
import type { CRDConfidence, TierBalance, TierBarView } from "@/domains/dashboard"
import { formatCRDAmount, tierBarModel } from "../model/crdDisplay"
import { ConfidenceLabel } from "./ConfidenceLabel"

export interface ProviderTierBarsProps {
  providerName: string
  freeTiers: TierBalance[]
  paidTiers: TierBalance[]
  tierSplitKnown: boolean
}

const STATE_TEXT: Record<TierBarView["state"], string> = {
  finite: "Remaining",
  unmetered: "Free - unmetered",
  postpaid: "Postpaid access",
  unknown: "Unknown",
}

function barAmount(bar: TierBarView): string {
  if (bar.state !== "finite") return STATE_TEXT[bar.state]
  if (bar.remainingCRD === null) return "Unknown"
  if (bar.allowanceCRD === null) return formatCRDAmount(bar.remainingCRD)
  return formatCRDAmount(bar.remainingCRD) + " of " + formatCRDAmount(bar.allowanceCRD)
}

function confidenceCell(confidence: CRDConfidence): ReactNode {
  if (confidence === "unknown") {
    return <span className="text-[11px] text-[var(--muted)]">unknown</span>
  }
  return <ConfidenceLabel confidence={confidence} />
}

/**
 * Free and Paid credit-unit bars of one provider card.
 *
 * The two tiers stay separate: a combined bar would invent a split the vendor
 * did not report. A percentage appears only when the allowance is known.
 */
export function ProviderTierBars({
  providerName,
  freeTiers,
  paidTiers,
  tierSplitKnown,
}: ProviderTierBarsProps): ReactNode {
  const bars: TierBarView[] = []
  if (freeTiers.length > 0 || !tierSplitKnown) {
    bars.push(tierBarModel({ tier: "free", balances: freeTiers, tierSplitKnown }))
  }
  if (paidTiers.length > 0 || !tierSplitKnown) {
    bars.push(tierBarModel({ tier: "paid", balances: paidTiers, tierSplitKnown }))
  }
  if (bars.length === 0) return null

  return (
    <div className="space-y-2.5">
      {bars.map((bar) => (
        <div key={bar.tier} className="space-y-1">
          <div className="flex items-center justify-between gap-2 text-[12px]">
            <span className="text-[var(--text-strong)]">
              {bar.tier === "free" ? "Free tier" : "Paid tier"}
            </span>
            <span className="tnum text-[var(--text)]">{barAmount(bar)}</span>
          </div>
          {bar.percentRemaining !== null && (
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"
              role="progressbar"
              aria-label={providerName + " " + bar.tier + " tier credit units remaining"}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={bar.percentRemaining}
            >
              <div
                className="h-full rounded-full bg-[var(--signal)]"
                style={{ width: bar.percentRemaining + "%" }}
              />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--muted)]">
            {confidenceCell(bar.confidence)}
            {bar.resetNotes.map((note) => (
              <span key={note}>{note}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
