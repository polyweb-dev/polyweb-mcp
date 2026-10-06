import type { ProviderConfig } from "@/domains/providers"
import { isMissingQuotaSnapshot } from "@/domains/dashboard"
import type { DashboardQuota } from "@/domains/dashboard"
import { isManualQuotaEligible } from "./quotaEligibility"
import { resolveQuota } from "./quotaDetails"
import type { ManualQuotaEstimate } from "./useManualQuota"

export interface QuotaRowEstimates {
  hasUsableEstimate: boolean
  pairedSnapshot: boolean
}

/**
 * Providers that may hold a manual native anchor under the current dashboard
 * snapshot. Eligibility keeps its current rule: Brave always, and the other
 * providers only while no vendor budget is configured.
 */
export function manualEligibleProviders(
  providers: ProviderConfig[],
  dashboardQuotas: DashboardQuota[],
  manualQuotaEligible: typeof isManualQuotaEligible
): Set<string> {
  const ids = new Set<string>()
  for (const provider of providers) {
    const latest = dashboardQuotas.find((quota) => quota.provider === provider.id)
    const { display } = resolveQuota(provider, latest)
    const budgetNotConfigured = manualBudgetMissing(provider, latest, display.remainingPercent)
    if (manualQuotaEligible(provider.id, budgetNotConfigured)) ids.add(provider.id)
  }
  return ids
}

/**
 * Whether Exa/Parallel/Tinyfish lack a vendor budget (Brave callers always pass an
 * eligible row). A missing snapshot with no comparable percentage means the
 * row can only offer Manual Entry.
 */
export function manualBudgetMissing(
  provider: ProviderConfig,
  latestQuota: DashboardQuota | undefined,
  remainingPercent: number | null
): boolean {
  const noSnapshot = isMissingQuotaSnapshot(latestQuota)
  return (
    ["exa", "parallel", "tinyfish"].includes(provider.id) &&
    noSnapshot &&
    remainingPercent === null
  )
}

/**
 * Row-level pairing decisions. A usable estimate — vendor percent, manual
 * window, or reported balance — means there is nothing to connect. An
 * AUTHORITATIVE remaining-only snapshot is itself pairing evidence, so
 * Disconnect stays available even when the status endpoint is unreachable.
 */
export function resolveQuotaRow(
  provider: ProviderConfig,
  latestQuota: DashboardQuota | undefined,
  remainingPercent: number | null,
  manualEstimate: ManualQuotaEstimate | null
): QuotaRowEstimates {
  const vendorBalance = latestQuota !== undefined && latestQuota.remaining !== null
  return {
    hasUsableEstimate:
      remainingPercent !== null || manualEstimate !== null || vendorBalance,
    pairedSnapshot:
      provider.id === "parallel" &&
      latestQuota?.source === "authoritative" &&
      latestQuota.remaining !== null,
  }
}
