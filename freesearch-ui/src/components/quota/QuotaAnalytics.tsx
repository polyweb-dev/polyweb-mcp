import type { FC } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { QuotaPage } from "@/features/quota/ui/QuotaPage"
import type { RateTierSlotArgs } from "@/features/quota/ui/ProviderLimitsCard"
import { isManualQuotaEligible } from "@/features/quota/model/quotaEligibility"
import { TavilyRateTierSelect } from "../settings/TavilyRateTierSelect"

/**
 * Compatibility shell: the usage route keeps rendering QuotaAnalytics while
 * the quota feature owns the page. The Tavily tier control stays composed
 * here, so the quota feature never imports the Settings feature directly.
 * Parallel OAuth no longer pairs from this page: OAuth belongs to one
 * credential instance and connects from its credential row (U3).
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
      renderRateTier={renderRateTier}
    />
  )
}


