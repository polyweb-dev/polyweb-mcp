import { asRecord } from "@/shared/api/decode"

export type OrderOperation = "search" | "fetch"
export type OrderStrategy = "free_first" | "lowest_cost" | "custom"

export interface OrderProvider {
  provider: string
  name: string
  callCostUsd: string | number | null
  keyless: boolean
}

export interface OperationOrder {
  strategy: OrderStrategy
  providers: OrderProvider[]
  hasSavedCustom: boolean
  notAllowed: string[]
}

export interface ProjectOrder {
  revision: number
  search: OperationOrder
  fetch: OperationOrder
}

function invalid(): never {
  throw new Error("Invalid provider order response.")
}

function decodeProvider(value: unknown): OrderProvider {
  const row = asRecord(value)
  if (!row || typeof row.provider !== "string" || typeof row.name !== "string") return invalid()
  const cost = row.call_cost_usd
  if (cost !== null && typeof cost !== "string" && typeof cost !== "number") return invalid()
  if (cost !== null && (cost === "" || !Number.isFinite(Number(cost)) || Number(cost) < 0)) return invalid()
  return { provider: row.provider, name: row.name, callCostUsd: cost, keyless: row.keyless === true }
}

function decodeOperation(value: unknown): OperationOrder {
  const row = asRecord(value)
  if (!row || (row.strategy !== "free_first" && row.strategy !== "lowest_cost" && row.strategy !== "custom")) return invalid()
  if (!Array.isArray(row.providers) || !Array.isArray(row.not_allowed) || typeof row.has_saved_custom !== "boolean") return invalid()
  if (!row.not_allowed.every((item: unknown) => typeof item === "string")) return invalid()
  return {
    strategy: row.strategy,
    providers: row.providers.map(decodeProvider),
    hasSavedCustom: row.has_saved_custom,
    notAllowed: row.not_allowed,
  }
}

export function decodeProjectOrder(value: unknown): ProjectOrder {
  const row = asRecord(value)
  if (!row || typeof row.revision !== "number" || !Number.isInteger(row.revision)) return invalid()
  return { revision: row.revision, search: decodeOperation(row.search), fetch: decodeOperation(row.fetch) }
}
