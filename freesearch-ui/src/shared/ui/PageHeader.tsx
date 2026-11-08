import type { ReactNode } from "react"

export interface PageHeaderProps {
  title: string
  description?: ReactNode
  /** Quiet inline facts beside the title, such as role or status tags. */
  meta?: ReactNode
  actions?: ReactNode
}

/**
 * Shared page header of every workspace page: one quiet title line, an
 * optional one-line description and right-aligned actions on a hairline.
 * The heading keeps level h2, matching the section pages it unifies.
 */
export function PageHeader({ title, description, meta, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex min-h-12 items-center justify-between gap-6 border-b border-[var(--border-subtle)] pb-4">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-3">
          <h2 className="truncate text-[20px] leading-7 font-medium text-[var(--text-strong)]">
            {title}
          </h2>
          {meta !== undefined && <div className="flex shrink-0 items-center gap-1.5">{meta}</div>}
        </div>
        {description !== undefined && (
          <p className="mt-0.5 max-w-[72ch] text-[13px] leading-5 text-[var(--muted)]">
            {description}
          </p>
        )}
      </div>
      {actions !== undefined && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
