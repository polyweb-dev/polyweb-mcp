/**
 * Project usage: the project's own usage ledger only. Shared provider quota
 * and health are installation-wide observations and never appear here.
 */
import type { UnitKind } from "@/shared/api/units"

/** Aggregated units of one provider and operation. */
export interface ProjectUsageTotal {
  /** Wire provider id; the feature resolves the display name. */
  provider: string
  operation: string
  totalUnits: number
  eventCount: number
  unitKind: UnitKind | null
}

/** One privacy-projected recent usage event. */
export interface ProjectUsageEntry {
  provider: string
  operation: string
  units: number
  observedAt: string
  latencyMs: number | null
  status: "success" | "failure"
  unitKind: UnitKind | null
  displayUnit: string | null
}

/** Usage snapshot of one project (`/usage` and `/dashboard` share the shape). */
export interface ProjectUsage {
  projectId: string
  totals: ProjectUsageTotal[]
  recent: ProjectUsageEntry[]
  generatedAt: string
}

/** Units of one unit kind; kinds are never summed together. */
export interface UsageUnitAmount {
  unitKind: UnitKind | null
  units: number
}
