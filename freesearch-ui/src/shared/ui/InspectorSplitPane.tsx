import type { ReactNode } from "react"
import { cn } from "cn"

export interface InspectorSplitPaneProps {
  /** Accessible name of the primary working pane (list, rows, document). */
  primaryLabel: string
  /** Accessible name of the side inspector that explains the selection. */
  detailLabel: string
  primary: ReactNode
  detail: ReactNode
  className?: string
}

/**
 * Neutral master/detail geometry: a primary pane the user works in and a side
 * inspector that stays visible while that pane scrolls. It owns layout only —
 * no domain types, selection state, fetching, or copy — so the Playground and
 * the Activity dialog can share one composition without sharing a model.
 */
export function InspectorSplitPane({
  primaryLabel,
  detailLabel,
  primary,
  detail,
  className,
}: InspectorSplitPaneProps) {
  return (
    <div
      className={cn(
        "grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(20rem,5fr)] lg:gap-6",
        className
      )}
    >
      <section role="region" aria-label={primaryLabel} className="min-w-0">
        {primary}
      </section>
      <section role="region" aria-label={detailLabel} className="min-w-0 lg:sticky lg:top-0">
        {detail}
      </section>
    </div>
  )
}
