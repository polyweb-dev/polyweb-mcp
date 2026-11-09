import { ApiError } from "@/shared/api/http"
import type { KeyPool, PoolOperation, RateLimit, VaultKey, VaultKeyDeleteResult, VaultOAuthDevice, VaultOAuthStatus, VaultProject } from "../model/types"

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return value as Record<string, unknown>
}

function required(value: unknown, keys: readonly string[]): Record<string, unknown> {
  const item = record(value)
  if (keys.some((key) => !(key in item))) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return item
}

function decodeRate(value: unknown): RateLimit {
  const item = required(value, ["limit", "window_seconds"])
  if ((item.limit !== null && typeof item.limit !== "number") || typeof item.window_seconds !== "number") {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return { limit: item.limit, window_seconds: item.window_seconds }
}

function decodeBudget(value: unknown): KeyPool["budget"] {
  if (value === null) return null
  const item = required(value, ["limit", "period"])
  if (typeof item.limit !== "number" || !Number.isFinite(item.limit) || item.limit < 0 ||
      (item.period !== "day" && item.period !== "week" && item.period !== "month")) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return { limit: item.limit, period: item.period }
}

function decodeOperations(value: unknown): PoolOperation[] {
  if (!Array.isArray(value)) throw new ApiError(0, "The server returned an unexpected vault response.", value)
  const operations = value.filter((operation): operation is PoolOperation => operation === "search" || operation === "fetch")
  if (operations.length === 0) throw new ApiError(0, "The server returned an unexpected vault response.", value)
  return operations
}

export function decodeOperationLimits(value: unknown): KeyPool["operation_limits"] {
  if (value === null) return null
  const item = record(value)
  const limits: NonNullable<KeyPool["operation_limits"]> = {}
  for (const operation of ["search", "fetch"] as const) {
    const limit = item[operation]
    if (limit === undefined) continue
    if (limit === null || typeof limit === "number") limits[operation] = limit
    else {
      const nested = required(limit, ["rate_limit", "rate_window_seconds"])
      if ((nested.rate_limit !== null && typeof nested.rate_limit !== "number") || typeof nested.rate_window_seconds !== "number") {
        throw new ApiError(0, "The server returned an unexpected vault response.", value)
      }
      limits[operation] = { rate_limit: nested.rate_limit, rate_window_seconds: nested.rate_window_seconds }
    }
  }
  return limits
}

function isContentionMode(value: unknown): value is VaultKey["contention_mode"] {
  return value === "equal" || value === "ratio"
}

export function decodeVaultKey(value: unknown): VaultKey {
  const item = required(value, ["id", "provider_type", "label", "auth_mode", "status", "generation", "created_at", "capacity", "overcommit", "contention_mode", "pool_count"])
  if (typeof item.id !== "string" || typeof item.label !== "string" || typeof item.provider_type !== "string" ||
      typeof item.auth_mode !== "string" || typeof item.status !== "string" || typeof item.generation !== "number" ||
      typeof item.created_at !== "string" || typeof item.overcommit !== "boolean" || typeof item.pool_count !== "number" ||
      !isContentionMode(item.contention_mode)) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return {
    id: item.id, provider_type: item.provider_type, label: item.label, auth_mode: item.auth_mode,
    status: item.status, generation: item.generation, created_at: item.created_at,
    capacity: item.capacity === null ? null : decodeRate(item.capacity), overcommit: item.overcommit,
    contention_mode: item.contention_mode, pool_count: item.pool_count,
  }
}

export function decodeKeyPool(value: unknown): KeyPool {
  const item = required(value, ["id", "credential_id", "project_id", "provider_type", "label", "rate", "budget", "budget_used_usd", "operations", "operation_limits"])
  if (typeof item.id !== "string" || typeof item.credential_id !== "string" || typeof item.provider_type !== "string" ||
      typeof item.label !== "string" || (item.project_id !== null && typeof item.project_id !== "string") ||
      typeof item.budget_used_usd !== "number" || !Number.isFinite(item.budget_used_usd) || item.budget_used_usd < 0) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return {
    id: item.id, credential_id: item.credential_id, provider_type: item.provider_type,
    project_id: item.project_id, label: item.label, rate: decodeRate(item.rate), budget: decodeBudget(item.budget),
    budget_used_usd: item.budget_used_usd,
    operations: decodeOperations(item.operations),
    operation_limits: decodeOperationLimits(item.operation_limits),
  }
}

export function decodeKeyDeleteResult(value: unknown): VaultKeyDeleteResult {
  const item = required(value, ["deleted_pools"])
  return { deleted_pools: decodeList(item.deleted_pools, (entry) => {
    const pool = required(entry, ["id", "project_id"])
    if (typeof pool.id !== "string" || (pool.project_id !== null && typeof pool.project_id !== "string")) {
      throw new ApiError(0, "The server returned an unexpected vault response.", entry)
    }
    return { id: pool.id, project_id: pool.project_id }
  }) }
}

export function decodeVaultProjects(value: unknown): VaultProject[] {
  if (!Array.isArray(value)) throw new ApiError(0, "The server returned an unexpected vault response.", value)
  return value.map((entry) => {
    const item = required(entry, ["id", "name", "available_providers"])
    if (typeof item.id !== "string" || typeof item.name !== "string" ||
        !Array.isArray(item.available_providers) || !item.available_providers.every((provider: unknown) => typeof provider === "string")) {
      throw new ApiError(0, "The server returned an unexpected vault response.", entry)
    }
    return { id: item.id, name: item.name, available_providers: item.available_providers }
  })
}

export function decodeList<T>(value: unknown, decode: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new ApiError(0, "The server returned an unexpected vault response.", value)
  return value.map(decode)
}

export function decodeOAuthDevice(value: unknown): VaultOAuthDevice {
  const item = required(value, ["user_code", "verification_uri", "interval", "expires_in"])
  if (typeof item.user_code !== "string" || typeof item.verification_uri !== "string" ||
      typeof item.interval !== "number" || typeof item.expires_in !== "number") {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  let url: URL
  try { url = new URL(item.verification_uri) } catch { throw new ApiError(0, "The server returned an unexpected vault response.", value) }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return { user_code: item.user_code, verification_uri: item.verification_uri, interval: item.interval, expires_in: item.expires_in }
}

export function decodeOAuthStatus(value: unknown): VaultOAuthStatus {
  const item = required(value, ["status"])
  if (!["pending", "connected", "refresh_failed", "disconnected"].includes(String(item.status)) ||
      (item.interval !== undefined && item.interval !== null && typeof item.interval !== "number")) {
    throw new ApiError(0, "The server returned an unexpected vault response.", value)
  }
  return { status: item.status as VaultOAuthStatus["status"], ...(item.interval === undefined ? {} : { interval: item.interval as number | null }) }
}
