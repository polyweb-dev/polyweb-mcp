/**
 * Shared upstream pools, their credential links and per-project allocations.
 *
 * Pools are system-managed and never carry a balance or consumption. The
 * allocation explanation is the one shared wording of strict caps, loans and
 * best effort used on the project Providers page and the Capacity page.
 */
import type { ProviderOperation } from "./projectProviders"

export type RateAlgorithm = "fixed_window" | "rolling_window" | "token_bucket"
export const RATE_ALGORITHMS: readonly RateAlgorithm[] = [
  "fixed_window",
  "rolling_window",
  "token_bucket",
]

export type UpstreamScope = "account" | "credential" | "ip" | "installation"
export const UPSTREAM_SCOPES: readonly UpstreamScope[] = [
  "account",
  "credential",
  "ip",
  "installation",
]

export type PoolStatus = "active" | "disabled"
export const POOL_STATUSES: readonly PoolStatus[] = ["active", "disabled"]

export interface RateConstraint {
  algorithm: RateAlgorithm
  windowSeconds: number
  limit: number
}

export interface Pool {
  id: string
  providerType: string
  upstreamScope: UpstreamScope
  poolKey: string
  label: string
  constraints: RateConstraint[]
  maxConcurrency: number | null
  maxQueuedRequests: number | null
  status: PoolStatus
  version: number
}

/** Body of one pool creation or update. */
export interface PoolInput {
  providerType: string
  upstreamScope: UpstreamScope
  poolKey: string
  label: string
  constraints: RateConstraint[]
  maxConcurrency: number | null
  maxQueuedRequests: number | null
  status: PoolStatus
}

export interface PoolLink {
  credentialId: string
  poolId: string
  operation: ProviderOperation
  providerType: string
  version: number
}

export interface Allocation {
  projectId: string
  poolId: string
  operation: ProviderOperation
  baseRate: number
  windowSeconds: number
  borrowEnabled: boolean
  maxRate: number | null
  effectiveMaxRate: number
  weight: number
  bestEffort: boolean
  maxConcurrency: number | null
  maxQueuedRequests: number | null
  maxQueuedBytes: number | null
  maxQueueWaitMs: number | null
  version: number
}

/** Body of one allocation write (`AllocationPut`). */
export interface AllocationInput {
  baseRate: number
  windowSeconds: number
  borrowEnabled: boolean
  maxRate: number | null
  weight: number
  bestEffort: boolean
  maxConcurrency: number | null
  maxQueuedRequests: number | null
  maxQueuedBytes: number | null
  maxQueueWaitMs: number | null
}

const NAMED_WINDOWS: Readonly<Record<number, string>> = {
  1: "second",
  60: "minute",
  3600: "hour",
  86400: "day",
}

/** "second", "minute", "hour", "day", else "<n> seconds". */
export function formatWindow(seconds: number): string {
  return NAMED_WINDOWS[seconds] ?? `${seconds} seconds`
}

const ALGORITHM_TEXT: Record<RateAlgorithm, string> = {
  fixed_window: "fixed window",
  rolling_window: "rolling window",
  token_bucket: "token bucket",
}

/** "10 per second (token bucket)". */
export function constraintText(constraint: RateConstraint): string {
  const window = formatWindow(constraint.windowSeconds)
  return `${constraint.limit} per ${window} (${ALGORITHM_TEXT[constraint.algorithm]})`
}

/** Mode badge and sentence of one allocation. */
export interface AllocationExplanationText {
  badge: "Strict cap" | "Loans enabled" | "Best effort"
  text: string
}

/** Explain one allocation: best effort for zero base, else loans or strict cap. */
export function explainAllocation(
  allocation: Pick<
    Allocation,
    "baseRate" | "windowSeconds" | "borrowEnabled" | "effectiveMaxRate" | "weight" | "bestEffort"
  >
): AllocationExplanationText {
  const window = formatWindow(allocation.windowSeconds)
  if (allocation.bestEffort && allocation.baseRate === 0) {
    return {
      badge: "Best effort",
      text: "No guaranteed share. Runs only when the pool has idle capacity.",
    }
  }
  if (allocation.borrowEnabled) {
    return {
      badge: "Loans enabled",
      text:
        `Guaranteed ${allocation.baseRate} per ${window} under contention ` +
        `(weight ${allocation.weight}). Can borrow up to ${allocation.effectiveMaxRate} ` +
        `per ${window} when the pool is idle. The pool limit always applies.`,
    }
  }
  return {
    badge: "Strict cap",
    text: `Up to ${allocation.baseRate} per ${window}. Unused capacity of other projects is not lent.`,
  }
}
