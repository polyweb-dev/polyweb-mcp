interface FailoverReadOnlyRowProps {
  label: string
  description: string
  value: string
}

/** Read-only failover policy row for a role without control-edit access. */
export function FailoverReadOnlyRow({ label, description, value }: FailoverReadOnlyRowProps) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-[13px] text-[var(--text)]">{label}</p>
        <p className="mt-0.5 text-[12px] text-[var(--muted)]">{description}</p>
      </div>
      <span className="shrink-0 text-[13px] text-[var(--text-strong)] tnum">{value}</span>
    </div>
  )
}
