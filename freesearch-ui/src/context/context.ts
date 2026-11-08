import { createContext } from "react"
import type {
  CircuitBreakerStatus,
  ProviderConfig,
} from "@/domains/providers"
import type { FallbackConfig } from "@/domains/routing"
import type {
  CRDUsageTotal,
  DashboardQuota,
  ProviderLimits,
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
  usageEvents: UsageEvent[]
  usageLoading: boolean
  usageError: string | null
  usageTotals: UsageTotal[]
  dashboardQuotas: DashboardQuota[]
  providerLimits: ProviderLimits[]
  crdUsageTotals: CRDUsageTotal[]
  quotaAvailable: boolean
  dashboardNotice: string | null
  toasts: ToastNotification[]
  toggleProvider: (id: string, enabled: boolean) => Promise<void>
  toggleProviderSearch: (id: string, enabled: boolean) => Promise<void>
  toggleProviderFetch: (id: string, enabled: boolean) => Promise<void>
  setCircuitBreaker: (id: string, status: CircuitBreakerStatus) => Promise<void>
  testProviderConnection: (id: string) => Promise<{
    success: boolean
    latencyMs: number
    message: string
  }>
  updateFallbackConfig: (partial: Partial<FallbackConfig>) => Promise<void>
  refreshProviders: () => Promise<void>
  refreshDashboard: () => Promise<void>
  showToast: (message: string, type?: ToastNotification["type"]) => void
  dismissToast: (id: string) => void
}

export const FreeSearchContext = createContext<FreeSearchContextType | undefined>(undefined)
