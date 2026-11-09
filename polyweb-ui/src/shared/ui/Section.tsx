import { useId } from "react"
import type { ReactNode } from "react"
import { cn } from "cn"

export interface SectionProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
  /** Wraps the body in the shared panel surface. */
  panel?: boolean
  className?: string
  children: ReactNode
}

/**
 * One titled block of a workspace page: an h3 title, an optional muted
 * description, right-aligned actions and the body. Every page section uses
 * it, so section headings share one size, weight and rhythm.
 */
export function Section({ title, description, actions, panel = false, className, children }: SectionProps) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className={cn("space-y-3", className)}>
      <div className="flex min-h-8 items-end justify-between gap-4">
        <div className="min-w-0">
          <h3 id={headingId} className="fs-section-title">
            {title}
          </h3>
          {description !== undefined && <p className="fs-section-description">{description}</p>}
        </div>
        {actions !== undefined && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {panel ? <div className="fs-panel overflow-hidden">{children}</div> : children}
    </section>
  )
}
