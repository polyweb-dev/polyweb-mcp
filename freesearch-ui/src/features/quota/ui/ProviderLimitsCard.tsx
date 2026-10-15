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
import {
  activeAuth,
  creditCardModel,
  operationAvailable,
  PARALLEL_FREE_ALLOWANCE_CRD,
  YOUCOM_FREE_ALLOWANCE_CRD,
  usdBalanceToCRD,
  type CreditCardModel,
} from "../model/crdCardModel"
import { percentRemaining } from "../model/crdDisplay"
import { displayAdapterOf, profileOf, type TavilyDisplayAdapter } from "../model/tavilyCredits"
import { manualUnit, type ManualUnit } from "../model/manualQuotaUnit"
import { providerInfo, type BalancePrefill } from "../model/providerInfo"
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
import { ProviderRateBars } from "./ProviderRateBars"
import type { OAuthSlotArgs } from "./QuotaRow"

export interface RateTierSlotArgs {
  providerId: string
  onConfirmed: (environment: "dev" | "prod") => void
}

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
  /** Native entry units for each selectable provider. */
  providerUnits?: Readonly<Record<string, ManualUnit>>
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
  /**
   * Tavily tier control of this provider. Supplied by composition (the quota
   * overlay stays in app composition), so the quota feature never imports the
   * Settings feature directly.
   */
  renderRateTier?: (args: RateTierSlotArgs) => ReactNode
}

const CARD = "flex h-full flex-col justify-between gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-4"

/** The one provider that opts into the shared bar. */
const KEENABLE_PROVIDER = "keenable"

/** The one provider whose rate bars share the card-body bar with short titles. */
const TINYFISH_PROVIDER = "tinyfish"

/**
 * The Parallel provider. It keeps per-operation rate bars (Brave pattern):
 * search and fetch costs differ and the catalog defines distinct bucket ids,
 * so no shared bar, no shared title, and no authoritative hiding. Funds reuse
 * the finite-USD path; the Tavily nativeDisplay path and FREE_COST_LABELS
 * never apply here.
 */
const PARALLEL_PROVIDER = "parallel"

/**
 * The You.com provider (UI id `youcom`; backend `you` via idMapping). It keeps
 * per-operation rate bars (Brave pattern): search ($5/1k) and fetch ($1/1k
 * live pages) costs differ, so no shared bar, no shared title, and no
 * authoritative hiding. Funds reuse the finite-USD path; the Tavily
 * nativeDisplay path and FREE_COST_LABELS never apply here, so a keyed rail
 * shows no Free strike.
 */
const YOUCOM_PROVIDER = "youcom"

function slug(providerId: string): string {
  return providerId.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

/** A new stored grant remounts the form, so its draft starts from the server. */
function grantKey(auth: ProviderAuthLimits): string {
  const grants = auth.grants
  if (grants === null) return auth.auth_mode + "-none"
  return auth.auth_mode + "-" + grants.version + "-" + grants.period_start
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
  // Mirror the row selector: a vendor percent, a manual estimate, a reported
  // remaining balance, or dashboard vendor funds is a usable estimate. The
  // dashboard remaining matters for Parallel and You.com: the paired
  // AUTHORITATIVE Parallel balance and the ESTIMATED You.com cents balance
  // live in latestQuota, not in the limits model, so without this either
  // balance would wrongly show Connect. Generic for every provider; only
  // Parallel and You.com render the slot.
  const vendorBalance = latestQuota !== undefined && latestQuota.remaining !== null
  const vendorPercent = latestQuota?.remainingPercent != null
  return {
    hasUsableEstimate:
      model.percentRemaining !== null ||
      manualEstimate !== null ||
      model.remainingCRD !== null ||
      vendorBalance ||
      vendorPercent,
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
  /** The native display inputs of one Tavily rail; null on every other card. */
  nativeDisplay: TavilyDisplayAdapter | null
  providers?: ProviderConfig[]
  providerUnits?: Readonly<Record<string, ManualUnit>>
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
        {...(input.providerUnits !== undefined ? { providerUnits: input.providerUnits } : {})}
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
          {...(input.nativeDisplay !== null ? { nativeDisplay: input.nativeDisplay } : {})}
          onSave={controller.saveGrant}
          onClose={close}
          onReload={() => void controller.reload()}
        />
      </ManualQuotaModal>
    )
  }
  if (modal === "history") {
    // The history view converts a CRD-only Tavily amount with the live rail
    // profile, the same auth every other dialog of this card reads.
    const profile = profileOf(auth)
    return (
      <LimitHistoryModal
        open
        providerName={providerName}
        events={controller.history}
        loading={controller.historyLoading}
        error={controller.historyError}
        hasMore={controller.hasMoreHistory}
        onLoadMore={controller.loadMoreHistory}
        {...(profile !== null ? { profile } : {})}
        onClose={close}
      />
    )
  }
  return null
}

