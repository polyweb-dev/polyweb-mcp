import type { ReactNode } from "react"

export interface KpiCardProps {
  icon: ReactNode
  label: string
  children: ReactNode
}

/** Small KPI tile for the usage overview strip. */
export function KpiCard({ icon, label, children }: KpiCardProps) {
  return (
    <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
      {icon}
      <div>
        <div className="text-[12px] text-[var(--muted)]">{label}</div>
        <div className="text-[14px] font-medium text-[var(--text-strong)]">{children}</div>
      </div>
    </div>
  )
}
