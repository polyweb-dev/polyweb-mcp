import { ExternalLink, FileText } from "lucide-react"
import type { SearchResult } from "@/domains/execution"
import { Button } from "@/shared/ui/button"
import { LinkButton } from "@/shared/ui/LinkButton"
import { SearchResultCard } from "@/shared/ui/SearchResultCard"
import { toPlaygroundResultView } from "../model/searchResultPresentation"

export interface ResultCardProps {
  result: SearchResult
  selected: boolean
  isSearching: boolean
  isFetching: boolean
  /** The caller holds `fetch.execute` in the project; without it the fetch action is disabled. */
  canFetch: boolean
  showAttribution?: boolean
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
  showAttribution = true,
  onSelect,
  onFetch,
}: ResultCardProps) {
  return (
    <SearchResultCard
      result={toPlaygroundResultView(result, showAttribution)}
      selected={selected}
      onSelect={() => onSelect(result)}
      actions={
        <>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            data-testid={"fetch-result-" + result.id}
            title={canFetch ? "Fetch this page" : "Fetch is not permitted in this project"}
            aria-label={"Fetch " + result.title}
            disabled={!canFetch || isSearching || isFetching}
            onClick={(e) => {
              e.stopPropagation()
              void onFetch(result)
            }}
            className="text-[var(--muted)]"
          >
            <FileText aria-hidden="true" className="size-3.5" />
          </Button>

          <LinkButton
            to={result.url}
            target="_blank"
            rel="noreferrer"
            aria-label={"Open " + result.title}
            title="Open external link"
          >
            <ExternalLink aria-hidden="true" className="size-3.5" />
          </LinkButton>
        </>
      }
    />
  )
}
