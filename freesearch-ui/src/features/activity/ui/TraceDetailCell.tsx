/** One labelled value in the detail summary strip. */
export function TraceDetailCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-3">
      <span className="block text-[12px] text-[var(--muted)]">{label}</span>
      <span className="text-[13px] text-[var(--text-strong)] tnum">{value}</span>
    </div>
  )
}
