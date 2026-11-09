export type BudgetPeriod = "day" | "week" | "month"

const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
})

const periodText: Record<string, string> = {
  day: "today", week: "this week", month: "this month",
}

export function formatBudgetUsd(amount: number): string {
  return usd.format(amount)
}

export function formatBudgetUsage(budget: { limit: number; period: string }, used: number): string {
  return `${formatBudgetUsd(used)} of ${formatBudgetUsd(budget.limit)} ${periodText[budget.period]}`
}
