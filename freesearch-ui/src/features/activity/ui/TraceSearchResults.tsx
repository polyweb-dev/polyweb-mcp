import { useState } from "react"
import type { TraceSearchOutput } from "@/domains/activity"
import { TraceResultRow } from "./TraceResultRow"

const INITIAL_RESULTS = 3

/** Normalized search results, bounded until the user asks for the full list. */
export function TraceSearchResults({ output }: { output: TraceSearchOutput }) {
  const [showAll, setShowAll] = useState(false)
  if (output.results.length === 0) {
    return <p className="text-[13px] text-[var(--muted)]">No result was returned.</p>
  }
  const visible = showAll ? output.results : output.results.slice(0, INITIAL_RESULTS)
  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {visible.map((result, index) => (
          <TraceResultRow key={`${result.url}-${index}`} result={result} />
        ))}
      </ul>
      {!showAll && output.results.length > INITIAL_RESULTS && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="rounded px-2 py-1 text-[12px] font-medium text-[var(--signal)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
        >
          Show all {output.results.length}
        </button>
      )}
    </div>
  )
}
