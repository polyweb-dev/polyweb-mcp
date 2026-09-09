import type {
  BackendDashboard,
  BackendProviderStatus,
  BackendSecretStatus,
} from "@/services/api/backendTypes"
import { ApiError, isAbortOrTimeout, statusMessage } from "@/services/api/httpErrors"
import { catalogEntryForId } from "@/services/api/providerCatalog"
import { mergeProviderStatus } from "@/services/api/mappers"
import type {
  FetchResponse,
  ProviderConfig,
  SearchResponse,
  UsageEvent,
  UsageTotal,
} from "@/types/freesearch"

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail
  if (isAbortOrTimeout(error)) {
    const detail =
      error && typeof error === "object" && "message" in error
        ? String((error as { message?: unknown }).message ?? "timeout")
        : "timeout"
    return statusMessage(0, detail)
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}

export function mapProviderRows(rows: BackendProviderStatus[]): ProviderConfig[] {
  return rows
    .map((row) => {
      const entry = catalogEntryForId(row.provider_id)
      return entry ? mergeProviderStatus(entry, row) : null
    })
    .filter((row): row is ProviderConfig => row !== null)
    .sort((a, b) => a.priority - b.priority)
}

export function updateProviderFromWire(
  previous: ProviderConfig[],
  row: BackendProviderStatus
): ProviderConfig[] {
  const entry = catalogEntryForId(row.provider_id)
  if (!entry) return previous
  const mapped = mergeProviderStatus(entry, row)
  return previous
    .map((provider) => (provider.id === mapped.id ? mapped : provider))
    .sort((a, b) => a.priority - b.priority)
}

export function updateSecretRow(
  previous: ProviderConfig[],
  id: string,
  secret: BackendSecretStatus
): ProviderConfig[] {
  return previous.map((provider) =>
    provider.id === id
      ? {
          ...provider,
          hasKey: secret.presence !== "missing",
          keyVaultStatus: secret.presence,
          keyMasked: secret.fingerprint ?? "—",
          keySource: secret.source,
        }
      : provider
  )
}

export function usageTotalsFromDashboard(
  rows: BackendDashboard["usage_totals"]
): UsageTotal[] {
  return rows.map(({ provider, operation, total_units }) => ({
    provider,
    operation,
    total_units,
  }))
}

export function makeSearchEvent(response: SearchResponse): UsageEvent {
  const providerName = response.waterfall[0]?.providerName ?? response.selectedProviderId
  return {
    id: `${response.timestamp}-${response.selectedProviderId}-local`,
    timestamp: response.timestamp,
    operation: "search",
    queryOrUrl: "",
    providerId: response.selectedProviderId,
    providerName,
    latencyMs: response.executionTimeMs,
    costCredits: response.costEstimateCredits,
    status: "success",
    routeReason: `Recorded search via ${response.selectedProviderId}`,
    fallbackChain: response.fallbackChain,
  }
}

export function makeFetchEvent(response: FetchResponse): UsageEvent {
  return {
    id: `${response.timestamp}-${response.providerId}-local`,
    timestamp: response.timestamp,
    operation: "fetch",
    queryOrUrl: "",
    providerId: response.providerId,
    providerName: response.document.providerName,
    latencyMs: response.executionTimeMs,
    costCredits: response.costEstimateCredits,
    status: "success",
    routeReason: `Recorded fetch via ${response.providerId}`,
    fallbackChain: response.fallbackChain,
  }
}

export interface ProviderPriorityPatch {
  provider: ProviderConfig
  priority: number
}

export function priorityPatchesForMove(
  sorted: ProviderConfig[],
  index: number,
  targetIndex: number
): ProviderPriorityPatch[] {
  const reordered = [...sorted]
  const moving = reordered[index]
  reordered[index] = reordered[targetIndex]
  reordered[targetIndex] = moving
  return reordered
    .map((provider, rankIndex) => {
      const priority = rankIndex + 1
      return provider.priority === priority ? null : { provider, priority }
    })
    .filter((patch): patch is ProviderPriorityPatch => patch !== null)
}

export function compensatePriority(
  completed: ProviderPriorityPatch[]
): ProviderPriorityPatch[] {
  return [...completed].reverse()
}
