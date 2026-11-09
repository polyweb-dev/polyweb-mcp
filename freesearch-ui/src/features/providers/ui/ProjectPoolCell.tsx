import type { ProjectPool } from "@/domains/projects"
import { formatCostBudgetUsage } from "@/domains/providers"
import { formatPoolRate, operationRate } from "@/domains/vault"
import type { PoolOperation } from "@/domains/vault"
import { useFreeProvider } from "@/features/vault/model/useFreeProvider"

export function ProjectPoolCell({ pool, operation }: { pool: ProjectPool | undefined; operation: PoolOperation }) {
  const free = useFreeProvider(pool?.provider_type ?? "")
  if (!pool) return <span className="text-[var(--muted)]">No pool</span>
  const budget = free ? null : pool.budget ? formatCostBudgetUsage(pool.budget, pool.budget_used) : "No budget"
  const rate = formatPoolRate(operationRate(pool.operation_limits?.[operation], pool.rate), { short: true })
  const otherOperation = pool.operations.length === 1 && !pool.operations.includes(operation) ? pool.operations[0] : undefined
  return <div title={`Pool: ${pool.label}. Key: ${pool.key_label}. Supplied by ${pool.owner.email}`}>
    <span className="text-[12px] text-[var(--muted)]">{rate}{budget && ` · ${budget}`}{otherOperation && ` · ${otherOperation === "search" ? "Search" : "Fetch"} only`}</span>
  </div>
}
