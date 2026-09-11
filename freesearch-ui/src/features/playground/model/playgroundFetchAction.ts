import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig, SearchResult } from "@/types/freesearch"
import type { PlaygroundMode } from "./playgroundTypes"

export interface FetchResultDeps {
  selectedProviderId: string
  providers: ProviderConfig[]
  isSearching: boolean
  isFetching: boolean
  runFetch: ReturnType<typeof useFreeSearch>["runFetch"]
  setSelectedProviderId: (value: string) => void
  setFetchUrl: (value: string) => void
  switchMode: (next: PlaygroundMode) => void
  isEligibleForFetch: (provider: ProviderConfig) => boolean
}

/**
 * Per-result fetch: inherits the pinned provider when it can fetch,
 * otherwise resets to auto, then navigates to Fetch and runs immediately.
 */
export function createFetchResultHandler(deps: FetchResultDeps): (result: SearchResult) => Promise<void> {
  return async (result: SearchResult) => {
    const url = result.url.trim()
    if (deps.isSearching || deps.isFetching || !url) return

    const providerId =
      deps.selectedProviderId !== "auto" &&
      deps.providers.some(
        (provider) =>
          provider.id === deps.selectedProviderId &&
          deps.isEligibleForFetch(provider)
      )
        ? deps.selectedProviderId
        : undefined

    if (!providerId) deps.setSelectedProviderId("auto")
    deps.setFetchUrl(url)
    deps.switchMode("fetch")
    await deps.runFetch({
      url,
      providerId,
      format: "markdown",
      timeoutMs: 4000,
    })
  }
}
