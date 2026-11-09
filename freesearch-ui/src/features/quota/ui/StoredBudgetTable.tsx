import type { UsdGrantsSummary } from "@/domains/dashboard"
import { formatCostTotal } from "@/domains/providers"
import { formatUsdBudgetUsage } from "../model/usdDisplay"

/** Current calendar-window usage, with in-flight spend shown separately. */
export function StoredBudgetTable({ grants, fetchAvailable }: {
  grants: UsdGrantsSummary; fetchAvailable: boolean
}) {
  const rows = [{ name: "Search", limit: grants.search_granted_usd, used: grants.search_consumed_usd,
    reserved: grants.search_reserved_usd }]
  if (fetchAvailable) rows.push({ name: "Fetch", limit: grants.fetch_granted_usd,
    used: grants.fetch_consumed_usd, reserved: grants.fetch_reserved_usd })
  return <table className="fs-table" aria-label="Current budget limit">
    <thead><tr><th scope="col">Operation</th><th scope="col" className="text-right">Usage</th>
      <th scope="col" className="text-right">Reserved (USD)</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.name}><td className="fs-cell-strong">{row.name}</td>
      <td className="tnum text-right">{formatUsdBudgetUsage(row.limit, row.used, grants.period)}</td>
      <td className="tnum text-right">{formatCostTotal(row.reserved)}</td></tr>)}</tbody>
  </table>
}
