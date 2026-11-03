import { constraintText, providerTypeName } from "@/domains/providers"
import type { Pool } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { CELL_CLASS, HEAD_CLASS } from "./formStyles"

const COLUMNS = ["Provider", "Label", "Scope", "Pool key", "Limits", "Concurrency", "Queue", "Status"]

interface PoolsTableProps {
  pools: readonly Pool[]
  canManage: boolean
  onEdit: (pool: Pool) => void
  onLinks: (pool: Pool) => void
}

const orDash = (value: number | null) => (value === null ? "—" : String(value))

/** Upstream pools with their rate constraints; never a balance. */
export function PoolsTable({ pools, canManage, onEdit, onLinks }: PoolsTableProps) {
  return (
    <table aria-label="Pools" className="w-full text-left text-[13px]">
      <thead>
        <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
          {COLUMNS.map((column) => (<th key={column} scope="col" className={HEAD_CLASS}>{column}</th>))}
          <th scope="col" className={HEAD_CLASS}><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {pools.length === 0 && (
          <tr><td colSpan={COLUMNS.length + 1} className="py-3 text-[var(--muted)]">No pools yet.</td></tr>
        )}
        {pools.map((pool) => (
          <tr key={pool.id} className="border-b border-[var(--border-subtle)] text-[var(--text)]">
            <td className={CELL_CLASS}>{providerTypeName(pool.providerType)}</td>
            <td className={CELL_CLASS}>{pool.label}</td>
            <td className={CELL_CLASS}>{pool.upstreamScope}</td>
            <td className={`${CELL_CLASS} font-mono text-[12px]`}>{pool.poolKey}</td>
            <td className={CELL_CLASS}>
              {pool.constraints.length === 0 ? "None" : pool.constraints.map((constraint, index) => (
                <div key={index}>{constraintText(constraint)}</div>
              ))}
            </td>
            <td className={`${CELL_CLASS} tnum`}>{orDash(pool.maxConcurrency)}</td>
            <td className={`${CELL_CLASS} tnum`}>{orDash(pool.maxQueuedRequests)}</td>
            <td className={CELL_CLASS}>{pool.status}</td>
            <td className="py-2 align-top">
              {canManage && (
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="outline" aria-label={`Edit pool ${pool.label}`} onClick={() => onEdit(pool)}>Edit</Button>
                  <Button size="sm" variant="outline" aria-label={`Links ${pool.label}`} onClick={() => onLinks(pool)}>Links</Button>
                </div>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
