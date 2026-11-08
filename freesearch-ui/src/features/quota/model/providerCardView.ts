/**
 * The display facts of one provider usage card, shared by the card list (to
 * split reporting providers from the rest and sort them) and by the card.
 */

import type { CRDUsageTotal, DashboardQuota, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import { activeAuth, creditCardModel, operationAvailable, type CreditCardModel } from "./crdCardModel"
import { dollarText } from "./crdDisplay"
import { nativeLeftText } from "./numberText"
import { multiplyDecimal } from "./manualQuotaMath"
import { balanceFallbackOf, type BalanceFallback } from "./providerCardFunds"
import { providerCardRule, type ProviderCardRule } from "./providerCardRules"
import { rateBarRows } from "./rateBarRows"
import { confirmedFree, reportsVendorUsage } from "./quotaReporting"
import { displayAdapterOf, type TavilyDisplayAdapter } from "./tavilyCredits"

export interface ProviderCardViewInput {
  providerId: string
  limits: ProviderLimits
  usageTotals: CRDUsageTotal[]
  latestQuota: DashboardQuota | undefined
  refreshableOverride?: boolean
}

export interface ProviderCardView {
  auth: ProviderAuthLimits
  rule: ProviderCardRule
  /** The shown funds model; a remaining amount above the allowance carries no percent. */
  model: CreditCardModel
  nativeDisplay: TavilyDisplayAdapter | null
  fallback: BalanceFallback | null
  fetchAvailable: boolean
  hasRateRows: boolean
  keyless: boolean
  /** The card knows funds, Free, a balance, Credits, or a rate window. */
  reports: boolean
  refreshable: boolean
  measurable: boolean
  free: boolean
  /** One amount-only headline when no fraction is honest: "$192.33 left", "1,320 credits left". */
  amountText: string | null
  /** A quiet note beside an amount above the plan allowance. */
  amountNote: string | null
  /** The remaining share for the least-remaining-first order; unknown sorts last. */
  sortShare: number
}

function isAbove(remaining: string, allowance: string): boolean {
  const left = Number(remaining)
  const right = Number(allowance)
  return Number.isFinite(left) && Number.isFinite(right) && right > 0 && left > right
}

/** The remaining pool amount in its own unit, else its USD reference value. */
function leftText(auth: ProviderAuthLimits, remainingCRD: string): string {
  const pool = auth.aggregate_pool
  const native = pool?.remaining == null ? null : nativeLeftText(pool.remaining, pool.native_unit)
  const usd = multiplyDecimal(remainingCRD, "0.001")
  return native ?? (usd === null ? "Not reported" : dollarText(usd) + " left")
}

interface Headline {
  model: CreditCardModel
  amountText: string | null
  amountNote: string | null
}

/**
 * The honest headline of one funds model. A fraction needs a known allowance
 * at least as large as the remaining amount; otherwise the card shows the
 * remaining amount alone, in the provider's own unit, with no bar.
 */
function headlineOf(auth: ProviderAuthLimits, model: CreditCardModel): Headline {
  const remaining = model.remainingCRD
  if (remaining === null) {
    const pool = auth.aggregate_pool
    const amountText = pool?.remaining == null ? null : nativeLeftText(pool.remaining, pool.native_unit)
    return { model, amountText, amountNote: null }
  }
  if (model.state !== "finite") return { model, amountText: null, amountNote: null }
  if (model.allowanceCRD === null) return { model, amountText: leftText(auth, remaining), amountNote: null }
  if (!isAbove(remaining, model.allowanceCRD)) return { model, amountText: null, amountNote: null }
  return {
    model: { ...model, percentRemaining: null },
    amountText: leftText(auth, remaining),
    amountNote: "Includes credits above the plan allowance",
  }
}

function knowsUsage(view: Omit<ProviderCardView, "reports" | "sortShare" | "measurable">): boolean {
  if (view.hasRateRows || view.fallback !== null || view.amountText !== null) return true
  if (view.model.state === "unmetered" || view.model.remainingCRD !== null) return true
  if (view.nativeDisplay === null) return false
  const credits = view.nativeDisplay.credits
  return credits.remaining !== null || credits.allowance !== null || credits.state === "unavailable"
}

/** The display facts of one card, or null when the payload holds no rail. */
export function providerCardView(input: ProviderCardViewInput): ProviderCardView | null {
  const auth = activeAuth(input.limits)
  if (auth === undefined) return null
  const rule = providerCardRule(input.providerId)
  const fetchAvailable = operationAvailable(auth, "fetch")
  const base = creditCardModel({ auth, usageTotals: input.usageTotals })
  const headline = headlineOf(auth, base)
  const partial = {
    auth,
    rule,
    model: headline.model,
    nativeDisplay: displayAdapterOf(input.providerId, auth),
    fallback: balanceFallbackOf(input.providerId, base, input.latestQuota, auth),
    fetchAvailable,
    hasRateRows: !rule.noRateBars && rateBarRows(auth.rate_progress, fetchAvailable, rule.sharedRateBars).length > 0,
    keyless: auth.auth_mode === "keyless",
    amountText: headline.amountText,
    amountNote: headline.amountNote,
    refreshable: reportsVendorUsage(auth) || input.refreshableOverride === true,
    free: confirmedFree(auth),
  }
  const reports = knowsUsage(partial)
  const share = headline.model.percentRemaining ?? nativeShare(partial.nativeDisplay)
  const rateShares = (partial.hasRateRows ? rateBarRows(auth.rate_progress, fetchAvailable, rule.sharedRateBars) : [])
    .flatMap(({ bar }) => bar.percentRemaining === null ? [] : [bar.percentRemaining])
  const measurable = headline.amountText === null && (share !== null || rateShares.length > 0)
  const sortShare = Math.min(share ?? Number.POSITIVE_INFINITY, ...rateShares)
  return { ...partial, reports, measurable, sortShare }
}

function nativeShare(nativeDisplay: TavilyDisplayAdapter | null): number | null {
  if (nativeDisplay === null) return null
  const { remaining, allowance } = nativeDisplay.credits
  if (remaining === null || allowance === null) return null
  const left = Number(remaining)
  const total = Number(allowance)
  return Number.isFinite(left) && total > 0 ? Math.min(100, (left / total) * 100) : null
}
