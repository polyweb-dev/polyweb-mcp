import type { BackendUnitKind } from "@/shared/api/units"

export interface BackendDashboardQuota {
  provider: string
  source: "authoritative" | "observed" | "estimated"
  observed_at: string
  remaining: string | number | null
  /** Canonical 0..100 remaining percentage; absent on older backends. */
  remaining_percent?: string | number | null
  limit: string | number | null
  reset_at: string | null
  unit_kind?: BackendUnitKind | null
  display_unit?: string | null
  /** Optional scope label for rolling/keyless windows (for example hourly). */
  window?: string | null
}
