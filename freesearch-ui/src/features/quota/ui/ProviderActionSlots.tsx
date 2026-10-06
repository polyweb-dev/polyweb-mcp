import type { ReactNode } from "react"
import type { DashboardQuota, ProviderLimits } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { ProviderActionSlot } from "./ProviderActionSlot"
import type { OAuthSlotArgs } from "./QuotaRow"

export interface ProviderActionSlotsProps {
  providers: ProviderConfig[]
  dashboardQuotas: DashboardQuota[]
  /** The reported limit entries that already own a credit-unit card. */
  providerLimits: ProviderLimits[]
  manualQuotaEligible: typeof isManualQuotaEligible
  /**
   * OAuth pairing controls per provider. Supplied by composition (the quota
   * overlay stays in app composition), so the quota feature never imports the
   * OAuth feature directly.
   */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

/**
 * Action-only page slot of the configured providers.
 *
 * The legacy quota grid mounted one row per provider; this section mounts only
 * the actions and the saved manual estimate, so no native balance column and no
 * native window column returns to the page. A provider with a credit-unit card
 * holds its manual action on that card, so one manual entry point stays per
 * provider.
 */
export function ProviderActionSlots({
  providers,
  dashboardQuotas,
  providerLimits,
  manualQuotaEligible,
  renderOAuthActions,
}: ProviderActionSlotsProps): ReactNode {
  return (
    <section aria-labelledby="provider-actions-heading" className="space-y-3">
      <div>
        <h3 id="provider-actions-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">
          Provider actions
        </h3>
        <p className="mt-1 text-[12px] text-[var(--muted)]">
          Account pairing, manual entries, and saved manual estimates. Funds and credit units appear
          on the cards above.
        </p>
      </div>
      {providers.map((provider) => (
        <ProviderActionSlot
          key={provider.id}
          provider={provider}
          latestQuota={dashboardQuotas.find((quota) => quota.provider === provider.id)}
          manualQuotaEligible={manualQuotaEligible}
          hasCard={providerLimits.some((entry) => entry.provider === provider.id)}
          {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
        />
      ))}
    </section>
  )
}
