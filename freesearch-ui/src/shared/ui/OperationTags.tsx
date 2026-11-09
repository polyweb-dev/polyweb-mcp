export interface OperationTagsProps {
  operations: readonly string[]
}

/**
 * Mono operation tag row — the quiet signature mark of the product: small
 * `search` / `fetch` chips on a hairline. An empty list renders a muted dash.
 */
export function OperationTags({ operations }: OperationTagsProps) {
  if (operations.length === 0) {
    return <span className="text-[var(--muted)]">—</span>
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {operations.map((operation) => (
        <span
          key={operation}
          className="rounded border border-[var(--border-subtle)] px-1.5 font-mono text-[12px] leading-5 text-[var(--muted)]"
        >
          {operation}
        </span>
      ))}
    </span>
  )
}
