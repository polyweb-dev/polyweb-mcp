export function PlaygroundHeader() {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
      <div>
        <h2 className="text-[var(--text-strong)]">Search Playground</h2>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          Run queries and fetches across the provider fleet with live arbitration.
        </p>
      </div>
    </div>
  )
}
