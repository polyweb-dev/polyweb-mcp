import { useEffect } from "react"
import type { Dispatch, FormEvent, SetStateAction } from "react"
import { providersForOperation } from "@/domains/providers"
import type { ProjectProvider } from "@/domains/providers"
import type { FetchResponse, SearchResponse, SearchResult } from "@/domains/execution"
import { useProjectExecution } from "@/domains/execution/state/useProjectExecution"
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

/**
 * Project inputs of the playground: the project provider view and the
 * execution permissions of the caller in the URL project.
 */
export interface PlaygroundScope {
  /** Project provider view; empty without `providers.read`. */
  providers: readonly ProjectProvider[]
  providersLoading: boolean
  canSearch: boolean
  canFetch: boolean
}

export interface PlaygroundController {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  resultCount: number
  eligibleProviders: ProjectProvider[]
  canSearch: boolean
  canFetch: boolean
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

/** A mode the caller lacks permission for falls back to the permitted one. */
function resolveMode(mode: PlaygroundMode, scope: PlaygroundScope): PlaygroundMode {
  if (mode === "search" && !scope.canSearch && scope.canFetch) return "fetch"
  if (mode === "fetch" && !scope.canFetch && scope.canSearch) return "search"
  return mode
}

/**
 * `auto`/`all` always pass through; a pinned id that is no longer eligible for
 * the active mode falls back to `auto` for display and for the next request.
 */
function resolveEffectiveProviderId(
  selectedProviderId: string,
  eligibleProviders: readonly ProjectProvider[]
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
 * Interaction coordination for the project search/fetch playground. Composer
 * drafts, view mode, request options, latest results, and execution status are
 * Redux state of the project store (persisted); only inspector/clipboard
 * presentation state stays local. The picker offers the providers whose
 * project `effective_operations` hold the mode. Rendering lives in ui/.
 */
export function usePlaygroundController(scope: PlaygroundScope): PlaygroundController {
  const { providers, providersLoading } = scope
  const { runSearch, runFetch } = useProjectExecution()
  const dispatch = useAppDispatch()
  const sliceFields = usePlaygroundSliceFields()
  const fields = { ...sliceFields, mode: resolveMode(sliceFields.mode, scope) }
  const preview = useResultPreview()
  const { setSelectedResultForPreview } = preview

  const eligibleProviders = providersForOperation(providers, fields.mode)

  const effectiveSelectedProviderId = resolveEffectiveProviderId(
    fields.selectedProviderId,
    eligibleProviders
  )
  const isSelectionStale = effectiveSelectedProviderId !== fields.selectedProviderId

  // The project view arrives asynchronously and a persisted provider can lose
  // its binding between sessions: rewrite the stored choice once the view has
  // settled so a reload cannot resurrect an ineligible id. Display already
  // falls back.
  useEffect(() => {
    if (!providersLoading && isSelectionStale) {
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
    if (next === "search" ? !scope.canSearch : !scope.canFetch) return
    const selectionLostForNextMode =
      effectiveSelectedProviderId !== "auto" &&
      effectiveSelectedProviderId !== "all" &&
      !providersForOperation(providers, next).some(
        (provider) => provider.id === effectiveSelectedProviderId
      )
    if (next === "fetch" && effectiveSelectedProviderId === "all") {
      setSelectedProviderId("auto")
    } else if (selectionLostForNextMode) {
      setSelectedProviderId("auto")
    }
    dispatch(setModeAction(next))
    setSelectedResultForPreview(null)
  }

  const fetchResult = createFetchResultHandler({
    selectedProviderId: effectiveSelectedProviderId,
    providers,
    isSearching: fields.isSearching,
    isFetching: fields.isFetching,
    runFetch,
    setSelectedProviderId,
    setFetchUrl,
    switchMode,
    isEligibleForFetch: (provider) => provider.effectiveOperations.includes("fetch"),
  })
  const handleFetchResult = async (result: SearchResult) => {
    if (scope.canFetch) await fetchResult(result)
  }

  return {
    ...fields,
    eligibleProviders,
    canSearch: scope.canSearch,
    canFetch: scope.canFetch,
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
