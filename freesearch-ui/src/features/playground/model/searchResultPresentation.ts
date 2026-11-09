import type { SearchResult } from "@/domains/execution"
import { providerIdentity } from "@/domains/providers"
import { formatDate } from "@/shared/lib/formatTime"
import type { ResultProviderView, SearchResultView } from "@/shared/ui/searchResultView"

const SINGLE_CONTRIBUTOR = 1

function plainSnippet(snippet: string): string {
  return snippet
    .replace(/^[ \t]*\|?[ \t:|-]*---[ \t:|-]*\|?[ \t]*$/gm, "")
    .replace(/^[ \t]*\|.*$/gm, (row) => row
      .replace(/^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$/g, "")
      .replace(/(?<!\\)[ \t]*\|[ \t]*/g, " "))
    .replace(/\\\|/g, "|")
    .replace(/!?\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|>\s*)/gm, "")
    .replace(/(\*\*|__|~~|`)(.*?)\1/g, "$2")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1$2")
}

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
export function toPlaygroundResultView(result: SearchResult, showAttribution = true): SearchResultView {
  return {
    id: result.id,
    title: result.title,
    url: result.url,
    snippet: plainSnippet(result.snippet),
    providers: showAttribution ? contributorsOf(result) : [],
    attributionLabel: "Attributed",
    score: { label: "Score", value: result.relevanceScore, format: "percent" },
    ...(result.publishedDate !== undefined ? {
      publishedDate: formatDate(/^\d{4}-\d{2}-\d{2}$/.test(result.publishedDate) ? `${result.publishedDate}T00:00:00` : result.publishedDate),
    } : {}),
  }
}
