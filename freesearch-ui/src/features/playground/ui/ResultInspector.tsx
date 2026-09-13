import { ExternalLink } from "lucide-react"
import type { SearchResult } from "@/domains/execution"

/** Live result inspector: full metadata for the selected hit, or the empty prompt. */
export function ResultInspector({ result }: { result: SearchResult | null }) {
  if (!result) {
    return (
      <div className="p-6 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] text-center text-[13px] text-[var(--muted)]">
        Select a search result from the list to inspect full metadata and snippet extraction.
      </div>
    )
  }
  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
      <div className="flex items-start justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
        <div className="min-w-0">
          <span className="text-[12px] text-[var(--signal)] block mb-1">
            Result Inspector
          </span>
          <h3 className="text-[16px] font-medium text-[var(--text-strong)] leading-snug">
            Selected result
          </h3>
        </div>

        <a
          href={result.url}
          target="_blank"
          rel="noreferrer"
          className="p-1.5 rounded text-[var(--muted)] hover:text-white bg-[var(--surface)] border border-[var(--border-subtle)] transition-colors shrink-0"
          title="Open source"
        >
          <ExternalLink className="size-3.5" />
        </a>
      </div>

      <div className="space-y-3">
        <div>
          <span className="text-[12px] text-[var(--muted)] block mb-1">Target URL</span>
          <div className="p-2 rounded bg-[var(--surface)] border border-[var(--border-subtle)] font-mono text-[12px] text-[var(--text)] break-all">
            {result.url}
          </div>
        </div>

        <div>
          <span className="text-[12px] text-[var(--muted)] block mb-1">Snippet summary</span>
          <p className="text-[13px] text-[var(--text)] leading-relaxed p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)]">
            {result.snippet}
          </p>
        </div>

        <div className="pt-2 border-t border-[var(--border-subtle)] flex items-center justify-between text-[12px] text-[var(--muted)] tnum">
          <span>Attributed: {result.providerName}</span>
          <span>Score: {Math.round(result.relevanceScore * 100)}%</span>
        </div>
      </div>
    </div>
  )
}
