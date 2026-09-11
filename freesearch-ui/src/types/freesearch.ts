/**
 * UI-facing domain models. Backend DTOs stay snake_case in services/api.
 * Canonical definitions live in domains/* and shared/api; this module
 * re-exports them so existing `@/types/freesearch` imports keep working
 * during the migration (plan rule 4: import via small public entry points).
 */

export type { UnitKind } from "@/shared/api/units";
export type {
  Capability,
  ProviderHealthStatus,
  CircuitBreakerStatus,
  KeySource,
  ProviderQuota,
  ProviderConfig,
} from "@/domains/providers";
export type { FallbackConfig, RoutingPreset } from "@/domains/routing";
export type {
  SearchRequest,
  SearchResult,
  SearchResponse,
  ProviderWaterfallItem,
  FetchRequest,
  FetchedDocument,
  FetchResponse,
} from "@/domains/execution";
export type { QuotaConfidence, DashboardQuota } from "@/domains/dashboard";
export type { UsageEvent, UsageTotal } from "@/domains/dashboard";
