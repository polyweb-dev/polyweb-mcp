import type { SearchResponse, SearchResult } from "@/types/freesearch"
import { SearchResultInspector } from "./SearchResultInspector"
import { SearchResultList } from "./SearchResultList"
import { SearchResultsSummary } from "./SearchResultsSummary"

type SearchResultsViewOptions = {
  activeSearch: SearchResponse
  selectedResultForPreview: SearchResult | null
  isSearching: boolean
  isFetching: boolean
  showJsonInspector: boolean
  copied: boolean
  onToggleJsonInspector: () => void
  onCopy: (text: string) => void
  onSelectResult: (result: SearchResult) => void
  onFetchResult: (result: SearchResult) => void
}

export function SearchResultsView({
  activeSearch,
  selectedResultForPreview,
  isSearching,
  isFetching,
  showJsonInspector,
  copied,
  onToggleJsonInspector,
  onCopy,
  onSelectResult,
  onFetchResult,
}: SearchResultsViewOptions) {
  return (
    <div className="space-y-6 pt-2">
      <SearchResultsSummary
        activeSearch={activeSearch}
        showJsonInspector={showJsonInspector}
        copied={copied}
        onToggleJsonInspector={onToggleJsonInspector}
        onCopy={onCopy}
      />

      {/* 2-Column Split: Results List (left) + Detail Inspector / Preview (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        <SearchResultList
          activeSearch={activeSearch}
          selectedResultForPreview={selectedResultForPreview}
          isSearching={isSearching}
          isFetching={isFetching}
          onSelectResult={onSelectResult}
          onFetchResult={onFetchResult}
        />
        <SearchResultInspector
          activeSearch={activeSearch}
          selectedResultForPreview={selectedResultForPreview}
        />
      </div>
    </div>
  )
}
