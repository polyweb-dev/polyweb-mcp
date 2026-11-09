import { formatPoolBudget, type KeyPool } from "@/domains/vault"
import { formatCallCost } from "@/domains/providers"
import { useFreeProvider } from "../model/useFreeProvider"

export function PoolBudgetUsage({ pool }: { pool: KeyPool }) {
  const free = useFreeProvider(pool.provider_type)
  if (free) return <span className="text-[var(--muted)]">{formatCallCost(0)}</span>
  if (!pool.budget) return <span>No budget cap</span>
  const { limit } = pool.budget
  const text = formatPoolBudget(pool.budget, pool.budget_used_usd)
  const percent = limit <= 0 ? 100 : Math.min(100, Math.max(0, pool.budget_used_usd / limit * 100))
  const color = percent >= 100 ? "bg-[var(--status-danger)]" : percent >= 80 ? "bg-[var(--status-warning)]" : "bg-[var(--muted)]"
  return <div className="space-y-1">
    <span className="tnum block">{text}</span>
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"
      role="progressbar" aria-label={`Budget used for ${pool.label}`} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={percent} aria-valuetext={text}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
    </div>
  </div>
}
