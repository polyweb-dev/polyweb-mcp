import { conflictDetail, isForbidden } from "@/shared/api/conflict"

export const NOT_FEASIBLE_FALLBACK = "the pool cannot fit this allocation."
export const CAPACITY_FORBIDDEN = "You do not have permission to make this change."

/** "Not feasible: <server message>" for a 409, else safe fallback text. */
export function capacityFailureMessage(error: unknown, fallback: string): string {
  const conflict = conflictDetail(error)
  if (conflict !== null) return `Not feasible: ${conflict.message ?? NOT_FEASIBLE_FALLBACK}`
  return isForbidden(error) ? CAPACITY_FORBIDDEN : fallback
}

/** Server conflict text of a pool or link write, else safe fallback text. */
export function poolFailureMessage(error: unknown, fallback: string): string {
  const conflict = conflictDetail(error)
  if (conflict !== null) return conflict.message ?? fallback
  return isForbidden(error) ? CAPACITY_FORBIDDEN : fallback
}
