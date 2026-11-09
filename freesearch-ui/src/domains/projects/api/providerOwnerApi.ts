import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"

export interface ProviderOwner {
  user_id: string
  email: string
}

export interface OwnershipTransfer extends ProviderOwner {
  unassigned_pools: { pool_id: string; label: string }[]
}

function owner(value: unknown): ProviderOwner {
  if (typeof value !== "object" || value === null || !("user_id" in value) || !("email" in value) ||
      typeof value.user_id !== "string" || typeof value.email !== "string") {
    throw new ApiError(0, "The server returned an unexpected provider owner.", value)
  }
  return { user_id: value.user_id, email: value.email }
}

export async function getProviderOwner(projectId: string, signal?: AbortSignal): Promise<ProviderOwner | null> {
  const result = await requestJson<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/provider-owner`, { signal })
  return result === null ? null : owner(result)
}

export async function transferProviderOwner(projectId: string, userId: string): Promise<OwnershipTransfer> {
  const result = await requestJson<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/provider-owner`, {
    method: "POST", body: JSON.stringify({ user_id: userId }),
  })
  const decoded = owner(result)
  if (typeof result !== "object" || result === null || !("unassigned_pools" in result) ||
      !Array.isArray(result.unassigned_pools) || !result.unassigned_pools.every((pool: unknown) =>
        typeof pool === "object" && pool !== null && "pool_id" in pool && typeof pool.pool_id === "string" &&
        "label" in pool && typeof pool.label === "string")) {
    throw new ApiError(0, "The server returned an unexpected provider owner.", result)
  }
  return { ...decoded, unassigned_pools: result.unassigned_pools }
}
