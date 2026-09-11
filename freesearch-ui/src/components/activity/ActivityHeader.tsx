import React from "react"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"

export type OperationFilter = "all" | "search" | "fetch"

const FILTER_OPTIONS = ["All", "Search", "Fetch"] as const

export const ActivityHeader: React.FC<{
  filterOp: OperationFilter
  onFilterChange: (value: string) => void
}> = ({ filterOp, onFilterChange }) => (
  <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
    <div>
      <h2 className="text-[var(--text-strong)]">Activity</h2>
      <p className="text-[13px] text-[var(--muted)] mt-0.5">Operational telemetry for routing decisions, failover traces, and latency.</p>
    </div>
    <SegmentedControl
      options={FILTER_OPTIONS}
      value={filterOp.charAt(0).toUpperCase() + filterOp.slice(1)}
      onChange={onFilterChange}
      ariaLabel="Activity operation filter"
    />
  </div>
)
