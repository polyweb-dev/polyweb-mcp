import { usageOperationLabel, usageUnitsText } from "@/domains/usage"
import type { ProjectUsageTotal } from "@/domains/usage"
import { usageProviderLabel } from "../model/usageView"
import { USAGE_CELL, renderUsageTable } from "./usageTableParts"

const COLUMNS = ["Provider", "Operation", "Units", "Events"]

/** Units and events per provider and operation. */
export function UsageTotalsTable({ totals }: { totals: readonly ProjectUsageTotal[] }) {
  return renderUsageTable(
    "Usage totals",
    COLUMNS,
    totals.map((total) => (
      <tr
        key={`${total.provider}:${total.operation}:${total.unitKind ?? "legacy"}`}
        className="border-b border-[var(--border-subtle)] text-[var(--text)]"
      >
        <td className={USAGE_CELL}>{usageProviderLabel(total.provider)}</td>
        <td className={USAGE_CELL}>{usageOperationLabel(total.operation)}</td>
        <td className={`${USAGE_CELL} tnum`}>{usageUnitsText(total.totalUnits, total.unitKind)}</td>
        <td className={`${USAGE_CELL} tnum`}>{total.eventCount}</td>
      </tr>
    ))
  )
}
