import { formatBudgetUsage } from "@/shared/lib/budget"
import type { PoolBudget } from "./types"

export function formatPoolBudget(budget: PoolBudget, used: number): string {
  return formatBudgetUsage(budget, used)
}
export const POOL_BUDGET_HELP = "Calls with no known cost do not count. Resets each period"
