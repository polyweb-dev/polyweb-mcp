import type { OperationLimit, OperationLimits, PoolOperation, RateLimit } from "./types"

const OPERATIONS: readonly PoolOperation[] = ["search", "fetch"]
const SHORT_WINDOWS: Readonly<Record<number, string>> = { 1: "s", 60: "min", 3600: "h", 86400: "day" }

export function defaultPoolOperations(capabilities: readonly string[]): PoolOperation[] {
  return OPERATIONS.filter((operation) => capabilities.includes(operation))
}

export function hasAllowedOperations(operations: readonly PoolOperation[]): boolean {
  return operations.length > 0
}

function windowLabel(seconds: number, short: boolean): string {
  if (short) return SHORT_WINDOWS[seconds] ?? `${seconds}s`
  if (seconds === 1) return "second"
  if (seconds === 60) return "minute"
  if (seconds === 3600) return "hour"
  return `${seconds} seconds`
}

export function operationRate(value: OperationLimit | undefined, fallback: RateLimit): RateLimit {
  if (value === undefined) return fallback
  if (typeof value === "object" && value !== null) return { limit: value.rate_limit, window_seconds: value.rate_window_seconds }
  return { limit: value, window_seconds: fallback.window_seconds }
}

export function formatPoolRate(rate: RateLimit, { short = false, operationLimits }: {
  short?: boolean
  operationLimits?: OperationLimits | null
} = {}): string {
  const separateUnits = Object.values(operationLimits ?? {}).some((value) => typeof value === "object")
  const parts = OPERATIONS.flatMap((operation) => {
    const limit = operationLimits?.[operation]
    if (limit === undefined) return []
    const effective = operationRate(limit, rate)
    if (separateUnits) return [`${operation === "search" ? "Search" : "Fetch"} ${formatPoolRate(effective, { short })}`]
    return [`${operation === "search" ? "Search" : "Fetch"} ${limit}`]
  })
  const unit = `${short ? "/" : " per "}${windowLabel(rate.window_seconds, short)}`
  if (parts.length > 0) return parts.join(", ") + (separateUnits ? "" : unit)
  if (rate.limit === null) return "No limit"
  return `${rate.limit}${unit}`
}
