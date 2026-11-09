import { useMemo } from "react"
import type { ReactNode } from "react"
import { usePolyweb } from "@/context/usePolyweb"
import { PageHeader } from "@/shared/ui/PageHeader"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { manualEligibleProviders } from "../model/quotaRowModel"
import { ProviderLimitsCards } from "./ProviderLimitsCards"
import type { RateTierSlotArgs } from "./ProviderLimitsCard"
import type { OAuthSlotArgs } from "../model/oauthSlot"
import { UsageTotals } from "./UsageTotals"

export interface QuotaPageProps {
  manualQuotaEligible?: typeof isManualQuotaEligible
  refreshableProviders?: ReadonlySet<string>
  renderKeyBalances?: ((providerId: string, providerName: string) => ReactNode) | undefined
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
 * Show provider balances and recorded usage totals.
 */
export function QuotaPage({
  manualQuotaEligible = isManualQuotaEligible,
  refreshableProviders,
  renderKeyBalances,
  renderOAuthActions,
  renderRateTier,
}: QuotaPageProps): ReactNode {
  const {
    providers,
    providerLimits,
    usdUsageTotals,
    dashboardQuotas,
    usageLoading,
    usageError,
    refreshDashboard,
  } = usePolyweb()

  const manualEligible = useMemo(
    () => manualEligibleProviders(providers, dashboardQuotas, manualQuotaEligible),
    [providers, dashboardQuotas, manualQuotaEligible]
  )

  return (
    <div className="space-y-8">
      <PageHeader
        title="Quotas"
        description="Provider balances and allowances across all projects"
      />

      {usageError && (
        <p role="alert" className="fs-panel px-4 py-3 text-[13px] text-[var(--status-danger)]">
          Usage data unavailable: {usageError}
        </p>
      )}

      {usageLoading && (
        <p className="text-[13px] text-[var(--muted)]" role="status">Loading usage…</p>
      )}

      <ProviderLimitsCards
        providers={providers}
        providerLimits={providerLimits}
        usdUsageTotals={usdUsageTotals}
        refreshDashboard={refreshDashboard}
        manualEligible={manualEligible}
        {...(refreshableProviders !== undefined ? { refreshableProviders } : {})}
        {...(renderKeyBalances !== undefined ? { renderKeyBalances } : {})}
        dashboardQuotas={dashboardQuotas}
        {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
        {...(renderRateTier !== undefined ? { renderRateTier } : {})}
      />

      <UsageTotals usdUsageTotals={usdUsageTotals} providers={providers} />

    </div>
  )
}
