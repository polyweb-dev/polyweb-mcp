import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type {
  BackendDashboard,
  BackendSearchRequest,
  BackendProviderStatus,
  BackendRoutingConfig,
  BackendSecretStatus,
} from "@/services/api/backendTypes"
import { ApiError, isAbortOrTimeout, statusMessage } from "@/services/api/httpErrors"
import { apiService } from "@/services/api/freesearchApi"
import { catalogEntryForId, catalogNameOf } from "@/services/api/providerCatalog"
import {
  mapBackendHealth,
  mapDashboardQuotas,
  mapDashboardUsage,
  mapFetchResponse,
  mapRoutingConfig,
  mapSearchResponse,
  mergeProviderStatus,
  toBackendId,
  toUiId,
} from "@/services/api/mappers"
import type {
  CircuitBreakerStatus,
  DashboardQuota,
  FallbackConfig,
  FetchRequest,
  FetchResponse,
  ProviderConfig,
  RoutingPreset,
  SearchRequest,
  SearchResponse,
  UsageEvent,
  UsageTotal,
} from "@/types/freesearch"
import { FreeSearchContext, type ToastNotification } from "./context"

const INITIAL_FALLBACK_CONFIG: FallbackConfig = {
  enabled: true,
  maxAttempts: 3,
  fallbackOnRateLimit: true,
  fallbackOnTimeout: true,
  fallbackOnServerError: true,
}

const DEFAULT_COST_PRESET: BackendRoutingConfig["cost_optimization_preset"] = "balanced"
let toastSequence = 0

