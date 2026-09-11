export type BackendRoutingMode = "auto" | "prefer" | "require"
export type BackendBreakerState = "closed" | "open" | "half_open"
export type BackendHealth = "healthy" | "degraded" | "unavailable" | "unknown"
export type BackendSecretPresence = "configured" | "missing" | "keyless_public"
export type BackendSecretSource = "environment" | "dotenv" | "keyring" | "none"
export type BackendUsageStatus = "success" | "failure"
import type { BackendUnitKind } from "@/shared/api/units";
export type { BackendUnitKind } from "@/shared/api/units";
export type BackendCircuitBreaker = {
  state: BackendBreakerState
  updated_at: string
}

export interface BackendRoutingPreference {
  mode: BackendRoutingMode
  providers: string[]
  allow_fallback: boolean
}

export interface BackendSearchRequest {
  query: string
  limit: number
  language: string | null
  country_code: string | null
  domains: string[]
  routing: BackendRoutingPreference
}

export interface BackendSearchResult {
  title: string
  url: string
  snippet: string
  published_at: string | null
  source: string | null
  score: number | null
  metadata: Record<string, unknown>
}

export interface BackendUsageEvent {
  provider: string
  operation: string
  units: string
  unit_kind?: BackendUnitKind | null
  display_unit?: string | null
  observed_at: string
  request_id: string | null
  metadata: Record<string, unknown>
  latency_ms: number | null
  status: BackendUsageStatus
}

export interface BackendSearchResponse {
  query: string
  results: BackendSearchResult[]
  provider: string
  total_results: number | null
  usage: BackendUsageEvent | null
}

export interface BackendFetchRequest {
  url: string
  max_chars: number | null
  routing: BackendRoutingPreference
}

export interface BackendFetchedDocument {
  url: string
  content: string
  title: string | null
  content_type: string | null
  fetched_at: string
  metadata: Record<string, unknown>
}

export interface BackendFetchResponse {
  provider: string
  document: BackendFetchedDocument
  usage: BackendUsageEvent | null
}

export interface BackendProviderStatus {
  provider_id: string
  enabled: boolean
  priority: number
  health: BackendHealth | null
  circuit_breaker: BackendCircuitBreaker
  latency_p95_ms: number | null
  secret_presence: BackendSecretPresence
  free_tier_estimates: Record<string, string>
  reset_schedule: string | null
}

export interface BackendProviderTest {
  provider: string
  ok: boolean
  status: BackendHealth
  latency_ms: number
  checked_at: string
  detail: string | null
}

export interface BackendSecretStatus {
  provider: string
  presence: BackendSecretPresence
  fingerprint: string | null
  updated_at: string | null
  source: BackendSecretSource
}

export interface BackendRoutingConfig {
  fallback_policy: "chained" | "first_only"
  cost_optimization_preset: "balanced" | "free_first"
  max_attempts: number
}

export interface BackendDashboardUsage {
  provider: string
  operation: string
  total_units: string
  event_count: number
  unit_kind?: BackendUnitKind | null
}

export interface BackendDashboardQuota {
  provider: string
  source: "authoritative" | "observed" | "estimated"
  observed_at: string
  remaining: string | number | null
  /** Canonical 0..100 remaining percentage; absent on older backends. */
  remaining_percent?: string | number | null
  limit: string | number | null
  reset_at: string | null
  unit_kind?: BackendUnitKind | null
  display_unit?: string | null
  /** Optional scope label for rolling/keyless windows (for example hourly). */
  window?: string | null
}

export interface BackendDashboardHealth {
  provider: string
  status: BackendHealth
  checked_at: string
}

export interface BackendDashboard {
  notice: string
  usage_totals: BackendDashboardUsage[]
  recent_usage: Array<{
    provider: string
    operation: string
    units: string
    unit_kind?: BackendUnitKind | null
    display_unit?: string | null
    observed_at: string
    latency_ms: number | null
    status: BackendUsageStatus
  }>
  latest_quota: BackendDashboardQuota[]
  latest_health: BackendDashboardHealth[]
  generated_at: string
}

/**
 * Manually entered billing window for providers without a vendor balance
 * endpoint (Brave first, reusable for Exa/Parallel). Decimal-as-string
 * allowance/used stay verbatim; ISO YYYY-MM-DD billing bounds.
 */
export interface BackendManualQuota {
  provider: string
  billing_start: string
  billing_end: string
  allowance: string
  current_usage: string
  remaining?: string | null
  remaining_percent?: string | null
  source?: string | null
  note?: string | null
  updated_at?: string | null
}

export interface BackendManualQuotaPayload {
  billing_start: string
  billing_end: string
  allowance: string
  current_usage: string
  note?: string | null
}

/** OAuth device-flow pairing state per provider (frozen backend contract). */
export type BackendOAuthFlowStatus = "pending" | "ready" | "expired" | "denied" | "unpaired"

export interface BackendOAuthDeviceCode {
  provider: string
  user_code: string
  verification_uri: string
  verification_uri_complete: string | null
  expires_in: number
  interval: number
}

export interface BackendOAuthStatus {
  provider: string
  status: BackendOAuthFlowStatus
  expires_in: number | null
}

export interface BackendValidationErrorItem {
  loc: Array<string | number>
  msg: string
  type?: string
}
