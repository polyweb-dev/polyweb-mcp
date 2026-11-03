/** Pool form draft and its validation into a `PoolInput`. */
import type { Pool, PoolInput, PoolStatus, RateAlgorithm, UpstreamScope } from "@/domains/providers"

export interface ConstraintDraft {
  algorithm: RateAlgorithm
  windowSeconds: string
  limit: string
}

export interface PoolDraft {
  providerType: string
  label: string
  upstreamScope: UpstreamScope
  poolKey: string
  constraints: ConstraintDraft[]
  maxConcurrency: string
  maxQueuedRequests: string
  status: PoolStatus
}

export const POOL_FIELDS_REQUIRED = "Label and pool key are required."
export const POOL_NUMBERS = "Limits and windows must be whole numbers; windows at least 1."

const text = (value: number | null): string => (value === null ? "" : String(value))

/** Draft of a new pool, or of an existing one to edit. */
export function poolDraft(pool: Pool | null, providerType: string): PoolDraft {
  if (pool === null) {
    return {
      providerType,
      label: "",
      upstreamScope: "account",
      poolKey: "",
      constraints: [],
      maxConcurrency: "",
      maxQueuedRequests: "",
      status: "active",
    }
  }
  return {
    providerType: pool.providerType,
    label: pool.label,
    upstreamScope: pool.upstreamScope,
    poolKey: pool.poolKey,
    constraints: pool.constraints.map((constraint) => ({
      algorithm: constraint.algorithm,
      windowSeconds: String(constraint.windowSeconds),
      limit: String(constraint.limit),
    })),
    maxConcurrency: text(pool.maxConcurrency),
    maxQueuedRequests: text(pool.maxQueuedRequests),
    status: pool.status,
  }
}

function whole(value: string): number | undefined {
  return /^\d+$/.test(value.trim()) ? Number(value.trim()) : undefined
}

function optionalWhole(value: string): number | null | undefined {
  return value.trim() === "" ? null : whole(value)
}

export type PoolValidation = { ok: true; input: PoolInput } | { ok: false; message: string }

/** Validate one draft into the write body, or the first failure text. */
export function validatePool(draft: PoolDraft): PoolValidation {
  if (draft.label.trim() === "" || draft.poolKey.trim() === "") {
    return { ok: false, message: POOL_FIELDS_REQUIRED }
  }
  const constraints = draft.constraints.map((row) => ({
    algorithm: row.algorithm,
    windowSeconds: whole(row.windowSeconds),
    limit: whole(row.limit),
  }))
  const maxConcurrency = optionalWhole(draft.maxConcurrency)
  const maxQueuedRequests = optionalWhole(draft.maxQueuedRequests)
  const badConstraint = constraints.some(
    (row) => row.windowSeconds === undefined || row.windowSeconds < 1 || row.limit === undefined
  )
  if (badConstraint || maxConcurrency === undefined || maxQueuedRequests === undefined) {
    return { ok: false, message: POOL_NUMBERS }
  }
  return {
    ok: true,
    input: {
      providerType: draft.providerType,
      label: draft.label.trim(),
      upstreamScope: draft.upstreamScope,
      poolKey: draft.poolKey.trim(),
      constraints: constraints.map((row) => ({
        algorithm: row.algorithm,
        windowSeconds: row.windowSeconds ?? 1,
        limit: row.limit ?? 0,
      })),
      maxConcurrency,
      maxQueuedRequests,
      status: draft.status,
    },
  }
}
