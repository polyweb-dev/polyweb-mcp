import { useState } from "react"
import type { ReactNode } from "react"
import type { DashboardQuota } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { isManualQuotaEligible } from "../model/quotaEligibility"
import { resolveQuota } from "../model/quotaDetails"
import { manualBudgetMissing, resolveQuotaRow } from "../model/quotaRowModel"
import { BALANCE_ENTRY, BALANCE_ENTRY_NOTE } from "../model/quotaLabels"
import { useManualQuota } from "../model/useManualQuota"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import { ManualBudgetButton } from "./ManualBudgetButton"
import { ManualHeadline } from "./ManualHeadline"
import { ManualQuotaModal } from "./ManualQuotaModal"
import type { OAuthSlotArgs } from "./QuotaRow"

export interface ProviderActionSlotProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
  manualQuotaEligible: typeof isManualQuotaEligible
  /** A provider with a credit-unit card holds its manual action on that card. */
  hasCard: boolean
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

function manualDefaultsOf(manual: {
  billing_start: string
  billing_end: string
  allowance: string
  current_usage: string
} | null): ManualQuotaDefaults | null {
  if (manual === null) return null
  return {
    billingStart: manual.billing_start,
    billingEnd: manual.billing_end,
    allowance: manual.allowance,
    used: manual.current_usage,
  }
}

/**
 * One provider action row: the saved manual estimate, the manual anchor
 * action, and the composed OAuth action.
 *
 * The row uses the current row selectors for its estimate and paired-state
 * arguments. It holds the manual action of a provider without a credit-unit
 * card, so every eligible provider keeps one manual entry point. The row
 * renders nothing when it holds no action.
 */
export function ProviderActionSlot({
  provider,
  latestQuota,
  manualQuotaEligible,
  hasCard,
  renderOAuthActions,
}: ProviderActionSlotProps): ReactNode {
  const [oauthPaired, setOauthPaired] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const { display, unitKind, displayUnit } = resolveQuota(provider, latestQuota, oauthPaired)
  const budgetNotConfigured = manualBudgetMissing(provider, latestQuota, display.remainingPercent)
  const eligible = manualQuotaEligible(provider.id, budgetNotConfigured)
  const { manual, estimate, save, remove } = useManualQuota(provider.id, eligible)
  const { hasUsableEstimate, pairedSnapshot } = resolveQuotaRow(
    provider,
    latestQuota,
    display.remainingPercent,
    estimate
  )
  const oauth =
    renderOAuthActions === undefined
      ? null
      : renderOAuthActions({
          providerId: provider.id,
          providerName: provider.name,
          hasUsableEstimate,
          pairedSnapshot,
          onPairedChange: setOauthPaired,
        })
  const showManual = eligible && !hasCard
  if (oauth === null && estimate === null && !showManual) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-[13px] text-[var(--text-strong)]">{provider.name}</span>
        {estimate !== null && (
          <div className="flex flex-col gap-1">
            <ManualHeadline
              providerId={provider.id}
              providerName={provider.name}
              estimate={estimate}
            />
            <span className="text-[11px] text-[var(--muted)]">{estimate.rangeText}</span>
          </div>
        )}
      </div>
      <span className="flex flex-wrap items-center justify-end gap-2">
        {showManual && (
          <ManualBudgetButton
            providerId={provider.id}
            providerName={provider.name}
            label={BALANCE_ENTRY}
            note={BALANCE_ENTRY_NOTE}
            onOpen={() => setManualOpen(true)}
          />
        )}
        {oauth}
      </span>
      {manualOpen && (
        <ManualQuotaModal
          open
          providerId={provider.id}
          providerName={provider.name}
          unitKind={unitKind}
          displayUnit={displayUnit}
          defaults={manualDefaultsOf(manual)}
          onClose={() => setManualOpen(false)}
          onSave={save}
          {...(manual !== null ? { onDelete: remove } : {})}
        />
      )}
    </div>
  )
}
