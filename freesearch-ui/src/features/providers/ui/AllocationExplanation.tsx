import { explainAllocation } from "@/domains/providers"
import type { Allocation } from "@/domains/providers"

/** Shared strict / loans / best-effort explanation of one allocation. */
export function AllocationExplanation({ allocation }: { allocation: Allocation }) {
  const { badge, text } = explainAllocation(allocation)
  return (
    <div data-testid="allocation-explanation" className="space-y-1 text-[13px]">
      <span className="inline-block rounded border border-[var(--border-subtle)] px-1.5 py-0.5 text-[11px] uppercase tracking-wide text-[var(--text-strong)]">
        {badge}
      </span>
      <p className="text-[var(--text)]">{text}</p>
    </div>
  )
}
