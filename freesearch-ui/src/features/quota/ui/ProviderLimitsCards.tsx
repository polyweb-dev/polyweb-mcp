import type { ReactNode } from "react"
import type { CRDUsageTotal, DashboardQuota, ProviderLimits } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { activeAuth } from "../model/crdCardModel"
import { manualUnit, type ManualUnit } from "../model/manualQuotaUnit"
import { balancePrefill, type BalancePrefill } from "../model/providerInfo"
import { Footnote } from "./Footnote"
import type { OAuthSlotArgs } from "./QuotaRow"
import { ProviderLimitsCard, type RateTierSlotArgs } from "./ProviderLimitsCard"

export interface ProviderLimitsCardsProps {
  providers: ProviderConfig[]
  providerLimits: ProviderLimits[]
  /** Every reported credit-unit use row of the dashboard. */
  crdUsageTotals: CRDUsageTotal[]
  refreshDashboard: () => Promise<void>
  /** Providers that may hold a manual native anchor. */
  manualEligible: ReadonlySet<string>
  /** The dashboard quota rows, which state the pair evidence of each card. */
  dashboardQuotas?: DashboardQuota[]
  /**
   * OAuth pairing controls per provider. Supplied by composition (the quota
   * overlay stays in app composition), so the quota feature never imports the
   * OAuth feature directly.
   */
  renderOAuthActions?: (args: OAuthSlotArgs) => ReactNode
  /**
   * Tavily tier control per provider. Supplied by composition (the quota
   * overlay stays in app composition), so the quota feature never imports the
   * Settings feature directly.
   */
  renderRateTier?: (args: RateTierSlotArgs) => ReactNode
}

/** Credit-unit use rows of one provider; a card receives its own rows only. */
function usageFor(totals: CRDUsageTotal[], providerId: string): CRDUsageTotal[] {
  return totals.filter((total) => total.provider === providerId)
}

/** The observed balance of every reported provider, keyed by provider id. */
function observedByProvider(
  entries: { provider: ProviderConfig; limits: ProviderLimits }[],
): Record<string, BalancePrefill> {
  const map: Record<string, BalancePrefill> = {}
  for (const entry of entries) {
    const auth = activeAuth(entry.limits)
    if (auth === undefined) continue
    const prefill = balancePrefill(auth)
    if (prefill !== null) map[entry.provider.id] = prefill
  }
  return map
}

/** The native manual-entry unit for every provider with a reported limits rail. */
function manualUnitsByProvider(
  entries: { provider: ProviderConfig; limits: ProviderLimits }[],
): Record<string, ManualUnit> {
  const map: Record<string, ManualUnit> = {}
  for (const entry of entries) {
    const auth = activeAuth(entry.limits)
    if (auth !== undefined) map[entry.provider.id] = manualUnit(auth, entry.provider.id)
  }
  return map
}

/**
 * Display-only card order for the desktop 2-col Usage grid.
 *
 * Short single-bar cards (Parallel, You.com) sort first and taller cards
 * (Tinyfish, Tavily) sort last, so each 2-col row pairs equal-height cards
 * (row 1 Parallel + You.com, row 2 Tinyfish + Tavily) instead of mixing
 * tall and short cards. Stable within groups: every other provider keeps
 * its incoming (priority) relative order in the middle. Settings registry
 * priority (dispatch order) is untouched; this never drops or invents a
 * card, it only reorders reported entries.
 */
const USAGE_CARD_GROUP: Readonly<Record<string, number>> = {
  parallel: 0,
  you: 0,
  youcom: 0,
  tinyfish: 2,
  tavily: 2,
}

/** Within-group tiebreak for the paired cards; all others compare equal. */
const USAGE_CARD_TIEBREAK: Readonly<Record<string, number>> = {
  parallel: 0,
  you: 1,
  youcom: 1,
  tinyfish: 0,
  tavily: 1,
}

function usageCardGroup(providerId: string): number {
  return USAGE_CARD_GROUP[providerId] ?? 1
}

function usageCardTiebreak(providerId: string): number {
  return USAGE_CARD_TIEBREAK[providerId] ?? 0
}

/**
 * Credit-unit card list for the configured providers.
 *
 * A provider appears only when the payload reports a limit entry for it, so a
 * rail the backend does not support never gains an invented card. The card list
 * keeps both auth modes in the payload; each card shows its active rail.
 */
export function ProviderLimitsCards({
  providers,
  providerLimits,
  crdUsageTotals,
  refreshDashboard,
  manualEligible,
  dashboardQuotas,
  renderOAuthActions,
  renderRateTier,
}: ProviderLimitsCardsProps): ReactNode {
  const entries = providers
    .map((provider) => ({
      provider,
      limits: providerLimits.find((entry) => entry.provider === provider.id),
    }))
    .filter(
      (entry): entry is { provider: ProviderConfig; limits: ProviderLimits } =>
        entry.limits !== undefined,
    )
    .sort(
      (a, b) =>
        usageCardGroup(a.provider.id) - usageCardGroup(b.provider.id) ||
        usageCardTiebreak(a.provider.id) - usageCardTiebreak(b.provider.id),
    )
  const observed = observedByProvider(entries)
  const providerUnits = manualUnitsByProvider(entries)
  const selectable = providers.filter((provider) => manualEligible.has(provider.id))
  const quotaOf = (providerId: string): DashboardQuota | undefined =>
    dashboardQuotas?.find((quota) => quota.provider === providerId)

  return (
    <section aria-labelledby="crd-cards-heading" className="space-y-3">
      <div className="flex items-center gap-2.5">
        <h3 id="crd-cards-heading" className="text-[13px] font-semibold text-[var(--text-strong)]">
          Provider credit units
        </h3>
        <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
          {entries.length} reported
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="rounded-lg border border-[var(--border-subtle)] p-8 text-center text-[13px] text-[var(--muted)]">
          No provider limit data reported by the backend.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
          {entries.map((entry) => (
            <ProviderLimitsCard
              key={entry.provider.id}
              providerId={entry.provider.id}
              providerName={entry.provider.name}
              limits={entry.limits}
              crdUsageTotals={usageFor(crdUsageTotals, entry.provider.id)}
              refreshDashboard={refreshDashboard}
              manualEligible={manualEligible.has(entry.provider.id)}
              providers={selectable}
              providerUnits={providerUnits}
              observed={observed}
              {...(quotaOf(entry.provider.id) !== undefined
                ? { latestQuota: quotaOf(entry.provider.id) }
                : {})}
              {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
              {...(renderRateTier !== undefined ? { renderRateTier } : {})}
            />
          ))}
        </div>
      )}
      <Footnote className="border-t border-[var(--border-subtle)]/60 pt-2">
        Vendor funds in one common scale: one CRD is USD 0.001 of priced native use. Amounts show
        at most one decimal digit; the exact value governs admission, debit, and audit.
      </Footnote>
    </section>
  )
}
