/**
 * FreeSearch Domain & API Types
 * Provider-neutral models matching FreeSearch core architecture.
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

export interface ProviderQuota {
  used: number
  limit: number | null
  unit: string
  confidence: QuotaConfidence
  resetPeriod: string
  nextReset: string
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
  priority: number // 1 is highest priority
  healthStatus: ProviderHealthStatus
  circuitBreaker: CircuitBreakerStatus
  consecutiveFailures: number
  latencyP95Ms: number
  hasKey: boolean
  keyMasked: string
  keyVaultStatus: "configured" | "missing" | "keyless_public"
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
  mode: "fast" | "balanced" | "deep"
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
  author?: string
  contentPreview?: string
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
  extractedAuthor?: string
  extractedDate?: string
  providerId: string
  providerName: string
  statusCode: number
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
  latencyMs: number
  costCredits: number
  status: "success" | "error" | "fallback_recovered"
  routeReason: string
  fallbackChain: string[]
}

export interface CacheStats {
  totalEntries: number
  searchHits: number
  fetchHits: number
  hitRatio: number
  sizeKb: number
  lastPurged: string
}

export interface SystemMetrics {
  totalSearches: number
  totalFetches: number
  avgLatencyMs: number
  estimatedCostSavedUsd: number
  activeProvidersCount: number
  circuitBreakersTripped: number
}
