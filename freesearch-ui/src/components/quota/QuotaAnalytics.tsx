import type { FC } from "react"
import { QuotaPage } from "@/features/quota/ui/QuotaPage"
import { isManualQuotaEligible } from "@/features/quota/model/quotaEligibility"
import { ParallelOAuthActions } from "../oauth/ParallelOAuthActions"

/**
 * Compatibility shell: the usage route keeps rendering QuotaAnalytics while
 * the quota feature owns the page. OAuth pairing stays composed here (app
 * composition owns the quota overlay) so features never import each other.
 */
export const QuotaAnalytics: FC<{
  manualQuotaEligible?: typeof isManualQuotaEligible
}> = ({ manualQuotaEligible = isManualQuotaEligible }) => (
  <QuotaPage
    manualQuotaEligible={manualQuotaEligible}
    renderOAuthActions={({ providerId, providerName, hasUsableEstimate, pairedSnapshot }) =>
      providerId === "parallel" ? (
        <ParallelOAuthActions
          providerId={providerId}
          providerName={providerName}
          hasUsableEstimate={hasUsableEstimate}
          pairedSnapshot={pairedSnapshot}
        />
      ) : null
    }
  />
)
