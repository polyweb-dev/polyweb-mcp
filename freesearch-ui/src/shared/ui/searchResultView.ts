/**
 * Presentation contract for one search result, shared by the Playground and
 * the Activity trace detail. These types describe what the screen shows; each
 * feature converts its own domain model into them. No domain import belongs in
 * this file.
 */

/** One recorded score in its own unit. `value` stays in that unit. */
export interface ResultScoreView {
  label: string
  value: number | null
  /** `decimal` keeps the recorded score; `percent` keeps Playground's match rate. */
  format: "decimal" | "percent"
}

/**
 * Whether a score carries a recorded value worth showing. A null score was
 * never recorded, and a zero score carries no ranking signal, so both stay
 * hidden instead of rendering as "Unavailable" or "0% match".
 */
export function hasRecordedScore(
  score: ResultScoreView
): score is ResultScoreView & { value: number } {
  return score.value !== null && score.value !== 0
}

/** One provider identity as the result surfaces show it. */
export interface ResultProviderView {
  id: string
  name: string
}

/** One ranked result, ready for the shared card and the shared inspector. */
export interface SearchResultView {
  id: string
  title: string
  url: string
  snippet: string
  providers: readonly ResultProviderView[]
  /** Name of the attribution field: "Provider", "Contributing providers", "Attributed". */
  attributionLabel: string
  score: ResultScoreView
  rank?: number
  total?: number
  publishedDate?: string
}
