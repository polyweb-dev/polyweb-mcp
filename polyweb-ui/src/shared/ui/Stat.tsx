import type { ReactNode } from "react"

export interface StatProps {
  label: string
  value: ReactNode
  /** One short line under the figure, such as the units behind it. */
  detail?: ReactNode
}

/** One figure tile: a label, the number and one quiet line of detail. */
export function Stat({ label, value, detail }: StatProps) {
  return (
    <div className="fs-panel px-4 py-3">
      <dt className="text-[12px] text-[var(--muted)]">{label}</dt>
      <dd className="m-0 mt-1 text-[24px] leading-8 font-medium text-[var(--text-strong)] tnum">{value}</dd>
      {detail !== undefined && (
        <dd className="m-0 truncate text-[12px] text-[var(--muted)] tnum">{detail}</dd>
      )}
    </div>
  )
}
