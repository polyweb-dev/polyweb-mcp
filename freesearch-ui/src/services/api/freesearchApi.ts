import type {
  BackendProviderStatus,
  BackendProviderTest,
  BackendSecretStatus,
} from "@/domains/providers/api/wire"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"
import type { BackendRoutingConfig } from "@/domains/routing/api/wire"
import type {
  BackendFetchRequest,
  BackendFetchResponse,
  BackendSearchRequest,
  BackendSearchResponse,
} from "@/domains/execution/api/wire"
import type { BackendDashboard } from "@/domains/dashboard/api/wire"
import type {
  BackendTraceDetail,
  BackendTraceList,
} from "@/domains/activity/api/wire"
import type {
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"

type RoutingConfigPatch = Partial<BackendRoutingConfig>
type ProviderPatch = { enabled?: boolean; priority?: number }

/** Optional Activity list filters; omitted values ask for the backend default. */
export type TraceListFilters = {
  limit?: number
  operation?: "search" | "fetch"
  outcome?: "success" | "partial" | "error"
}

export class FreeSearchApiService {
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
    if (patch.enabled !== undefined) body.enabled = patch.enabled
    if (patch.priority !== undefined) body.priority = patch.priority
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

  putSecret(backendId: string, key: string): Promise<BackendSecretStatus> {
    return this.request<BackendSecretStatus>(`/api/v1/providers/${backendId}/secret`, {
      method: "PUT",
      body: JSON.stringify({ key }),
    })
  }

  deleteSecret(backendId: string): Promise<BackendSecretStatus> {
    return this.request<BackendSecretStatus>(`/api/v1/providers/${backendId}/secret`, {
      method: "DELETE",
    })
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

  /**
   * Trace summaries for the Activity list. Summary-only by contract: the
   * backend never sends query text or results here, so the list stays fast and
   * payload-free.
   */
  listTraces(
    filters: TraceListFilters = {},
    signal?: AbortSignal
  ): Promise<BackendTraceList> {
    const params = new URLSearchParams()
    if (filters.limit !== undefined) params.set("limit", String(filters.limit))
    if (filters.operation !== undefined) params.set("operation", filters.operation)
    if (filters.outcome !== undefined) params.set("outcome", filters.outcome)
    const query = params.toString()
    return this.request<BackendTraceList>(`/api/v1/traces${query ? `?${query}` : ""}`, {
      ...(signal !== undefined ? { signal } : {}),
    })
  }

  /** Full detail for one trace, including query, results, and stage timeline. */
  getTrace(traceId: string, signal?: AbortSignal): Promise<BackendTraceDetail> {
    return this.request<BackendTraceDetail>(
      `/api/v1/traces/${encodeURIComponent(traceId)}`,
      { ...(signal !== undefined ? { signal } : {}) }
    )
  }

  /**
   * Manually entered billing window for one provider. A 404 means no manual
   * entry is configured (honest null, not an error) — every other failure
   * surfaces as ApiError via the shared request() mapping.
   */
  async getManualQuota(backendId: string): Promise<BackendManualQuota | null> {
    try {
      return await this.request<BackendManualQuota>(
        `/api/v1/providers/${backendId}/manual-quota`
      )
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
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

  /**
   * OAuth device-flow pairing (Parallel Account API). A 404 on status means
   * no pairing exists (honest unpaired null-shape, not an error) — every
   * other failure surfaces as ApiError via the shared request() mapping.
   */
  beginOAuthDeviceFlow(backendId: string): Promise<BackendOAuthDeviceCode> {
    return this.request<BackendOAuthDeviceCode>(
      `/api/v1/providers/${backendId}/oauth/device-code`,
      { method: "POST" }
    )
  }

  async getOAuthStatus(backendId: string): Promise<BackendOAuthStatus> {
    try {
      return await this.request<BackendOAuthStatus>(
        `/api/v1/providers/${backendId}/oauth/status`
      )
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return { provider: backendId, status: "unpaired", expires_in: null }
      }
      throw error
    }
  }

  async revokeOAuth(backendId: string): Promise<void> {
    await this.request<unknown>(`/api/v1/providers/${backendId}/oauth`, {
      method: "DELETE",
    })
  }

  async deleteManualQuota(backendId: string): Promise<void> {
    await this.request<unknown>(`/api/v1/providers/${backendId}/manual-quota`, {
      method: "DELETE",
    })
  }
}

export const apiService = new FreeSearchApiService()
