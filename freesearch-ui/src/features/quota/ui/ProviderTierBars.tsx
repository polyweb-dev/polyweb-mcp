import type { ReactNode } from "react"
import type { TierBalance, TierBarView } from "@/domains/dashboard"
import { formatCRDAmount, tierBarModel } from "../model/crdDisplay"

export interface ProviderTierBarsProps {
  providerName: string
  freeTiers: TierBalance[]
  paidTiers: TierBalance[]
  tierSplitKnown: boolean
}

/** Known tier amounts only; an unknown tier yields no row at all. */
function barAmount(bar: TierBarView): string | null {
  if (bar.state === "unmetered") return "Free - unmetered"
  if (bar.state === "postpaid") return "Postpaid access"
  if (bar.remainingCRD === null) return null
  if (bar.allowanceCRD === null) return formatCRDAmount(bar.remainingCRD)
  return formatCRDAmount(bar.remainingCRD) + " of " + formatCRDAmount(bar.allowanceCRD)
}

/** Reset notes of the known facts only; an unknown rule stays absent. */
function knownNotes(bar: TierBarView): string[] {
  return bar.resetNotes.filter((note) => !/unknown|unavailable/i.test(note))
}

/**
 * Free and Paid credit-unit facts of one provider card.
 *
 * The two tiers stay separate, because a combined amount would invent a split
 * the vendor did not report. These are detail rows only: the card body carries
 * the one funds bar, so no second funds bar appears here.
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
  const rows = bars
    .map((bar) => ({ bar, amount: barAmount(bar) }))
    .filter((row): row is { bar: TierBarView; amount: string } => row.amount !== null)
  if (rows.length === 0) return null

  return (
    <dl className="space-y-1 border-t border-[var(--border-subtle)] pt-3 text-[12px]" aria-label={providerName + " tier balances"}>
      {rows.map(({ bar, amount }) => {
        const notes = knownNotes(bar)
        return (
          <div
            key={bar.tier}
            className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5"
          >
            <dt className="text-[var(--muted)]">
              {bar.tier === "free" ? "Free tier" : "Paid tier"}
            </dt>
            <dd className="tnum text-right text-[var(--text)]">{amount}</dd>
            {notes.length > 0 && (
              <dd className="w-full text-[11px] text-[var(--muted)]">{notes.join(" · ")}</dd>
            )}
          </div>
        )
      })}
    </dl>
  )
}
