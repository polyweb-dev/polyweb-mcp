import { createContext } from "react"
import type {
  CircuitBreakerStatus,
  ProviderConfig,
} from "@/domains/providers"
import type { FallbackConfig, RoutingPreset } from "@/domains/routing"
import type {
  FetchRequest,
  FetchResponse,
  SearchRequest,
  SearchResponse,
} from "@/domains/execution"
import type {
  DashboardQuota,
  UsageEvent,
  UsageTotal,
} from "@/domains/dashboard"

import type { ToastNotification } from "@/shared/notifications/context";
export type { ToastNotification } from "@/shared/notifications/context";

export interface FreeSearchContextType {
  providers: ProviderConfig[]
  providersLoading: boolean
  providersError: string | null
  /** Role capability flags from the composition. */
  canReadControls: boolean
  canEditControls: boolean
  fallbackConfig: FallbackConfig
  routingLoading: boolean
  routingError: string | null
  routingPreset: RoutingPreset
  costOptimizationPreset: "balanced" | "free_first"
  activeSearch: SearchResponse | null
  activeFetch: FetchResponse | null
  isSearching: boolean
  isFetching: boolean
  searchError: string | null
  fetchError: string | null
  usageEvents: UsageEvent[]
  usageLoading: boolean
  usageError: string | null
  usageTotals: UsageTotal[]
  dashboardQuotas: DashboardQuota[]
  quotaAvailable: boolean
  dashboardNotice: string | null
  toasts: ToastNotification[]
  toggleProvider: (id: string, enabled: boolean) => Promise<void>
  toggleProviderSearch: (id: string, enabled: boolean) => Promise<void>
  toggleProviderFetch: (id: string, enabled: boolean) => Promise<void>
  updateProviderPriority: (id: string, newPriority: number) => Promise<boolean>
  moveProviderPriority: (id: string, direction: "up" | "down") => Promise<void>
  setCircuitBreaker: (id: string, status: CircuitBreakerStatus) => Promise<void>
  testProviderConnection: (id: string) => Promise<{
    success: boolean
    latencyMs: number
    message: string
  }>
  saveProviderKey: (id: string, rawKey: string) => Promise<boolean>
  deleteProviderKey: (id: string) => Promise<boolean>
  updateFallbackConfig: (partial: Partial<FallbackConfig>) => Promise<void>
  updateCostPreset: (preset: "balanced" | "free_first") => Promise<void>
  setRoutingPreset: (preset: RoutingPreset) => void
  runSearch: (request: SearchRequest) => Promise<SearchResponse | null>
  runFetch: (request: FetchRequest) => Promise<FetchResponse | null>
  clearActiveResults: () => void
  refreshProviders: () => Promise<void>
  refreshDashboard: () => Promise<void>
  showToast: (message: string, type?: ToastNotification["type"]) => void
  dismissToast: (id: string) => void
}

export const FreeSearchContext = createContext<FreeSearchContextType | undefined>(undefined)
