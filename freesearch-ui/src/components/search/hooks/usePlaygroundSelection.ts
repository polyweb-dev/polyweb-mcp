import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react"
import type {
  FetchRequest,
  FetchResponse,
  ProviderConfig,
  SearchRequest,
  SearchResponse,
  SearchResult,
} from "@/types/freesearch"

export type PlaygroundMode = "search" | "fetch"
export type PlaygroundOperation = PlaygroundMode

export function isEligibleForOperation(
  provider: ProviderConfig,
  operation: PlaygroundOperation
): boolean {
  if (!provider.globalEnabled) return false
  return operation === "search"
    ? provider.searchEnabled && provider.capabilities.includes("search")
    : provider.fetchEnabled && provider.capabilities.includes("fetch")
}

export function usePlaygroundSelection(
  providers: ProviderConfig[],
  mode: PlaygroundMode
) {
  const [selectedProviderId, setSelectedProviderId] = useState("auto")
  const eligibleProviders = providers.filter((provider) =>
    isEligibleForOperation(provider, mode)
  )

  const resetInvalidSelection = (nextMode: PlaygroundMode) => {
    if (selectedProviderId === "auto") return
    const selectedProvider = providers.find(({ id }) => id === selectedProviderId)
    if (!selectedProvider || !isEligibleForOperation(selectedProvider, nextMode)) {
      setSelectedProviderId("auto")
    }
  }

  return {
    eligibleProviders,
    selectedProviderId,
    setSelectedProviderId,
    resetInvalidSelection,
  }
}

type RunSearch = (request: SearchRequest) => Promise<SearchResponse | null>
type RunFetch = (request: FetchRequest) => Promise<FetchResponse | null>

type ExecuteOptions = {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  eligibleProviders: ProviderConfig[]
  resultCount: number
  runSearch: RunSearch
  runFetch: RunFetch
  setSelectedResultForPreview: Dispatch<SetStateAction<SearchResult | null>>
}

export function createHandleExecute({
  mode,
  query,
  fetchUrl,
  selectedProviderId,
  eligibleProviders,
  resultCount,
  runSearch,
  runFetch,
  setSelectedResultForPreview,
}: ExecuteOptions) {
  return async (event?: FormEvent) => {
    if (event) event.preventDefault()

    const selectedProvider =
      selectedProviderId !== "auto" &&
      eligibleProviders.some((provider) => provider.id === selectedProviderId)
        ? selectedProviderId
        : undefined

    if (mode === "search") {
      if (!query.trim()) return
      const response = await runSearch({
        query: query.trim(),
        providerIds: selectedProvider ? [selectedProvider] : undefined,
        maxResults: resultCount,
        timeoutMs: 3000,
      })
      setSelectedResultForPreview(response?.results[0] ?? null)
      return
    }

    if (!fetchUrl.trim()) return
    await runFetch({
      url: fetchUrl.trim(),
      providerId: selectedProvider,
      format: "markdown",
      timeoutMs: 4000,
    })
    setSelectedResultForPreview(null)
  }
}

type FetchResultOptions = {
  providers: ProviderConfig[]
  selectedProviderId: string
  isSearching: boolean
  isFetching: boolean
  setSelectedProviderId: Dispatch<SetStateAction<string>>
  setFetchUrl: (url: string) => void
  switchMode: (mode: PlaygroundMode) => void
  runFetch: RunFetch
}

export function createHandleFetchResult({
  providers,
  selectedProviderId,
  isSearching,
  isFetching,
  setSelectedProviderId,
  setFetchUrl,
  switchMode,
  runFetch,
}: FetchResultOptions) {
  return async (result: SearchResult) => {
    const url = result.url.trim()
    if (isSearching || isFetching || !url) return

    const providerId =
      selectedProviderId !== "auto" &&
      providers.some(
        (provider) =>
          provider.id === selectedProviderId &&
          isEligibleForOperation(provider, "fetch")
      )
        ? selectedProviderId
        : undefined

    if (!providerId) setSelectedProviderId("auto")
    setFetchUrl(url)
    switchMode("fetch")
    await runFetch({
      url,
      providerId,
      format: "markdown",
      timeoutMs: 4000,
    })
  }
}

export function createCopyToClipboard(
  setCopied: Dispatch<SetStateAction<boolean>>
) {
  return (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
}
