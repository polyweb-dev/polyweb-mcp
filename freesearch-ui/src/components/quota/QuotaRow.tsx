import React from "react"
import { ProviderLogo } from "@/components/common/ProviderLogo"
import type { DashboardQuota, ProviderConfig } from "@/types/freesearch"

interface QuotaRowProps {
  provider: ProviderConfig
  latestQuota: DashboardQuota | undefined
}

export const QuotaRow: React.FC<QuotaRowProps> = ({ provider, latestQuota }) => {
  const { quota } = provider
  const remaining = latestQuota?.remaining ?? null
  const limit = latestQuota?.limit ?? null
  const hasValues = remaining !== null && limit !== null
  const percent = hasValues
    ? Math.min(100, Math.round((Number(remaining) / Number(limit)) * 100))
    : 0
  return (
    <div className="grid grid-cols-[1fr_1fr_1.5fr] items-center gap-4 py-3 px-4 border-b last:border-b-0 border-[var(--border-subtle)]">
      <span className="flex items-center gap-2 min-w-0 text-[13px] font-medium text-[var(--text-strong)]">
        <ProviderLogo providerId={provider.id} />
        {provider.name} quota
      </span>
      <span className="text-[13px] text-[var(--muted)]">{quota.resetPeriod ?? "—"}</span>
      <div className="flex items-center gap-3">
        {hasValues && (
          <div className="flex-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
            <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: `${percent}%` }} />
          </div>
        )}
        <span className="text-[13px] text-[var(--text)] tnum shrink-0">
          {remaining ?? "—"}/{limit ?? "∞"} {quota.unit}
        </span>
      </div>
    </div>
  )
}
