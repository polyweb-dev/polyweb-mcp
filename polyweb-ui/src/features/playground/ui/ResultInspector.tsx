import type { SearchResult } from "@/domains/execution"
import { SearchResultInspector } from "@/shared/ui/SearchResultInspector"
import { toPlaygroundResultView } from "../model/searchResultPresentation"

/** Live result inspector: a thin adapter to the shared inspector. */
export function ResultInspector({ result }: { result: SearchResult | null }) {
  return (
    <SearchResultInspector result={result === null ? null : toPlaygroundResultView(result)} />
  )
}
