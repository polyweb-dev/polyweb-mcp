import type { FormEvent } from "react"
import type { ProviderConfig } from "@/types/freesearch"
import { FetchRequestForm } from "./FetchRequestForm"
import { SearchRequestForm } from "./SearchRequestForm"
import type { PlaygroundMode } from "./hooks/usePlaygroundSelection"

type PlaygroundRequestFormOptions = {
  mode: PlaygroundMode
  query: string
  fetchUrl: string
  isSearching: boolean
  isFetching: boolean
  eligibleProviders: ProviderConfig[]
  selectedProviderId: string
  resultCount: number
  onSubmit: (event?: FormEvent) => void | Promise<void>
  onQueryChange: (query: string) => void
  onFetchUrlChange: (url: string) => void
  onProviderChange: (providerId: string) => void
  onResultCountChange: (count: number) => void
}

export function PlaygroundRequestForm({
  mode,
  query,
  fetchUrl,
  isSearching,
  isFetching,
  eligibleProviders,
  selectedProviderId,
  resultCount,
  onSubmit,
  onQueryChange,
  onFetchUrlChange,
  onProviderChange,
  onResultCountChange,
}: PlaygroundRequestFormOptions) {
  if (mode === "search") {
    return (
      <SearchRequestForm
        query={query}
        isSearching={isSearching}
        isFetching={isFetching}
        eligibleProviders={eligibleProviders}
        selectedProviderId={selectedProviderId}
        resultCount={resultCount}
        onSubmit={onSubmit}
        onQueryChange={onQueryChange}
        onProviderChange={onProviderChange}
        onResultCountChange={onResultCountChange}
      />
    )
  }

  return (
    <FetchRequestForm
      fetchUrl={fetchUrl}
      isSearching={isSearching}
      isFetching={isFetching}
      eligibleProviders={eligibleProviders}
      selectedProviderId={selectedProviderId}
      onSubmit={onSubmit}
      onFetchUrlChange={onFetchUrlChange}
      onProviderChange={onProviderChange}
    />
  )
}