function errorMessage(error: unknown, fallback: string): string {
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

function mapProviderRows(rows: BackendProviderStatus[]): ProviderConfig[] {
  return rows
    .map((row) => {
      const entry = catalogEntryForId(row.provider_id)
      return entry ? mergeProviderStatus(entry, row) : null
    })
    .filter((row): row is ProviderConfig => row !== null)
    .sort((a, b) => a.priority - b.priority)
}

function updateProviderFromWire(
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

function usageTotalsFromDashboard(
  rows: BackendDashboard["usage_totals"]
): UsageTotal[] {
  return rows.map(({ provider, operation, total_units }) => ({
    provider,
    operation,
    total_units,
  }))
}

function makeSearchEvent(response: SearchResponse): UsageEvent {
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

function makeFetchEvent(response: FetchResponse): UsageEvent {
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

function createTimeoutSignal(timeoutMs: number): AbortSignal {
  // GAP: 11 — the backend does not expose a request timeout; enforce it client-side.
  return AbortSignal.timeout(Math.max(0, timeoutMs))
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 1
  return Math.min(100, Math.max(1, Math.trunc(value)))
}

interface ProviderPriorityPatch {
  provider: ProviderConfig
  priority: number
}

function priorityPatchesForMove(
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

async function restoreProviderPriorities(completed: ProviderPriorityPatch[]): Promise<void> {
  for (const { provider } of [...completed].reverse()) {
    try {
      await apiService.patchProvider(toBackendId(provider.id), { priority: provider.priority })
    } catch {
      // The authoritative refresh remains the fallback if compensation fails.
    }
  }
}

export const FreeSearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)
  const [providersError, setProvidersError] = useState<string | null>(null)
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>(INITIAL_FALLBACK_CONFIG)
  const [routingLoading, setRoutingLoading] = useState(true)
  const [routingError, setRoutingError] = useState<string | null>(null)
  const [routingPreset, setRoutingPreset] = useState<RoutingPreset>("priority")
  const [costOptimizationPreset, setCostOptimizationPreset] = useState<
    BackendRoutingConfig["cost_optimization_preset"]
  >(DEFAULT_COST_PRESET)

  const [activeSearch, setActiveSearch] = useState<SearchResponse | null>(null)
  const [activeFetch, setActiveFetch] = useState<FetchResponse | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>([])
  const [usageLoading, setUsageLoading] = useState(true)
  const [usageError, setUsageError] = useState<string | null>(null)
  const [usageTotals, setUsageTotals] = useState<UsageTotal[]>([])
  const [dashboardQuotas, setDashboardQuotas] = useState<DashboardQuota[]>([])
  const [dashboardNotice, setDashboardNotice] = useState<string | null>(null)
  const [toasts, setToasts] = useState<ToastNotification[]>([])
  const priorityMoveInFlight = useRef(false)
  const quotaAvailable = dashboardQuotas.length > 0

  const showToast = useCallback(
    (message: string, type: ToastNotification["type"] = "info") => {
      toastSequence += 1
      const id = `toast-${toastSequence}`
      setToasts((previous) => [...previous, { id, message, type }])
      setTimeout(() => {
        setToasts((previous) => previous.filter((toast) => toast.id !== id))
      }, 4500)
    },
    []
  )

  const dismissToast = useCallback((id: string) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
  }, [])

  const refreshProviders = useCallback(async () => {
    setProvidersLoading(true)
    setProvidersError(null)
    try {
      const rows = await apiService.listProviders()
      setProviders(mapProviderRows(rows))
    } catch (error) {
      const message = errorMessage(error, "Unable to load providers")
      setProviders([])
      setProvidersError(message)
      showToast(message, "error")
    } finally {
      setProvidersLoading(false)
    }
  }, [showToast])

  const refreshDashboard = useCallback(async () => {
    setUsageLoading(true)
    setUsageError(null)
    try {
      const dashboard = await apiService.getDashboard()
      setUsageEvents(mapDashboardUsage(dashboard, catalogNameOf))
      setUsageTotals(usageTotalsFromDashboard(dashboard.usage_totals))
      setDashboardQuotas(mapDashboardQuotas(dashboard))
      setDashboardNotice(dashboard.notice)
    } catch (error) {
      const message = errorMessage(error, "Unable to load usage telemetry")
      setUsageEvents([])
      setUsageTotals([])
      setDashboardQuotas([])
      setUsageError(message)
      showToast(message, "error")
    } finally {
      setUsageLoading(false)
    }
  }, [showToast])

  useEffect(() => {
    let mounted = true

    const loadProviders = async () => {
      try {
        const rows = await apiService.listProviders()
        if (mounted) setProviders(mapProviderRows(rows))
      } catch (error) {
        if (!mounted) return
        const message = errorMessage(error, "Unable to load providers")
        setProviders([])
        setProvidersError(message)
        showToast(message, "error")
      } finally {
        if (mounted) setProvidersLoading(false)
      }
    }

    const loadRouting = async () => {
      try {
        const wire = await apiService.getRoutingConfig()
        if (!mounted) return
        setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }))
        setCostOptimizationPreset(wire.cost_optimization_preset)
      } catch (error) {
        if (!mounted) return
        const message = errorMessage(error, "Unable to load routing configuration")
        setRoutingError(message)
        showToast(message, "error")
      } finally {
        if (mounted) setRoutingLoading(false)
      }
    }

    const loadDashboard = async () => {
      try {
        const dashboard = await apiService.getDashboard()
        if (!mounted) return
        setUsageEvents(mapDashboardUsage(dashboard, catalogNameOf))
        setUsageTotals(usageTotalsFromDashboard(dashboard.usage_totals))
        setDashboardQuotas(mapDashboardQuotas(dashboard))
        setDashboardNotice(dashboard.notice)
      } catch (error) {
        if (!mounted) return
        const message = errorMessage(error, "Unable to load usage telemetry")
        setUsageEvents([])
        setUsageTotals([])
        setDashboardQuotas([])
        setUsageError(message)
        showToast(message, "error")
      } finally {
        if (mounted) setUsageLoading(false)
      }
    }

    void loadProviders()
    void loadRouting()
    void loadDashboard()
    return () => {
      mounted = false
    }
  }, [showToast])

  const toggleProvider = useCallback(
    async (id: string, enabled: boolean): Promise<void> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { enabled })
        setProviders((previous) => updateProviderFromWire(previous, wire))
        showToast(`${enabled ? "Enabled" : "Disabled"} provider "${id}"`, "success")
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider"), "error")
      }
    },
    [showToast]
  )

  const toggleProviderSearch = useCallback(
    (id: string, enabled: boolean) => {
      // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === id && provider.capabilities.includes("search")
            ? { ...provider, searchEnabled: enabled }
            : provider
        )
      )
    },
    []
  )

  const toggleProviderFetch = useCallback(
    (id: string, enabled: boolean) => {
      // GAP: 4 — the backend exposes global enable only; operation toggles are session-only.
      setProviders((previous) =>
        previous.map((provider) =>
          provider.id === id && provider.capabilities.includes("fetch")
            ? { ...provider, fetchEnabled: enabled }
            : provider
        )
      )
    },
    []
  )

  const updateProviderPriority = useCallback(
    async (id: string, newPriority: number): Promise<boolean> => {
      try {
        const wire = await apiService.patchProvider(toBackendId(id), { priority: newPriority })
        setProviders((previous) => updateProviderFromWire(previous, wire))
        return true
      } catch (error) {
        showToast(errorMessage(error, "Unable to update provider priority"), "error")
        return false
      }
    },
    [showToast]
  )

  const moveProviderPriority = useCallback(
    async (id: string, direction: "up" | "down") => {
      if (priorityMoveInFlight.current) return

      const sorted = [...providers].sort((a, b) => a.priority - b.priority)
      const index = sorted.findIndex((provider) => provider.id === id)
      const targetIndex = direction === "up" ? index - 1 : index + 1
      if (index < 0 || targetIndex < 0 || targetIndex >= sorted.length) return

      const patches = priorityPatchesForMove(sorted, index, targetIndex)
      const completed: ProviderPriorityPatch[] = []
      priorityMoveInFlight.current = true

      try {
        for (const patch of patches) {
          const wire = await apiService.patchProvider(toBackendId(patch.provider.id), {
            priority: patch.priority,
          })
          completed.push(patch)
          setProviders((previous) => updateProviderFromWire(previous, wire))
        }
        await refreshProviders()
      } catch (error) {
        await restoreProviderPriorities(completed)
        await refreshProviders()
        showToast(errorMessage(error, "Unable to move provider priority"), "error")
      } finally {
        priorityMoveInFlight.current = false
      }
    },
    [providers, refreshProviders, showToast]
  )

  const setCircuitBreaker = useCallback(
    async (id: string, status: CircuitBreakerStatus) => {
      if (status === "open") {
        // GAP: 5 — the backend exposes reset only, so trips stay local to this session.
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === id
              ? { ...provider, circuitBreaker: "open", healthStatus: "circuit_broken" }
              : provider
          )
        )
        showToast(`Local trip for "${id}" — local trip — backend exposes reset only`, "warning")
        return
      }

      if (status !== "closed") return
      try {
        const reset = await apiService.resetCircuitBreaker(toBackendId(id))
        setProviders((previous) =>
          previous.map((provider) =>
            provider.id === toUiId(reset.provider)
              ? {
                  ...provider,
                  circuitBreaker: "closed",
                  healthStatus:
                    provider.healthStatus === "circuit_broken"
                      ? "healthy"
                      : provider.healthStatus,
                }
              : provider
          )
        )
      } catch (error) {
        showToast(errorMessage(error, "Unable to reset circuit breaker"), "error")
      }
    },
    [showToast]
  )

  const testProviderConnection = useCallback(
    async (id: string) => {
      const provider = providers.find((candidate) => candidate.id === id)
      if (!provider) return { success: false, latencyMs: 0, message: "Provider not found" }

      try {
        const result = await apiService.testProvider(toBackendId(id))
        setProviders((previous) =>
          previous.map((candidate) =>
            candidate.id === id
              ? {
                  ...candidate,
                  latencyP95Ms: result.latency_ms,
                  healthStatus: mapBackendHealth(result.status, candidate.circuitBreaker),
                }
              : candidate
          )
        )
        const message = result.detail ?? result.status
        showToast(
          result.ok ? `Test passed for ${provider.name}` : `Test failed for ${provider.name}: ${message}`,
          result.ok ? "success" : "error"
        )
        return { success: result.ok, latencyMs: result.latency_ms, message }
      } catch (error) {
        const message = errorMessage(error, "Provider test failed")
        showToast(`Test failed for ${provider.name}: ${message}`, "error")
        return { success: false, latencyMs: provider.latencyP95Ms ?? 0, message }
      }
    },
    [providers, showToast]
  )

  const updateSecretRow = useCallback((id: string, secret: BackendSecretStatus) => {
    setProviders((previous) =>
      previous.map((provider) =>
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
    )
  }, [])

  const saveProviderKey = useCallback(
    async (id: string, rawKey: string): Promise<boolean> => {
      const trimmed = rawKey.trim()
      if (!trimmed) return false
      // GAP: 13 — environment and dotenv sources can shadow a vault write.
      try {
        const secret = await apiService.putSecret(toBackendId(id), trimmed)
        updateSecretRow(id, secret)
        if (secret.source === "environment" || secret.source === "dotenv") {
          showToast(`Stored key for "${id}" — env key shadows vault`, "warning")
        } else {
          showToast(`API key stored for "${id}"`, "success")
        }
        return true
      } catch (error) {
        showToast(errorMessage(error, "Unable to store API key"), "error")
        return false
      }
    },
    [showToast, updateSecretRow]
  )

  const deleteProviderKey = useCallback(
    async (id: string): Promise<boolean> => {
      try {
        const secret = await apiService.deleteSecret(toBackendId(id))
        updateSecretRow(id, secret)
        showToast(`API key deleted for "${id}"`, "success")
        return true
      } catch (error) {
        showToast(errorMessage(error, "Unable to delete API key"), "error")
        return false
      }
    },
    [showToast, updateSecretRow]
  )

  const updateFallbackConfig = useCallback(
    async (partial: Partial<FallbackConfig>) => {
      const hasBackendFields = partial.enabled !== undefined || partial.maxAttempts !== undefined
      setFallbackConfig((previous) => ({ ...previous, ...partial }))
      if (!hasBackendFields) {
        // GAP: 10 — backend does not expose per-condition or timeout-budget controls.
        return
      }

      const nextEnabled = partial.enabled ?? fallbackConfig.enabled
      const nextMaxAttempts = partial.maxAttempts ?? fallbackConfig.maxAttempts
      try {
        const wire = await apiService.updateRoutingConfig({
          fallback_policy: nextEnabled ? "chained" : "first_only",
          cost_optimization_preset: costOptimizationPreset,
          max_attempts: nextMaxAttempts,
        })
        const mapped = mapRoutingConfig(wire)
        setFallbackConfig((previous) => ({ ...previous, ...mapped, ...partial }))
        setCostOptimizationPreset(wire.cost_optimization_preset)
      } catch (error) {
        showToast(errorMessage(error, "Unable to update fallback configuration"), "error")
        try {
          const authoritative = await apiService.getRoutingConfig()
          setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(authoritative) }))
          setCostOptimizationPreset(authoritative.cost_optimization_preset)
        } catch {
          // Keep the error toast when the authoritative read is unavailable.
        }
      }
    },
    [costOptimizationPreset, fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast]
  )

  const updateCostPreset = useCallback(
    async (preset: BackendRoutingConfig["cost_optimization_preset"]): Promise<void> => {
      try {
        const wire = await apiService.updateRoutingConfig({
          fallback_policy: fallbackConfig.enabled ? "chained" : "first_only",
          cost_optimization_preset: preset,
          max_attempts: fallbackConfig.maxAttempts,
        })
        setFallbackConfig((previous) => ({ ...previous, ...mapRoutingConfig(wire) }))
        setCostOptimizationPreset(wire.cost_optimization_preset)
      } catch (error) {
        showToast(errorMessage(error, "Unable to update cost optimization"), "error")
      }
    },
    [fallbackConfig.enabled, fallbackConfig.maxAttempts, showToast]
  )

  const runSearch = useCallback(
    async (request: SearchRequest): Promise<SearchResponse | null> => {
      setIsSearching(true)
      setSearchError(null)
      const startedAt = performance.now()
      const providerIds = request.providerIds ?? []
      const body: BackendSearchRequest = {
        query: request.query.trim(),
        limit: clampLimit(request.maxResults),
        language: null,
        country_code: null,
        domains: [],
        routing: {
          mode: providerIds.length > 0 ? "require" : "auto",
          providers: providerIds.map(toBackendId),
          allow_fallback: fallbackConfig.enabled,
        },
      }

      try {
        const wire = await apiService.search(body, createTimeoutSignal(request.timeoutMs))
        const response = mapSearchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
          catalogNameOf,
        })
        setActiveSearch(response)
        setUsageEvents((previous) => [makeSearchEvent(response), ...previous])
        void refreshDashboard()
        return response
      } catch (error) {
        const message = errorMessage(error, "Search failed")
        setSearchError(message)
        showToast(message, "error")
        return null
      } finally {
        setIsSearching(false)
      }
    },
    [fallbackConfig.enabled, refreshDashboard, showToast]
  )

  const runFetch = useCallback(
    async (request: FetchRequest): Promise<FetchResponse | null> => {
      setIsFetching(true)
      setFetchError(null)
      setActiveFetch(null)
      const startedAt = performance.now()
      const providerIds = request.providerId ? [toBackendId(request.providerId)] : []
      const body = {
        url: request.url.trim(),
        max_chars: null,
        routing: {
          mode: request.providerId ? "require" : "auto",
          providers: providerIds,
          allow_fallback: fallbackConfig.enabled,
        },
      } as const

      try {
        const wire = await apiService.fetchDoc(body, createTimeoutSignal(request.timeoutMs))
        const response = mapFetchResponse(wire, {
          wallClockMs: Math.round(performance.now() - startedAt),
        })
        setActiveFetch(response)
        setUsageEvents((previous) => [makeFetchEvent(response), ...previous])
        void refreshDashboard()
        return response
      } catch (error) {
        const message = errorMessage(error, "Document fetch failed")
        setFetchError(message)
        showToast(message, "error")
        return null
      } finally {
        setIsFetching(false)
      }
    },
    [fallbackConfig.enabled, refreshDashboard, showToast]
  )

  const clearActiveResults = useCallback(() => {
    setActiveSearch(null)
    setActiveFetch(null)
    setSearchError(null)
    setFetchError(null)
  }, [])

  const value = useMemo(
    () => ({
      providers,
      providersLoading,
      providersError,
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      quotaAvailable,
      dashboardNotice,
      costOptimizationPreset,
      toasts,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
      updateFallbackConfig,
      updateCostPreset,
      setRoutingPreset,
      runSearch,
      runFetch,
      clearActiveResults,
      refreshProviders,
      refreshDashboard,
      showToast,
      dismissToast,
    }),
    [
      providers,
      providersLoading,
      providersError,
      fallbackConfig,
      routingLoading,
      routingError,
      routingPreset,
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      usageEvents,
      usageLoading,
      usageError,
      usageTotals,
      dashboardQuotas,
      quotaAvailable,
      dashboardNotice,
      costOptimizationPreset,
      toasts,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
      updateFallbackConfig,
      updateCostPreset,
      runSearch,
      runFetch,
      clearActiveResults,
      refreshProviders,
      refreshDashboard,
      showToast,
      dismissToast,
    ]
  )

  return <FreeSearchContext.Provider value={value}>{children}</FreeSearchContext.Provider>
}
