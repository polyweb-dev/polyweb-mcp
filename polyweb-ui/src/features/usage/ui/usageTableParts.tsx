import type { ReactNode } from "react"

const EMPTY_MESSAGE = "No usage recorded for this project yet"

/** Header of one usage column; numeric columns align right. */
export interface UsageColumn {
  label: string
  numeric?: boolean
  /** What the column counts, as a header tooltip. */
  hint?: string
}

/** One usage table: its accessible name, the column headers, rows and an optional total row. */
interface UsageTableOptions {
  label: string
  columns: readonly UsageColumn[]
  rows: ReactNode[]
  footer?: ReactNode
}

/**
 * One usage table on the shared table styles, or the project empty state when
 * there is no row.
 */
export function renderUsageTable({ label, columns, rows, footer }: UsageTableOptions) {
  return (
    <div className="fs-panel overflow-x-auto">
      <table aria-label={label} className="fs-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.label}
                scope="col"
                title={column.hint}
                className={column.numeric === true ? "text-right" : undefined}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="fs-cell-empty">
                {EMPTY_MESSAGE}
              </td>
            </tr>
          ) : (
            rows
          )}
        </tbody>
        {rows.length > 0 && footer !== undefined && <tfoot>{footer}</tfoot>}
      </table>
    </div>
  )
}
