import type { ReactNode } from "react"

/** Collapsible section used for the timeline and technical disclosures. */
export function TraceDisclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} className="rounded border border-[var(--border-subtle)]">
      <summary className="cursor-pointer px-3 py-2 text-[13px] text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40">
        {title}
      </summary>
      <div className="space-y-3 border-t border-[var(--border-subtle)] p-3">{children}</div>
    </details>
  )
}
