import type { Allocation, Pool } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { AllocationExplanation } from "./AllocationExplanation"
import { CELL_CLASS, HEAD_CLASS } from "./formStyles"

interface AllocationsTableProps {
  allocations: readonly Allocation[]
  pools: readonly Pool[]
  canManage: boolean
  pending: boolean
  onEdit: (allocation: Allocation) => void
  onRemove: (allocation: Allocation) => void
}

/** Allocations of one project, each with the shared explanation. */
export function AllocationsTable(props: AllocationsTableProps) {
  const { allocations, pools, canManage, pending, onEdit, onRemove } = props
  const labels = new Map(pools.map((pool) => [pool.id, pool.label]))
  return (
    <table aria-label="Allocations" className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
          <th scope="col" className={HEAD_CLASS}>Pool</th>
          <th scope="col" className={HEAD_CLASS}>Operation</th>
          <th scope="col" className={HEAD_CLASS}>Allocation</th>
          <th scope="col" className={HEAD_CLASS}><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {allocations.length === 0 && (
          <tr><td colSpan={4} className="py-3 text-[var(--muted)]">No shared-pool allocations are set for this project.</td></tr>
        )}
        {allocations.map((allocation) => {
          const name = `${labels.get(allocation.poolId) ?? allocation.poolId} ${allocation.operation}`
          return (
            <tr key={`${allocation.poolId}:${allocation.operation}`} className="border-b border-[var(--border-subtle)]">
              <td className={CELL_CLASS}>{labels.get(allocation.poolId) ?? allocation.poolId}</td>
              <td className={CELL_CLASS}>{allocation.operation}</td>
              <td className={CELL_CLASS}><AllocationExplanation allocation={allocation} /></td>
              <td className="py-2 align-top">
                {canManage && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="outline" aria-label={`Edit allocation ${name}`} disabled={pending} onClick={() => onEdit(allocation)}>Edit</Button>
                    <Button size="sm" variant="destructive" aria-label={`Remove allocation ${name}`} disabled={pending} onClick={() => onRemove(allocation)}>Remove</Button>
                  </div>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
