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
  if (pools.length === 0) return <tr><td colSpan={5}>No pools yet. Create a pool to let a project use this key</td></tr>
  return <>
    {pools.map((pool) => <tr key={pool.id}>
      <td />
      <td className="font-medium">{pool.label}</td>
      <td><div className="flex flex-wrap items-center gap-2 text-[var(--muted)]">
          {pool.operations.map((op) => <Tag key={op}>{op === "search" ? "Search" : "Fetch"}</Tag>)}
          <span>{formatPoolRate(pool.rate, { short: true, operationLimits: pool.operation_limits })}</span>
      </div></td>
      <td><div className="space-y-2">
        {pool.project_id ? (() => {
          const name = projects.find((entry) => entry.id === pool.project_id)?.name ?? pool.project_id
          return name !== pool.label ? <div>{name}</div> : null
        })() : <Tag tone="warning">Unassigned</Tag>}
        <PoolBudgetUsage pool={pool} />
      </div></td>
      <td className="w-16 !text-right"><RowActionsMenu label={`Actions for ${pool.label}`} actions={[
        { key: "edit", label: "Edit pool", onSelect: () => onAction("edit", pool) },
        { key: "copy", label: "Copy to another project", onSelect: () => onAction("copy", pool) },
        pool.project_id ? { key: "unassign", label: "Remove from project", onSelect: () => onAction("unassign", pool) } : { key: "assign", label: "Assign to project", onSelect: () => onAction("assign", pool) },
        { key: "delete", label: "Delete pool", danger: true, onSelect: () => onAction("delete", pool) },
      ]} /></td>
    </tr>)}
    {!free && pools.some((pool) => pool.budget) && <tr><td /><td colSpan={4}><p className="fs-hint">{POOL_BUDGET_HELP}</p></td></tr>}
  </>
}
