import type {
  BackendDashboard,
  BackendFetchRequest,
  BackendFetchResponse,
  BackendProviderStatus,
  BackendProviderTest,
  BackendRoutingConfig,
  BackendSearchRequest,
  BackendSearchResponse,
  BackendSecretStatus,
} from "./backendTypes"
import { ApiError, isAbortOrTimeout, parseDetail, statusMessage } from "./httpErrors"

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ""

type RoutingConfigPatch = Partial<BackendRoutingConfig>
type ProviderPatch = { enabled?: boolean; priority?: number }

export class FreeSearchApiService {
  private buildJsonHeaders(init?: RequestInit): Headers {
    const headers = new Headers(init?.headers)
    if (init?.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json")
    }
    return headers
  }

  private async throwForStatus(
    response: Response,
    body: unknown
  ): Promise<never | void> {
    if (!response.ok) {
      const detail = parseDetail(body)
      throw new ApiError(response.status, detail, body)
    }
  }

  private throwNormalizedNetworkError(error: unknown): never {
    if (error instanceof ApiError) throw error
    if (isAbortOrTimeout(error)) {
      const detail =
        error && typeof error === "object" && "message" in error
          ? String((error as { message?: unknown }).message ?? "timeout")
          : "timeout"
      throw new ApiError(0, statusMessage(0, detail), error)
    }
    if (error instanceof TypeError) {
      throw new ApiError(0, statusMessage(0, error.message), error)
    }
    throw error
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = this.buildJsonHeaders(init)
    try {
      const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
      const body = await this.readBody(response)
      await this.throwForStatus(response, body)
      return body as T
    } catch (error) {
      this.throwNormalizedNetworkError(error)
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
      signal,
    })
  }

  fetchDoc(body: BackendFetchRequest, signal?: AbortSignal): Promise<BackendFetchResponse> {
    return this.request<BackendFetchResponse>("/fetch", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    })
  }

  getDashboard(limit = 50): Promise<BackendDashboard> {
    return this.request<BackendDashboard>(`/dashboard?limit=${limit}`)
  }
}

export const apiService = new FreeSearchApiService()