/**
 * The composed OAuth control of one card, rendered inline in the shared
 * action row, or null when the card holds none.
 *
 * The card renders nothing when the composition supplies no callback or the
 * callback returns no node. The caller passes the node into ProviderCardActions
 * as oauthActions so Connect/Disconnect shares one flex-wrap row with Refresh
 * Limits, Provider Balance, Budget Limit, and History.
 */
function oauthControl(
  args: OAuthSlotArgs,
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode,
): ReactNode {
  if (renderOAuthActions === undefined) return null
  const control = renderOAuthActions(args)
  if (control === null || control === undefined) return null
  return control
}

/** The confirmed minute ceiling of one Tavily key environment. */
const TAVILY_CEILING_OF_ENV: Record<"dev" | "prod", string> = {
  dev: "100",
  prod: "1000",
}

/** The one provider with a rate-tier selector. */
const TAVILY_PROVIDER = "tavily"

/** A known text of one field; an absent, empty, or unknown value yields null. */
function knownText(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "" || text.toLowerCase() === "unknown" || text === "n/a") return null
  return text
}

/** Whole-number form of one ceiling text: "100.0" reads "100". */
function normalizeCeiling(value: string): string {
  return value.trim().replace(/\.0+$/, "")
}

/** The current dashboard minute ceiling of one rail, or null when unknown. */
function dashboardMinuteCeiling(auth: ProviderAuthLimits): string | null {
  const windows = auth.detail?.rate_windows ?? []
  const minute = windows.find((entry) => entry.window === "1m")
  const limit = knownText(minute?.limit ?? null)
  return limit === null ? null : normalizeCeiling(limit)
}

interface BalanceFallback { usd: string; crd: string | null; allowanceCRD: string | null }

/**
 * OAuth balance fallback of one card (Option A, frontend-only): the Parallel
 * Account-API balance and the You.com cents balance-API balance live in
 * latestQuota, not in the limits model (aggregate_pool null, unknown views).
 * A remaining-only snapshot (no limit, no percent) yields the raw USD with
 * its CRD equivalent (USD / reference_usd_per_crd). For Parallel only, the
 * $5/mo free credit (5000 CRD) is attached as a display-only denominator;
 * for You.com only, the $100 signup credit (100000 CRD total, fetch-basis)
 * is attached the same way, so each card shows a capped bar and percent like
 * Firecrawl remaining-over-allowance; every other provider keeps an
 * amount-only fallback with no invented allowance. Parallel accepts only the
 * AUTHORITATIVE OAuth snapshot, while You.com accepts the AUTHORITATIVE or
 * the ESTIMATED cents-balance snapshot (the vendor exposes no plan limit, so
 * the adapter maps it estimated). No backend allowance is invented.
 */
function balanceFallbackOf(
  providerId: string,
  model: CreditCardModel,
  latestQuota: DashboardQuota | undefined,
  auth: ProviderAuthLimits,
): BalanceFallback | null {
  if (model.remainingCRD !== null) return null
  const isYoucom = providerId === YOUCOM_PROVIDER
  const source = latestQuota?.source
  const sourceOk = isYoucom
    ? source === "authoritative" || source === "estimated"
    : source === "authoritative"
  if (!sourceOk || latestQuota === undefined) return null
  if (latestQuota.remaining === null || latestQuota.remaining.trim() === "") return null
  if (latestQuota.limit !== null || latestQuota.remainingPercent != null) return null
  const usd = latestQuota.remaining
  const allowanceCRD =
    providerId === PARALLEL_PROVIDER
      ? PARALLEL_FREE_ALLOWANCE_CRD
      : isYoucom
        ? YOUCOM_FREE_ALLOWANCE_CRD
        : null
  return { usd, crd: usdBalanceToCRD(usd, auth), allowanceCRD }
}

