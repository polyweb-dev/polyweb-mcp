import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"
import { decodeOperationLimits, unassignKeyPool } from "@/domains/vault"
import type { OperationLimits, PoolBudget, PoolOperation, RateLimit } from "@/domains/vault"

export interface ProjectPool {
  pool_id: string
  label: string
  provider_type: string
  key_label: string
  owner: { user_id: string; email: string; username?: string | null; first_name?: string | null; last_name?: string | null }
  rate: RateLimit
  budget: PoolBudget | null
  budget_used: number
  operations: PoolOperation[]
  operation_limits?: OperationLimits | null
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  return value as Record<string, unknown>
}

function decodeRate(value: unknown): RateLimit {
  const item = asRecord(value)
  if ((item.limit !== null && typeof item.limit !== "number") || typeof item.window_seconds !== "number") {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  return { limit: item.limit, window_seconds: item.window_seconds }
}

function decodeBudget(value: unknown): PoolBudget | null {
  if (value === null) return null
  const item = asRecord(value)
  if (typeof item.limit !== "number" || typeof item.period !== "string") {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  return { limit: item.limit, period: item.period }
}

function optionalOwnerText(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null
  return typeof value === "string" ? value : undefined
}

function decodeOwner(value: unknown): ProjectPool["owner"] {
  const item = asRecord(value)
  if (typeof item.user_id !== "string" || typeof item.email !== "string") {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  const username = "username" in item ? optionalOwnerText(item.username) : null
  const firstName = "first_name" in item ? optionalOwnerText(item.first_name) : null
  const lastName = "last_name" in item ? optionalOwnerText(item.last_name) : null
  if (username === undefined || firstName === undefined || lastName === undefined) {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  if (!("username" in item) && !("first_name" in item) && !("last_name" in item)) {
    return { user_id: item.user_id, email: item.email }
  }
  return { user_id: item.user_id, email: item.email, username, first_name: firstName, last_name: lastName }
}

function decodeOperations(value: unknown): PoolOperation[] {
  if (!Array.isArray(value)) throw new ApiError(0, "The server returned an unexpected pool.", value)
  const operations = value.filter((operation): operation is PoolOperation => operation === "search" || operation === "fetch")
  if (operations.length === 0) throw new ApiError(0, "The server returned an unexpected pool.", value)
  return operations
}

function decodePool(value: unknown): ProjectPool {
  const fields = asRecord(value)
  if (typeof fields.pool_id !== "string" || typeof fields.label !== "string" ||
      typeof fields.provider_type !== "string" || typeof fields.key_label !== "string" ||
      typeof fields.budget_used !== "number") {
    throw new ApiError(0, "The server returned an unexpected pool.", value)
  }
  return {
    pool_id: fields.pool_id, label: fields.label, provider_type: fields.provider_type, key_label: fields.key_label,
    owner: decodeOwner(fields.owner), rate: decodeRate(fields.rate), budget: decodeBudget(fields.budget),
    budget_used: fields.budget_used, operations: decodeOperations(fields.operations),
    operation_limits: decodeOperationLimits(fields.operation_limits ?? null),
  }
}

const path = (projectId: string) => `/api/v1/projects/${encodeURIComponent(projectId)}/pools`

export async function listProjectPools(projectId: string, signal?: AbortSignal): Promise<ProjectPool[]> {
  const result = await requestJson<unknown>(path(projectId), { signal })
  if (!Array.isArray(result)) throw new ApiError(0, "The server returned an unexpected pool list.", result)
  return result.map(decodePool)
}

export async function detachProjectPool(_projectId: string, poolId: string): Promise<void> {
  await unassignKeyPool(poolId)
}
