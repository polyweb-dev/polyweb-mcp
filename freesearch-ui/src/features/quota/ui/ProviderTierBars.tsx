import { multiplyDecimal } from "../model/manualQuotaMath"
import type { ReactNode } from "react"
import type { CRDConversionProfile, TierBalance, TierBarView } from "@/domains/dashboard"
import { dollarText, sumAmounts, tierBarModel } from "../model/crdDisplay"
import { formatTavilyPopoverAmount, tavilyCRDToCredits } from "../model/tavilyCredits"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { groupDigits } from "../model/numberText"

export interface ProviderTierBarsProps {
  providerName: string
  freeTiers: TierBalance[]
  paidTiers: TierBalance[]
  tierSplitKnown: boolean
  nativeDisplay?: TavilyDisplayAdapter
}

/** Known tier amounts only; an unknown tier yields no row at all. */
function barAmount(bar: TierBarView): string | null {
  if (bar.state === "unmetered") return "Free"
  if (bar.state === "postpaid") return "Postpaid access"
  if (bar.remainingCRD === null) return null
  if (bar.allowanceCRD === null) return dollarText(multiplyDecimal(bar.remainingCRD, "0.001") ?? "0")
  return dollarText(multiplyDecimal(bar.remainingCRD, "0.001") ?? "0") + " of " + dollarText(multiplyDecimal(bar.allowanceCRD, "0.001") ?? "0")
}

/** A CREDIT-kind unit text of any casing. */
function isCreditUnit(value: string | null | undefined): boolean {
  return (value ?? "").trim().toUpperCase() === "CREDIT"
}

/** Known text only: an absent, empty, or unknown value yields null. */
function knownAmount(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === "unknown" || text === "n/a") return null
  return text
}

/** Exact Tavily Credits of one tier balance: native fields first, else converted CRD-only values. */
function nativeCreditsOf(
  balance: TierBalance,
  field: "remaining" | "allowance",
  profile: CRDConversionProfile | null,
): string | null {
  if (isCreditUnit(balance.native_unit)) {
    const raw = field === "remaining" ? balance.native_remaining : balance.native_allowance
    const native = knownAmount(raw)
    if (native !== null) return native
  }
  const crdRaw = field === "remaining" ? balance.remaining_crd : balance.allowance_crd
  const crd = knownAmount(crdRaw)
  if (crd === null || profile === null) return null
  return tavilyCRDToCredits(crd, profile)
}

/** Whole Tavily Credits word of one floored integer amount. */
function tavilyWord(amount: string): string {
  return amount === "1" ? "1 Tavily credit" : groupDigits(amount) + " Tavily credits"
}

/** Native Tavily tier amount with integer display; unknown stays null for the generic fallback. */
function nativeTierAmount(balances: TierBalance[], profile: CRDConversionProfile | null): string | null {
  if (balances.length === 0) return null
  const remainings: string[] = []
  for (const balance of balances) {
    const exact = nativeCreditsOf(balance, "remaining", profile)
    if (exact === null) return null
    remainings.push(exact)
  }
  const remainingExact = sumAmounts(remainings)
  const remainingFloored = remainingExact === null ? null : formatTavilyPopoverAmount(remainingExact, "native")
  if (remainingFloored === null) return null
  const remainingWord = tavilyWord(remainingFloored)
  const allowances: string[] = []
  for (const balance of balances) {
    const exact = nativeCreditsOf(balance, "allowance", profile)
    if (exact === null) return remainingWord
    allowances.push(exact)
  }
  if (allowances.length !== balances.length) return remainingWord
  const allowanceExact = sumAmounts(allowances)
  const allowanceFloored = allowanceExact === null ? null : formatTavilyPopoverAmount(allowanceExact, "native")
  if (allowanceFloored === null) return remainingWord
  return remainingWord + " of " + tavilyWord(allowanceFloored)
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
  freeTiers: reportedFreeTiers,
  paidTiers: reportedPaidTiers,
  tierSplitKnown,
  nativeDisplay,
}: ProviderTierBarsProps): ReactNode {
  const freeTiers = reportedFreeTiers.filter((tier) => tier.source !== "operator_grant")
  const paidTiers = reportedPaidTiers.filter((tier) => tier.source !== "operator_grant")
  const bars: TierBarView[] = []
  if (freeTiers.length > 0 || !tierSplitKnown) {
    bars.push(tierBarModel({ tier: "free", balances: freeTiers, tierSplitKnown }))
  }
  if (paidTiers.length > 0 || !tierSplitKnown) {
    bars.push(tierBarModel({ tier: "paid", balances: paidTiers, tierSplitKnown }))
  }
  const rows = bars
    .map((bar) => {
      if (nativeDisplay !== undefined && bar.state !== "unmetered" && bar.state !== "postpaid") {
        const balances = bar.tier === "free" ? freeTiers : paidTiers
        const native = nativeTierAmount(balances, nativeDisplay.profile)
        if (native !== null) return { bar, amount: native }
      }
      return { bar, amount: barAmount(bar) }
    })
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
