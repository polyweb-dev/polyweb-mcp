// Compat re-export shim (backendTypes wire split): canonical owners live in
// domain wire files. This file defines no types; it only re-exports so all
// existing imports keep working with zero UI/behavior change.
export type {
  BackendBreakerState,
  BackendHealth,
  BackendSecretPresence,
  BackendSecretSource,
  BackendCircuitBreaker,
  BackendProviderStatus,
  BackendProviderTest,
  BackendSecretStatus,
} from "@/domains/providers/api/wire"
export type {
  BackendOAuthFlowStatus,
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"
export type {
  BackendRoutingMode,
  BackendRoutingPreference,
  BackendRoutingConfig,
} from "@/domains/routing/api/wire"
export type {
  BackendUsageStatus,
  BackendSearchRequest,
  BackendSearchResult,
  BackendUsageEvent,
  BackendSearchResponse,
  BackendFetchRequest,
  BackendFetchedDocument,
  BackendFetchResponse,
} from "@/domains/execution/api/wire"
export type {
  BackendDashboardUsage,
  BackendDashboardHealth,
  BackendDashboard,
} from "@/domains/dashboard/api/wire"
export type { BackendDashboardQuota } from "@/domains/dashboard/api/quotaWire"
export type {
  BackendManualQuota,
  BackendManualQuotaPayload,
} from "@/domains/dashboard/api/manualQuotaWire"
export type { BackendValidationErrorItem } from "@/shared/api/validationWire"
export type { BackendUnitKind } from "@/shared/api/units"
