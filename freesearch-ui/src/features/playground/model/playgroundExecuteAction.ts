import type { FormEvent } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig, SearchResponse, SearchResult } from "@/types/freesearch"
import type { PlaygroundMode } from "./playgroundTypes"

export interface ExecuteActionDeps {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  resultCount: number
  eligibleProviders: ProviderConfig[]
  runSearch: ReturnType<typeof useFreeSearch>["runSearch"]
  runFetch: ReturnType<typeof useFreeSearch>["runFetch"]
  showResult: (result: SearchResult | null) => void
}

/**
 * Playground submit: pinned providers run as require, otherwise auto. Search
 * previews its first hit; fetch keeps the document view for the new run.
 */
export function createExecuteHandler(deps: ExecuteActionDeps): (e?: FormEvent) => Promise<void> {
  return async (e?: FormEvent) => {
    if (e) e.preventDefault()
    const {
      mode,
      query,
      fetchUrl,
      selectedProviderId,
      resultCount,
      eligibleProviders,
      runSearch,
      runFetch,
      showResult,
    } = deps

    const selectedProvider =
      selectedProviderId !== "auto" &&
      eligibleProviders.some((provider) => provider.id === selectedProviderId)
        ? selectedProviderId
        : undefined

    if (mode === "search") {
      if (!query.trim()) return
      const res: SearchResponse | null = await runSearch({
        query: query.trim(),
        providerIds: selectedProvider ? [selectedProvider] : undefined,
        maxResults: resultCount,
        timeoutMs: 3000,
      })
      showResult(res?.results[0] ?? null)
    } else {
      if (!fetchUrl.trim()) return
      await runFetch({
        url: fetchUrl.trim(),
        providerId: selectedProvider,
        format: "markdown",
        timeoutMs: 4000,
      })
      showResult(null)
    }
  }
}
