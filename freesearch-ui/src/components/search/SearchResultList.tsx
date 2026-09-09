import { FileText, ExternalLink } from "lucide-react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { SearchResponse, SearchResult } from "@/types/freesearch"

type SearchResultListOptions = {
  activeSearch: SearchResponse
  selectedResultForPreview: SearchResult | null
  isSearching: boolean
  isFetching: boolean
  onSelectResult: (result: SearchResult) => void
  onFetchResult: (result: SearchResult) => void
}

export function SearchResultList({
  activeSearch,
  selectedResultForPreview,
  isSearching,
  isFetching,
  onSelectResult,
  onFetchResult,
}: SearchResultListOptions) {
  return (
    <div className="lg:col-span-7 space-y-3">
      <div className="flex items-center justify-between text-[13px] text-[var(--muted)] pb-1">
        <span>Returned results ({activeSearch.results.length})</span>
        <span>Select item to inspect</span>
      </div>

      <div className="space-y-2">
        {activeSearch.results.map((res) => {
          const isSelected = selectedResultForPreview?.id === res.id
          return (
            <div
              key={res.id}
              onClick={() => onSelectResult(res)}
              className={`p-3.5 rounded-lg border transition-all cursor-pointer ${
                isSelected
                  ? "border-[var(--signal)] bg-[var(--signal-muted)]"
                  : "border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <h4 className="text-[14px] font-medium text-[var(--text-strong)] hover:text-[var(--signal)] transition-colors">
                    {res.title}
                  </h4>

                  <p className="text-[12px] font-mono text-[var(--muted)] truncate">
                    {res.url}
                  </p>

                  <p className="text-[13px] text-[var(--text)] line-clamp-2 leading-relaxed mt-1">
                    {res.snippet}
                  </p>

                  <div className="flex items-center gap-3 text-[12px] text-[var(--muted)] pt-1">
                    <span className="inline-flex items-center gap-1.5 text-[var(--text-strong)]">
                      <ProviderLogo providerId={res.providerId} name={res.providerName} className="size-3.5" />
                      {res.providerName}
                    </span>
                    <span className="tnum">
                      {Math.round(res.relevanceScore * 100)}% match
                    </span>
                    {res.publishedDate && (
                      <span className="tnum">{res.publishedDate}</span>
                    )}
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    data-testid={`fetch-result-${res.id}`}
                    title="Fetch this page"
                    aria-label={`Fetch ${res.title}`}
                    disabled={isSearching || isFetching}
                    onClick={(e) => {
                      e.stopPropagation()
                      void onFetchResult(res)
                    }}
                    className="p-1 text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <FileText className="size-3.5" />
                  </button>

                  <a
                    href={res.url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="p-1 text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors shrink-0"
                    title="Open external link"
                  >
                    <ExternalLink className="size-3.5" />
                  </a>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
