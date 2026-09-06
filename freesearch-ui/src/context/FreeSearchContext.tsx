import React, { useState, useCallback, useMemo } from "react"
import type {
  CacheStats,
  CircuitBreakerStatus,
  FallbackConfig,
  FetchRequest,
  FetchResponse,
  ProviderConfig,
  RoutingPreset,
  SearchRequest,
  SearchResponse,
  UsageEvent,
} from "@/types/freesearch"
import { DEFAULT_PROVIDERS } from "@/services/api/defaultProviders"
import { apiService } from "@/services/api/freesearchApi"
import { formatMaskedKey } from "@/lib/maskKey"
import { FreeSearchContext, type ToastNotification } from "./context"

const INITIAL_FALLBACK_CONFIG: FallbackConfig = {
  enabled: true,
  maxAttempts: 3,
  fallbackOnRateLimit: true,
  fallbackOnTimeout: true,
  fallbackOnServerError: true,
}

const INITIAL_CACHE_STATS: CacheStats = {
  totalEntries: 248,
  searchHits: 814,
  fetchHits: 342,
  hitRatio: 0.384,
  sizeKb: 1420,
  lastPurged: "Never",
}

const INITIAL_USAGE_EVENTS: UsageEvent[] = [
  {
    id: "evt-init-1",
    timestamp: "2026-09-05T14:30:00.000Z",
    operation: "search",
    queryOrUrl: "distributed consensus algorithms",
    providerId: "brave",
    providerName: "Brave Search",
    latencyMs: 142,
    costCredits: 1,
    status: "success",
    routeReason: "Priority 1 (Healthy)",
    fallbackChain: ["brave"],
  },
  {
    id: "evt-init-2",
    timestamp: "2026-09-05T14:26:00.000Z",
    operation: "fetch",
    queryOrUrl: "https://docs.freesearch.dev/getting-started",
    providerId: "keenable",
    providerName: "Keenable",
    latencyMs: 194,
    costCredits: 0,
    status: "success",
    routeReason: "Keyless free tier active",
    fallbackChain: ["keenable"],
  },
]

let toastSequence = 0

