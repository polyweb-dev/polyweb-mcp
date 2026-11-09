import { asRecord } from "@/shared/api/decode"

type Operation = "search" | "fetch"
type CallCosts = Partial<Record<Operation, string | number | null>>

export interface ProviderPricing {
  callCostUsd?: CallCosts
  /** A priced operation here also confirms that public keyless access exists. */
  keylessCallCostUsd?: CallCosts
}

export function decodeCallCosts(value: unknown): CallCosts {
  const record = asRecord(value)
  const costs: CallCosts = {}
  for (const operation of ["search", "fetch"] as const) {
    const cost = record?.[operation]
    if ((typeof cost === "string" || typeof cost === "number") && cost !== "" && Number.isFinite(Number(cost)) && Number(cost) >= 0) costs[operation] = cost
  }
  return costs
}

export function formatCallCost(cost: string | number | null | undefined): string {
  if (cost == null || (typeof cost === "string" && cost.trim() === "") || !Number.isFinite(Number(cost)) || Number(cost) < 0) return "—"
  return Number(cost) === 0 ? "Free" : `$${Number(cost).toFixed(4)}`
}

function decimalNumber(cost: number): string {
  const [coefficient = "0", exponentText] = String(cost).split("e")
  if (exponentText === undefined) return coefficient
  const [whole = "0", fraction = ""] = coefficient.split(".")
  const digits = whole + fraction
  const position = whole.length + Number(exponentText)
  if (position <= 0) return "0." + "0".repeat(-position) + digits
  if (position >= digits.length) return digits + "0".repeat(position - digits.length)
  return digits.slice(0, position) + "." + digits.slice(position)
}

export function formatCostTotal(cost: string | number | null | undefined): string {
  if (cost == null || (typeof cost === "number" && (!Number.isFinite(cost) || cost < 0))) return "—"
  const text = typeof cost === "number" ? decimalNumber(cost) : cost.trim()
  if (!/^\d+(?:\.\d+)?$/.test(text)) return "—"
  const [whole = "0", fraction = ""] = text.split(".")
  const digits = fraction.replace(/0+$/, "").padEnd(2, "0")
  return "$" + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + digits
}

export function formatCostBudgetUsage(budget: { limit: string | number; period: string }, used: string | number): string {
  const periods: Record<string, string> = { day: "today", week: "this week", month: "this month" }
  return `${formatCostTotal(used)} of ${formatCostTotal(budget.limit)} ${periods[budget.period] ?? budget.period}`
}

export function providerCallCost(provider: ProviderPricing | undefined, operation: Operation, keyless = false): string {
  const cost = keyless ? provider?.keylessCallCostUsd?.[operation] : provider?.callCostUsd?.[operation]
  return formatCallCost(cost)
}
