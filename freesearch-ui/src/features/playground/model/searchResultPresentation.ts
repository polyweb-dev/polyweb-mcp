import type { SearchResult } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import type { ResultProviderView, SearchResultView } from "@/shared/ui/searchResultView"

const SINGLE_CONTRIBUTOR = 1

/**
 * Contributor ids of one hit in recorded order, deduplicated without a sort.
 * A multi-source hit lists every recorded engine; a single-source hit keeps the
 * provider the execution mapped for it.
 */
function contributorsOf(result: SearchResult): ResultProviderView[] {
  const recorded =
    result.sources !== undefined && result.sources.length > SINGLE_CONTRIBUTOR
      ? result.sources
      : [result.providerId]
  const seen = new Set<string>()
  const contributors: ResultProviderView[] = []
  for (const raw of recorded) {
    const identity = providerIdentity(raw)
    if (identity.id === "" || seen.has(identity.id)) continue
    seen.add(identity.id)
    contributors.push(identity)
  }
  return contributors
}

/**
 * Playground adapter: one execution result in the shared presentation. The
 * match score stays a percentage and the recorded published date is kept.
 */
export function toPlaygroundResultView(result: SearchResult): SearchResultView {
  return {
    id: result.id,
    title: result.title,
    url: result.url,
    snippet: result.snippet,
    providers: contributorsOf(result),
    attributionLabel: "Attributed",
    score: { label: "Score", value: result.relevanceScore, format: "percent" },
    ...(result.publishedDate !== undefined ? { publishedDate: result.publishedDate } : {}),
  }
}
