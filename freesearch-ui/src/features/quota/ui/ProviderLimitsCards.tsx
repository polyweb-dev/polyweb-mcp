import { useQuotaPrices, quotaPricedProvider } from "../model/useQuotaPrices"
import type { ReactNode } from "react"
import type { UsdUsageTotal, DashboardQuota, ProviderLimits } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { EmptyState } from "@/shared/ui/EmptyState"
import { activeAuth } from "../model/usdCardModel"
import { manualUnit, type ManualUnit } from "../model/manualQuotaUnit"
import { balancePrefill, type BalancePrefill } from "../model/providerInfo"
import { providerCardView, type ProviderCardView } from "../model/providerCardView"
import type { OAuthSlotArgs } from "../model/oauthSlot"
import { ProviderLimitsCard, type RateTierSlotArgs } from "./ProviderLimitsCard"
import { ProviderUsageRow } from "./ProviderUsageRow"

export interface ProviderLimitsCardsProps {
  providers: ProviderConfig[]
  providerLimits: ProviderLimits[]
  /** Every reported credit-unit use row of the dashboard. */
  usdUsageTotals: UsdUsageTotal[]
  refreshDashboard: () => Promise<void>
  /** Providers that may hold a manual native anchor. */
  manualEligible: ReadonlySet<string>
  refreshableProviders?: ReadonlySet<string>
  renderKeyBalances?: (providerId: string, providerName: string) => ReactNode
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
function usageFor(totals: UsdUsageTotal[], providerId: string): UsdUsageTotal[] {
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

interface ViewEntry {
  provider: ProviderConfig
  limits: ProviderLimits
  view: ProviderCardView
}

/**
 * Allowance list for the configured providers.
 *
 * A provider appears only when the payload reports a limit entry for it, so a
 * rail the backend does not support never gains an invented card. Providers
 * that report usage become cards, least remaining first; the rest collapse
 * into one compact list, one row each.
 */
export function ProviderLimitsCards({
  providers,
  providerLimits,
  usdUsageTotals,
  refreshDashboard,
  manualEligible,
  refreshableProviders,
  renderKeyBalances,
  dashboardQuotas,
  renderOAuthActions,
  renderRateTier,
}: ProviderLimitsCardsProps): ReactNode {
  const prices = useQuotaPrices()
  const entries = providers
    .map((provider) => ({
      provider: quotaPricedProvider(provider, prices),
      limits: providerLimits.find((entry) => entry.provider === provider.id),
    }))
    .filter(
      (entry): entry is { provider: ProviderConfig; limits: ProviderLimits } =>
        entry.limits !== undefined,
    )
  const observed = observedByProvider(entries)
  const providerUnits = manualUnitsByProvider(entries)
  const selectable = providers.filter((provider) => manualEligible.has(provider.id))
  const quotaOf = (providerId: string): DashboardQuota | undefined => dashboardQuotas?.find((quota) => quota.provider === providerId)
  const viewed: ViewEntry[] = []
  for (const entry of entries) {
    const view = providerCardView({
      providerId: entry.provider.id,
      limits: entry.limits,
      usageTotals: usageFor(usdUsageTotals, entry.provider.id),
      latestQuota: quotaOf(entry.provider.id),
      refreshableOverride: refreshableProviders?.has(entry.provider.id) ?? false,
    })
    if (view !== null) viewed.push({ ...entry, view })
  }
  const byName = (a: ViewEntry, b: ViewEntry) => a.provider.name.localeCompare(b.provider.name)
  const reporting = viewed.filter((entry) => entry.view.measurable).sort(byName)
  const keyed = viewed.filter((entry) =>
    renderKeyBalances !== undefined || (!entry.view.keyless && !entry.view.measurable)).sort(byName)
  return (
    <section aria-labelledby="usd-cards-heading" className="space-y-4">
      <h3 id="usd-cards-heading" className="fs-section-title">
        Allowance left
      </h3>{viewed.length === 0 && (
        <EmptyState title="No provider usage yet" description="Add a system key to see usage" />
      )}
      {reporting.length > 0 && (
        <div className="grid grid-cols-2 items-start gap-4">
          {reporting.map((entry) => (
            <ProviderLimitsCard
              key={entry.provider.id}
              catalogProvider={entry.provider}
              providerId={entry.provider.id} providerName={entry.provider.name}
              limits={entry.limits}
              usdUsageTotals={usageFor(usdUsageTotals, entry.provider.id)}
              refreshDashboard={refreshDashboard}
              manualEligible={manualEligible.has(entry.provider.id)}
              refreshableOverride={refreshableProviders?.has(entry.provider.id) ?? false}
              providers={selectable} providerUnits={providerUnits}
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
      {keyed.length > 0 && (
        <div className="space-y-3">
          <h3 className="fs-section-title">Key balances</h3>
          <div className="fs-panel overflow-hidden"><table className="fs-table w-full" aria-label="Key balances"><thead><tr><th scope="col">Provider</th><th scope="col">Key</th><th scope="col">Balance</th><th scope="col">Last refresh</th><th scope="col"><span className="sr-only">Provider controls</span></th></tr></thead><tbody>
          {keyed.map((entry) => (
            <ProviderUsageRow
              key={entry.provider.id}
              catalogProvider={entry.provider}
              providerId={entry.provider.id} providerName={entry.provider.name}
              limits={entry.limits}
              view={entry.view}
              refreshDashboard={refreshDashboard}
              manualEligible={manualEligible.has(entry.provider.id)}
              keyBalances={renderKeyBalances?.(entry.provider.id, entry.provider.name)}
              providers={selectable} providerUnits={providerUnits}
              observed={observed}
              {...(quotaOf(entry.provider.id) !== undefined ? { latestQuota: quotaOf(entry.provider.id) } : {})}
              {...(renderOAuthActions !== undefined ? { renderOAuthActions } : {})}
            />
          ))}
            </tbody>
          </table></div>
        </div>
      )}
    </section>
  )
}
