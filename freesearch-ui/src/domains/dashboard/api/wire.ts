import type { BackendUnitKind } from "@/shared/api/units"
// Acyclic type-only edge: dashboard -> execution (execution never imports dashboard wire).
import type { BackendUsageStatus } from "@/domains/execution/api/wire"
// Acyclic type-only edge: dashboard -> providers (providers never imports dashboard wire).
import type { BackendHealth } from "@/domains/providers/api/wire"
import type { BackendDashboardQuota } from "./quotaWire"

export interface BackendDashboardUsage {
  provider: string
  operation: string
  total_units: string
  event_count: number
  unit_kind?: BackendUnitKind | null
}

export interface BackendDashboardHealth {
  provider: string
  status: BackendHealth
  checked_at: string
}

export interface BackendDashboard {
  notice: string
  usage_totals: BackendDashboardUsage[]
  recent_usage: Array<{
    provider: string
    operation: string
    units: string
    unit_kind?: BackendUnitKind | null
    display_unit?: string | null
    observed_at: string
    latency_ms: number | null
    status: BackendUsageStatus
  }>
  latest_quota: BackendDashboardQuota[]
  latest_health: BackendDashboardHealth[]
  generated_at: string
}
