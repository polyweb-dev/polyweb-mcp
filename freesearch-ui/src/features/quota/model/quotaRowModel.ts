import type { ProviderConfig } from "@/domains/providers"
import { isMissingQuotaSnapshot } from "@/domains/dashboard"
import type { DashboardQuota } from "@/domains/dashboard"
import type { ManualQuotaEstimate } from "./useManualQuota"

export interface QuotaRowEstimates {
  hasUsableEstimate: boolean
  pairedSnapshot: boolean
}

/**
 * Whether Exa/Parallel lack a vendor budget (Brave callers always pass an
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
    (provider.id === "exa" || provider.id === "parallel") &&
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
