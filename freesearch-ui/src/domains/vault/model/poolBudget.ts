import { formatBudgetUsage } from "@/shared/lib/budget"
import type { PoolBudget } from "./types"

export function formatPoolBudget(budget: PoolBudget, used: number): string {
  return formatBudgetUsage(budget, used)
}
