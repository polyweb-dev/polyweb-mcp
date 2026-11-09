import type { ReactNode } from "react"
import type { ProviderAuthLimits } from "@/domains/dashboard"
import type { BackendManualQuotaPayload } from "@/domains/dashboard/api/manualQuotaWire"
import type { ProviderConfig } from "@/domains/providers"
import type { ManualUnit } from "../model/manualQuotaUnit"
import type { BalancePrefill } from "../model/providerInfo"
import type { CreditMode } from "../model/quotaLabels"
import { profileOf, type TavilyDisplayAdapter } from "../model/tavilyCredits"
import { saveManualQuotaFor, type ManualQuotaOverlay } from "../model/useManualQuota"
import type { ProviderLimitsController } from "../model/useProviderLimits"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import { UsdGrantForm } from "./UsdGrantForm"
import { LimitHistoryModal } from "./LimitHistoryModal"
import { ManualQuotaModal } from "./ManualQuotaModal"
import type { CardModal } from "./ProviderCardMenu"

export interface ProviderCardModalsProps {
  providerId: string
  providerName: string
  modal: CardModal
  manualEligible: boolean
  unit: ManualUnit
  defaults: ManualQuotaDefaults | null
  manual: ManualQuotaOverlay
  controller: ProviderLimitsController
  auth: ProviderAuthLimits
  fetchAvailable: boolean
  creditMode: CreditMode | null
  /** The native display inputs of one Tavily rail; null on every other card. */
  nativeDisplay: TavilyDisplayAdapter | null
  providers: ProviderConfig[] | undefined
  providerUnits: Readonly<Record<string, ManualUnit>> | undefined
  observed: Record<string, BalancePrefill> | undefined
  refreshDashboard: () => Promise<void>
  onClose: () => void
}

/** A new stored grant remounts the form, so its draft starts from the server. */
function grantKey(auth: ProviderAuthLimits): string {
  const grants = auth.grants
  if (grants === null) return auth.auth_mode + "-none"
  return auth.auth_mode + "-" + grants.version + "-" + grants.period
}

/**
 * Save one manual entry for the target provider through the one PUT path.
 *
 * The own provider keeps its overlay save, so the card updates at once. Any
 * other target uses the same route and then refreshes the dashboard.
 */
async function saveManual(
  input: ProviderCardModalsProps,
  providerId: string,
  payload: BackendManualQuotaPayload,
): Promise<void> {
  if (providerId === input.providerId) return input.manual.save(payload)
  await saveManualQuotaFor(providerId, payload)
  await input.refreshDashboard()
}

function manualModal(input: ProviderCardModalsProps): ReactNode {
  const { providerId, providerName, unit, manual } = input
  return (
    <ManualQuotaModal
      open
      providerId={providerId}
      providerName={providerName}
      unitKind={unit.unitKind}
      displayUnit={unit.displayUnit}
      defaults={input.defaults}
      amountMode={unit.amountMode}
      creditMode={input.creditMode ?? "free"}
      {...(input.providers !== undefined ? { providers: input.providers } : {})}
      {...(input.providerUnits !== undefined ? { providerUnits: input.providerUnits } : {})}
      {...(input.observed !== undefined ? { observed: input.observed } : {})}
      onClose={input.onClose}
      onSave={(payload, targetId) => saveManual(input, targetId ?? providerId, payload)}
      {...(manual.manual !== null ? { onDelete: manual.remove } : {})}
    />
  )
}

function grantModal(input: ProviderCardModalsProps): ReactNode {
  const { providerId, providerName, controller, auth } = input
  return (
    <ManualQuotaModal mode="grant" open providerId={providerId} providerName={providerName} onClose={input.onClose}>
      <UsdGrantForm
        key={grantKey(auth)}
        providerName={providerName}
        authMode={auth.auth_mode}
        grants={auth.grants}
        fetchAvailable={input.fetchAvailable}
        saving={controller.saving}
        saveError={controller.saveError}
        staleVersion={controller.staleVersion}
        {...(input.nativeDisplay !== null ? { nativeDisplay: input.nativeDisplay } : {})}
        onSave={controller.saveGrant}
        onClose={input.onClose}
        onReload={() => void controller.reload()}
      />
    </ManualQuotaModal>
  )
}

function historyModal(input: ProviderCardModalsProps): ReactNode {
  const { controller } = input
  // The history view converts a Usd-only Tavily amount with the live rail
  // profile, the same auth every other dialog of this card reads.
  const profile = profileOf(input.auth)
  return (
    <LimitHistoryModal
      open
      providerName={input.providerName}
      events={controller.history}
      loading={controller.historyLoading}
      error={controller.historyError}
      hasMore={controller.hasMoreHistory}
      nativeUnit={input.auth.aggregate_pool?.native_unit ?? input.auth.detail?.native_unit ?? null}
      onLoadMore={controller.loadMoreHistory}
      {...(profile !== null ? { profile } : {})}
      onClose={input.onClose}
    />
  )
}

/** At most one dialog of a card stays mounted, so one card opens one dialog. */
export function ProviderCardModals(props: ProviderCardModalsProps): ReactNode {
  if (props.modal === "manual" && props.manualEligible) return manualModal(props)
  if (props.modal === "grant") return grantModal(props)
  if (props.modal === "history") return historyModal(props)
  return null
}
