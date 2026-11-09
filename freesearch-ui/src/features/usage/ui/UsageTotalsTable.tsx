import { usageOperationLabel } from "@/domains/usage"
import type { ProjectUsageTotal } from "@/domains/usage"
import type { ProjectOrder } from "@/domains/routing"
import {
  USAGE_COLUMN_HINTS,
  USAGE_COLUMN_LABELS,
  usageAmountText,
  usageTotalsView,
  type UsageAmountColumn,
  type UsageAmounts,
} from "../model/usageTotalsView"
import { UsageProviderCell } from "./UsageProviderCell"
import { renderUsageTable, type UsageColumn } from "./usageTableParts"

const FIXED_COLUMNS: UsageColumn[] = [
  { label: "Provider" },
  { label: "Operation" },
  { label: "Calls", numeric: true },
]

const FOOTER_CELL = "border-t border-[var(--border-subtle)] tnum text-right fs-cell-strong"

function amountCells(amounts: UsageAmounts, columns: readonly UsageAmountColumn[], className: string) {
  return columns.map((column) => {
    const text = usageAmountText(amounts, column)
    return (
      <td key={column} className={text === "—" ? `${className} text-[var(--muted)]` : className}>
        {text}
      </td>
    )
  })
}

/**
 * Calls and metered units per provider and operation, every unit kind in its
 * own column, with a total row when more than one provider row is listed.
 */
export function UsageTotalsTable({ totals, order }: { totals: readonly ProjectUsageTotal[]; order?: ProjectOrder }) {
  const view = usageTotalsView(totals, order)
  const columns: UsageColumn[] = [
    ...FIXED_COLUMNS,
    ...view.columns.map((column) => ({
      label: USAGE_COLUMN_LABELS[column],
      hint: USAGE_COLUMN_HINTS[column],
      numeric: true,
    })),
  ]
  const footer =
    view.rows.length > 1 ? (
      <tr>
        <td colSpan={2} className="border-t border-[var(--border-subtle)] fs-cell-strong">
          Total
        </td>
        <td className={FOOTER_CELL}>{view.total.calls.toLocaleString("en-US")}</td>
        {amountCells(view.total, view.columns, FOOTER_CELL)}
      </tr>
    ) : undefined
  return renderUsageTable({
    label: "Usage totals",
    columns,
    footer,
    rows: view.rows.map((row) => (
      <tr key={row.key}>
        <td>
          <UsageProviderCell provider={row.provider} />
        </td>
        <td>{usageOperationLabel(row.operation)}</td>
        <td className="tnum text-right">{row.calls.toLocaleString("en-US")}</td>
        {amountCells(row, view.columns, "tnum text-right")}
      </tr>
    )),
  })
}
