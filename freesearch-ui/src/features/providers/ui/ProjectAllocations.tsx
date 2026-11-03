import type { Allocation, ProviderTypeView } from "@/domains/providers"
import { AllocationExplanation } from "./AllocationExplanation"
import { NOTE_CLASS } from "./formStyles"

/** Pool label of one allocation from the view's credential pool refs, else the id. */
function poolLabel(poolId: string, providers: readonly ProviderTypeView[]): string {
  for (const provider of providers) {
    for (const credential of provider.credentials) {
      const pool = credential.pools.find((ref) => ref.poolId === poolId)
      if (pool !== undefined) return pool.label
    }
  }
  return poolId
}

interface ProjectAllocationsProps {
  allocations: readonly Allocation[]
  providers: readonly ProviderTypeView[]
}

/** Read-only shared-pool allocations of this project. */
export function ProjectAllocations({ allocations, providers }: ProjectAllocationsProps) {
  return (
    <section aria-labelledby="project-allocations-heading" className="space-y-3">
      <h2 id="project-allocations-heading" className="text-[var(--text-strong)]">
        Capacity allocations
      </h2>
      {allocations.length === 0 ? (
        <p className={NOTE_CLASS}>No shared-pool allocations are set for this project.</p>
      ) : (
        <ul className="space-y-3">
          {allocations.map((allocation) => (
            <li
              key={`${allocation.poolId}:${allocation.operation}`}
              className="rounded border border-[var(--border-subtle)] p-3"
            >
              <p className="mb-1 text-[13px] font-medium text-[var(--text-strong)]">
                {poolLabel(allocation.poolId, providers)} · {allocation.operation}
              </p>
              <AllocationExplanation allocation={allocation} />
            </li>
          ))}
        </ul>
      )}
      <p className={NOTE_CLASS}>Set by a system administrator.</p>
    </section>
  )
}
