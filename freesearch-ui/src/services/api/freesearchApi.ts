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
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
import { ApiError, parseDetail, toApiError } from "@/shared/api/http"

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ""

type RoutingConfigPatch = Partial<BackendRoutingConfig>
type ProviderPatch = { enabled?: boolean; priority?: number }

export class FreeSearchApiService {
  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers)
    if (init?.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json")
    }

    try {
      const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
      })
      const body = await this.readBody(response)
      if (!response.ok) {
        const detail = parseDetail(body)
        throw new ApiError(response.status, detail, body)
      }
      return body as T
    } catch (error) {
      throw toApiError(error)
    }
  }

  private async readBody(response: Response): Promise<unknown> {
    let text: string
    try {
      text = await response.text()
    } catch {
      return undefined
    }
    if (!text) return undefined
    try {
      return JSON.parse(text) as unknown
    } catch {
      return text
    }
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
