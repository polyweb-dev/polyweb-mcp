import type {
  BackendProviderStatus,
  BackendProviderTest,
} from "@/domains/providers/api/wire"
import type { BackendRoutingConfig } from "@/domains/routing/api/wire"
import type {
  BackendFetchRequest,
  BackendFetchResponse,
  BackendSearchRequest,
  BackendSearchResponse,
} from "@/domains/execution/api/wire"
import type { BackendDashboard } from "@/domains/dashboard/api/wire"
import type {
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
import { decodeManualQuota } from "@/domains/dashboard/api/manualQuotaWire"
import type {
  LimitHistoryQuery,
  ProviderLimitPatch,
} from "@/domains/dashboard"
import { requestJson } from "@/shared/api/client"

type RoutingConfigPatch = Partial<BackendRoutingConfig>
type ProviderPatch = {
  enable_mask?: number
  enabled?: boolean
  search_enabled?: boolean
  fetch_enabled?: boolean
  tavily_key_environment?: "dev" | "prod"
}

export class PolywebApiService {
  /**
   * Every method of this service uses the one shared transport, so Bearer
   * attachment, abort handling, and error normalization stay identical.
   */
  private request<T>(path: string, init?: RequestInit): Promise<T> {
    return requestJson<T>(path, init)
  }

  listProviders(): Promise<BackendProviderStatus[]> {
    return this.request<BackendProviderStatus[]>("/api/v1/providers")
  }

  getRoutingConfig(): Promise<BackendRoutingConfig> {
    return this.request<BackendRoutingConfig>("/api/v1/routing/config")
  }

  updateRoutingConfig(patch: RoutingConfigPatch): Promise<BackendRoutingConfig> {
    return this.request<BackendRoutingConfig>("/api/v1/routing/config", {
      method: "PUT",
      body: JSON.stringify(patch),
    })
  }

  patchProvider(backendId: string, patch: ProviderPatch): Promise<BackendProviderStatus> {
    const body: ProviderPatch = {}
    if (patch.enable_mask !== undefined) body.enable_mask = patch.enable_mask
    if (patch.enabled !== undefined) body.enabled = patch.enabled
    if (patch.search_enabled !== undefined) body.search_enabled = patch.search_enabled
    if (patch.fetch_enabled !== undefined) body.fetch_enabled = patch.fetch_enabled
    if (patch.tavily_key_environment !== undefined) {
      body.tavily_key_environment = patch.tavily_key_environment
    }
    return this.request<BackendProviderStatus>(`/api/v1/providers/${backendId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    })
  }

  testProvider(backendId: string): Promise<BackendProviderTest> {
    return this.request<BackendProviderTest>(`/api/v1/providers/${backendId}/test`, {
      method: "POST",
    })
  }

  resetCircuitBreaker(backendId: string): Promise<{ provider: string; state: "closed"; updated_at: string }> {
    return this.request<{ provider: string; state: "closed"; updated_at: string }>(
      `/api/v1/providers/${backendId}/circuit-breaker/reset`,
      { method: "POST" }
    )
  }

  search(body: BackendSearchRequest, signal?: AbortSignal): Promise<BackendSearchResponse> {
    return this.request<BackendSearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify(body),
      ...(signal !== undefined ? { signal } : {}),
    })
  }

  fetchDoc(body: BackendFetchRequest, signal?: AbortSignal): Promise<BackendFetchResponse> {
    return this.request<BackendFetchResponse>("/fetch", {
      method: "POST",
      body: JSON.stringify(body),
      ...(signal !== undefined ? { signal } : {}),
    })
  }

  getDashboard(limit = 50): Promise<BackendDashboard> {
    return this.request<BackendDashboard>(`/dashboard?limit=${limit}`)
  }

  /** A provider-wide billing entry, or a successful null when none exists. */
  async getManualQuota(backendId: string): Promise<BackendManualQuota | null> {
    return decodeManualQuota(await this.request<unknown>(
      `/api/v1/providers/${backendId}/manual-quota`
    ))
  }

  putManualQuota(
    backendId: string,
    payload: BackendManualQuotaPayload
  ): Promise<BackendManualQuota> {
    return this.request<BackendManualQuota>(
      `/api/v1/providers/${backendId}/manual-quota`,
      { method: "PUT", body: JSON.stringify(payload) }
    )
  }

  async deleteManualQuota(backendId: string): Promise<void> {
    await this.request<unknown>(`/api/v1/providers/${backendId}/manual-quota`, {
      method: "DELETE",
    })
  }

  /**
   * Provider limit state for both auth modes. The raw body returns `unknown`
   * so the dashboard domain decodes it defensively and keeps exact amounts.
   */
  getProviderLimits(backendId: string): Promise<unknown> {
    return this.request<unknown>(`/api/v1/providers/${backendId}/limits`)
  }

  /**
   * Partial catalog update. An omitted field keeps its stored value and an
   * explicit null clears it, so the body carries only present keys.
   */
  updateProviderLimit(input: ProviderLimitPatch): Promise<unknown> {
    const body: Record<string, unknown> = { version: input.version }
    for (const key of ["rate", "budget", "conversion_profile", "plan_name", "usage_url"] as const) {
      if (input[key] !== undefined) body[key] = input[key]
    }
    return this.request<unknown>(
      `/api/v1/providers/${input.backendId}/limits/${input.authMode}/${input.operation}`,
      { method: "PATCH", body: JSON.stringify(body) }
    )
  }

  /** One page of the provider limit audit trail. */
  getLimitHistory(input: LimitHistoryQuery): Promise<unknown> {
    const params = new URLSearchParams({ auth_mode: input.authMode })
    if (input.limit !== undefined) params.set("limit", String(input.limit))
    if (input.cursor !== undefined && input.cursor !== null) params.set("cursor", input.cursor)
    return this.request<unknown>(
      `/api/v1/providers/${input.backendId}/limits/history?${params.toString()}`
    )
  }

  /** Request one vendor usage sync for a provider. */
  syncProviderLimits(backendId: string): Promise<unknown> {
    return this.request<unknown>(`/api/v1/providers/${backendId}/limits/sync`, { method: "POST" })
  }
}

export const apiService = new PolywebApiService()
