import { catalogFree, catalogQuotaInfo } from "../model/catalogQuota"
import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import { ProviderCardHeader } from "./ProviderCardHeader"
import { formatDateTime } from "@/shared/lib/formatTime"
import type { UsdUsageTotal, DashboardQuota, ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import type { BackendManualQuota } from "@/domains/dashboard/api/manualQuotaWire"
import type { ProviderConfig } from "@/domains/providers"
import { manualUnit, type ManualUnit } from "../model/manualQuotaUnit"
import type { OAuthSlotArgs } from "../model/oauthSlot"
import { TAVILY_CEILING_OF_ENV, cardEstimates, dashboardMinuteCeiling } from "../model/providerCardFunds"
import { emptyUsageText, type ProviderCardRule } from "../model/providerCardRules"
import { providerCardView, type ProviderCardView } from "../model/providerCardView"
import { providerInfo, type BalancePrefill } from "../model/providerInfo"
import { useManualQuota } from "../model/useManualQuota"
import { useProviderLimits, type ProviderLimitsController } from "../model/useProviderLimits"
import type { ManualQuotaDefaults } from "../model/useQuotaForm"
import { refreshNote } from "../model/refreshNote"
import { ProviderCardActions } from "./ProviderCardActions"
import { ProviderCardMenu, type CardModal } from "./ProviderCardMenu"
import { ProviderCardModals } from "./ProviderCardModals"
import { ProviderCreditSummary, type ProviderCreditSummaryProps } from "./ProviderCreditSummary"
import { ProviderInfoPopover } from "./ProviderInfoPopover"
import { ProviderRateBars } from "./ProviderRateBars"
import { KeyBalancesLayoutScope, KeyBalancesRefreshScope } from "../model/keyBalanceContext"

export interface RateTierSlotArgs {
  providerId: string
  /** The active rail uses a key, so the tier control applies. */
  keyed: boolean
  onConfirmed: (environment: "dev" | "prod") => void
}

export interface ProviderLimitsCardProps {
  catalogProvider?: ProviderConfig
  providerId: string
  providerName: string
  limits: ProviderLimits
  /** This provider's credit-unit use rows only. */
  usdUsageTotals: UsdUsageTotal[]
  refreshDashboard: () => Promise<void>
  manualEligible: boolean
  refreshableOverride?: boolean
  keyBalances?: ReactNode
  /** The selectable providers of the balance dialog; the own provider is the default. */
  providers?: ProviderConfig[]
  /** Native entry units for each selectable provider. */
  providerUnits?: Readonly<Record<string, ManualUnit>>
  /** The observed balance per provider, which starts a new entry as an estimate. */
  observed?: Record<string, BalancePrefill>
  /** The dashboard quota row of this provider, which states the pair evidence. */
  latestQuota?: DashboardQuota
  /** OAuth pairing control of this provider, supplied by composition. */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
  /** Tavily tier control of this provider, supplied by composition. */
  renderRateTier?: (args: RateTierSlotArgs) => ReactNode
}

const CARD = "flex flex-col gap-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-5"

function slug(providerId: string): string {
  return providerId.toLowerCase().replace(/[^a-z0-9]+/g, "-")
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

/** The composed OAuth control of one card, or null when the composition supplies none. */
function oauthControl(args: OAuthSlotArgs, renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode): ReactNode {
  if (renderOAuthActions === undefined) return null
  return renderOAuthActions(args) ?? null
}

interface ConfirmedTier { ceiling: string; providerId: string; authMode: string | null }

/**
 * The confirmed Tavily ceiling override. A stale snapshot (provider or auth
 * change) and a dashboard-confirmed ceiling both yield no override.
 */
function confirmedCeilingOf(
  rule: ProviderCardRule,
  confirmed: ConfirmedTier | null,
  providerId: string,
  auth: ProviderAuthLimits,
): string | null {
  if (!rule.rateTier || confirmed === null) return null
  if (confirmed.providerId !== providerId || confirmed.authMode !== auth.auth_mode) return null
  return dashboardMinuteCeiling(auth) !== confirmed.ceiling ? confirmed.ceiling : null
}

/** The native Credits facts, the OAuth balance fallback, and the amount-only headline. */
function fundsProps(
  view: ProviderCardView,
): Pick<
  ProviderCreditSummaryProps,
  "credits" | "nativePool" | "balanceFallbackUsd" | "amountText" | "amountNote"
> {
  return {
    ...(view.nativeDisplay !== null ? { credits: view.nativeDisplay.credits } : {}),
    nativePool: view.auth.aggregate_pool,
    ...(view.fallback !== null
      ? { balanceFallbackUsd: view.fallback.usd }
      : {}),
    amountText: view.amountText,
    amountNote: view.amountNote,
  }
}

/** The rate bars of one card; a card whose rule holds none gets none. */
function rateBarsNode(view: ProviderCardView, providerName: string): ReactNode {
  if (view.rule.noRateBars) return null
  return (
    <ProviderRateBars
      providerName={providerName}
      progress={view.auth.rate_progress}
      fetchAvailable={view.fetchAvailable}
      useSharedBar={view.rule.sharedRateBars}
      {...(view.rule.sharedRateTitle === null ? {} : { sharedTitle: view.rule.sharedRateTitle })}
    />
  )
}

function infoNode(view: ProviderCardView, providerId: string, providerName: string, info: ReturnType<typeof providerInfo>): ReactNode {
  return <ProviderInfoPopover providerId={providerId} providerName={providerName} info={info} auth={view.auth}
    {...(view.nativeDisplay === null ? {} : { nativeDisplay: view.nativeDisplay })} />
}

function cardMenu(providerName: string, manualEligible: boolean, setModal: (modal: CardModal) => void,
  { free, locallyCounted }: { free: boolean; locallyCounted: boolean }): ReactNode {
  return <ProviderCardMenu providerName={providerName} manualEligible={manualEligible && !free} budgetAllowed={!free}
    historyAllowed={!(free && locallyCounted)} onOpenModal={setModal} />
}

/**
 * Refresh stays off a keyless rail (nothing to read), off a provider that
 * reports nothing, and after the provider says it has no usage endpoint.
 */
function refreshHidden(view: ProviderCardView, controller: ProviderLimitsController): boolean {
  return controller.refreshSkipped || !view.refreshable
}

function recordedTitle(auth: ProviderAuthLimits): string | undefined {
  const at = auth.aggregate_pool?.observed_at
  return at ? formatDateTime(at) : undefined
}

/**
 * One provider usage card.
 *
 * Every card shares one layout. The header holds the logo, the name, the
 * source statement, and the `…` menu with the card dialogs. The body holds
 * the funds bar and the rate bars through the one shared bar. The footer
 * holds Refresh with the result of the last refresh beside it, and the
 * credit amount with the info control at the trailing edge. Provider
 * differences come from the card rule map, never from branches here.
 */
export function ProviderLimitsCard(props: ProviderLimitsCardProps): ReactNode {
  const { providerId, providerName, limits, usdUsageTotals, refreshDashboard, manualEligible, latestQuota } = props
  const [actionsTarget, setActionsTarget] = useState<HTMLElement | null>(null)
  const [modal, setModal] = useState<CardModal>(null)
  // The composed control reports its pair state here; the card never feeds it back.
  const [, setOauthPaired] = useState(false)
  const controller = useProviderLimits({ providerId, limits, refreshDashboard, historyOpen: modal === "history" })
  const manualState = useManualQuota(providerId, manualEligible)
  const manualDefaults = useMemo(() => manualDefaultsOf(manualState.manual), [manualState.manual])
  const [confirmedTier, setConfirmedTier] = useState<ConfirmedTier | null>(null)
  const titleId = "limits-title-" + slug(providerId)
  const view = providerCardView({
    providerId, limits, usageTotals: usdUsageTotals, latestQuota,
    refreshableOverride: props.refreshableOverride ?? false,
  })
  if (view === null) {
    return (
      <article aria-labelledby={titleId} className={CARD}>
        <h4 id={titleId} className="text-[15px] font-semibold text-[var(--text-strong)]">{providerName}</h4>
        <p className="text-[13px] text-[var(--muted)]">{emptyUsageText(false)}</p>
      </article>
    )
  }
  const { auth, rule } = view
  const handleTierConfirmed = (environment: "dev" | "prod") => {
    setConfirmedTier({ ceiling: TAVILY_CEILING_OF_ENV[environment], providerId, authMode: auth.auth_mode })
  }
  const confirmedCeiling = confirmedCeilingOf(rule, confirmedTier, providerId, auth)
  const info = catalogQuotaInfo(providerInfo(auth, providerId, rule.wholeRequests, confirmedCeiling ?? undefined), props.catalogProvider, auth.auth_mode)
  const free = catalogFree(props.catalogProvider, auth.auth_mode) ?? view.free
  const estimates = cardEstimates(providerId, latestQuota, view.model, manualState.estimate)
  const oauthNode = oauthControl(
    { providerId, providerName, ...estimates, onPairedChange: setOauthPaired },
    props.renderOAuthActions,
  )
  const tierSlot =
    rule.rateTier && props.renderRateTier !== undefined
      ? props.renderRateTier({ providerId, keyed: !view.keyless, onConfirmed: handleTierConfirmed })
      : null

  return (
    <article aria-labelledby={titleId} className={CARD}>
      <ProviderCardHeader providerId={providerId} providerName={providerName} titleId={titleId}
        free={free} statement={info.statement} recordedAt={recordedTitle(auth)}
        info={infoNode(view, providerId, providerName, info)} onActionsTarget={setActionsTarget}>
        <ProviderCardActions providerName={providerName} syncing={controller.syncing}
          onSync={() => void controller.syncNow()} refreshSkipped={props.keyBalances != null || refreshHidden(view, controller)} />
        {cardMenu(providerName, manualEligible, setModal,
          { free, locallyCounted: auth.rate_progress.some((entry) => entry.source === "local_attempts") })}
      </ProviderCardHeader>

      <ProviderCreditSummary
        providerName={providerName}
        model={view.model}
        emptyText={view.reports ? null : emptyUsageText(controller.needsCredential, view.keyless)}
        {...fundsProps(view)}
        rateBars={rateBarsNode(view, providerName)}
        actions={
          <ProviderCardActions
            providerName={providerName}
            syncing={controller.syncing}
            updatedAt={controller.updatedAt}
            onSync={() => void controller.syncNow()}
            refreshSkipped
            syncNote={view.refreshable ? refreshNote(controller, view.reports) : null}
            {...(oauthNode !== null ? { oauthActions: oauthNode } : {})}
          />
        }
      />
      {tierSlot}
      {!view.keyless && <KeyBalancesLayoutScope.Provider value={{ compact: false, actionsTarget }}>
        <KeyBalancesRefreshScope.Provider value={view.refreshable}>{props.keyBalances}</KeyBalancesRefreshScope.Provider>
      </KeyBalancesLayoutScope.Provider>}

      <ProviderCardModals
        providerId={providerId}
        providerName={providerName}
        modal={modal}
        manualEligible={manualEligible}
        unit={manualUnit(auth, providerId)}
        defaults={manualDefaults}
        manual={manualState}
        controller={controller}
        auth={auth}
        fetchAvailable={view.fetchAvailable}
        creditMode={info.creditMode}
        nativeDisplay={view.nativeDisplay}
        providers={props.providers}
        providerUnits={props.providerUnits}
        observed={props.observed}
        refreshDashboard={refreshDashboard}
        onClose={() => setModal(null)}
      />
    </article>
  )
}
