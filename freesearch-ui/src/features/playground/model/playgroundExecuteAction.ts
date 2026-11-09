import type { FormEvent } from "react"
import type { SearchResponse, SearchResult } from "@/domains/execution"
import type { ProjectExecutionValue } from "@/domains/execution/state/projectExecutionContext"
import type { PlaygroundMode } from "@/store/playgroundSlice"

/** The one field the request helpers read from a picker provider. */
type ProviderRef = { id: string }

export interface ExecuteActionDeps {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  selectedProviderId: string
  resultCount: number
  eligibleProviders: readonly ProviderRef[]
  runSearch: ProjectExecutionValue["runSearch"]
  runFetch: ProjectExecutionValue["runFetch"]
  showResult: (result: SearchResult | null) => void
}

export function resolvePinnedProvider(
  selectedProviderId: string,
  eligibleProviders: readonly ProviderRef[]
): string | undefined {
  if (selectedProviderId === "auto" || selectedProviderId === "all") {
    return undefined
  }
  return eligibleProviders.some((p) => p.id === selectedProviderId)
    ? selectedProviderId
    : undefined
}

export function resolveSearchProviderIds(
  selectedProvider: string | undefined,
  isFanout: boolean,
  eligibleProviders: readonly ProviderRef[]
): string[] | undefined {
  if (selectedProvider !== undefined) return [selectedProvider]
  if (isFanout) return eligibleProviders.map((p) => p.id)
  return undefined
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

    const isFanout = selectedProviderId === "all"
    const selectedProvider = resolvePinnedProvider(selectedProviderId, eligibleProviders)

    if (mode === "search") {
      const trimmedQuery = query.trim()
      if (!trimmedQuery) return
      const providerIds = resolveSearchProviderIds(selectedProvider, isFanout, eligibleProviders)
      const res: SearchResponse | null = await runSearch({
        query: trimmedQuery,
        ...(providerIds ? { providerIds } : {}),
        fanout: isFanout,
        maxResults: resultCount,
        ...(isFanout ? { timeoutMs: 15000 } : { timeoutMs: 5000 }),
      })
      showResult(res?.results[0] ?? null)
    } else {
      const trimmedUrl = fetchUrl.trim()
      if (!trimmedUrl) return
      await runFetch({
        url: trimmedUrl,
        ...(selectedProvider !== undefined ? { providerId: selectedProvider } : {}),
        format: "markdown",
        timeoutMs: 15000,
      })
      showResult(null)
    }
  }
}
