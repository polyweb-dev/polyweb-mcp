import type { TraceSearchResult } from "@/domains/activity"
import { providerIdentity, type ProviderIdentity } from "@/domains/providers"
import type { SearchResultView } from "@/shared/ui/searchResultView"

export interface TraceResultViewOptions {
  result: TraceSearchResult
  rank: number
  total: number
  mode: "fusion" | "provider"
  providerId: string | null
}

const ATTRIBUTION_LABELS = {
  fusion: "Contributing providers",
  provider: "Provider",
} as const

const SCORE_LABELS = {
  fusion: "Fusion score",
  provider: "Provider score",
} as const

const CONTRIBUTOR_SEPARATOR = ","

/**
 * Contributor ids of a fused result. The fusion projection stores them as one
 * comma-separated `source` text, so this adapter trims, normalizes, and
 * deduplicates that text in its recorded order without a sort.
 */
function contributorIdentities(source: string | null): ProviderIdentity[] {
  if (source === null) return []
  const seen = new Set<string>()
  const contributors: ProviderIdentity[] = []
  for (const part of source.split(CONTRIBUTOR_SEPARATOR)) {
    const identity = providerIdentity(part)
    if (identity.id === "" || seen.has(identity.id)) continue
    seen.add(identity.id)
    contributors.push(identity)
  }
  return contributors
}

/** A single-provider result keeps the identity its scope recorded. */
function scopedIdentities(providerId: string | null): ProviderIdentity[] {
  if (providerId === null) return []
  const identity = providerIdentity(providerId)
  return identity.id === "" ? [] : [identity]
}

/**
 * Activity adapter: one recorded trace result in the shared presentation. The
 * rank and the recorded order are the identity, never the URL. A missing score
 * stays missing and a missing contributor list stays empty.
 */
export function toTraceResultView(options: TraceResultViewOptions): SearchResultView {
  const { result, rank, total, mode, providerId } = options
  return {
    id: String(rank),
    title: result.title,
    url: result.url,
    snippet: result.snippet,
    providers:
      mode === "fusion" ? contributorIdentities(result.source) : scopedIdentities(providerId),
    attributionLabel: ATTRIBUTION_LABELS[mode],
    score: { label: SCORE_LABELS[mode], value: result.score, format: "decimal" },
    rank,
    total,
  }
}
