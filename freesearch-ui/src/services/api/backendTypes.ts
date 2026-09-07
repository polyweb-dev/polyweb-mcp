export type BackendRoutingMode = "auto" | "prefer" | "require"
export type BackendBreakerState = "closed" | "open" | "half_open"
export type BackendHealth = "healthy" | "degraded" | "unavailable" | "unknown"
export type BackendSecretPresence = "configured" | "missing" | "keyless_public"
export type BackendSecretSource = "environment" | "dotenv" | "keyring" | "none"
export type BackendUsageStatus = "success" | "failure"
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
}

export interface BackendDashboardQuota {
  provider: string
  source: "authoritative" | "observed" | "estimated"
  observed_at: string
  remaining: string | number | null
  limit: string | number | null
  reset_at: string | null
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
    observed_at: string
    latency_ms: number | null
    status: BackendUsageStatus
  }>
  latest_quota: BackendDashboardQuota[]
  latest_health: BackendDashboardHealth[]
  generated_at: string
}

export interface BackendValidationErrorItem {
  loc: Array<string | number>
  msg: string
  type?: string
}
