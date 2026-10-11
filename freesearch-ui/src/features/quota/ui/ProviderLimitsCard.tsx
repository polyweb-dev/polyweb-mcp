import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import type {
  CRDUsageTotal,
  DashboardQuota,
  ProviderAuthLimits,
  ProviderLimits,
} from "@/domains/dashboard"
import type {
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
import type { ProviderConfig } from "@/domains/providers"
import type { UnitKind } from "@/shared/api/units"
import {
  activeAuth,
  creditCardModel,
  operationAvailable,
  type CreditCardModel,
} from "../model/crdCardModel"
import type { ManualAmountMode } from "../model/manualQuotaMath"
import { providerInfo, type BalancePrefill, type ProviderInfo } from "../model/providerInfo"
import type { CreditMode } from "../model/quotaLabels"
import type { QuotaRowEstimates } from "../model/quotaRowModel"
import { pairedSnapshotOf } from "../model/quotaRowModel"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import {
  saveManualQuotaFor,
  useManualQuota,
  type ManualQuotaEstimate,
  type ManualQuotaOverlay,
} from "../model/useManualQuota"
import { useProviderLimits, type ProviderLimitsController } from "../model/useProviderLimits"
import { CRDGrantForm } from "./CRDGrantForm"
import { LimitHistoryModal } from "./LimitHistoryModal"
import { ManualQuotaModal } from "./ManualQuotaModal"
import { ProviderCardActions, type CardModal } from "./ProviderCardActions"
import { ProviderCreditSummary } from "./ProviderCreditSummary"
import { ProviderInfoPopover } from "./ProviderInfoPopover"
import type { OAuthSlotArgs } from "./QuotaRow"

export interface ProviderLimitsCardProps {
  providerId: string
  providerName: string
  limits: ProviderLimits
  /** This provider's credit-unit use rows only. */
  crdUsageTotals: CRDUsageTotal[]
  refreshDashboard: () => Promise<void>
  manualEligible: boolean
  /** The selectable providers of the balance dialog; the own provider is the default. */
  providers?: ProviderConfig[]
  /** The observed balance per provider, which starts a new entry as an estimate. */
  observed?: Record<string, BalancePrefill>
  /** The dashboard quota row of this provider, which states the pair evidence. */
  latestQuota?: DashboardQuota
  /**
   * OAuth pairing control of this provider. Supplied by composition (the quota
   * overlay stays in app composition), so the quota feature never imports the
   * OAuth feature directly.
   */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
}

interface ManualUnit {
  unitKind: UnitKind | null
  displayUnit: string | null
  amountMode: ManualAmountMode
}

const CARD = "space-y-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-4"
const LABEL = "text-[12px] text-[var(--muted)]"

/** The one provider that opts into the shared bar and the free strike. */
const KEENABLE_PROVIDER = "keenable"

function slug(providerId: string): string {
  return providerId.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

/** A new stored grant remounts the form, so its draft starts from the server. */
function grantKey(auth: ProviderAuthLimits): string {
  const grants = auth.grants
  if (grants === null) return auth.auth_mode + "-none"
  return auth.auth_mode + "-" + grants.version + "-" + grants.period_start
}

/**
 * The native unit of the manual anchor. A USD pool accepts the vendor USD
 * balance; any other unit keeps the current usage entry.
 */
function manualUnit(auth: ProviderAuthLimits): ManualUnit {
  const nativeUnit = auth.aggregate_pool?.native_unit ?? null
  if (nativeUnit === "USD") {
    return { unitKind: "USD", displayUnit: "USD", amountMode: "balance" }
  }
  if (nativeUnit === "REQUEST" || nativeUnit === "CREDIT" || nativeUnit === "FREE") {
    return { unitKind: nativeUnit, displayUnit: nativeUnit, amountMode: "usage" }
  }
  return { unitKind: null, displayUnit: null, amountMode: "usage" }
}

function manualDefaultsOf(manual: BackendManualQuota | null): ManualQuotaDefaults | null {
  if (manual === null) return null
  return {
    billingStart: manual.billing_start,
    billingEnd: manual.billing_end,
    allowance: manual.allowance,
    used: manual.current_usage,
  }
}

/**
 * The two row facts of one card: its estimates and its pair evidence.
 *
 * A finite percent, a manual estimate, or a reported remaining balance is a
 * usable estimate. The authoritative snapshot of the OAuth provider is pair
 * evidence, exactly as the row selector reads it.
 */
function cardEstimates(
  providerId: string,
  latestQuota: DashboardQuota | undefined,
  model: CreditCardModel,
  manualEstimate: ManualQuotaEstimate | null,
): QuotaRowEstimates {
  return {
    hasUsableEstimate:
      model.percentRemaining !== null || manualEstimate !== null || model.remainingCRD !== null,
    pairedSnapshot: pairedSnapshotOf(providerId, latestQuota),
  }
}

interface CardModalInput {
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
  providers?: ProviderConfig[]
  observed?: Record<string, BalancePrefill>
  refreshDashboard: () => Promise<void>
  onClose: () => void
}

/**
 * Save one manual entry for the target provider through the one PUT path.
 *
 * The own provider keeps its overlay save, so the card updates at once. Any
 * other target uses the same route and then refreshes the dashboard.
 */
async function saveManual(
  input: CardModalInput,
  providerId: string,
  payload: BackendManualQuotaPayload,
): Promise<void> {
  if (providerId === input.providerId) return input.manual.save(payload)
  await saveManualQuotaFor(providerId, payload)
  await input.refreshDashboard()
}

/** At most one dialog of this card stays mounted, so one card opens one dialog. */
function cardModals(input: CardModalInput): ReactNode {
  const { modal, providerId, providerName, unit, defaults, manual, controller, auth } = input
  const close = input.onClose
  if (modal === "manual" && input.manualEligible) {
    return (
      <ManualQuotaModal
        open
        providerId={providerId}
        providerName={providerName}
        unitKind={unit.unitKind}
        displayUnit={unit.displayUnit}
        defaults={defaults}
        amountMode={unit.amountMode}
        creditMode={input.creditMode ?? "free"}
        {...(input.providers !== undefined ? { providers: input.providers } : {})}
        {...(input.observed !== undefined ? { observed: input.observed } : {})}
        onClose={close}
        onSave={(payload, targetId) => saveManual(input, targetId ?? providerId, payload)}
        {...(manual.manual !== null ? { onDelete: manual.remove } : {})}
      />
    )
  }
  if (modal === "grant") {
    return (
      <ManualQuotaModal
        mode="grant"
        open
        providerId={providerId}
        providerName={providerName}
        onClose={close}
      >
        <CRDGrantForm
          key={grantKey(auth)}
          providerName={providerName}
          authMode={auth.auth_mode}
          grants={auth.grants}
          fetchAvailable={input.fetchAvailable}
          saving={controller.saving}
          saveError={controller.saveError}
          staleVersion={controller.staleVersion}
          onSave={controller.saveGrant}
          onClose={close}
          onReload={() => void controller.reload()}
        />
      </ManualQuotaModal>
    )
  }
  if (modal === "history") {
    return (
      <LimitHistoryModal
        open
        providerName={providerName}
        events={controller.history}
        loading={controller.historyLoading}
        error={controller.historyError}
        hasMore={controller.hasMoreHistory}
        onLoadMore={controller.loadMoreHistory}
        onClose={close}
      />
    )
  }
  return null
}

/**
 * The composed OAuth control of one card at its trailing edge, or null when
 * the card holds none.
 *
 * The card renders nothing when the composition supplies no callback or the
 * callback returns no node.
 */
function oauthControl(
  args: OAuthSlotArgs,
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode,
): ReactNode {
  if (renderOAuthActions === undefined) return null
  const control = renderOAuthActions(args)
  if (control === null || control === undefined) return null
  return <div className="flex flex-wrap items-center justify-end gap-2">{control}</div>
}

/** The details control of one card, shown beside the credit fraction. */
function infoPopover(info: ProviderInfo, providerId: string, providerName: string, auth: ProviderAuthLimits): ReactNode {
  return <ProviderInfoPopover providerId={providerId} providerName={providerName} info={info} auth={auth} />
}

/**
 * One provider credit-unit card.
 *
 * The header holds the logo, the name, and the source statement. The credit row
 * holds the four actions at its leading edge and the credit fraction at its
 * trailing edge. The card holds the composed OAuth control at the trailing edge
 * of its content. The card owns its one open modal, so a dialog of one provider
 * never moves another. The dashboard payload supplies the funds. The info
 * control states the call cost, the call count, the rate limit, the last sync
 * time, the usage page, the known tier facts, the known rate bars, and the
 * vendor detail.
 */
export function ProviderLimitsCard({
  providerId,
  providerName,
  limits,
  crdUsageTotals,
  refreshDashboard,
  manualEligible,
  providers,
  observed,
  latestQuota,
  renderOAuthActions,
}: ProviderLimitsCardProps): ReactNode {
  const [modal, setModal] = useState<CardModal>(null)
  // The composed control reports its pair state here. The card shows the funds
  // of the limits payload, so it never feeds that state back into the args. A
  // feed-back holds the Disconnect control after a revoke.
  const [, setOauthPaired] = useState(false)
  const controller = useProviderLimits({
    providerId,
    limits,
    refreshDashboard,
    historyOpen: modal === "history",
  })
  const manualState = useManualQuota(providerId, manualEligible)
  const manualDefaults = useMemo(
    () => manualDefaultsOf(manualState.manual),
    [manualState.manual]
  )
  const auth = activeAuth(limits)
  if (auth === undefined) {
    return <article className={CARD}>{providerName}: no limit data reported by the backend.</article>
  }

  const model = creditCardModel({ auth, usageTotals: crdUsageTotals })
  const keenableBar = providerId === KEENABLE_PROVIDER
  const info = providerInfo(auth, keenableBar)
  const unit = manualUnit(auth)
  const titleId = "limits-title-" + slug(providerId)
  const fetchAvailable = operationAvailable(auth, "fetch")
  const estimates = cardEstimates(providerId, latestQuota, model, manualState.estimate)
  const oauth = oauthControl(
    { providerId, providerName, ...estimates, onPairedChange: setOauthPaired },
    renderOAuthActions,
  )

  return (
    <article aria-labelledby={titleId} className={CARD}>
      <div className="flex min-w-0 items-center gap-3">
        <ProviderLogo providerId={providerId} name={providerName} className="size-9 rounded-full" />
        <div className="min-w-0">
          <h4 id={titleId} className="truncate text-[15px] font-semibold text-[var(--text-strong)]">
            {providerName}
          </h4>
          {info.statement !== null && (
            <p className="truncate text-[12px] text-[var(--muted)]">{info.statement}</p>
          )}
        </div>
      </div>

      {controller.syncNote !== null && (
        <p role="status" className={LABEL}>{controller.syncNote}</p>
      )}

      <ProviderCreditSummary
        providerName={providerName}
        model={model}
        useSharedBar={keenableBar}
        {...(keenableBar && auth.auth_mode === "keyless" ? { freeKeyless: true } : {})}
        actions={
          <ProviderCardActions
            providerId={providerId}
            providerName={providerName}
            manualEligible={manualEligible}
            syncing={controller.syncing}
            onSync={() => void controller.syncNow()}
            onOpenModal={setModal}
          />
        }
        info={infoPopover(info, providerId, providerName, auth)}
      />

      {oauth}

      {cardModals({
        providerId,
        providerName,
        modal,
        manualEligible,
        unit,
        defaults: manualDefaults,
        manual: manualState,
        controller,
        auth,
        fetchAvailable,
        creditMode: info.creditMode,
        ...(providers !== undefined ? { providers } : {}),
        ...(observed !== undefined ? { observed } : {}),
        refreshDashboard,
        onClose: () => setModal(null),
      })}
    </article>
  )
}
