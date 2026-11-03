/**
 * System pool, pool link and project allocation routes.
 */
import { requestJson } from "@/shared/api/client"
import { decodeList, decodeOne } from "@/shared/api/decode"
import { decodeAllocation, decodePool, decodePoolLink } from "./capacityWire"
import type { Allocation, AllocationInput, Pool, PoolInput, PoolLink } from "../model/capacity"
import type { ProviderOperation } from "../model/projectProviders"

const POOLS = "/api/v1/system/pools"

function signalInit(signal?: AbortSignal): RequestInit {
  return signal === undefined ? {} : { signal }
}

function poolPath(poolId: string): string {
  return `${POOLS}/${encodeURIComponent(poolId)}`
}

function linkPath(poolId: string, credentialId: string, operation: ProviderOperation): string {
  const query = new URLSearchParams({ operation_scope: operation })
  return `${poolPath(poolId)}/links/${encodeURIComponent(credentialId)}?${query.toString()}`
}

function allocationPath(projectId: string, poolId: string, operation: ProviderOperation): string {
  const query = new URLSearchParams({ operation_scope: operation })
  const project = encodeURIComponent(projectId)
  return `/api/v1/system/projects/${project}/allocations/${encodeURIComponent(poolId)}?${query.toString()}`
}

function poolBody(input: PoolInput, includeStatus: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    upstream_scope: input.upstreamScope,
    pool_key: input.poolKey,
    label: input.label,
    constraints: input.constraints.map((constraint) => ({
      algorithm: constraint.algorithm,
      window_seconds: constraint.windowSeconds,
      limit: constraint.limit,
    })),
    max_concurrency: input.maxConcurrency,
    max_queued_requests: input.maxQueuedRequests,
  }
  if (includeStatus) body.status = input.status
  return body
}

/** List every pool. */
export async function listPools(signal?: AbortSignal): Promise<Pool[]> {
  return decodeList(await requestJson<unknown>(POOLS, signalInit(signal)), decodePool, "pool list")
}

/** Create one pool. */
export async function createPool(input: PoolInput): Promise<Pool> {
  const body = { provider_type: input.providerType, ...poolBody(input, false) }
  const payload = await requestJson<unknown>(POOLS, { method: "POST", body: JSON.stringify(body) })
  return decodeOne(payload, decodePool, "pool")
}

/** Update one pool; the provider type never changes. */
export async function updatePool(poolId: string, input: PoolInput): Promise<Pool> {
  const payload = await requestJson<unknown>(poolPath(poolId), {
    method: "PATCH",
    body: JSON.stringify(poolBody(input, true)),
  })
  return decodeOne(payload, decodePool, "pool")
}

/** List the credential links of one pool. */
export async function listPoolLinks(poolId: string, signal?: AbortSignal): Promise<PoolLink[]> {
  const payload = await requestJson<unknown>(`${poolPath(poolId)}/links`, signalInit(signal))
  return decodeList(payload, decodePoolLink, "pool link list")
}

/** Link one credential to a pool for one operation. */
export async function putPoolLink(
  poolId: string,
  credentialId: string,
  operation: ProviderOperation
): Promise<PoolLink> {
  const payload = await requestJson<unknown>(linkPath(poolId, credentialId, operation), {
    method: "PUT",
  })
  return decodeOne(payload, decodePoolLink, "pool link")
}

/** Remove one credential link. */
export async function deletePoolLink(
  poolId: string,
  credentialId: string,
  operation: ProviderOperation
): Promise<void> {
  await requestJson<unknown>(linkPath(poolId, credentialId, operation), { method: "DELETE" })
}

/** List the allocations of one project. */
export async function listProjectAllocations(
  projectId: string,
  signal?: AbortSignal
): Promise<Allocation[]> {
  const payload = await requestJson<unknown>(
    `/api/v1/system/projects/${encodeURIComponent(projectId)}/allocations`,
    signalInit(signal)
  )
  return decodeList(payload, decodeAllocation, "allocation list")
}

/** Create or replace one allocation; an infeasible base rate answers 409. */
export async function putAllocation(
  target: { projectId: string; poolId: string; operation: ProviderOperation },
  input: AllocationInput
): Promise<Allocation> {
  const body = {
    base_rate: input.baseRate,
    rate_window_seconds: input.windowSeconds,
    borrow_enabled: input.borrowEnabled,
    max_rate: input.borrowEnabled ? input.maxRate : null,
    weight: input.weight,
    best_effort: input.bestEffort,
    max_concurrency: input.maxConcurrency,
    max_queued_requests: input.maxQueuedRequests,
    max_queued_bytes: input.maxQueuedBytes,
    max_queue_wait_ms: input.maxQueueWaitMs,
  }
  const payload = await requestJson<unknown>(
    allocationPath(target.projectId, target.poolId, target.operation),
    { method: "PUT", body: JSON.stringify(body) }
  )
  return decodeOne(payload, decodeAllocation, "allocation")
}

/** Remove one allocation. */
export async function deleteAllocation(
  projectId: string,
  poolId: string,
  operation: ProviderOperation
): Promise<void> {
  await requestJson<unknown>(allocationPath(projectId, poolId, operation), { method: "DELETE" })
}
