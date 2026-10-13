import { useMemo } from "react"
import type { ReactNode } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { manualEligibleProviders } from "../model/quotaRowModel"
import { CRDPriceNote } from "./CRDPriceNote"
import { Footnote } from "./Footnote"
import { ProviderLimitsCards } from "./ProviderLimitsCards"
import type { RateTierSlotArgs } from "./ProviderLimitsCard"
import type { OAuthSlotArgs } from "./QuotaRow"
import { UsageTotals } from "./UsageTotals"

export interface QuotaPageProps {
  manualQuotaEligible?: typeof isManualQuotaEligible
  /**
   * OAuth pairing controls per provider row. Supplied by composition (the
   * quota overlay stays in app composition) so the quota feature never
   * imports the OAuth feature directly.
   */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
  /**
   * Tavily tier control per provider. Supplied by composition (the quota
   * overlay stays in app composition) so the quota feature never imports the
   * Settings feature directly.
   */
  renderRateTier?: (args: RateTierSlotArgs) => ReactNode
}

/**
 * Usage page: the credit-unit cards, the recorded aggregates, the provider
 * actions, and one price note. The legacy native grid and its cache widgets
 * left this page; the reusable dialog and row parts stay in the feature.
 */
export function QuotaPage({
  manualQuotaEligible = isManualQuotaEligible,
  renderOAuthActions,
  renderRateTier,
}: QuotaPageProps): ReactNode {
  const {
    providers,
    providerLimits,
    crdUsageTotals,
    dashboardQuotas,
    dashboardNotice,
    usageLoading,
    usageError,
    refreshDashboard,
  } = useFreeSearch()

  const manualEligible = useMemo(
    () => manualEligibleProviders(providers, dashboardQuotas, manualQuotaEligible),
    [providers, dashboardQuotas, manualQuotaEligible]
  )

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-2 pb-2 border-b border-[var(--border-subtle)]">
        <h2 className="text-[var(--text-strong)]">Usage</h2>
        <Footnote>
          Credit-unit capacity and recorded provider usage reported by the backend.
        </Footnote>
        {dashboardNotice && <Footnote>{dashboardNotice}</Footnote>}
      </div>

      {usageError && (
        <p
          role="alert"
          className="p-3 rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          Usage data unavailable — {usageError}
        </p>
      )}

      {usageLoading && (
        <p className="text-[13px] text-[var(--muted)]" role="status">Loading usage telemetry...</p>
      )}

      <ProviderLimitsCards
        providers={providers}
        providerLimits={providerLimits}
        crdUsageTotals={crdUsageTotals}
        refreshDashboard={refreshDashboard}
        manualEligible={manualEligible}
        dashboardQuotas={dashboardQuotas}
        {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
        {...(renderRateTier !== undefined ? { renderRateTier } : {})}
      />

      <UsageTotals crdUsageTotals={crdUsageTotals} providers={providers} providerLimits={providerLimits} />

      <CRDPriceNote providers={providers} providerLimits={providerLimits} />
    </div>
  )
}
