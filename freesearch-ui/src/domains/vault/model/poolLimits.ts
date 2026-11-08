import type { PoolOperation, RateLimit } from "./types"

const OPERATIONS: readonly PoolOperation[] = ["search", "fetch"]

export function defaultPoolOperations(capabilities: readonly string[]): PoolOperation[] {
  return OPERATIONS.filter((operation) => capabilities.includes(operation))
}

export function hasAllowedOperations(operations: readonly PoolOperation[]): boolean {
  return operations.length > 0
}

function windowLabel(seconds: number): string {
  if (seconds === 1) return "second"
  if (seconds === 60) return "minute"
  if (seconds === 3600) return "hour"
  return `${seconds} seconds`
}

export function formatPoolRate(rate: RateLimit, operationLimits?: Partial<Record<PoolOperation, number>> | null): string {
  const parts = OPERATIONS.flatMap((operation) => {
    const limit = operationLimits?.[operation]
    if (limit === undefined) return []
    return [`${operation === "search" ? "Search" : "Fetch"} ${limit}`]
  })
  if (parts.length > 0) return `${parts.join(", ")} per ${windowLabel(rate.window_seconds)}`
  if (rate.limit === null) return "No limit"
  return `${rate.limit} per ${windowLabel(rate.window_seconds)}`
}
