import type { ProjectPool } from "@/domains/projects"
import { formatPoolBudget, formatPoolRate } from "@/domains/vault"
import type { PoolOperation } from "@/domains/vault"
import { useFreeProvider } from "@/features/vault/model/useFreeProvider"

export function ProjectPoolCell({ pool, operation }: { pool: ProjectPool | undefined; operation: PoolOperation }) {
  const free = useFreeProvider(pool?.provider_type ?? "")
  if (!pool) return <span className="text-[var(--muted)]">No pool</span>
  const budget = free ? "Free" : pool.budget ? formatPoolBudget(pool.budget, pool.budget_used) : "No budget"
  const rate = formatPoolRate(pool.rate).replace(/ per minute$/, "/min")
  const otherOperation = pool.operations.length === 1 && !pool.operations.includes(operation) ? pool.operations[0] : undefined
  return <div title={`Key: ${pool.key_label}. Supplied by ${pool.owner.email}`}>
    <span>{pool.label}</span>
    <div className="text-[12px] text-[var(--muted)]">{rate} · {budget}{otherOperation && ` · ${otherOperation === "search" ? "Search" : "Fetch"} only`}</div>
  </div>
}
