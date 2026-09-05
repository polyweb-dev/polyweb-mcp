import { createContext } from "react"
import type {
  CacheStats,
  CircuitBreakerStatus,
  FallbackConfig,
  FetchRequest,
  FetchResponse,
  ProviderConfig,
  RoutingPreset,
  SearchRequest,
  SearchResponse,
  UsageEvent,
} from "@/types/freesearch"

export interface ToastNotification {
  id: string
  message: string
  type: "success" | "info" | "warning" | "error"
}

export interface FreeSearchContextType {
  providers: ProviderConfig[]
  fallbackConfig: FallbackConfig
  routingPreset: RoutingPreset
  activeSearch: SearchResponse | null
  activeFetch: FetchResponse | null
  isSearching: boolean
  isFetching: boolean
  searchError: string | null
  fetchError: string | null
  usageEvents: UsageEvent[]
  cacheStats: CacheStats
  toasts: ToastNotification[]
  // Provider operations
  toggleProvider: (id: string, enabled: boolean) => void
  toggleProviderSearch: (id: string, enabled: boolean) => void
  toggleProviderFetch: (id: string, enabled: boolean) => void
  updateProviderPriority: (id: string, newPriority: number) => void
  moveProviderPriority: (id: string, direction: "up" | "down") => void
  addProvider: (provider: Omit<ProviderConfig, "isCustom">) => void
  removeProvider: (id: string) => void
  setCircuitBreaker: (id: string, status: CircuitBreakerStatus) => void
  testProviderConnection: (id: string) => Promise<{ success: boolean; latencyMs: number; message: string }>
  // Key Vault & One-time view
  saveProviderKey: (id: string, rawKey: string) => void
  burnOneTimeKey: (id: string) => void
  // Fallback and routing configuration
  updateFallbackConfig: (partial: Partial<FallbackConfig>) => void
  setRoutingPreset: (preset: RoutingPreset) => void
  // Search & Fetch actions
  runSearch: (request: SearchRequest) => Promise<SearchResponse | null>
  runFetch: (request: FetchRequest) => Promise<FetchResponse | null>
  clearActiveResults: () => void
  // Cache & events
  purgeCache: (providerId?: string) => void
  clearUsageEvents: () => void
  // Toast
  showToast: (message: string, type?: ToastNotification["type"]) => void
  dismissToast: (id: string) => void
}

export const FreeSearchContext = createContext<FreeSearchContextType | undefined>(undefined)
