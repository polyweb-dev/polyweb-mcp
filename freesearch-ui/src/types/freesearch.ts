/**
 * UI-facing domain models. Backend DTOs stay snake_case in services/api.
 */

export type Capability =
  | "search"
  | "fetch"
  | "extract"
  | "neural_search"
  | "live_crawl"
  | "keyless_tier"

export type ProviderHealthStatus =
  | "healthy"
  | "degraded"
  | "rate_limited"
  | "circuit_broken"
  | "offline"

export type CircuitBreakerStatus = "closed" | "open" | "half_open"
export type QuotaConfidence = "authoritative" | "observed" | "estimated"
export type KeySource = "environment" | "dotenv" | "keyring" | "none"

export interface ProviderQuota {
  used: number | null
  limit: number | null
  unit: string
  confidence: QuotaConfidence
  resetPeriod: string | null
  nextReset: string | null
}

export interface ProviderConfig {
  id: string
  name: string
  description: string
  baseUrl: string
  isCustom: boolean
  capabilities: Capability[]
  globalEnabled: boolean
  searchEnabled: boolean
  fetchEnabled: boolean
  priority: number
  healthStatus: ProviderHealthStatus
  circuitBreaker: CircuitBreakerStatus
  consecutiveFailures: number
  latencyP95Ms: number | null
  hasKey: boolean
  keyMasked: string
  keyVaultStatus: "configured" | "missing" | "keyless_public"
  keySource?: KeySource
  authHeaderName?: string
  quota: ProviderQuota
}

export interface FallbackConfig {
  enabled: boolean
  maxAttempts: number
  fallbackOnRateLimit: boolean
  fallbackOnTimeout: boolean
  fallbackOnServerError: boolean
}

export type RoutingPreset =
  | "priority"
  | "cost_optimized"
  | "latency_optimized"
  | "quality_first"
  | "round_robin"

export interface SearchRequest {
  query: string
  providerIds?: string[]
  maxResults: number
  timeoutMs: number
}

export interface SearchResult {
  id: string
  providerId: string
  providerName: string
  title: string
  url: string
  snippet: string
  relevanceScore: number
  publishedDate?: string
  rawMetadata?: Record<string, unknown>
}

export interface ProviderWaterfallItem {
  providerId: string
  providerName: string
  latencyMs: number
  status: "success" | "failed" | "rate_limited" | "skipped"
  resultsCount: number
  costCredits: number
  error?: string
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  totalResults: number
  selectedProviderId: string
  fallbackChain: string[]
  waterfall: ProviderWaterfallItem[]
  executionTimeMs: number
  costEstimateCredits: number
  timestamp: string
}

export interface FetchRequest {
  url: string
  providerId?: string
  format: "markdown" | "text" | "html"
  includeRawHtml?: boolean
  timeoutMs: number
}

export interface FetchedDocument {
  url: string
  title: string
  content: string
  markdown: string
  providerId: string
  providerName: string
  statusCode: number | null
  contentLength: number
  executionTimeMs: number
}

export interface FetchResponse {
  document: FetchedDocument
  providerId: string
  fallbackChain: string[]
  costEstimateCredits: number
  executionTimeMs: number
  timestamp: string
}

export interface UsageEvent {
  id: string
  timestamp: string
  operation: "search" | "fetch"
  queryOrUrl: string
  providerId: string
  providerName: string
  latencyMs: number | null
  costCredits: number
  status: "success" | "error" | "fallback_recovered"
  routeReason: string
  fallbackChain: string[]
}

export interface UsageTotal {
  provider: string
  operation: string
  total_units: string
}

export interface DashboardQuota {
  provider: string
  remaining: string | null
  limit: string | null
  observed_at: string
  source: QuotaConfidence
}
