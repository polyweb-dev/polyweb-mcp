import type { ReactNode } from "react"
import { cn } from "cn"

export interface FormActionsProps {
  children: ReactNode
  /** Left-aligned content such as a status line or a secondary link. */
  start?: ReactNode
  className?: string
}

/**
 * The action row at the end of every form and dialog: optional status on the
 * left, then the buttons on the right with Cancel first and the primary last.
 * Buttons inside use `size="form"`.
 */
export function FormActions({ children, start, className }: FormActionsProps) {
  return (
    <div className={cn("mt-6 flex items-center justify-between gap-3", className)}>
      <div className="min-w-0 text-[13px] text-[var(--muted)]">{start}</div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  )
}
