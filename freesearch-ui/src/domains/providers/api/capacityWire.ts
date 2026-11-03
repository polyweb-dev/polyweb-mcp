/**
 * Decoders of pool, pool link and allocation payloads; only named fields
 * are copied.
 */
import { asRecord, readEnum, readFlag, readInt, readString } from "@/shared/api/decode"
import { CREDENTIAL_OPERATIONS } from "../model/credentials"
import { POOL_STATUSES, RATE_ALGORITHMS, UPSTREAM_SCOPES } from "../model/capacity"
import type { Allocation, Pool, PoolLink, RateConstraint } from "../model/capacity"

function decodeConstraint(value: unknown): RateConstraint | null {
  const record = asRecord(value)
  if (record === null) return null
  const algorithm = readEnum(record, "algorithm", RATE_ALGORITHMS)
  const windowSeconds = readInt(record, "window_seconds")
  const limit = readInt(record, "limit")
  if (algorithm === null || windowSeconds === null || limit === null) return null
  return { algorithm, windowSeconds, limit }
}

/** Decode one pool (`PoolRead`). */
export function decodePool(value: unknown): Pool | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const providerType = readString(record, "provider_type")
  const upstreamScope = readEnum(record, "upstream_scope", UPSTREAM_SCOPES)
  if (id === null || providerType === null || upstreamScope === null) return null
  const constraints = Array.isArray(record.constraints) ? record.constraints : []
  return {
    id,
    providerType,
    upstreamScope,
    poolKey: readString(record, "pool_key") ?? "",
    label: readString(record, "label") ?? id,
    constraints: constraints.map(decodeConstraint).filter((row) => row !== null),
    maxConcurrency: readInt(record, "max_concurrency"),
    maxQueuedRequests: readInt(record, "max_queued_requests"),
    status: readEnum(record, "status", POOL_STATUSES) ?? "active",
    version: readInt(record, "version") ?? 1,
  }
}

/** Decode one credential link of a pool (`PoolLinkRead`). */
export function decodePoolLink(value: unknown): PoolLink | null {
  const record = asRecord(value)
  if (record === null) return null
  const credentialId = readString(record, "credential_id")
  const poolId = readString(record, "pool_id")
  const operation = readEnum(record, "operation_scope", CREDENTIAL_OPERATIONS)
  if (credentialId === null || poolId === null || operation === null) return null
  return {
    credentialId,
    poolId,
    operation,
    providerType: readString(record, "provider_type") ?? "",
    version: readInt(record, "version") ?? 1,
  }
}

/** Decode one project allocation (`AllocationRead`). */
export function decodeAllocation(value: unknown): Allocation | null {
  const record = asRecord(value)
  if (record === null) return null
  const projectId = readString(record, "project_id")
  const poolId = readString(record, "pool_id")
  const operation = readEnum(record, "operation_scope", CREDENTIAL_OPERATIONS)
  const baseRate = readInt(record, "base_rate")
  const windowSeconds = readInt(record, "rate_window_seconds")
  if (
    projectId === null ||
    poolId === null ||
    operation === null ||
    baseRate === null ||
    windowSeconds === null
  ) {
    return null
  }
  const maxRate = readInt(record, "max_rate")
  return {
    projectId,
    poolId,
    operation,
    baseRate,
    windowSeconds,
    borrowEnabled: readFlag(record, "borrow_enabled"),
    maxRate,
    effectiveMaxRate: readInt(record, "effective_max_rate") ?? maxRate ?? baseRate,
    weight: readInt(record, "weight") ?? 1,
    bestEffort: readFlag(record, "best_effort"),
    maxConcurrency: readInt(record, "max_concurrency"),
    maxQueuedRequests: readInt(record, "max_queued_requests"),
    maxQueuedBytes: readInt(record, "max_queued_bytes"),
    maxQueueWaitMs: readInt(record, "max_queue_wait_ms"),
    version: readInt(record, "version") ?? 1,
  }
}
