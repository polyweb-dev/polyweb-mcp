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
  if (cost == null || cost === "" || !Number.isFinite(Number(cost)) || Number(cost) < 0) return "—"
  return Number(cost) === 0 ? "Free" : `$${Number(cost).toFixed(4)}`
}

export function providerCallCost(provider: ProviderPricing | undefined, operation: Operation, keyless = false): string {
  const cost = keyless ? provider?.keylessCallCostUsd?.[operation] : provider?.callCostUsd?.[operation]
  const price = formatCallCost(cost)
  return keyless && price === "Free" ? "Free without a key" : price
}
