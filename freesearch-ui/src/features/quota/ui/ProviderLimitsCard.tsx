import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import type { CRDUsageTotal, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import type { BackendManualQuota } from "@/domains/dashboard/api/manualQuotaWire"
import type { UnitKind } from "@/shared/api/units"
import { activeAuth, creditCardModel, operationAvailable } from "../model/crdCardModel"
import type { ManualAmountMode } from "../model/manualQuotaMath"
import { providerInfo } from "../model/providerInfo"
import type { CreditMode } from "../model/quotaLabels"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import { useManualQuota, type ManualQuotaOverlay } from "../model/useManualQuota"
import { useProviderLimits, type ProviderLimitsController } from "../model/useProviderLimits"
import { CRDGrantForm } from "./CRDGrantForm"
import { LimitHistoryModal } from "./LimitHistoryModal"
import { ManualQuotaModal } from "./ManualQuotaModal"
import { ProviderCardActions, type CardModal } from "./ProviderCardActions"
import { ProviderCreditSummary } from "./ProviderCreditSummary"
import { ProviderInfoPopover } from "./ProviderInfoPopover"

export interface ProviderLimitsCardProps {
  providerId: string
  providerName: string
  limits: ProviderLimits
  /** This provider's credit-unit use rows only. */
  crdUsageTotals: CRDUsageTotal[]
  refreshDashboard: () => Promise<void>
  manualEligible: boolean
}

interface ManualUnit {
  unitKind: UnitKind | null
  displayUnit: string | null
  amountMode: ManualAmountMode
}

const CARD = "space-y-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-4"
const LABEL = "text-[12px] text-[var(--muted)]"

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
  onClose: () => void
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
        onClose={close}
        onSave={manual.save}
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
 * One provider credit-unit card.
 *
 * The header holds the logo, the name, and the source statement. The credit row
 * holds the four actions at its leading edge and the credit fraction at its
 * trailing edge. The card owns its one open modal, so a dialog of one provider
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
}: ProviderLimitsCardProps): ReactNode {
  const [modal, setModal] = useState<CardModal>(null)
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
  const info = providerInfo(auth)
  const unit = manualUnit(auth)
  const titleId = "limits-title-" + slug(providerId)
  const fetchAvailable = operationAvailable(auth, "fetch")

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
        info={
          <ProviderInfoPopover
            providerId={providerId}
            providerName={providerName}
            info={info}
            auth={auth}
          />
        }
      />

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
        onClose: () => setModal(null),
      })}
    </article>
  )
}
