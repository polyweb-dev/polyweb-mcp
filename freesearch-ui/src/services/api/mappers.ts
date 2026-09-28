import type {
  BackendHealth,
  BackendProviderStatus,
} from "@/domains/providers/api/wire"
import type { BackendRoutingConfig } from "@/domains/routing/api/wire"
import type {
  BackendFetchResponse,
  BackendSearchResponse,
} from "@/domains/execution/api/wire"
import type {
  BackendDashboard,
  BackendDashboardUsage,
} from "@/domains/dashboard/api/wire"
import type { StaticProviderMeta } from "./providerCatalog"
import type {
  DashboardQuota,
  UsageEvent,
  UsageTotal,
} from "@/domains/dashboard"
import type {
  FetchResponse,
  ProviderWaterfallItem,
  SearchResponse,
} from "@/domains/execution"
import type { ProviderConfig, ProviderHealthStatus } from "@/domains/providers"
import { normalizeUnitKind } from "@/shared/api/units"
import { toUiId } from "@/domains/providers"

export { toBackendId, toUiId } from "@/domains/providers"

function parseUnits(units: string | undefined): number {
  const parsed = Number.parseFloat(units ?? "0")
  return Number.isFinite(parsed) ? parsed : 0
}

function decimalString(value: string | number | null): string | null {
  return value === null ? null : String(value)
}

export { normalizeUnitKind, unitLabel } from "@/shared/api/units"

function providerDisplayName(
  providerId: string,
  catalogNameOf: (id: string) => string | undefined
): string {
  if (providerId === "aggregated") return "All Providers"
  return catalogNameOf(providerId) ?? providerId
}

export function mapSearchResponse(
  wire: BackendSearchResponse,
  options: { wallClockMs: number; catalogNameOf: (id: string) => string | undefined }
): SearchResponse {
  const providerId = toUiId(wire.provider)
  const cost = parseUnits(wire.usage?.units)
  const latency = wire.usage?.latency_ms ?? options.wallClockMs
  const results = wire.results.map((result, index) => {
    const rawSources = Array.isArray(result.metadata?.sources)
      ? (result.metadata.sources as string[])
      : (result.sources ?? [wire.provider])
    const primarySource = rawSources[0] ?? wire.provider
    const itemProviderId = toUiId(wire.provider === "aggregated" ? primarySource : wire.provider)
    return {
      id: `${wire.provider}-${index}`,
      providerId: itemProviderId,
      providerName: result.source ?? (rawSources.length > 1 ? rawSources.join(", ") : wire.provider),
      title: result.title,
      url: result.url,
      snippet: result.snippet,
      relevanceScore: result.score ?? 0,
      ...(result.published_at ? { publishedDate: result.published_at.slice(0, 10) } : {}),
      rawMetadata: result.metadata,
      sources: rawSources.map(toUiId),
    }
  })
  const providerName = providerDisplayName(providerId, options.catalogNameOf)

  const waterfall: ProviderWaterfallItem[] =
    wire.waterfall && wire.waterfall.length > 0
      ? wire.waterfall.map((item) => {
          const itemUiId = toUiId(item.provider)
          return {
            providerId: itemUiId,
            providerName: providerDisplayName(itemUiId, options.catalogNameOf),
            latencyMs: item.latency_ms,
            status: item.status,
            resultsCount: item.results_count,
            costCredits: item.cost_credits ?? 0,
            ...(item.error ? { error: item.error } : {}),
          }
        })
      : [
          {
            providerId,
            providerName,
            latencyMs: latency,
            status: "success",
            resultsCount: results.length,
            costCredits: cost,
          },
        ]

  return {
    query: wire.query,
    results,
    totalResults: wire.total_results ?? results.length,
    selectedProviderId: providerId,
    participatingProviders: wire.participating_providers?.map(toUiId),
    fallbackChain: [providerId],
    waterfall,
    executionTimeMs: latency,
    costEstimateCredits: cost,
    timestamp: wire.usage?.observed_at ?? new Date().toISOString(),
  }
}

export function mapFetchResponse(
  wire: BackendFetchResponse,
  options: { wallClockMs: number }
): FetchResponse {
  const providerId = toUiId(wire.provider)
  const executionTimeMs = wire.usage?.latency_ms ?? options.wallClockMs
  const timestamp = wire.usage?.observed_at ?? new Date().toISOString()
  const document = wire.document

  return {
    document: {
      url: document.url,
      title: document.title ?? document.url,
      content: document.content,
      markdown: document.content,
      providerId,
      providerName: wire.provider,
      statusCode: null, // GAP: backend doesn't return status — unavailable
      contentLength: document.content.length,
      executionTimeMs,
    },
    providerId,
    fallbackChain: [providerId],
    costEstimateCredits: parseUnits(wire.usage?.units),
    executionTimeMs,
    timestamp,
  }
}

