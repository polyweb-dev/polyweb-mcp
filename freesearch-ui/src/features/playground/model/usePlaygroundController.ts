import { useEffect } from "react"
import type { Dispatch, FormEvent, SetStateAction } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig } from "@/domains/providers"
import type { FetchResponse, SearchResponse, SearchResult } from "@/domains/execution"
import { useAppDispatch, useAppSelector } from "@/store/hooks"
import {
  selectActiveFetch,
  selectActiveSearch,
  selectFetchError,
  selectFetchUrl,
  selectHasFetchContent,
  selectHasSearchContent,
  selectIsFetching,
  selectIsSearching,
  selectMode,
  selectQuery,
  selectResultCount,
  selectSearchError,
  selectSelectedProviderId,
  setFetchUrl as setFetchUrlAction,
  setMode as setModeAction,
  setQuery as setQueryAction,
  setResultCount as setResultCountAction,
  setSelectedProviderId as setSelectedProviderIdAction,
} from "@/store/playgroundSlice"
import type { PlaygroundMode } from "@/store/playgroundSlice"
import { useResultPreview } from "./useResultPreview"
import { createExecuteHandler } from "./playgroundExecuteAction"
import { createFetchResultHandler } from "./playgroundFetchAction"

export type { PlaygroundMode }

export interface PlaygroundController {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  resultCount: number
  eligibleProviders: ProviderConfig[]
  hasSearchContent: boolean
  hasFetchContent: boolean
  activeSearch: SearchResponse | null
  activeFetch: FetchResponse | null
  isSearching: boolean
  isFetching: boolean
  searchError: string | null
  fetchError: string | null
  selectedResultForPreview: SearchResult | null
  showJsonInspector: boolean
  copied: boolean
  setQuery: (value: string) => void
  setFetchUrl: (value: string) => void
  setSelectedProviderId: (value: string) => void
  setResultCount: (value: number) => void
  setSelectedResultForPreview: (value: SearchResult | null) => void
  setShowJsonInspector: Dispatch<SetStateAction<boolean>>
  copyToClipboard: (text: string) => void
  handleExecute: (e?: FormEvent) => Promise<void>
  switchMode: (next: PlaygroundMode) => void
  handleFetchResult: (result: SearchResult) => Promise<void>
}

function isEligibleForOperation(
  provider: ProviderConfig,
  operation: "search" | "fetch"
): boolean {
  if (!provider.globalEnabled) return false
  const hasCredential = provider.hasKey || provider.capabilities.includes("keyless_tier")
  if (!hasCredential) return false
  return operation === "search"
    ? provider.searchEnabled && provider.capabilities.includes("search")
    : provider.fetchEnabled && provider.capabilities.includes("fetch")
}

/**
 * `auto`/`all` always pass through; a pinned id that is no longer eligible for
 * the active mode falls back to `auto` for display and for the next request.
 */
function resolveEffectiveProviderId(
  selectedProviderId: string,
  eligibleProviders: ProviderConfig[]
): string {
  if (selectedProviderId === "auto" || selectedProviderId === "all") return selectedProviderId
  return eligibleProviders.some((provider) => provider.id === selectedProviderId)
    ? selectedProviderId
    : "auto"
}

/** Slice-backed controller fields, selected in one place to stay within budget. */
function usePlaygroundSliceFields() {
  return {
    mode: useAppSelector(selectMode),
    query: useAppSelector(selectQuery),
    fetchUrl: useAppSelector(selectFetchUrl),
    selectedProviderId: useAppSelector(selectSelectedProviderId),
    resultCount: useAppSelector(selectResultCount),
    activeSearch: useAppSelector(selectActiveSearch),
    activeFetch: useAppSelector(selectActiveFetch),
    isSearching: useAppSelector(selectIsSearching),
    isFetching: useAppSelector(selectIsFetching),
    searchError: useAppSelector(selectSearchError),
    fetchError: useAppSelector(selectFetchError),
    hasSearchContent: useAppSelector(selectHasSearchContent),
    hasFetchContent: useAppSelector(selectHasFetchContent),
  }
}

/**
 * Interaction coordination for the search/fetch playground. Composer drafts,
 * view mode, request options, latest results, and execution status are Redux
 * state (persisted); only inspector/clipboard presentation state stays local.
 * Rendering lives in ui/.
 */
export function usePlaygroundController(): PlaygroundController {
  const { providers, providersLoading, runSearch, runFetch } = useFreeSearch()
  const dispatch = useAppDispatch()
  const fields = usePlaygroundSliceFields()
  const preview = useResultPreview()
  const { setSelectedResultForPreview } = preview

  const eligibleProviders = providers.filter((provider) =>
    isEligibleForOperation(provider, fields.mode)
  )

  const effectiveSelectedProviderId = resolveEffectiveProviderId(
    fields.selectedProviderId,
    eligibleProviders
  )
  const isSelectionStale = effectiveSelectedProviderId !== fields.selectedProviderId

  // The catalog arrives asynchronously and a persisted provider can lose its key
  // between sessions: rewrite the stored choice once the catalog has settled so
  // a reload cannot resurrect an ineligible id. Display already falls back.
  useEffect(() => {
    if (providersLoading !== true && isSelectionStale) {
      dispatch(setSelectedProviderIdAction("auto"))
    }
  }, [dispatch, isSelectionStale, providersLoading])

  const setQuery = (value: string) => dispatch(setQueryAction(value))
  const setFetchUrl = (value: string) => dispatch(setFetchUrlAction(value))
  const setSelectedProviderId = (value: string) =>
    dispatch(setSelectedProviderIdAction(value))
  const setResultCount = (value: number) => dispatch(setResultCountAction(value))

  const handleExecute = createExecuteHandler({
    mode: fields.mode,
    query: fields.query,
    fetchUrl: fields.fetchUrl,
    selectedProviderId: effectiveSelectedProviderId,
    resultCount: fields.resultCount,
    eligibleProviders,
    runSearch,
    runFetch,
    showResult: setSelectedResultForPreview,
  })

  const switchMode = (next: PlaygroundMode) => {
    const selectionLostForNextMode =
      effectiveSelectedProviderId !== "auto" &&
      effectiveSelectedProviderId !== "all" &&
      !providers.some(
        (provider) =>
          provider.id === effectiveSelectedProviderId && isEligibleForOperation(provider, next)
      )
    if (next === "fetch" && effectiveSelectedProviderId === "all") {
      setSelectedProviderId("auto")
    } else if (selectionLostForNextMode) {
      setSelectedProviderId("auto")
    }
    dispatch(setModeAction(next))
    setSelectedResultForPreview(null)
  }

  const handleFetchResult = createFetchResultHandler({
    selectedProviderId: effectiveSelectedProviderId,
    providers,
    isSearching: fields.isSearching,
    isFetching: fields.isFetching,
    runFetch,
    setSelectedProviderId,
    setFetchUrl,
    switchMode,
    isEligibleForFetch: (provider) => isEligibleForOperation(provider, "fetch"),
  })

  return {
    ...fields,
    eligibleProviders,
    selectedProviderId: effectiveSelectedProviderId,
    selectedResultForPreview: preview.selectedResultForPreview,
    showJsonInspector: preview.showJsonInspector,
    copied: preview.copied,
    setQuery,
    setFetchUrl,
    setSelectedProviderId,
    setResultCount,
    setSelectedResultForPreview,
    setShowJsonInspector: preview.setShowJsonInspector,
    copyToClipboard: preview.copyToClipboard,
    handleExecute,
    switchMode,
    handleFetchResult,
  }
}
