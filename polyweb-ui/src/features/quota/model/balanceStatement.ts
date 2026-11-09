import type { NativePool } from "@/domains/dashboard"
import { formatRelativeTime } from "@/shared/lib/formatTime"

export function balanceStatement(pool: NativePool | null): string | null {
  if (pool === null) return null
  if (pool.source === "local_ledger" && !pool.manual_anchor) {
    const observed = pool.observed_at === null ? NaN : Date.parse(pool.observed_at)
    const recorded = Number.isFinite(observed) ? " " + formatRelativeTime(observed, Date.now()) : ""
    return "Balance recorded" + recorded + "; usage since then deducted"
  }
  if (pool.manual_anchor) return "Set balance · not reduced by usage"
  if (pool.source === "vendor_api" || pool.source === "vendor_headers") return "Reported by provider"
  return null
}
