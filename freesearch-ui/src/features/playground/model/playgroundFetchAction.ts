import type { SearchResult } from "@/domains/execution"
import type { ProjectProvider } from "@/domains/providers"
import type { ProjectExecutionValue } from "@/domains/execution/state/projectExecutionContext"
import type { PlaygroundMode } from "@/store/playgroundSlice"

export interface FetchResultDeps {
  selectedProviderId: string
  providers: readonly ProjectProvider[]
  isSearching: boolean
  isFetching: boolean
  runFetch: ProjectExecutionValue["runFetch"]
  setSelectedProviderId: (value: string) => void
  setFetchUrl: (value: string) => void
  switchMode: (next: PlaygroundMode) => void
  isEligibleForFetch: (provider: ProjectProvider) => boolean
}

/**
 * Per-result fetch: inherits the pinned provider when it can fetch,
 * otherwise resets to auto, then navigates to Fetch and runs immediately.
 */
export function createFetchResultHandler(
  deps: FetchResultDeps
): (result: SearchResult) => Promise<void> {
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
      ...(providerId !== undefined ? { providerId } : {}),
      format: "markdown",
      timeoutMs: 15000,
    })
  }
}
