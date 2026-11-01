import { ExternalLink, FileText } from "lucide-react"
import type { SearchResult } from "@/domains/execution"
import { SearchResultCard } from "@/shared/ui/SearchResultCard"
import { toPlaygroundResultView } from "../model/searchResultPresentation"

export interface ResultCardProps {
  result: SearchResult
  selected: boolean
  isSearching: boolean
  isFetching: boolean
  /** The caller holds `fetch.execute` in the project; without it the fetch action is disabled. */
  canFetch: boolean
  onSelect: (result: SearchResult) => void
  onFetch: (result: SearchResult) => void
}

/**
 * One search hit: a thin adapter to the shared card. The card owns the visual
 * structure; the fetch and external-link actions stay Playground-owned and sit
 * outside the selection button, so neither one selects the card.
 */
export function ResultCard({
  result,
  selected,
  isSearching,
  isFetching,
  canFetch,
  onSelect,
  onFetch,
}: ResultCardProps) {
  return (
    <SearchResultCard
      result={toPlaygroundResultView(result)}
      selected={selected}
      onSelect={() => onSelect(result)}
      actions={
        <>
          <button
            type="button"
            data-testid={"fetch-result-" + result.id}
            title={canFetch ? "Fetch this page" : "Fetch is not permitted in this project"}
            aria-label={"Fetch " + result.title}
            disabled={!canFetch || isSearching || isFetching}
            onClick={(e) => {
              e.stopPropagation()
              void onFetch(result)
            }}
            className="p-1 text-[var(--muted)] transition-colors hover:text-[var(--text-strong)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <FileText className="size-3.5" />
          </button>

          <a
            href={result.url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 p-1 text-[var(--muted)] transition-colors hover:text-[var(--text-strong)]"
            title="Open external link"
          >
            <ExternalLink className="size-3.5" />
          </a>
        </>
      }
    />
  )
}
