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
  return <><table className="fs-table w-full" aria-label="Pools of this key">
    <thead><tr><th>Project</th><th>Pool</th><th>Allows</th><th>Rate</th><th>Budget</th><th><span className="sr-only">Actions</span></th></tr></thead>
    <tbody>{pools.map((pool) => <tr key={pool.id}>
      <td>{pool.project_id ? projects.find((entry) => entry.id === pool.project_id)?.name ?? pool.project_id : <Tag tone="warning">Unassigned</Tag>}</td>
      <td>{pool.label}</td><td>{pool.operations.map((op) => <Tag key={op}>{op === "search" ? "Search" : "Fetch"}</Tag>)}</td>
      <td>{formatPoolRate(pool.rate, { short: true, operationLimits: pool.operation_limits })}</td><td><PoolBudgetUsage pool={pool} /></td>
      <td className="w-12 !pr-0 !text-right"><RowActionsMenu label={`Actions for ${pool.label}`} actions={[
        { key: "edit", label: "Edit pool", onSelect: () => onAction("edit", pool) },
        { key: "copy", label: "Copy to another project", onSelect: () => onAction("copy", pool) },
        pool.project_id ? { key: "unassign", label: "Remove from project", onSelect: () => onAction("unassign", pool) } : { key: "assign", label: "Assign to project", onSelect: () => onAction("assign", pool) },
        { key: "delete", label: "Delete pool", danger: true, onSelect: () => onAction("delete", pool) },
      ]} /></td>
    </tr>)}</tbody>
  </table>{!free && pools.some((pool) => pool.budget) && <p className="fs-hint">{POOL_BUDGET_HELP}</p>}</>
}
