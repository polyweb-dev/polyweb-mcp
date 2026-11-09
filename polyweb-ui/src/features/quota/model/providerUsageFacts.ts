import type { BackendManualQuota } from "@/domains/dashboard/api/manualQuotaWire"
import type { ManualQuotaDefaults } from "./useQuotaForm"
import type { ProviderCardView } from "./providerCardView"
import type { ProviderLimitsController } from "./useProviderLimits"
import { nativeLeftText } from "./numberText"

export function manualDefaults(manual: BackendManualQuota | null): ManualQuotaDefaults | null {
  return manual === null ? null : { billingStart: manual.billing_start, billingEnd: manual.billing_end,
    allowance: manual.allowance, used: manual.current_usage }
}

export function rowBalance(view: ProviderCardView): string | null {
  const status = view.amountText ?? (view.fallback === null ? null : nativeLeftText(view.fallback.usd, "USD"))
  return status && view.auth.aggregate_pool?.manual_anchor ? status + " · manual balance" : status
}

export function hideRowRefresh(view: ProviderCardView, controller: ProviderLimitsController, hasKeys: boolean): boolean {
  return hasKeys || !view.refreshable || controller.refreshSkipped
}
