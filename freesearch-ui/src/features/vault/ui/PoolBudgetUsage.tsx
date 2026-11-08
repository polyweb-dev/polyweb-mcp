import type { KeyPool } from "@/domains/vault"
import { useFreeProvider } from "../model/useFreeProvider"

const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6,
})

export function PoolBudgetUsage({ pool }: { pool: KeyPool }) {
  const free = useFreeProvider(pool.provider_type)
  if (free) return <span className="text-[var(--muted)]">Free</span>
  if (!pool.budget) return <span>No budget cap</span>
  const { limit, period } = pool.budget
  const text = `${usd.format(pool.budget_used_usd)} of ${usd.format(limit)} per ${period}`
  const percent = limit <= 0 ? 100 : Math.min(100, Math.max(0, pool.budget_used_usd / limit * 100))
  const color = percent >= 100 ? "bg-[var(--status-danger)]" : percent >= 80 ? "bg-[var(--status-warning)]" : "bg-[var(--muted)]"
  return <div className="space-y-1">
    <span className="tnum">{text}</span>
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"
      role="progressbar" aria-label={`Budget used for ${pool.label}`} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={percent} aria-valuetext={text}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
    </div>
  </div>
}
