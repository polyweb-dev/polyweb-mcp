import type { ReactNode } from "react"
import { catalogNameOf } from "@/services/api/providerCatalog"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import type { CRDUsageTotal } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import { dollarText, sumAmounts } from "../model/crdDisplay"
import { groupDigits, latencyText } from "../model/numberText"
import { multiplyDecimal } from "../model/manualQuotaMath"

export interface UsageTotalsProps {
  crdUsageTotals: CRDUsageTotal[]
  providers: ProviderConfig[]
}

/** One provider row of the merged usage table. */
interface UsageRow {
  provider: string
  searches: number
  urls: number
  crd: string[]
}

const COLUMNS = ["Provider", "Searches", "URLs fetched", "Known cost", "p95"]

/** One row per provider, in first-seen order, with searches, URLs, and CRD added up. */
function usageRows(totals: CRDUsageTotal[]): UsageRow[] {
  const rows: UsageRow[] = []
  for (const total of totals) {
    let row = rows.find((entry) => entry.provider === total.provider)
    if (row === undefined) {
      row = { provider: total.provider, searches: 0, urls: 0, crd: [] }
      rows.push(row)
    }
    if (total.operation === "fetch") row.urls += total.volume_count
    else row.searches += total.volume_count
    row.crd.push(total.normalized_crd)
  }
  return rows
}

/** The USD reference value of one normalized usage amount. */
function costText(crd: string | null): string {
  if (crd === null) return ""
  const usd = multiplyDecimal(crd, "0.001")
  return usd === null ? "" : groupDigits(dollarText(usd))
}

/**
 * Usage totals: one table, one row per provider, with searches, fetched URLs,
 * the USD cost, and the provider p95. Numbers carry separators.
 */
export function UsageTotals({ crdUsageTotals, providers }: UsageTotalsProps) {
  const nameOf = (providerId: string) => catalogNameOf(providerId) ?? providerId
  const p95Of = (providerId: string) =>
    latencyText(providers.find((provider) => provider.id === providerId)?.latencyP95Ms ?? null)
  const rows = usageRows(crdUsageTotals)
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
            <tbody>{rows.map((row) => usageRow(row, nameOf(row.provider), p95Of(row.provider)))}</tbody>
          </table>
        )}
      </div>
    </section>
  )
}

function usageRow(row: UsageRow, name: string, p95: string): ReactNode {
  const crd = sumAmounts(row.crd)
  return (
    <tr key={row.provider}>
      <td className="fs-cell-strong">
        <span className="flex min-w-0 items-center gap-2">
          <ProviderLogo providerId={row.provider} name={name} />
          <span className="truncate">{name}</span>
        </span>
      </td>
      <td className="tnum text-right">{row.searches.toLocaleString("en-US")}</td>
      <td className="tnum text-right">{row.urls.toLocaleString("en-US")}</td>
      <td className="tnum text-right">{costText(crd)}</td>
      <td className="tnum text-right">{p95}</td>
    </tr>
  )
}