/**
 * One provider credit-unit card.
 *
 * The header holds the logo, the name, and the source statement. The credit row
 * holds the actions at its leading edge and the credit fraction at its
 * trailing edge. The composed OAuth control (Parallel Connect/Disconnect)
 * sits inline at the trailing edge of the same action row, supplied by
 * composition so the quota feature never imports the OAuth feature directly.
 * The card owns its one open modal, so a dialog of one provider
 * never moves another. The dashboard payload supplies the funds. The info
 * control states the call cost, the call count, the rate limit, the last sync
 * time, the usage page, the known tier facts, and the vendor detail. The card
 * body holds the hourly and daily rate bars below the credit summary; the
 * keyless rail of the shared-bar provider holds its shared bars there too,
 * while its popover leaves them out. The Tavily card holds its rate-tier
 * selector beside the native Credits bar.
 */
export function ProviderLimitsCard({
  providerId,
  providerName,
  limits,
  crdUsageTotals,
  refreshDashboard,
  manualEligible,
  providers,
  providerUnits,
  observed,
  latestQuota,
  renderOAuthActions,
  renderRateTier,
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
  const authMode = auth?.auth_mode ?? null
  // The confirmed Tavily ceiling snapshot. The derived ceiling below ignores a
  // stale snapshot after a provider or auth change and after the fresh
  // dashboard confirms the same ceiling, so no effect clears it.
  const [confirmedTier, setConfirmedTier] = useState<{
    ceiling: string
    providerId: string
    authMode: string | null
  } | null>(null)
  const handleTierConfirmed = (environment: "dev" | "prod") => {
    setConfirmedTier({
      ceiling: TAVILY_CEILING_OF_ENV[environment],
      providerId,
      authMode,
    })
  }
  if (auth === undefined) {
    return <article className={CARD}>{providerName}: no limit data reported by the backend.</article>
  }

  const model = creditCardModel({ auth, usageTotals: crdUsageTotals })
  const keenableBar = providerId === KEENABLE_PROVIDER
  const tinyfishBar = providerId === TINYFISH_PROVIDER
  const isTavily = providerId === TAVILY_PROVIDER
  const isParallel = providerId === PARALLEL_PROVIDER
  const isYoucom = providerId === YOUCOM_PROVIDER
  const keenableKeyless = keenableBar && auth.auth_mode === "keyless"
  // The keyless Tavily rail has no usage endpoint to refresh, like the keyless
  // Keenable rail. The hide decision reads the current rail, never a prior skip.
  const tavilyKeyless = isTavily && auth.auth_mode === "keyless"
  const firecrawlKeyless = providerId === "firecrawl" && auth.auth_mode === "keyless"
  // The keyed Parallel rail keeps Refresh Limits visible: its keyed local
  // ledger has a refreshable usage endpoint. Only a keyless Parallel rail
  // hides refresh, like the keyless Keenable rail. The keyed You.com rail
  // keeps Refresh Limits visible the same way: its keyed cents balance API
  // is refreshable, while a keyless rail (100/day MCP profile) has no usage
  // endpoint to refresh.
  const parallelKeyless = isParallel && auth.auth_mode === "keyless"
  const youcomKeyless = isYoucom && auth.auth_mode === "keyless"
  const refreshSkipped = controller.refreshSkipped || keenableKeyless || tavilyKeyless || firecrawlKeyless || parallelKeyless || youcomKeyless
  // The whole-request floor applies to the release request rails (Keenable);
  // every other rail keeps the verbatim values, and Tavily reads its native
  // Credits facts through the optional display adapter.
  // A stale snapshot (provider or auth change) and a dashboard-confirmed
  // ceiling both yield no override, so the popover shows unknown headroom
  // with the new ceiling until current dashboard data confirms that ceiling.
  const confirmedCeiling =
    isTavily &&
    confirmedTier !== null &&
    confirmedTier.providerId === providerId &&
    confirmedTier.authMode === auth.auth_mode &&
    dashboardMinuteCeiling(auth) !== confirmedTier.ceiling
      ? confirmedTier.ceiling
      : null
  const info = providerInfo(auth, providerId, keenableBar, confirmedCeiling ?? undefined)
  const unit = manualUnit(auth, providerId)
  const nativeDisplay = displayAdapterOf(providerId, auth)
  const titleId = "limits-title-" + slug(providerId)
  const fetchAvailable = operationAvailable(auth, "fetch")
  // Display-only You.com allowance for the vendor-balance pool without a
  // backend allowance (screenshot: 199520 CRD amount-only). The backend pool
  // reports remaining without an allowance, so the finite model holds no
  // percent and the summary would stay amount-only with a footnote. Attaching
  // the $100 signup total (100000 CRD, fetch-basis) yields the capped bar and
  // fraction like Firecrawl 4761/3800 and Parallel 24870/5000, with no
  // footnote and no invented reset. The fallback path (no pool) already
  // carries the same allowance through balanceFallbackOf.
  const youcomDisplayAllowance =
    isYoucom && model.state === "finite" && model.remainingCRD !== null && model.allowanceCRD === null
      ? YOUCOM_FREE_ALLOWANCE_CRD
      : null
  const displayModel: CreditCardModel =
    youcomDisplayAllowance !== null && model.remainingCRD !== null
      ? {
          ...model,
          allowanceCRD: youcomDisplayAllowance,
          percentRemaining: percentRemaining(model.remainingCRD, youcomDisplayAllowance),
        }
      : model
  const estimates = cardEstimates(providerId, latestQuota, displayModel, manualState.estimate)
  // Amount-only fallback with its CRD equivalent through ProviderCreditSummary.
  // Parallel attaches the display-only $5 (5000 CRD) allowance and You.com
  // attaches the display-only $100 signup (100000 CRD total, fetch-basis)
  // allowance for its bar.
  const balanceFallback = balanceFallbackOf(providerId, model, latestQuota, auth)
  const oauthNode = oauthControl(
    { providerId, providerName, ...estimates, onPairedChange: setOauthPaired },
    renderOAuthActions,
  )
  const tierSlot =
    isTavily && renderRateTier !== undefined
      ? renderRateTier({ providerId, onConfirmed: handleTierConfirmed })
      : null
  const cardButtons = (
    <ProviderCardActions
      providerId={providerId}
      providerName={providerName}
      manualEligible={manualEligible}
      syncing={controller.syncing}
      onSync={() => void controller.syncNow()}
      refreshSkipped={refreshSkipped}
      onOpenModal={setModal}
      {...(oauthNode !== null ? { oauthActions: oauthNode } : {})}
    />
  )

  return (
    <article aria-labelledby={titleId} className={CARD}>
      <div className="flex min-h-11 min-w-0 items-start justify-between gap-3">
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
          <p role="status" className="shrink-0 pt-0.5 text-right text-[11px] text-[var(--muted)]">
            {controller.syncNote}
          </p>
        )}
      </div>

      <ProviderCreditSummary
        providerName={providerName}
        model={displayModel}
        {...(nativeDisplay !== null ? { credits: nativeDisplay.credits } : {})}
        {...(balanceFallback !== null ? { balanceFallbackUSD: balanceFallback.usd } : {})}
        {...(balanceFallback?.crd != null ? { balanceFallbackCRD: balanceFallback.crd } : {})}
        {...(balanceFallback?.allowanceCRD != null
          ? { balanceFallbackAllowanceCRD: balanceFallback.allowanceCRD }
          : {})}
        useSharedBar={keenableBar || nativeDisplay !== null}
        fundsControl={tierSlot}
        {...(isTavily
          ? {}
          : {
              rateBars: (
                <ProviderRateBars
                  providerName={providerName}
                  progress={auth.rate_progress}
                  fetchAvailable={fetchAvailable}
                  useSharedBar={keenableBar || tinyfishBar}
                  hideAuthoritative={keenableBar || tinyfishBar}
                  {...(keenableBar ? { sharedTitle: "Search and Fetch Limits" } : {})}
                />
              ),
            })}
        actions={cardButtons}
        info={
          <ProviderInfoPopover providerId={providerId} providerName={providerName}
            info={info} auth={auth}
            {...(nativeDisplay !== null ? { nativeDisplay } : {})}
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
        nativeDisplay,
        providers,
        providerUnits,
        observed,
        refreshDashboard,
        onClose: () => setModal(null),
      })}
    </article>
  )
}
