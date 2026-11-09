/**
 * Funds facts of one provider card that the card body reads: the row
 * estimates, the OAuth balance fallback, and the confirmed Tavily minute
 * ceiling. No allowance is ever invented for display.
 */

import type { DashboardQuota, ProviderAuthLimits } from "@/domains/dashboard"
import { type CreditCardModel } from "./usdCardModel"
import { pairedSnapshotOf, type QuotaRowEstimates } from "./quotaRowModel"
import type { ManualQuotaEstimate } from "./useManualQuota"

const YOUCOM_PROVIDER = "youcom"

/**
 * The two row facts of one card: its estimates and its pair evidence.
 *
 * A vendor percent, a manual estimate, a reported remaining balance, or
 * dashboard vendor funds is a usable estimate. The dashboard remaining matters
 * for Parallel and You.com, whose balances live in the dashboard quota row.
 */
export function cardEstimates(
  providerId: string,
  latestQuota: DashboardQuota | undefined,
  model: CreditCardModel,
  manualEstimate: ManualQuotaEstimate | null,
): QuotaRowEstimates {
  const vendorBalance = latestQuota !== undefined && latestQuota.remaining !== null
  const vendorPercent = latestQuota?.remainingPercent != null
  return {
    hasUsableEstimate:
      model.percentRemaining !== null ||
      manualEstimate !== null ||
      model.remainingUsd !== null ||
      vendorBalance ||
      vendorPercent,
    pairedSnapshot: pairedSnapshotOf(providerId, latestQuota),
  }
}

export interface BalanceFallback { usd: string; allowanceUsd: string | null }

function fallbackSourceOk(providerId: string, source: string | undefined): boolean {
  if (providerId === YOUCOM_PROVIDER) return source === "authoritative" || source === "estimated"
  return source === "authoritative"
}

/**
 * OAuth balance fallback of one card: the Parallel Account-API balance and the
 * You.com cents balance live in the dashboard quota row, not in the limits
 * model. A remaining-only snapshot yields the raw USD with its Usd equivalent
 * and no allowance, so the card shows the amount alone.
 */
export function balanceFallbackOf(
  providerId: string,
  model: CreditCardModel,
  latestQuota: DashboardQuota | undefined,
): BalanceFallback | null {
  if (model.remainingUsd !== null || latestQuota === undefined) return null
  if (!fallbackSourceOk(providerId, latestQuota.source)) return null
  if (latestQuota.remaining === null || latestQuota.remaining.trim() === "") return null
  if (latestQuota.limit !== null || latestQuota.remainingPercent != null) return null
  const usd = latestQuota.remaining
  return { usd, allowanceUsd: null }
}

/** The confirmed minute ceiling of one Tavily key environment. */
export const TAVILY_CEILING_OF_ENV: Record<"dev" | "prod", string> = {
  dev: "100",
  prod: "1000",
}

/** A known text of one field; an absent, empty, or unknown value yields null. */
function knownText(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === "unknown" || text === "n/a") return null
  return text
}

/** The current dashboard minute ceiling of one rail, or null when unknown. */
export function dashboardMinuteCeiling(auth: ProviderAuthLimits): string | null {
  const windows = auth.detail?.rate_windows ?? []
  const minute = windows.find((entry) => entry.window === "1m")
  const limit = knownText(minute?.limit ?? null)
  return limit === null ? null : limit.trim().replace(/\.0+$/, "")
}
