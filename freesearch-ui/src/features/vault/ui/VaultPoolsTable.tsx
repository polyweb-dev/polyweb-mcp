import { formatPoolRate, POOL_BUDGET_HELP } from "@/domains/vault"
import type { KeyPool, VaultProject } from "@/domains/vault"
import { RowActionsMenu } from "@/shared/ui/RowActionsMenu"
import { Tag } from "@/shared/ui/Tag"
import { useFreeProvider } from "../model/useFreeProvider"
import { PoolBudgetUsage } from "./PoolBudgetUsage"
import type { PoolAction } from "./vaultTableTypes"

export function VaultPoolsTable({ pools, projects, onAction }: {
  pools: KeyPool[]
  projects: VaultProject[]
  onAction: (action: PoolAction, pool: KeyPool) => void
}) {
  const free = useFreeProvider(pools[0]?.provider_type ?? "")
  if (pools.length === 0) return <p>No pools yet. Create a pool to let a project use this key</p>
  return <><ul aria-label="Pools of this key" className="space-y-3 pl-6">
    {pools.map((pool) => <li key={pool.id} className="flex items-start justify-between gap-4">
      <div className="space-y-1">
        <div className="font-medium">{pool.label}</div>
        <div className="flex flex-wrap items-center gap-2 text-[var(--muted)]">
          <span>{pool.project_id ? projects.find((entry) => entry.id === pool.project_id)?.name ?? pool.project_id : <Tag tone="warning">Unassigned</Tag>}</span>
          {pool.operations.map((op) => <Tag key={op}>{op === "search" ? "Search" : "Fetch"}</Tag>)}
          <span>{formatPoolRate(pool.rate, { short: true, operationLimits: pool.operation_limits })}</span>
          <PoolBudgetUsage pool={pool} />
        </div>
      </div>
      <RowActionsMenu label={`Actions for ${pool.label}`} actions={[
        { key: "edit", label: "Edit pool", onSelect: () => onAction("edit", pool) },
        { key: "copy", label: "Copy to another project", onSelect: () => onAction("copy", pool) },
        pool.project_id ? { key: "unassign", label: "Remove from project", onSelect: () => onAction("unassign", pool) } : { key: "assign", label: "Assign to project", onSelect: () => onAction("assign", pool) },
        { key: "delete", label: "Delete pool", danger: true, onSelect: () => onAction("delete", pool) },
      ]} />
    </li>)}
  </ul>{!free && pools.some((pool) => pool.budget) && <p className="fs-hint pl-6">{POOL_BUDGET_HELP}</p>}</>
}
