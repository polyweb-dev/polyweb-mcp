import { usageOperationLabel, usageUnitsText } from "@/domains/usage"
import type { ProjectUsageEntry } from "@/domains/usage"
import { usageLatencyText, usageProviderLabel, usageTimeText } from "../model/usageView"
import { USAGE_CELL, renderUsageTable } from "./usageTableParts"

const COLUMNS = ["Time", "Provider", "Operation", "Units", "Status", "Latency"]

/** The recent usage ledger, newest first as the server sends it. */
export function RecentUsageTable({ entries }: { entries: readonly ProjectUsageEntry[] }) {
  return renderUsageTable(
    "Recent usage",
    COLUMNS,
    entries.map((entry, index) => (
      <tr
        key={`${entry.observedAt}:${entry.provider}:${index}`}
        className="border-b border-[var(--border-subtle)] text-[var(--text)]"
      >
        <td className={`${USAGE_CELL} tnum`}>{usageTimeText(entry.observedAt)}</td>
        <td className={USAGE_CELL}>{usageProviderLabel(entry.provider)}</td>
        <td className={USAGE_CELL}>{usageOperationLabel(entry.operation)}</td>
        <td className={`${USAGE_CELL} tnum`}>
          {usageUnitsText(entry.units, entry.unitKind, entry.displayUnit)}
        </td>
        <td className={USAGE_CELL}>{entry.status === "failure" ? "Failure" : "Success"}</td>
        <td className={`${USAGE_CELL} tnum`}>{usageLatencyText(entry.latencyMs)}</td>
      </tr>
    ))
  )
}
