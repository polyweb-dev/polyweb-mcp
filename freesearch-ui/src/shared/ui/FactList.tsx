import type { ReactNode } from "react"
import { cn } from "cn"

export interface Fact {
  label: string
  value: ReactNode
  /** Ids and figures use tabular mono digits. */
  mono?: boolean
}

/** Label and value pairs in one panel, one row each. The caller sets the width. */
export function FactList({
  facts,
  label,
  className,
}: {
  facts: readonly Fact[]
  label?: string
  className?: string
}) {
  return (
    <dl aria-label={label} className={cn("fs-panel divide-y divide-[var(--hairline)]", className)}>
      {facts.map((fact) => (
        <div key={fact.label} className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-4 px-4 py-2.5 text-[13px]">
          <dt className="text-[var(--muted)]">{fact.label}</dt>
          <dd className={fact.mono === true ? "m-0 break-all font-mono text-[12px] leading-5 text-[var(--text)]" : "m-0 text-[var(--text-strong)]"}>
            {fact.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
