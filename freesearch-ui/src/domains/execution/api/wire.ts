import type { UnitKind } from "@/shared/api/units"
// Acyclic type-only edge: execution -> routing (routing never imports execution).
import type { BackendRoutingPreference } from "@/domains/routing/api/wire"

export type BackendUsageStatus = "success" | "failure"

/** Provider names are validated by the backend's operation-specific schemas. */
export interface BackendSearchProviderOptions {
  brave?: Record<string, unknown> | null
  exa?: Record<string, unknown> | null
  firecrawl?: Record<string, unknown> | null
  keenable?: Record<string, unknown> | null
  parallel?: Record<string, unknown> | null
  tavily?: Record<string, unknown> | null
  tinyfish?: Record<string, unknown> | null
  you?: Record<string, unknown> | null
}

export interface BackendFetchProviderOptions {
  exa?: Record<string, unknown> | null
  firecrawl?: Record<string, unknown> | null
  keenable?: Record<string, unknown> | null
  parallel?: Record<string, unknown> | null
  tavily?: Record<string, unknown> | null
  tinyfish?: Record<string, unknown> | null
  you?: Record<string, unknown> | null
}

export interface BackendSearchRequest {
  query: string
  limit: number
  mode?: "turbo" | "fast" | "basic" | "advanced" | null
  extra_bundles?: number
  language: string | null
  country_code: string | null
  domains: string[]
  routing: BackendRoutingPreference
  providerOptions?: BackendSearchProviderOptions | null
  fanout?: boolean
}

export interface BackendSearchResult {
  title: string
  url: string
  snippet: string
  published_at: string | null
  source: string | null
  score: number | null
  metadata: Record<string, unknown>
  sources?: string[]
}

export interface BackendUsageEvent {
  provider: string
  operation: string
  units: string
  unit_kind?: UnitKind | null
  display_unit?: string | null
  observed_at: string
  request_id: string | null
  metadata: Record<string, unknown>
  latency_ms: number | null
  status: BackendUsageStatus
}

export interface BackendProviderTraceItem {
  provider: string
  latency_ms: number
  status: "success" | "failed" | "rate_limited" | "skipped"
  results_count: number
  cost_credits?: number
  error?: string | null
}

export interface BackendSearchResponse {
  query: string
  results: BackendSearchResult[]
  provider: string
  total_results: number | null
  usage: BackendUsageEvent | null
  participating_providers?: string[]
  waterfall?: BackendProviderTraceItem[]
  provider_metadata?: Record<string, unknown> | null
}

export interface BackendFetchRequest {
  url: string
  max_chars: number | null
  routing: BackendRoutingPreference
  providerOptions?: BackendFetchProviderOptions | null
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
  provider_metadata?: Record<string, unknown> | null
}
