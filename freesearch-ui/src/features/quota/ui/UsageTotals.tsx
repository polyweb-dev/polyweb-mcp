import type { ReactNode } from "react"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { formatBudgetUsd } from "@/shared/lib/budget"
import type { UsdUsageTotal } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { sumAmounts } from "../model/usdDisplay"
import { latencyText } from "../model/numberText"
import { catalogFree } from "../model/catalogQuota"
import { useQuotaPrices, quotaPricedProvider } from "../model/useQuotaPrices"

export interface UsageTotalsProps {
  usdUsageTotals: UsdUsageTotal[]
  providers: ProviderConfig[]
}

/** One provider row of the merged usage table. */
interface UsageRow {
  provider: string
  searches: number
  urls: number
  usd: string[]
}

const COLUMNS = ["Provider", "Searches", "URLs fetched", "Cost", "p95"]

/** One row per provider, in first-seen order, with searches, URLs, and Usd added up. */
function usageRows(totals: UsdUsageTotal[]): UsageRow[] {
  const rows: UsageRow[] = []
  for (const total of totals) {
    let row = rows.find((entry) => entry.provider === total.provider)
    if (row === undefined) {
      row = { provider: total.provider, searches: 0, urls: 0, usd: [] }
      rows.push(row)
    }
    if (total.operation === "fetch") row.urls += total.volume_count
    else row.searches += total.volume_count
    row.usd.push(total.spend_usd)
  }
  return rows
}

/** The USD reference value of one normalized usage amount. */
function costText(usd: string | null): string {
  if (usd === null || !Number.isFinite(Number(usd))) return "—"
  return formatBudgetUsd(Number(usd))
}

/**
 * Usage totals: one table, one row per provider, with searches, fetched URLs,
 * the USD cost, and the provider p95. Numbers carry separators.
 */
export function UsageTotals({ usdUsageTotals, providers }: UsageTotalsProps) {
  const prices = useQuotaPrices()
  const pricedProviders = providers.map((provider) => quotaPricedProvider(provider, prices))
  const nameOf = (providerId: string) => catalogNameOf(providerId) ?? providerId
  const p95Of = (providerId: string) =>
    latencyText(providers.find((provider) => provider.id === providerId)?.latencyP95Ms ?? null) || "—"
  const rows = usageRows(usdUsageTotals)
  return (
    <section aria-labelledby="usage-totals-heading" className="space-y-4">
      <h3 id="usage-totals-heading" className="fs-section-title">Usage totals</h3>
      <div className="fs-panel overflow-hidden">
        {rows.length === 0 ? (
          <p className="px-4 py-8 text-center text-[13px] text-[var(--muted)]">No usage recorded yet</p>
        ) : (
          <table className="fs-table" aria-label="Usage totals">
            <thead>
              <tr>
                {COLUMNS.map((column, index) => (
                  <th key={column} scope="col" className={index === 0 ? undefined : "text-right"}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>{rows.map((row) => usageRow({ row, name: nameOf(row.provider), p95: p95Of(row.provider),
              free: catalogFree(pricedProviders.find((provider) => provider.id === row.provider), "keyed") === true }))}</tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function usageRow({ row, name, p95, free }: { row: UsageRow; name: string; p95: string; free: boolean }): ReactNode {
  const usd = sumAmounts(row.usd)
  return (
    <tr key={row.provider}>
      <td className="fs-cell-strong">
        <ProviderBadge providerId={row.provider} name={name} />
      </td>
      <td className="tnum text-right">{row.searches.toLocaleString("en-US")}</td>
      <td className="tnum text-right">{row.urls.toLocaleString("en-US")}</td>
      <td className="tnum text-right">{free ? "Free" : costText(usd)}</td>
      <td className="tnum text-right">{p95}</td>
    </tr>
  )
}
