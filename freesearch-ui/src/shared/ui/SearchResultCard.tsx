import type { ReactNode } from "react"
import { cn } from "cn"
import { ProviderBadge } from "./ProviderBadge"
import { ResultScore } from "./ResultScore"
import type { SearchResultView } from "./searchResultView"

export interface SearchResultCardProps {
  result: SearchResultView
  selected: boolean
  onSelect: () => void
  /** Fetch, external-link, or copy controls. Kept outside the selection button. */
  actions?: ReactNode
}

/**
 * One search hit: title, URL, a two-line snippet, provider identities, and the
 * recorded score. The whole text block is one selection button, so every action
 * the caller passes in `actions` stays a separate control with its own target.
 */
function providerSummary(result: SearchResultView): ReactNode {
  const first = result.providers[0]
  if (first === undefined) return null
  if (result.providers.length === 1) {
    return (
      <ProviderBadge
        providerId={first.id}
        name={first.name}
        className="text-[11px] text-[var(--muted)]"
        logoClassName="size-3.5"
      />
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-[var(--text-strong)]">
      <span className="rounded bg-[var(--surface-muted)] px-1.5 py-0.5 text-[11px] font-medium text-[var(--signal)]">
        {result.providers.length} engines
      </span>
      {result.providers.map((provider) => (
        <ProviderBadge
          key={provider.id}
          providerId={provider.id}
          name={provider.name}
          className="text-[11px] text-[var(--muted)]"
          logoClassName="size-3"
        />
      ))}
    </span>
  )
}

export function SearchResultCard({
  result,
  selected,
  onSelect,
  actions,
}: SearchResultCardProps): ReactNode {
  const cardClass = selected
    ? "border-[var(--signal)] bg-[var(--signal-muted)]"
    : "border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)]"
  return (
    <div className={cn("flex min-w-0 items-start gap-3 rounded-lg border p-3.5 transition-all", cardClass)}>
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className="min-w-0 flex-1 cursor-pointer text-left"
      >
        <h4 className="text-[14px] font-medium text-[var(--text-strong)] [overflow-wrap:anywhere]">
          {result.title}
        </h4>
        <p className="mono truncate text-[12px] text-[var(--muted)]">{result.url}</p>
        <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-[var(--text)]">
          {result.snippet}
        </p>
        <div className="flex flex-wrap items-center gap-3 pt-1 text-[12px] text-[var(--muted)]">
          {providerSummary(result)}
          <ResultScore score={result.score} />
          {result.publishedDate !== undefined && (
            <span className="tnum">{result.publishedDate}</span>
          )}
        </div>
      </button>

      {actions !== undefined && (
        <div className="flex shrink-0 items-center gap-1">{actions}</div>
      )}
    </div>
  )
}
