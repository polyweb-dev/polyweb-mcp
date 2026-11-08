import type { ProjectPool } from "@/domains/projects"
import { formatPoolRate } from "@/domains/vault"

export function ProjectPoolCell({ pool, free = false }: { pool: ProjectPool | undefined; free?: boolean }) {
  if (!pool) return <span className="text-[var(--muted)]">No pool</span>
  const budget = pool.budget && !free
    ? `$${pool.budget_used.toFixed(2)} of $${pool.budget.limit.toFixed(2)} this ${pool.budget.period}`
    : "No budget"
  return <div title={`Key: ${pool.key_label}. Supplied by ${pool.owner.email}`}>
    <span>{pool.label}</span>
    <div className="text-[12px] text-[var(--muted)]">{formatPoolRate(pool.rate)}{!free && ` · ${budget}`}{pool.operations.length === 1 && ` · ${pool.operations[0] === "search" ? "Search" : "Fetch"} only`}</div>
  </div>
}
