import type { ReactNode } from "react"
import { cn } from "cn"

export interface EmptyStateProps {
  title: string
  description?: ReactNode
  action?: ReactNode
  /** Drops the panel surface when the state already sits inside one. */
  bare?: boolean
}

/** Quiet empty or unavailable state: what is missing and the next step. */
export function EmptyState({ title, description, action, bare = false }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center gap-1 px-6 py-10 text-center", !bare && "fs-panel")}>
      <p className="text-[13px] font-medium text-[var(--text-strong)]">{title}</p>
      {description !== undefined && (
        <p className="max-w-[56ch] text-[13px] text-[var(--muted)]">{description}</p>
      )}
      {action !== undefined && <div className="mt-3">{action}</div>}
    </div>
  )
}
