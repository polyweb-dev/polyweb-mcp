import { catalogFree, catalogQuotaInfo } from "../model/catalogQuota"
import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Tag } from "@/shared/ui/Tag"
import { manualDefaults, rowBalance, hideRowRefresh } from "../model/providerUsageFacts"
import type { DashboardQuota, ProviderLimits } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { manualUnit, type ManualUnit } from "../model/manualQuotaUnit"
import type { ProviderCardView } from "../model/providerCardView"
import { providerInfo, type BalancePrefill } from "../model/providerInfo"
import { refreshNote } from "../model/refreshNote"
import { useManualQuota } from "../model/useManualQuota"
import { useProviderLimits } from "../model/useProviderLimits"
import { ProviderCardActions } from "./ProviderCardActions"
import { ProviderCardMenu, type CardModal } from "./ProviderCardMenu"
import { ProviderCardModals } from "./ProviderCardModals"
import type { OAuthSlotArgs } from "../model/oauthSlot"
import { cardEstimates } from "../model/providerCardFunds"
import { ProviderInfoPopover } from "./ProviderInfoPopover"
import { KeyBalancesLayoutScope, KeyBalancesRefreshScope } from "../model/keyBalanceContext"

export interface ProviderUsageRowProps {
  catalogProvider?: ProviderConfig
  providerId: string
  providerName: string
  limits: ProviderLimits
  view: ProviderCardView
  refreshDashboard: () => Promise<void>
  manualEligible: boolean
  keyBalances?: ReactNode
  providers?: ProviderConfig[]
  providerUnits?: Readonly<Record<string, ManualUnit>>
  observed?: Record<string, BalancePrefill>
  latestQuota?: DashboardQuota
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

/**
 * One compact row of a provider that reports no usage: the logo, the name,
 * one quiet status, Refresh when the provider can be read, and the same `…`
 * menu as a card. A keyless provider has nothing to refresh.
 */
export function ProviderUsageRow(props: ProviderUsageRowProps): ReactNode {
  const { providerId, providerName, limits, view, refreshDashboard, manualEligible } = props
  const [actionsTarget, setActionsTarget] = useState<HTMLElement | null>(null)
  const [modal, setModal] = useState<CardModal>(null)
  const [, setPaired] = useState(false)
  const controller = useProviderLimits({ providerId, limits, refreshDashboard, historyOpen: modal === "history" })
  const manualState = useManualQuota(providerId, manualEligible)
  const defaults = useMemo(() => manualDefaults(manualState.manual), [manualState.manual])
  const info = catalogQuotaInfo(providerInfo(view.auth, providerId, view.rule.wholeRequests), props.catalogProvider, view.auth.auth_mode)
  const free = catalogFree(props.catalogProvider, view.auth.auth_mode) ?? view.free
  const status = rowBalance(view)
  const note = view.refreshable ? refreshNote(controller, view.reports) : null
  const estimates = cardEstimates(providerId, props.latestQuota, view.model, manualState.estimate)
  const oauthActions = props.renderOAuthActions?.({ providerId, providerName, ...estimates, onPairedChange: setPaired })
  return (
    <tr>
      <td className="px-4 py-3 align-top">
      <div className="flex min-h-8 items-center gap-3">
      <ProviderLogo providerId={providerId} name={providerName} />
      <h4 className="min-w-0 truncate text-[13px] font-medium text-[var(--text-strong)]">{providerName}</h4>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--muted)]">{status}</span>
      {free && <Tag tone="neutral">Free</Tag>}
      <div ref={setActionsTarget} className="flex items-center gap-2" />
      <ProviderCardActions
        providerName={providerName}
        syncing={controller.syncing}
        updatedAt={controller.updatedAt}
        onSync={() => void controller.syncNow()}
        refreshSkipped={hideRowRefresh(view, controller, props.keyBalances != null)}
        syncNote={note === status ? null : note}
        oauthActions={oauthActions}
      />
      <ProviderInfoPopover providerId={providerId} providerName={providerName} info={info} auth={view.auth}
        {...(view.nativeDisplay === null ? {} : { nativeDisplay: view.nativeDisplay })} />
      <ProviderCardMenu providerName={providerName} manualEligible={manualEligible && !free} budgetAllowed={!free} onOpenModal={setModal} />
      </div>
      <ProviderCardModals
        providerId={providerId}
        providerName={providerName}
        modal={modal}
        manualEligible={manualEligible}
        unit={manualUnit(view.auth, providerId)}
        defaults={defaults}
        manual={manualState}
        controller={controller}
        auth={view.auth}
        fetchAvailable={view.fetchAvailable}
        creditMode={info.creditMode}
        nativeDisplay={view.nativeDisplay}
        providers={props.providers}
        providerUnits={props.providerUnits}
        observed={props.observed}
        refreshDashboard={refreshDashboard}
        onClose={() => setModal(null)}
      />
      </td>
      <td colSpan={2} className="px-4 py-3 align-top">
        <KeyBalancesLayoutScope.Provider value={{ compact: true, actionsTarget }}>
          <KeyBalancesRefreshScope.Provider value={view.refreshable}>{props.keyBalances ?? "—"}</KeyBalancesRefreshScope.Provider>
        </KeyBalancesLayoutScope.Provider>
      </td>

    </tr>
  )
}
