import { useState } from "react"
import type { TraceFetchOutput } from "@/domains/activity"
import { Button } from "@/shared/ui/button"

const CONTENT_PREVIEW = 600

/** Fetched document disclosure: metadata plus a bounded, wrapping preview. */
export function TraceFetchDocument({ output }: { output: TraceFetchOutput }) {
  const [showAll, setShowAll] = useState(false)
  const truncated = output.content.length > CONTENT_PREVIEW
  const content =
    showAll || !truncated ? output.content : output.content.slice(0, CONTENT_PREVIEW)
  return (
    <div className="min-w-0 space-y-2">
      <p className="text-[13px] font-medium text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {output.title ?? output.url}
      </p>
      <p className="mono text-[12px] text-[var(--muted)] [overflow-wrap:anywhere]">{output.url}</p>
      <p className="text-[12px] text-[var(--muted)] tnum">
        {output.contentLength} characters
        {output.truncated ? " (truncated by the request limit)" : ""}
      </p>
      <pre className="mono max-h-64 overflow-x-hidden overflow-y-auto rounded border border-[var(--border-subtle)] bg-[var(--surface)] p-3 text-[12px] whitespace-pre-wrap text-[var(--text)] [overflow-wrap:anywhere]">
        {content}
      </pre>
      {truncated && (
        <Button variant="outline" size="sm" onClick={() => setShowAll((current) => !current)}>
          {showAll ? "Show less" : "Show full content"}
        </Button>
      )}
    </div>
  )
}
