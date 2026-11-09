import type { TraceOperation, TraceOutcome } from "@/domains/activity"

/** Activity list filters; `null` means every value. They live in the URL query. */
export interface ActivityFilters {
  operation: TraceOperation | null
  outcome: TraceOutcome | null
}

const OPERATIONS: readonly TraceOperation[] = ["search", "fetch"]
const OUTCOMES: readonly TraceOutcome[] = ["success", "partial", "error"]

/** Read the filters of `?operation=&outcome=`; an unknown value means every value. */
export function filtersFromSearch(params: URLSearchParams): ActivityFilters {
  const operation = params.get("operation")
  const outcome = params.get("outcome")
  return {
    operation: OPERATIONS.find((value) => value === operation) ?? null,
    outcome: OUTCOMES.find((value) => value === outcome) ?? null,
  }
}

/** Write the filters into a copy of the query; an every-value filter is omitted. */
export function filtersToSearch(params: URLSearchParams, filters: ActivityFilters): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const [key, value] of [
    ["operation", filters.operation],
    ["outcome", filters.outcome],
  ] as const) {
    if (value === null) next.delete(key)
    else next.set(key, value)
  }
  return next
}
