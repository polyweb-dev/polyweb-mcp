import type { ReactNode } from "react"
import { ExternalLink } from "lucide-react"
import { ProviderBadge } from "./ProviderBadge"
import { ResultScore } from "./ResultScore"
import type { SearchResultView } from "./searchResultView"

export interface SearchResultInspectorProps {
  result: SearchResultView | null
  /** Shown instead of the default prompt when nothing is selected. */
  emptyState?: ReactNode
}

const SNIPPET_BOX =
  "max-h-[18rem] overflow-y-auto rounded border border-[var(--border-subtle)] bg-[var(--surface)] p-2.5 text-[13px] leading-relaxed text-[var(--text)] whitespace-pre-wrap [overflow-wrap:anywhere]"

/** The host is what a reader scans; the full URL stays the link target. */
function urlHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function metaRow(label: string, value: ReactNode): ReactNode {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 text-[12px] text-[var(--text-strong)] tnum [overflow-wrap:anywhere]">
        {value}
      </dd>
    </div>
  )
}

function attributionValue(result: SearchResultView): ReactNode {
  if (result.providers.length === 0) {
    return <span className="text-[var(--muted)]">Not recorded</span>
  }
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {result.providers.map((provider) => (
        <ProviderBadge
          key={provider.id}
          providerId={provider.id}
          name={provider.name}
          logoClassName="size-3.5"
        />
      ))}
    </span>
  )
}

function rankLine(result: SearchResultView): ReactNode {
  if (result.rank === undefined) return null
  const total = result.total === undefined ? "" : ` of ${result.total}`
  return (
    <p className="text-[12px] text-[var(--muted)] tnum">
      Result {result.rank}
      {total}
    </p>
  )
}

/**
 * Side inspector for one selected result in either feature. The recorded
 * metadata (rank, attribution, score, target host) comes first, so a long
 * snippet can never push it below the fold; the snippet keeps its own bounded
 * scroll region. Presentation only: the caller supplies the converted result.
 */
export function SearchResultInspector({
  result,
  emptyState,
}: SearchResultInspectorProps): ReactNode {
  if (result === null) {
    return (
      emptyState ?? (
        <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-6 text-center text-[13px] text-[var(--muted)]">
          Select a search result from the list to inspect full metadata and snippet extraction.
        </div>
      )
    )
  }
  return (
    <div className="min-w-0 space-y-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] p-4">
      <div className="flex min-w-0 items-start justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
        <div className="min-w-0">
          <span className="mb-1 block text-[12px] text-[var(--signal)]">Result Inspector</span>
          <h3 className="text-[16px] font-medium leading-snug text-[var(--text-strong)]">
            Selected result
          </h3>
        </div>

        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          title="Open target URL"
          className="shrink-0 rounded border border-[var(--border-subtle)] bg-[var(--surface)] p-1.5 text-[var(--muted)] transition-colors hover:text-white"
        >
          <ExternalLink className="size-3.5" />
        </a>
      </div>

      {rankLine(result)}

      <dl className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-2">
        {metaRow(result.attributionLabel, attributionValue(result))}
        {metaRow(result.score.label, <ResultScore score={result.score} />)}
      </dl>

      <div className="min-w-0 space-y-1">
        <span className="block text-[12px] text-[var(--muted)]">Target URL</span>
        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          title={result.url}
          aria-label={result.url}
          className="mono block truncate text-[12px] text-[var(--signal)] hover:underline"
        >
          {urlHost(result.url)}
        </a>
      </div>

      <div className="min-w-0 space-y-1">
        <span className="block text-[12px] text-[var(--muted)]">Snippet summary</span>
        <p className={SNIPPET_BOX}>
          {result.snippet === "" ? (
            <span className="text-[var(--muted)]">Snippet not recorded</span>
          ) : (
            result.snippet
          )}
        </p>
      </div>
    </div>
  )
}
