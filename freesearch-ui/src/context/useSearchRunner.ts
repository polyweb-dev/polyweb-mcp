import {
  useCallback,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react"
import type { BackendFetchRequest, BackendSearchRequest } from "@/services/api/backendTypes"
import { apiService } from "@/services/api/freesearchApi"
import { catalogNameOf } from "@/services/api/providerCatalog"
import {
  mapFetchResponse,
  mapSearchResponse,
  toBackendId,
} from "@/services/api/mappers"
import type {
  FetchRequest,
  FetchResponse,
  SearchRequest,
  SearchResponse,
  UsageEvent,
} from "@/types/freesearch"
import type { ToastNotification } from "./context"
import { errorMessage, makeFetchEvent, makeSearchEvent } from "./providerMappers"

type ShowToast = (message: string, type?: ToastNotification["type"]) => void

type SearchRunnerOptions = {
  fallbackEnabled: boolean
  refreshDashboard: () => Promise<void>
  showToast: ShowToast
  setUsageEvents: Dispatch<SetStateAction<UsageEvent[]>>
  setActiveSearch: Dispatch<SetStateAction<SearchResponse | null>>
  setSearchError: Dispatch<SetStateAction<string | null>>
  setIsSearching: Dispatch<SetStateAction<boolean>>
}

type FetchRunnerOptions = {
  fallbackEnabled: boolean
  refreshDashboard: () => Promise<void>
  showToast: ShowToast
  setActiveFetch: Dispatch<SetStateAction<FetchResponse | null>>
  setFetchError: Dispatch<SetStateAction<string | null>>
  setIsFetching: Dispatch<SetStateAction<boolean>>
  setUsageEvents: Dispatch<SetStateAction<UsageEvent[]>>
}

function createTimeoutSignal(timeoutMs: number): AbortSignal {
  // GAP: 11 — the backend does not expose a request timeout; enforce it client-side.
  return AbortSignal.timeout(Math.max(0, timeoutMs))
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 1
  return Math.min(100, Math.max(1, Math.trunc(value)))
}

function createRunSearch({
  fallbackEnabled,
  refreshDashboard,
  showToast,
  setActiveSearch,
  setSearchError,
  setIsSearching,
  setUsageEvents,
}: SearchRunnerOptions) {
  return async (request: SearchRequest): Promise<SearchResponse | null> => {
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
        allow_fallback: fallbackEnabled,
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
  }
}

function createRunFetch({
  fallbackEnabled,
  refreshDashboard,
  showToast,
  setActiveFetch,
  setFetchError,
  setIsFetching,
  setUsageEvents,
}: FetchRunnerOptions) {
  return async (request: FetchRequest): Promise<FetchResponse | null> => {
    setIsFetching(true)
    setFetchError(null)
    setActiveFetch(null)
    const startedAt = performance.now()
    const providerIds = request.providerId ? [toBackendId(request.providerId)] : []
    const body: BackendFetchRequest = {
      url: request.url.trim(),
      max_chars: null,
      routing: {
        mode: request.providerId ? "require" : "auto",
        providers: providerIds,
        allow_fallback: fallbackEnabled,
      },
    }

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
  }
}

export function useSearchRunner({
  fallbackEnabled,
  refreshDashboard,
  showToast,
  setUsageEvents,
}: {
  fallbackEnabled: boolean
  refreshDashboard: () => Promise<void>
  showToast: ShowToast
  setUsageEvents: Dispatch<SetStateAction<UsageEvent[]>>
}) {
  const [activeSearch, setActiveSearch] = useState<SearchResponse | null>(null)
  const [activeFetch, setActiveFetch] = useState<FetchResponse | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isFetching, setIsFetching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const runSearch = useMemo(
    () =>
      createRunSearch({
        fallbackEnabled,
        refreshDashboard,
        showToast,
        setActiveSearch,
        setSearchError,
        setIsSearching,
        setUsageEvents,
      }),
    [fallbackEnabled, refreshDashboard, setUsageEvents, showToast]
  )
  const runFetch = useMemo(
    () =>
      createRunFetch({
        fallbackEnabled,
        refreshDashboard,
        showToast,
        setActiveFetch,
        setFetchError,
        setIsFetching,
        setUsageEvents,
      }),
    [fallbackEnabled, refreshDashboard, setUsageEvents, showToast]
  )
  const clearActiveResults = useCallback(() => {
    setActiveSearch(null)
    setActiveFetch(null)
    setSearchError(null)
    setFetchError(null)
  }, [])

  return useMemo(
    () => ({
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      runSearch,
      runFetch,
      clearActiveResults,
    }),
    [
      activeSearch,
      activeFetch,
      isSearching,
      isFetching,
      searchError,
      fetchError,
      runSearch,
      runFetch,
      clearActiveResults,
    ]
  )
}
