import type { TraceFetchOutput } from "@/domains/activity"

/** The stored document fills the Results pane and scrolls with its parent. */
export function TraceFetchDocument({ output, input }: { output: TraceFetchOutput; input: string | null }) {
  return (
    <article className="min-w-0 space-y-2 pb-2">
      <h3 className="text-[14px] font-medium leading-snug text-[var(--text-strong)] [overflow-wrap:anywhere]">
        {output.title ?? output.url}
      </h3>
      {output.url !== input && <p className="mono text-[12px] text-[var(--muted)] [overflow-wrap:anywhere]">{output.url}</p>}
      <p className="text-[11px] text-[var(--muted)] tnum">
        {output.contentLength.toLocaleString("en-US")} {output.contentLength === 1 ? "character" : "characters"}
        {output.truncated ? " · Truncated by the request limit" : ""}
      </p>
      <pre className="mono min-w-0 rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[12px] leading-relaxed whitespace-pre-wrap text-[var(--text)] [overflow-wrap:anywhere]">
        {output.content}
      </pre>
    </article>
  )
}
