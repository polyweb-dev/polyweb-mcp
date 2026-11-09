import type { ReactNode } from "react"

interface FailoverPolicyRowProps {
  label: string
  description: string
  /** The control, or the stored value as text for a read-only role. */
  children: ReactNode
}

/** One policy row: label and a one-line description on the left, the control on the right. */
export function FailoverPolicyRow({ label, description, children }: FailoverPolicyRowProps) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-4">
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-[var(--text-strong)]">{label}</p>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">{description}</p>
      </div>
      <div className="shrink-0 text-[13px] text-[var(--text-strong)] tnum">{children}</div>
    </div>
  )
}