export const FreeSearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>(DEFAULT_PROVIDERS)
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>(INITIAL_FALLBACK_CONFIG)
  const [routingPreset, setRoutingPreset] = useState<RoutingPreset>("priority")

  const [activeSearch, setActiveSearch] = useState<SearchResponse | null>(null)
  const [activeFetch, setActiveFetch] = useState<FetchResponse | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [usageEvents, setUsageEvents] = useState<UsageEvent[]>(INITIAL_USAGE_EVENTS)

  // Cache statistics are read-only telemetry in this build; no purge action.
  const [cacheStats] = useState<CacheStats>(INITIAL_CACHE_STATS)
  const [toasts, setToasts] = useState<ToastNotification[]>([])

  const showToast = useCallback((message: string, type: ToastNotification["type"] = "info") => {
    toastSequence += 1
    const id = `toast-${toastSequence}`
    setToasts((prev) => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 4500)
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  // Provider toggle handlers
  const toggleProvider = useCallback(
    (id: string, enabled: boolean) => {
      setProviders((prev) =>
        prev.map((p) => (p.id === id ? { ...p, globalEnabled: enabled } : p))
      )
      showToast(`${enabled ? "Enabled" : "Disabled"} provider "${id}"`, "info")
    },
    [showToast]
  )

  const toggleProviderSearch = useCallback(
    (id: string, enabled: boolean) => {
      setProviders((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p
          if (!p.capabilities.includes("search")) return p // Guard against enabling unsupported
          return { ...p, searchEnabled: enabled }
        })
      )
      showToast(`${enabled ? "Enabled" : "Disabled"} search for "${id}"`, "info")
    },
    [showToast]
  )

  const toggleProviderFetch = useCallback(
    (id: string, enabled: boolean) => {
      setProviders((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p
          if (!p.capabilities.includes("fetch")) return p // Guard against enabling unsupported
          return { ...p, fetchEnabled: enabled }
        })
      )
      showToast(`${enabled ? "Enabled" : "Disabled"} fetch for "${id}"`, "info")
    },
    [showToast]
  )

  const updateProviderPriority = useCallback(
    (id: string, newPriority: number) => {
      setProviders((prev) => {
        const target = prev.find((p) => p.id === id)
        if (!target) return prev
        const updated = prev.map((p) => (p.id === id ? { ...p, priority: newPriority } : p))
        return updated.sort((a, b) => a.priority - b.priority)
      })
      showToast(`Priority for "${id}" updated to ${newPriority}`, "info")
    },
    [showToast]
  )

  const moveProviderPriority = useCallback(
    (id: string, direction: "up" | "down") => {
      setProviders((prev) => {
        const sorted = [...prev].sort((a, b) => a.priority - b.priority)
        const idx = sorted.findIndex((p) => p.id === id)
        if (idx === -1) return prev
        const targetIdx = direction === "up" ? idx - 1 : idx + 1
        if (targetIdx < 0 || targetIdx >= sorted.length) return prev

        // Swap priorities
        const currentP = sorted[idx]
        const neighborP = sorted[targetIdx]
        const tempPriority = currentP.priority
        currentP.priority = neighborP.priority
        neighborP.priority = tempPriority

        return [...sorted].sort((a, b) => a.priority - b.priority)
      })
    },
    []
  )

  const removeProvider = useCallback((id: string) => {
    setProviders((prev) => prev.filter((p) => p.id !== id))
    showToast(`Provider "${id}" removed`, "info")
  }, [showToast])

  const setCircuitBreaker = useCallback(
    (id: string, status: CircuitBreakerStatus) => {
      setProviders((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p
          return {
            ...p,
            circuitBreaker: status,
            healthStatus: status === "open" ? "circuit_broken" : "healthy",
          }
        })
      )
      showToast(`Circuit breaker for "${id}" set to ${status.toUpperCase()}`, "warning")
    },
    [showToast]
  )

  const testProviderConnection = useCallback(
    async (id: string) => {
      const provider = providers.find((p) => p.id === id)
      if (!provider) {
        return { success: false, latencyMs: 0, message: "Provider not found" }
      }
      const res = await apiService.testConnection(provider)
      if (res.success) {
        showToast(`Test passed for ${provider.name} (${res.latencyMs}ms)`, "success")
      } else {
        showToast(`Test failed for ${provider.name}: ${res.message}`, "error")
      }
      return res
    },
    [providers, showToast]
  )

  // Key Vault: write-only. The raw secret is never stored on the provider —
  // only its masked fingerprint — so it can never be rendered back.
  const saveProviderKey = useCallback(
    (id: string, rawKey: string) => {
      const trimmed = rawKey.trim()
      if (!trimmed) return

      const masked = formatMaskedKey(trimmed)
      setProviders((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p
          return {
            ...p,
            hasKey: true,
            keyMasked: masked,
            keyVaultStatus: "configured" as const,
          }
        })
      )
      showToast(
        `API key stored for "${id}". Credentials are write-only and never displayed.`,
        "success"
      )
    },
    [showToast]
  )

  const updateFallbackConfig = useCallback((partial: Partial<FallbackConfig>) => {
    setFallbackConfig((prev) => ({ ...prev, ...partial }))
  }, [])

  // Execute Search
  const runSearch = useCallback(
    async (request: SearchRequest): Promise<SearchResponse | null> => {
      setIsSearching(true)
      setSearchError(null)
      try {
        const res = await apiService.executeSearch(request, providers, fallbackConfig)
        setActiveSearch(res)

        // Decrement quota and log event
        setProviders((prev) =>
          prev.map((p) => {
            if (p.id === res.selectedProviderId) {
              return {
                ...p,
                quota: {
                  ...p.quota,
                  used: p.quota.used + 1,
                },
              }
            }
            return p
          })
        )

        const newEvent: UsageEvent = {
          id: `evt-${Date.now()}`,
          timestamp: res.timestamp,
          operation: "search",
          queryOrUrl: res.query,
          providerId: res.selectedProviderId,
          providerName:
            providers.find((p) => p.id === res.selectedProviderId)?.name || res.selectedProviderId,
          latencyMs: res.executionTimeMs,
          costCredits: res.costEstimateCredits,
          status: res.fallbackChain.length > 1 ? "fallback_recovered" : "success",
          routeReason:
            res.fallbackChain.length > 1
              ? `Recovered via fallback chain [${res.fallbackChain.join(" -> ")}]`
              : "Primary provider selected",
          fallbackChain: res.fallbackChain,
        }
        setUsageEvents((prev) => [newEvent, ...prev])

        return res
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Search failed"
        setSearchError(msg)
        showToast(msg, "error")
        return null
      } finally {
        setIsSearching(false)
      }
    },
    [providers, fallbackConfig, showToast]
  )

  // Execute Fetch
  const runFetch = useCallback(
    async (request: FetchRequest): Promise<FetchResponse | null> => {
      setIsFetching(true)
      setFetchError(null)
      try {
        const res = await apiService.executeFetch(request, providers, fallbackConfig)
        setActiveFetch(res)

        // Decrement quota and log event
        setProviders((prev) =>
          prev.map((p) => {
            if (p.id === res.providerId) {
              return {
                ...p,
                quota: {
                  ...p.quota,
                  used: p.quota.used + 1,
                },
              }
            }
            return p
          })
        )

        const newEvent: UsageEvent = {
          id: `evt-fetch-${Date.now()}`,
          timestamp: res.timestamp,
          operation: "fetch",
          queryOrUrl: res.document.url,
          providerId: res.providerId,
          providerName: res.document.providerName,
          latencyMs: res.executionTimeMs,
          costCredits: res.costEstimateCredits,
          status: "success",
          routeReason: "Fetch adapter executed",
          fallbackChain: res.fallbackChain,
        }
        setUsageEvents((prev) => [newEvent, ...prev])

        return res
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Document fetch failed"
        setFetchError(msg)
        showToast(msg, "error")
        return null
      } finally {
        setIsFetching(false)
      }
    },
    [providers, fallbackConfig, showToast]
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
      fallbackConfig,
      routingPreset,
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      usageEvents,
      cacheStats,
      toasts,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      removeProvider,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      updateFallbackConfig,
      setRoutingPreset,
      runSearch,
      runFetch,
      clearActiveResults,
      showToast,
      dismissToast,
    }),
    [
      providers,
      fallbackConfig,
      routingPreset,
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      usageEvents,
      cacheStats,
      toasts,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      removeProvider,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      updateFallbackConfig,
      setRoutingPreset,
      runSearch,
      runFetch,
      clearActiveResults,
      showToast,
      dismissToast,
    ]
  )

  return <FreeSearchContext.Provider value={value}>{children}</FreeSearchContext.Provider>
}