export function mapBackendHealth(
  health: BackendHealth | null,
  breakerState: "closed" | "open" | "half_open"
): ProviderHealthStatus {
  if (breakerState === "open") return "circuit_broken"
  if (health === "healthy") return "healthy"
  if (health === "degraded" || health === "unknown") return "degraded"
  return "offline"
}

export function mergeProviderStatus(
  catalogEntry: StaticProviderMeta,
  wire: BackendProviderStatus
): ProviderConfig {
  const searchEnabled = wire.enabled && catalogEntry.capabilities.includes("search")
  const fetchEnabled = wire.enabled && catalogEntry.capabilities.includes("fetch")
  return {
    id: catalogEntry.id,
    name: catalogEntry.name,
    description: catalogEntry.description,
    baseUrl: catalogEntry.baseUrl,
    isCustom: false,
    capabilities: [...catalogEntry.capabilities],
    globalEnabled: wire.enabled,
    searchEnabled,
    fetchEnabled,
    priority: wire.priority,
    healthStatus:
      wire.circuit_breaker.state === "open"
        ? "circuit_broken"
        : wire.secret_presence === "missing" && !catalogEntry.capabilities.includes("keyless_tier")
          ? "offline"
          : mapBackendHealth(wire.health, wire.circuit_breaker.state),
    circuitBreaker: wire.circuit_breaker.state,
    consecutiveFailures: 0,
    latencyP95Ms: wire.latency_p95_ms,
    hasKey: wire.secret_presence !== "missing",
    // GAP: 12 — GET status has presence only; fingerprints arrive after secret writes.
    keyMasked: "—",
    keyVaultStatus: wire.secret_presence,
    authHeaderName: catalogEntry.authHeaderName,
    quota: {
      used: null,
      limit: null,
      unit: "units",
      confidence: "estimated",
      resetPeriod: wire.reset_schedule ?? "—",
      nextReset: "—",
      remaining: null,
      remainingPercent: null,
      unitKind: null,
      displayUnit: null,
      observedAt: null,
      window: null,
    },
  }
}

export function mapDashboardUsage(
  dashboard: BackendDashboard,
  catalogNameOf: (id: string) => string | undefined
): UsageEvent[] {
  return dashboard.recent_usage.map((usage, index) => {
    const providerId = toUiId(usage.provider)
    const unitKind = normalizeUnitKind(usage.unit_kind ?? null)
    return {
      id: `${usage.observed_at}-${usage.provider}-${index}`,
      timestamp: usage.observed_at,
      operation: usage.operation === "fetch" ? "fetch" : "search",
      queryOrUrl: "",
      providerId,
      providerName: catalogNameOf(providerId) ?? usage.provider,
      latencyMs: usage.latency_ms ?? null,
      costCredits: parseUnits(usage.units),
      status: usage.status === "success" ? "success" : "error",
      routeReason: `Recorded ${usage.operation} via ${usage.provider}`,
      fallbackChain: [providerId],
      unitKind,
      displayUnit: usage.display_unit ?? null,
    }
  })
}

export function mapDashboardTotals(dashboard: BackendDashboard): UsageTotal[] {
  return dashboard.usage_totals.map((total: BackendDashboardUsage) => ({
    provider: toUiId(total.provider),
    operation: total.operation,
    total_units: String(total.total_units),
    unitKind: normalizeUnitKind(total.unit_kind ?? null),
    eventCount: total.event_count ?? 0,
  }))
}

export function mapDashboardQuotas(dashboard: BackendDashboard): DashboardQuota[] {
  return dashboard.latest_quota.map((quota) => ({
    provider: toUiId(quota.provider),
    remaining: decimalString(quota.remaining),
    remainingPercent: decimalString(quota.remaining_percent ?? null),
    limit: decimalString(quota.limit),
    observed_at: quota.observed_at,
    source: quota.source,
    unitKind: normalizeUnitKind(quota.unit_kind ?? null),
    displayUnit: quota.display_unit ?? null,
    resetAt: quota.reset_at ?? null,
    window: quota.window ?? null,
  }))
}

export function mapRoutingConfig(
  wire: BackendRoutingConfig
): { enabled: boolean; maxAttempts: number } {
  return {
    enabled: wire.fallback_policy === "chained",
    maxAttempts: wire.max_attempts,
  }
}
