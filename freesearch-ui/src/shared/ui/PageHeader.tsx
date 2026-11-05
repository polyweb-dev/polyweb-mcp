import type { ReactNode } from "react"

export interface PageHeaderProps {
  title: string
  description?: string
  actions?: ReactNode
}

/**
 * Shared page header of the project sections: one quiet title line, an
 * optional one-line description and right-aligned actions. The heading keeps
 * level h2, matching the section pages it now unifies.
 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4 border-b border-[var(--border-subtle)] pb-3">
      <div className="min-w-0">
        <h2 className="text-xl font-medium text-[var(--text-strong)]">{title}</h2>
        {description !== undefined && (
          <p className="mt-0.5 truncate text-[13px] text-[var(--muted)]">{description}</p>
        )}
      </div>
      {actions !== undefined && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
