import { useState } from "react"
import type { TraceFetchOutput } from "@/domains/activity"

const CONTENT_PREVIEW = 600

/** Fetched document disclosure: metadata plus bounded content preview. */
export function TraceFetchDocument({ output }: { output: TraceFetchOutput }) {
  const [showAll, setShowAll] = useState(false)
  const truncated = output.content.length > CONTENT_PREVIEW
  const content =
    showAll || !truncated ? output.content : output.content.slice(0, CONTENT_PREVIEW)
  return (
    <div className="space-y-2">
      <p className="text-[13px] font-medium break-words text-[var(--text-strong)]">
        {output.title ?? output.url}
      </p>
      <p className="mono break-all text-[var(--muted)]">{output.url}</p>
      <p className="text-[12px] text-[var(--muted)] tnum">
        {output.contentLength} characters
        {output.truncated ? " (truncated by the request limit)" : ""}
      </p>
      <pre className="max-h-64 overflow-auto rounded border border-[var(--border-subtle)] bg-[var(--surface)] p-3 text-[12px] whitespace-pre-wrap text-[var(--text)]">
        {content}
      </pre>
      {truncated && (
        <button
          type="button"
          onClick={() => setShowAll((current) => !current)}
          className="rounded px-2 py-1 text-[12px] font-medium text-[var(--signal)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40"
        >
          {showAll ? "Show less" : "Show full content"}
        </button>
      )}
    </div>
  )
}
