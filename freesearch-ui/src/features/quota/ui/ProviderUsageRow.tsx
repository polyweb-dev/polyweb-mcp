import { catalogFree, catalogQuotaInfo } from "../model/catalogQuota"
import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { Tag } from "@/shared/ui/Tag"
import { formatDateTime, formatRelativeTime } from "@/shared/lib/formatTime"
import type { KeyBalance } from "../model/keyBalances"
import { nativeLeftText } from "../model/numberText"
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

function keyBalanceText(key: KeyBalance | null, fallback: string | null, refreshable: boolean): string {
  const amount = key?.balance?.remaining == null ? null : nativeLeftText(key.balance.remaining, key.balance.unit)
  if (amount !== null) return amount
  if (fallback !== null) return fallback
  return key && refreshable && !key.balance?.observedAt ? "Not refreshed yet" : "—"
}

function keyRefreshTime(key: KeyBalance | null, now: number): ReactNode {
  const observedAt = key?.balance?.observedAt
  const timestamp = observedAt ? Date.parse(observedAt) : NaN
  return <span title={observedAt ? formatDateTime(observedAt) : undefined}>
    {observedAt && Number.isFinite(timestamp) ? formatRelativeTime(timestamp, now) : "—"}
  </span>
}

interface TableRowsInput {
  keys: KeyBalance[]
  keyStatus: ReactNode
  refresh: ReactNode
  identity: ReactNode
  actions: ReactNode
  oauthActions: ReactNode
  fallback: string | null
  refreshable: boolean
  now: number
}

function keyOAuthActions(key: KeyBalance | null, actions: ReactNode, status: ReactNode): ReactNode {
  if (key === null) return status == null ? actions : null
  if (key.authMode !== "oauth" || key.oauthConnected !== false) return null
  return <><Tag tone="neutral">Disconnected</Tag>{actions}</>
}

function keyTableRows(input: TableRowsInput): ReactNode {
  const rows: (KeyBalance | null)[] = input.keys.length ? input.keys : [null]
  return rows.map((key, index) => (
    <tr key={key?.keyId ?? "empty"}>
      {index === 0 && <td rowSpan={rows.length} className="fs-cell-strong align-middle">{input.identity}</td>}
      <td className="align-middle">{key?.label ?? input.keyStatus ?? "—"}</td>
      <td className="align-middle">
        {keyBalanceText(key, input.keys.length <= 1 ? input.fallback : null, input.refreshable)}
      </td>
      <td className="align-middle text-[var(--muted)]">{keyRefreshTime(key, input.now)}</td>
      <td className="fs-cell-actions min-w-80 align-middle">
        <div className="flex flex-wrap items-center justify-end gap-2">
          {index === 0 && <>{input.refresh}{input.actions}{input.keys.length > 0 && input.keyStatus}</>}
          {keyOAuthActions(key, input.oauthActions, input.keyStatus)}
        </div>
      </td>
    </tr>
  ))
}

/**
 * One compact row of a provider that reports no usage: the logo, the name,
 * one quiet status, Refresh when the provider can be read, and the same `…`
 * menu as a card. A keyless provider has nothing to refresh.
 */
export function ProviderUsageRow(props: ProviderUsageRowProps): ReactNode {
  const { providerId, providerName, limits, view, refreshDashboard, manualEligible } = props
  const [modal, setModal] = useState<CardModal>(null)
  const [now] = useState(() => Date.now())
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
  const modals = <ProviderCardModals
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
  const identity = <><div className="flex items-center gap-2">
    <ProviderBadge providerId={providerId} name={providerName} />
    <ProviderInfoPopover providerId={providerId} providerName={providerName} info={info} auth={view.auth}
      {...(view.nativeDisplay === null ? {} : { nativeDisplay: view.nativeDisplay })} />
    {free && <Tag tone="neutral">Free</Tag>}
  </div>{modals}</>
  const actions = <>
    <ProviderCardActions providerName={providerName} syncing={controller.syncing}
      updatedAt={controller.updatedAt} onSync={() => void controller.syncNow()}
      refreshSkipped={hideRowRefresh(view, controller, props.keyBalances != null)}
      syncNote={note === status ? null : note} />
    <ProviderCardMenu providerName={providerName} manualEligible={manualEligible && !free}
      budgetAllowed={!free} historyAllowed={!(free && view.auth.rate_progress.some((entry) => entry.source === "local_attempts"))}
      onOpenModal={setModal} />
  </>
  const renderTable = (keys: KeyBalance[], keyStatus: ReactNode, refresh: ReactNode) => {
    if (view.keyless && keys.length === 0 && keyStatus == null) return null
    const fallback = view.keyless || (keys.length === 0 && props.keyBalances != null) ? null : status
    return keyTableRows({ keys, keyStatus, refresh, identity, actions, oauthActions, fallback, refreshable: view.refreshable, now })
  }
  return props.keyBalances == null ? renderTable([], null, null) : (
    <KeyBalancesLayoutScope.Provider value={{ compact: true, actionsTarget: null, renderTable }}>
      <KeyBalancesRefreshScope.Provider value={view.refreshable}>{props.keyBalances}</KeyBalancesRefreshScope.Provider>
    </KeyBalancesLayoutScope.Provider>
  )
}
