import type { ReactNode } from "react"

/** Cell style shared by the usage tables. */
export const USAGE_CELL = "py-2 pr-4 align-top"

const EMPTY_MESSAGE = "No usage recorded for this project yet."

/**
 * One usage table: an accessible name, the column headers, and its rows, or
 * the project empty state when there is no row.
 */
export function renderUsageTable(label: string, columns: readonly string[], rows: ReactNode[]) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
            {columns.map((column) => (
              <th key={column} scope="col" className="py-2 pr-4 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-3 text-[var(--muted)]">
                {EMPTY_MESSAGE}
              </td>
            </tr>
          ) : (
            rows
          )}
        </tbody>
      </table>
    </div>
  )
}
