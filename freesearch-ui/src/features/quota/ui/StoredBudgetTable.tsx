import type { ReactNode } from "react"
import type { CRDConversionProfile, CRDGrantsSummary } from "@/domains/dashboard"
import { dollarText } from "../model/crdDisplay"
import { multiplyDecimal } from "../model/manualQuotaMath"
import { SPEND_CAP } from "../model/quotaLabels"

/** The shown text of one stored amount: Credits under a profile, CRD otherwise. */
function storedAmountText(crd: string, conversion: CRDConversionProfile | null): string {
  void conversion
  return dollarText(multiplyDecimal(crd, "0.001") ?? "0")
}

/**
 * The stored budget limit of the reported operations as one compact table:
 * one row per operation with the set, used, and reserved amounts.
 */
export function StoredBudgetTable({ grants, fetchAvailable, conversion }: { grants: CRDGrantsSummary; fetchAvailable: boolean; conversion: CRDConversionProfile | null }): ReactNode {
  const rows = [
    {
      name: "Search",
      set: grants.search_granted_crd,
      used: grants.search_consumed_crd,
      reserved: grants.search_reserved_crd,
    },
  ]
  if (fetchAvailable) {
    rows.push({
      name: "Fetch",
      set: grants.fetch_granted_crd,
      used: grants.fetch_consumed_crd,
      reserved: grants.fetch_reserved_crd,
    })
  }
  return (
    <table className="fs-table" aria-label={"Current " + SPEND_CAP.toLowerCase()}>
      <thead>
        <tr>
          <th scope="col">Operation</th>
          <th scope="col" className="text-right">Set (USD)</th>
          <th scope="col" className="text-right">Used (USD)</th>
          <th scope="col" className="text-right">Reserved (USD)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <td className="fs-cell-strong">{row.name}</td>
            <td className="tnum text-right">{storedAmountText(row.set, conversion)}</td>
            <td className="tnum text-right">{storedAmountText(row.used, conversion)}</td>
            <td className="tnum text-right">{storedAmountText(row.reserved, conversion)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

