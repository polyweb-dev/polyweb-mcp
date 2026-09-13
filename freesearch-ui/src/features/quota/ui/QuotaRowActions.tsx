import type { ReactNode } from "react"
import type { BackendManualQuota } from "@/domains/dashboard/api/manualQuotaWire"
import type { ProviderConfig } from "@/domains/providers"
import { ManualBudgetButton } from "./ManualBudgetButton"

export interface QuotaRowActionsProps {
  provider: ProviderConfig
  manualEligible: boolean
  manual: BackendManualQuota | null
  onOpenManual: () => void
  oauth: ReactNode
}

/** Row actions: manual budget entry plus the composed OAuth pairing slot. */
export function QuotaRowActions({ provider, manualEligible, manual, onOpenManual, oauth }: QuotaRowActionsProps) {
  if (!manualEligible && oauth === null) return null
  return (
    <span className="flex flex-wrap items-center justify-end gap-2">
      {manualEligible ? (
        <ManualBudgetButton
          providerId={provider.id}
          providerName={provider.name}
          label={manual ? "Update usage" : "Set budget"}
          onOpen={onOpenManual}
        />
      ) : null}
      {oauth}
    </span>
  )
}
