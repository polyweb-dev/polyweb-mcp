/**
 * Allocation form draft and its client-side validation.
 *
 * Mirrors the `AllocationPut` contract: strict by default; with loans the
 * max rate is at least the base rate; weight at least 1; a zero base rate
 * needs best effort. Feasibility against the pool stays a server check (409).
 */
import type { Allocation, AllocationInput, ProviderOperation } from "@/domains/providers"

export const ZERO_BASE_NEEDS_BEST_EFFORT = "A zero base rate needs best effort."
export const MAX_RATE_BELOW_BASE = "Max rate must be at least the base rate."
export const WEIGHT_TOO_LOW = "Weight must be at least 1."
export const WHOLE_NUMBERS = "Enter whole numbers of zero or more."
export const WINDOW_TOO_LOW = "Window seconds must be at least 1."
export const POOL_REQUIRED = "Choose a pool."

export interface AllocationDraft {
  poolId: string
  operation: ProviderOperation
  baseRate: string
  windowSeconds: string
  borrowEnabled: boolean
  maxRate: string
  weight: string
  bestEffort: boolean
  maxConcurrency: string
  maxQueuedRequests: string
  maxQueuedBytes: string
  maxQueueWaitMs: string
}

const text = (value: number | null): string => (value === null ? "" : String(value))

/** Draft of a new allocation, or of an existing one to edit. */
export function allocationDraft(allocation: Allocation | null, poolId = ""): AllocationDraft {
  if (allocation === null) {
    return {
      poolId,
      operation: "search",
      baseRate: "10",
      windowSeconds: "60",
      borrowEnabled: false,
      maxRate: "",
      weight: "1",
      bestEffort: false,
      maxConcurrency: "",
      maxQueuedRequests: "",
      maxQueuedBytes: "",
      maxQueueWaitMs: "",
    }
  }
  return {
    poolId: allocation.poolId,
    operation: allocation.operation,
    baseRate: String(allocation.baseRate),
    windowSeconds: String(allocation.windowSeconds),
    borrowEnabled: allocation.borrowEnabled,
    maxRate: text(allocation.maxRate),
    weight: String(allocation.weight),
    bestEffort: allocation.bestEffort,
    maxConcurrency: text(allocation.maxConcurrency),
    maxQueuedRequests: text(allocation.maxQueuedRequests),
    maxQueuedBytes: text(allocation.maxQueuedBytes),
    maxQueueWaitMs: text(allocation.maxQueueWaitMs),
  }
}

/** Parse a whole number ≥ 0; `undefined` for invalid input. */
function whole(value: string): number | undefined {
  const trimmed = value.trim()
  if (!/^\d+$/.test(trimmed)) return undefined
  return Number(trimmed)
}

/** Parse an optional whole number; empty is `null`, invalid `undefined`. */
function optionalWhole(value: string): number | null | undefined {
  return value.trim() === "" ? null : whole(value)
}

export type AllocationValidation =
  | { ok: true; input: AllocationInput }
  | { ok: false; message: string }

function queueBounds(draft: AllocationDraft) {
  return {
    maxConcurrency: optionalWhole(draft.maxConcurrency),
    maxQueuedRequests: optionalWhole(draft.maxQueuedRequests),
    maxQueuedBytes: optionalWhole(draft.maxQueuedBytes),
    maxQueueWaitMs: optionalWhole(draft.maxQueueWaitMs),
  }
}

interface ParsedRates {
  baseRate: number
  windowSeconds: number
  weight: number
  maxRate: number | null
}

/** Parse the rate fields; `null` when any of them is not a whole number. */
function parseRates(draft: AllocationDraft): ParsedRates | null {
  const baseRate = whole(draft.baseRate)
  const windowSeconds = whole(draft.windowSeconds)
  const weight = whole(draft.weight)
  const maxRate = draft.borrowEnabled ? whole(draft.maxRate) : null
  if (baseRate === undefined || windowSeconds === undefined || weight === undefined) return null
  return maxRate === undefined ? null : { baseRate, windowSeconds, weight, maxRate }
}

/** First contract rule the parsed rates break, else `null`. */
function ruleFailure(rates: ParsedRates, bestEffort: boolean): string | null {
  if (rates.windowSeconds < 1) return WINDOW_TOO_LOW
  if (rates.weight < 1) return WEIGHT_TOO_LOW
  if (rates.maxRate !== null && rates.maxRate < rates.baseRate) return MAX_RATE_BELOW_BASE
  if (rates.baseRate === 0 && !bestEffort) return ZERO_BASE_NEEDS_BEST_EFFORT
  return null
}

/** Validate one draft into the write body, or the first failure text. */
export function validateAllocation(draft: AllocationDraft): AllocationValidation {
  if (draft.poolId === "") return { ok: false, message: POOL_REQUIRED }
  const rates = parseRates(draft)
  const bounds = queueBounds(draft)
  if (rates === null || Object.values(bounds).some((value) => value === undefined)) {
    return { ok: false, message: WHOLE_NUMBERS }
  }
  const failure = ruleFailure(rates, draft.bestEffort)
  if (failure !== null) return { ok: false, message: failure }
  return {
    ok: true,
    input: {
      ...rates,
      borrowEnabled: draft.borrowEnabled,
      bestEffort: draft.bestEffort,
      maxConcurrency: bounds.maxConcurrency ?? null,
      maxQueuedRequests: bounds.maxQueuedRequests ?? null,
      maxQueuedBytes: bounds.maxQueuedBytes ?? null,
      maxQueueWaitMs: bounds.maxQueueWaitMs ?? null,
    },
  }
}
