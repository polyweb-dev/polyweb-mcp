import type { TraceOutput } from "@/domains/activity"
import { TraceFetchDocument } from "./TraceFetchDocument"
import { TraceSearchResults } from "./TraceSearchResults"

/**
 * Results-out disclosure: dispatches the tagged output to the shape that
 * matches it, so a new operation adds one branch here and one component.
 */
export function TraceResults({ output }: { output: TraceOutput | null }) {
  if (output === null) {
    return (
      <p className="text-[13px] text-[var(--muted)]">
        No results were recorded for this trace.
      </p>
    )
  }
  if (output.kind === "search_results") return <TraceSearchResults output={output} />
  return <TraceFetchDocument output={output} />
}
