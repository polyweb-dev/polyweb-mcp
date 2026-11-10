import { Copy, MinusCircle, Pencil, PlusCircle, Trash2 } from "lucide-react"
import { formatPoolRate } from "@/domains/vault"
import type { KeyPool, VaultProject } from "@/domains/vault"
import { RowActionsMenu } from "@/shared/ui/RowActionsMenu"
import { Tag } from "@/shared/ui/Tag"
import { PoolBudgetUsage } from "./PoolBudgetUsage"
import type { PoolAction } from "./vaultTableTypes"

export function VaultPoolsTable({ pools, projects, onAction }: {
  pools: KeyPool[]
  projects: VaultProject[]
  onAction: (action: PoolAction, pool: KeyPool) => void
}) {
  if (pools.length === 0) return <tr><td colSpan={6}>No pools yet. Create a pool to let a project use this key</td></tr>
  return <>
    {pools.map((pool) => <tr key={pool.id}>
      <td />
      <td className="font-medium">{pool.label}</td>
      <td><div className="flex flex-wrap items-center gap-2 text-[var(--muted)]">
          {pool.operations.map((op) => <Tag key={op}>{op === "search" ? "Search" : "Fetch"}</Tag>)}
      </div></td>
      <td><span className="tnum text-[var(--muted)]">{formatPoolRate(pool.rate, { short: true, operationLimits: pool.operation_limits })}</span></td>
      <td><div className="space-y-2">
        {pool.project_id ? (() => {
          const name = projects.find((entry) => entry.id === pool.project_id)?.name ?? pool.project_id
          return name !== pool.label ? <div>{name}</div> : null
        })() : <Tag tone="warning">Unassigned</Tag>}
        <PoolBudgetUsage pool={pool} />
      </div></td>
      <td className="w-16 !text-right"><RowActionsMenu label={`Actions for ${pool.label}`} actions={[
        { key: "edit", label: "Edit pool", icon: Pencil, onSelect: () => onAction("edit", pool) },
        { key: "copy", label: "Copy to another project", icon: Copy, onSelect: () => onAction("copy", pool) },
        pool.project_id
          ? { key: "unassign", label: "Remove from project", icon: MinusCircle, onSelect: () => onAction("unassign", pool) }
          : { key: "assign", label: "Assign to project", icon: PlusCircle, onSelect: () => onAction("assign", pool) },
        { key: "delete", label: "Delete pool", icon: Trash2, danger: true, onSelect: () => onAction("delete", pool) },
      ]} /></td>
    </tr>)}
  </>
}
