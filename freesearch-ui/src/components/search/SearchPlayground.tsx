import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { PillTabs, PillTabsPanel } from "@/components/common/PillTabs"
import { FetchResultsView } from "./FetchDocumentView"
import { PlaygroundHeader } from "./PlaygroundHeader"
import { PlaygroundPanel } from "./PlaygroundPanel"
import { PlaygroundRequestForm } from "./PlaygroundRequestForm"
import { SearchResultsView } from "./SearchResultsView"
import {
  createCopyToClipboard,
  createHandleExecute,
  createHandleFetchResult,
  usePlaygroundSelection,
  type PlaygroundMode,
} from "./hooks/usePlaygroundSelection"
import type { SearchResult } from "@/types/freesearch"

const PLAYGROUND_VIEW_OPTIONS = [
  { value: "search", label: "Search" },
  { value: "fetch", label: "Fetch" },
] as const

export const SearchPlayground: React.FC = () => {
  const {
    providers, activeSearch, activeFetch, isSearching, isFetching,
    searchError, fetchError, runSearch, runFetch,
  } = useFreeSearch()

  const [mode, setMode] = useState<PlaygroundMode>("search")
  const [query, setQuery] = useState("")
  const [fetchUrl, setFetchUrl] = useState("")
  const [resultCount, setResultCount] = useState(6)
  const [selectedResultForPreview, setSelectedResultForPreview] = useState<SearchResult | null>(null)
  const [showJsonInspector, setShowJsonInspector] = useState(false)
  const [copied, setCopied] = useState(false)

  const {
    eligibleProviders,
    selectedProviderId,
    setSelectedProviderId,
    resetInvalidSelection,
  } = usePlaygroundSelection(providers, mode)
  const hasSearchContent =
    activeSearch !== null || isSearching || searchError !== null
  const hasFetchContent = activeFetch !== null || isFetching || fetchError !== null

  const switchMode = (next: PlaygroundMode) => {
    resetInvalidSelection(next)
    setMode(next)
    setSelectedResultForPreview(null)
  }

  const handleExecute = createHandleExecute({
    mode,
    query,
    fetchUrl,
    selectedProviderId,
    eligibleProviders,
    resultCount,
    runSearch,
    runFetch,
    setSelectedResultForPreview,
  })
  const handleFetchResult = createHandleFetchResult({
    providers,
    selectedProviderId,
    isSearching,
    isFetching,
    setSelectedProviderId,
    setFetchUrl,
    switchMode,
    runFetch,
  })

  const copyToClipboard = createCopyToClipboard(setCopied)
  const requestForm = (
    <PlaygroundRequestForm
      mode={mode}
      query={query}
      fetchUrl={fetchUrl}
      isSearching={isSearching}
      isFetching={isFetching}
      eligibleProviders={eligibleProviders}
      selectedProviderId={selectedProviderId}
      resultCount={resultCount}
      onSubmit={handleExecute}
      onQueryChange={setQuery}
      onFetchUrlChange={setFetchUrl}
      onProviderChange={setSelectedProviderId}
      onResultCountChange={setResultCount}
    />
  )

  return (
    <PillTabs
      options={PLAYGROUND_VIEW_OPTIONS}
      value={mode}
      onValueChange={(value) => switchMode(value as PlaygroundMode)}
      ariaLabel="Playground view"
      idPrefix="playground"
      className="flex flex-1 flex-col space-y-8"
    >
      <PlaygroundHeader />

      <PillTabsPanel value="search" className="flex flex-1 flex-col space-y-8">
        <PlaygroundPanel
          testId="search-layout"
          hasSearchContent={hasSearchContent}
          error={searchError}
        >
          {requestForm}
        </PlaygroundPanel>

        {activeSearch && (
          <SearchResultsView
            activeSearch={activeSearch}
            selectedResultForPreview={selectedResultForPreview}
            isSearching={isSearching}
            isFetching={isFetching}
            showJsonInspector={showJsonInspector}
            copied={copied}
            onToggleJsonInspector={() => setShowJsonInspector(!showJsonInspector)}
            onCopy={copyToClipboard}
            onSelectResult={setSelectedResultForPreview}
            onFetchResult={handleFetchResult}
          />
        )}
      </PillTabsPanel>

      <PillTabsPanel value="fetch" className="flex flex-1 flex-col space-y-8">
        <PlaygroundPanel
          testId="fetch-layout"
          hasFetchContent={hasFetchContent}
          error={fetchError}
        >
          {requestForm}
        </PlaygroundPanel>

        {activeFetch && (
          <FetchResultsView
            activeFetch={activeFetch}
            copied={copied}
            onCopy={copyToClipboard}
          />
        )}
      </PillTabsPanel>
    </PillTabs>
  )
}
