import { useState } from "react"
import type { Dispatch, FormEvent, SetStateAction } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig } from "@/domains/providers"
import type {
  FetchResponse,
  SearchResponse,
  SearchResult,
} from "@/domains/execution"
import { useResultPreview } from "./useResultPreview"
import { createExecuteHandler } from "./playgroundExecuteAction"
import { createFetchResultHandler } from "./playgroundFetchAction"
import type { PlaygroundMode } from "./playgroundTypes"

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
  return operation === "search"
    ? provider.searchEnabled && provider.capabilities.includes("search")
    : provider.fetchEnabled && provider.capabilities.includes("fetch")
}

/**
 * Interaction coordination for the search/fetch playground. Owns composer
 * drafts, view mode, and execution handlers; rendering lives in ui/.
 * hasSearchContent/hasFetchContent pin the hero->docked layouts exactly as
 * the monolith did (results, pending, or error each count as content).
 */
export function usePlaygroundController(): PlaygroundController {
  const {
    providers,
    activeSearch,
    activeFetch,
    isSearching,
    isFetching,
    searchError,
    fetchError,
    runSearch,
    runFetch,
  } = useFreeSearch()
  const [mode, setMode] = useState<PlaygroundMode>("search")
  const [query, setQuery] = useState("")
  const [fetchUrl, setFetchUrl] = useState("")
  const [selectedProviderId, setSelectedProviderId] = useState<string>("auto")
  const [resultCount, setResultCount] = useState(6)
  const preview = useResultPreview()

  const eligibleProviders = providers.filter((provider) =>
    isEligibleForOperation(provider, mode)
  )
  const hasSearchContent =
    activeSearch !== null || isSearching || searchError !== null
  const hasFetchContent = activeFetch !== null || isFetching || fetchError !== null

  const handleExecute = createExecuteHandler({
    mode,
    query,
    fetchUrl,
    selectedProviderId,
    resultCount,
    eligibleProviders,
    runSearch,
    runFetch,
    showResult: preview.setSelectedResultForPreview,
  })

  const switchMode = (next: PlaygroundMode) => {
    if (next === "fetch" && selectedProviderId === "all") {
      setSelectedProviderId("auto")
    } else if (
      selectedProviderId !== "auto" &&
      selectedProviderId !== "all" &&
      !providers.some((provider) =>
        provider.id === selectedProviderId && isEligibleForOperation(provider, next)
      )
    ) {
      setSelectedProviderId("auto")
    }
    setMode(next)
    preview.setSelectedResultForPreview(null)
  }

  const handleFetchResult = createFetchResultHandler({
    selectedProviderId,
    providers,
    isSearching,
    isFetching,
    runFetch,
    setSelectedProviderId,
    setFetchUrl,
    switchMode,
    isEligibleForFetch: (provider) => isEligibleForOperation(provider, "fetch"),
  })

  return {
    mode,
    query,
    fetchUrl,
    selectedProviderId,
    resultCount,
    eligibleProviders,
    hasSearchContent,
    hasFetchContent,
    activeSearch,
    activeFetch,
    isSearching,
    isFetching,
    searchError,
    fetchError,
    selectedResultForPreview: preview.selectedResultForPreview,
    showJsonInspector: preview.showJsonInspector,
    copied: preview.copied,
    setQuery,
    setFetchUrl,
    setSelectedProviderId,
    setResultCount,
    setSelectedResultForPreview: preview.setSelectedResultForPreview,
    setShowJsonInspector: preview.setShowJsonInspector,
    copyToClipboard: preview.copyToClipboard,
    handleExecute,
    switchMode,
    handleFetchResult,
  }
}
