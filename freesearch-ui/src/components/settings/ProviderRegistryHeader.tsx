import React from "react"
import type { ProviderConfig } from "@/domains/providers"

export const ProviderRegistryHeader: React.FC<{
  providers: ProviderConfig[]
}> = ({ providers }) => {
  const activeCount = providers.filter((p) => p.globalEnabled).length
  const healthyCount = providers.filter((p) => p.healthStatus === "healthy" && p.circuitBreaker !== "open").length

  return (
    <div className="flex flex-col gap-2 border-b border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2.5">
        <h3 className="text-[13px] font-semibold text-[var(--text-strong)]">Provider registry</h3>
        <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)] tnum">
          {providers.length} configured
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--status-healthy)]">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-[#22c55e]" />
          <span className="tnum">{activeCount} active</span>
        </span>
      </div>
      <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
        <span className="hidden sm:inline">Priority dispatch · P1 to P{providers.length}</span>
        <span className="hidden md:inline opacity-40">|</span>
        <span>
          <strong className="font-medium text-[var(--text-strong)] tnum">{healthyCount}/{providers.length}</strong> healthy
        </span>
      </div>
    </div>
  )
}
