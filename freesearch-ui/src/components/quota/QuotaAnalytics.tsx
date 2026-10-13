import type { FC } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { QuotaPage } from "@/features/quota/ui/QuotaPage"
import type { RateTierSlotArgs } from "@/features/quota/ui/ProviderLimitsCard"
import { isManualQuotaEligible } from "@/features/quota/model/quotaEligibility"
import { ParallelOAuthActions } from "../oauth/ParallelOAuthActions"
import { TavilyRateTierSelect } from "../settings/TavilyRateTierSelect"

/**
 * Compatibility shell: the usage route keeps rendering QuotaAnalytics while
 * the quota feature owns the page. OAuth pairing stays composed here (app
 * composition owns the quota overlay) so features never import each other.
 * The Tavily tier control stays composed here too, so the quota feature never
 * imports the Settings feature directly.
 */
export const QuotaAnalytics: FC<{
  manualQuotaEligible?: typeof isManualQuotaEligible
}> = ({ manualQuotaEligible = isManualQuotaEligible }) => {
  const { providers, canEditControls, refreshProviders, refreshDashboard } = useFreeSearch()

  const renderRateTier = (slotArgs: RateTierSlotArgs) => {
    if (slotArgs.providerId !== "tavily") return null
    const provider = providers.find((entry) => entry.id === "tavily")
    if (provider === undefined) return null
    return (
      <TavilyRateTierSelect
        provider={provider}
        canEdit={canEditControls}
        compact
        onConfirmed={slotArgs.onConfirmed}
        onUpdated={async () => {
          await refreshProviders()
          await refreshDashboard()
        }}
      />
    )
  }

  return (
    <QuotaPage
      manualQuotaEligible={manualQuotaEligible}
      renderOAuthActions={(slotArgs) =>
        slotArgs.providerId === "parallel" ? (
          <ParallelOAuthActions {...slotArgs} />
        ) : null
      }
      renderRateTier={renderRateTier}
    />
  )
}


