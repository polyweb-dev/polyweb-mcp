import type { TraceSearchResult } from "@/domains/activity"

/** One normalized search result row inside the results disclosure. */
export function TraceResultRow({ result }: { result: TraceSearchResult }) {
  return (
    <li className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-3">
      <p className="text-[13px] font-medium break-words text-[var(--text-strong)]">
        {result.title}
      </p>
      <p className="mono mt-1 break-all text-[var(--muted)]">{result.url}</p>
      {result.snippet !== "" && (
        <p className="mt-2 text-[13px] break-words text-[var(--text)]">{result.snippet}</p>
      )}
      {(result.source !== null || result.score !== null) && (
        <p className="mt-2 text-[12px] text-[var(--muted)] tnum">
          {result.source ?? "—"}
          {result.score !== null && ` · score ${result.score.toFixed(2)}`}
        </p>
      )}
    </li>
  )
}
